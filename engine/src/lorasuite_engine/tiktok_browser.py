from __future__ import annotations

import json
import ssl
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from lorasuite_engine.models import IngressScanResult, SourceKind
from lorasuite_engine.social_helper import scan_social_helper_payload
from lorasuite_engine.social_resilience import (
    SocialProviderError,
    error_from_subprocess,
    error_from_url,
)


SUPPORTED_BROWSER_COOKIE_SOURCES = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"}
)
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MetadataExtractor = Callable[[str, str, int, int], list[dict[str, Any]]]
ThumbnailFetcher = Callable[[str], tuple[bytes, str]]


class TikTokBrowserScanError(SocialProviderError):
    provider = "tiktok"


def scan_tiktok_url_with_browser_cookies(
    url: str,
    vault_root: Path,
    *,
    browser: str = "chrome",
    limit: int = 24,
    cursor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    metadata_extractor: MetadataExtractor | None = None,
    thumbnail_fetcher: ThumbnailFetcher | None = None,
) -> IngressScanResult:
    normalized_url = validate_tiktok_url(url)
    normalized_browser = validate_browser(browser)
    scan_limit = validate_limit(limit)
    validate_date_range(date_from, date_to)
    offset = cursor_offset(cursor)
    entries = (metadata_extractor or extract_yt_dlp_metadata)(
        normalized_url,
        normalized_browser,
        offset,
        scan_limit,
    )
    fetch_thumbnail = thumbnail_fetcher or fetch_thumbnail_asset
    cache_dir = Path(vault_root) / "previews" / "tiktok"
    cache_dir.mkdir(parents=True, exist_ok=True)

    media: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries, start=offset + 1):
        item = payload_item(
            entry,
            normalized_url,
            normalized_browser,
            index,
            cache_dir,
            fetch_thumbnail,
            date_from,
            date_to,
        )
        if item is None or item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        media.append(item)

    result = scan_social_helper_payload(
        {"helper_version": "lorasuite-yt-dlp-tiktok-v1", "media": media},
        vault_root,
        source_kind=SourceKind.TIKTOK,
    )
    result.metadata_json = {
        "scan_source": "tiktok",
        "browser_source": normalized_browser,
        "batch_offset": offset,
        "next_cursor": str(offset + scan_limit) if len(entries) >= scan_limit else None,
        "has_more": len(entries) >= scan_limit,
    }
    return result


def extract_yt_dlp_metadata(
    url: str,
    browser: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--cookies-from-browser",
        browser,
    ]
    if not is_direct_post_url(url):
        command.extend(
            [
                "--playlist-start",
                str(offset + 1),
                "--playlist-end",
                str(offset + limit),
            ]
        )
    command.append(url)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise error_from_url(
            TikTokBrowserScanError,
            "yt-dlp could not scan TikTok",
            error,
        ) from error
    if completed.returncode != 0:
        detail = clean_error(completed.stderr or completed.stdout)
        raise error_from_subprocess(TikTokBrowserScanError, "TikTok scan failed", detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise TikTokBrowserScanError("yt-dlp returned invalid TikTok metadata") from error
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [payload] if isinstance(payload, dict) else []


def payload_item(
    entry: dict[str, Any],
    input_url: str,
    browser: str,
    index: int,
    cache_dir: Path,
    fetch_thumbnail: ThumbnailFetcher,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any] | None:
    media_id = str(entry.get("id") or index)
    source_url = str(
        entry.get("webpage_url")
        or entry.get("url")
        or entry.get("original_url")
        or input_url
    ).strip()
    if not source_url.startswith("https://"):
        return None
    posted_at = posted_datetime(entry)
    if not date_allowed(posted_at, date_from, date_to):
        return None
    thumbnail_url = thumbnail_url_for_entry(entry)
    thumbnail_path = (
        cache_preview(thumbnail_url, cache_dir / media_id, fetch_thumbnail)
        if thumbnail_url
        else None
    )
    title = str(entry.get("description") or entry.get("title") or f"TikTok post {media_id}").strip()
    uploader = str(entry.get("uploader") or "").lstrip("@")
    audio = audio_metadata(entry)
    return {
        "id": f"tiktok_{media_id}",
        "source_url": source_url,
        "display_name": title,
        "media_type": "video",
        "download_url": None,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "poster_path": str(thumbnail_path) if thumbnail_path else None,
        "width": optional_int(entry.get("width")),
        "height": optional_int(entry.get("height")),
        "duration": optional_float(entry.get("duration")),
        "browser_source": browser,
        "extractor": "yt-dlp:tiktok",
        "scan_surface": "direct" if is_direct_post_url(input_url) else "profile",
        "owner_username": uploader or None,
        "uploader_username": uploader or None,
        "uploader_display_name": entry.get("channel") or entry.get("uploader"),
        "uploader_id": entry.get("uploader_id") or entry.get("channel_id"),
        "posted_at": posted_at.isoformat() if posted_at else None,
        "posted_timestamp": posted_at.timestamp() if posted_at else None,
        **audio,
    }


def audio_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    title = str(entry.get("track") or "").strip()
    artists = entry.get("artists")
    artist = ", ".join(str(value) for value in artists) if isinstance(artists, list) else str(artists or "").strip()
    explicit_original = entry.get("is_original_sound") is True
    title_original = title.lower().startswith("original sound")
    original = explicit_original or title_original
    return {
        "audio_original": original,
        "audio_kind": "original" if original else "reused_or_music",
        "audio_label": title or artist or "TikTok audio",
        "audio_title": title or None,
        "audio_artist": artist or None,
    }


def thumbnail_url_for_entry(entry: dict[str, Any]) -> str | None:
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list):
        for preferred_id in ("cover", "originCover", "dynamicCover"):
            for thumbnail in thumbnails:
                if (
                    isinstance(thumbnail, dict)
                    and thumbnail.get("id") == preferred_id
                    and isinstance(thumbnail.get("url"), str)
                ):
                    return str(thumbnail["url"])
        for thumbnail in thumbnails:
            if isinstance(thumbnail, dict) and isinstance(thumbnail.get("url"), str):
                return str(thumbnail["url"])
    thumbnail = entry.get("thumbnail")
    return str(thumbnail) if isinstance(thumbnail, str) and thumbnail else None


def cache_preview(
    url: str,
    target_stem: Path,
    fetch_thumbnail: ThumbnailFetcher,
) -> Path | None:
    try:
        content, mime_type = fetch_thumbnail(url)
    except TikTokBrowserScanError:
        return None
    suffix = ".png" if mime_type == "image/png" else ".webp" if mime_type == "image/webp" else ".jpg"
    target = target_stem.with_suffix(suffix)
    target.write_bytes(content)
    return target


def fetch_thumbnail_asset(url: str) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": WEB_USER_AGENT,
            "Accept": "image/avif,image/webp,image/png,image/jpeg",
        },
    )
    try:
        with urlopen(
            request,
            timeout=45,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            content = response.read(12 * 1024 * 1024 + 1)
            mime_type = response.headers.get_content_type().lower()
    except Exception as error:
        raise error_from_url(
            TikTokBrowserScanError,
            "TikTok thumbnail request failed",
            error,
        ) from error
    if len(content) > 12 * 1024 * 1024 or mime_type not in {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }:
        raise TikTokBrowserScanError("TikTok thumbnail response was not a supported image")
    return content, mime_type


def validate_tiktok_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or parsed.hostname not in {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }:
        raise TikTokBrowserScanError("Enter an https://www.tiktok.com URL")
    return normalized


def validate_browser(browser: str) -> str:
    normalized = browser.strip().lower()
    if normalized not in SUPPORTED_BROWSER_COOKIE_SOURCES:
        raise TikTokBrowserScanError(f"Unsupported browser cookie source: {browser}")
    return normalized


def validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise TikTokBrowserScanError("TikTok scan limit must be between 1 and 100")
    return limit


def cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError) as error:
        raise TikTokBrowserScanError("TikTok batch cursor is invalid") from error
    if offset < 0:
        raise TikTokBrowserScanError("TikTok batch cursor is invalid")
    return offset


def validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise TikTokBrowserScanError("TikTok start date must be on or before end date")


def posted_datetime(entry: dict[str, Any]) -> datetime | None:
    value = entry.get("timestamp") or entry.get("release_timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    upload_date = entry.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def date_allowed(posted_at: datetime | None, date_from: date | None, date_to: date | None) -> bool:
    if posted_at is None:
        return date_from is None and date_to is None
    posted_date = posted_at.date()
    return (date_from is None or posted_date >= date_from) and (
        date_to is None or posted_date <= date_to
    )


def is_direct_post_url(url: str) -> bool:
    path = urlparse(url).path
    return "/video/" in path or "/photo/" in path


def optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def clean_error(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:500] if lines else "unknown extractor error"
