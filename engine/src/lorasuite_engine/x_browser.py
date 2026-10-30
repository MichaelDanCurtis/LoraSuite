from __future__ import annotations

import json
import ssl
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
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
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
VIDEO_SUFFIXES = frozenset({".mp4", ".m3u8", ".mov", ".webm"})
WEB_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

MetadataExtractor = Callable[[str, str, int, int], list[dict[str, Any]]]
ThumbnailFetcher = Callable[[str], tuple[bytes, str]]


class XBrowserScanError(SocialProviderError):
    provider = "x"


def scan_x_url_with_browser_cookies(
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
    normalized_url = _validate_x_url(url)
    normalized_browser = _validate_browser(browser)
    scan_limit = _validate_limit(limit)
    _validate_date_range(date_from, date_to)
    offset = _cursor_offset(cursor)
    entries = (metadata_extractor or _extract_gallery_metadata)(normalized_url, normalized_browser, offset, scan_limit)
    fetch_thumbnail = thumbnail_fetcher or _fetch_thumbnail
    cache_dir = Path(vault_root) / "previews" / "x_twitter"
    cache_dir.mkdir(parents=True, exist_ok=True)
    media: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, entry in enumerate(entries, start=offset + 1):
        item = _payload_item(entry, normalized_url, normalized_browser, index, cache_dir, fetch_thumbnail, date_from, date_to)
        if item is None or item["download_url"] in seen_urls:
            continue
        seen_urls.add(item["download_url"])
        media.append(item)
    result = scan_social_helper_payload(
        {"helper_version": "lorasuite-gallery-dl-x-v1", "media": media},
        vault_root,
        source_kind=SourceKind.X_TWITTER,
    )
    result.metadata_json = {
        "scan_source": "x_twitter",
        "browser_source": normalized_browser,
        "batch_offset": offset,
        "next_cursor": str(offset + scan_limit) if len(entries) >= scan_limit else None,
        "has_more": len(entries) >= scan_limit,
    }
    return result


def _extract_gallery_metadata(url: str, browser: str, offset: int, limit: int) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--dump-json",
        "--cookies-from-browser",
        browser,
        "--range",
        f"{offset + 1}-{offset + limit}",
        "--option",
        "extractor.twitter.include=media",
        "--option",
        "extractor.twitter.replies=false",
        "--option",
        "extractor.twitter.quoted=false",
        url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as error:
        raise error_from_url(XBrowserScanError, "gallery-dl could not scan X", error) from error
    if completed.returncode != 0:
        detail = _clean_error(completed.stderr or completed.stdout)
        raise error_from_subprocess(XBrowserScanError, "X scan failed", detail)
    entries: list[dict[str, Any]] = []
    try:
        messages = json.loads(completed.stdout)
    except json.JSONDecodeError:
        messages = []
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        messages = []
    for message in messages:
        if isinstance(message, list) and len(message) >= 3 and message[0] == 3 and isinstance(message[1], str) and isinstance(message[2], dict):
            entries.append({**message[2], "download_url": message[1]})
        elif isinstance(message, dict) and isinstance(message.get("url") or message.get("download_url"), str):
            entries.append(message)
    if not entries and completed.stdout.strip():
        raise XBrowserScanError("gallery-dl returned no readable X media metadata")
    return entries


def _payload_item(
    entry: dict[str, Any],
    input_url: str,
    browser: str,
    index: int,
    cache_dir: Path,
    fetch_thumbnail: ThumbnailFetcher,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any] | None:
    download_url = str(entry.get("download_url") or entry.get("url") or "").strip()
    if not download_url.startswith(("https://", "http://")):
        return None
    media_type = _media_type(download_url, entry)
    if media_type is None:
        return None
    posted_at = _posted_at(entry)
    if not _date_allowed(posted_at, date_from, date_to):
        return None
    tweet_id = str(entry.get("tweet_id") or entry.get("id") or entry.get("post_id") or index)
    username = _username(entry)
    source_url = str(entry.get("tweet_url") or entry.get("post_url") or "").strip()
    if not source_url:
        source_url = f"https://x.com/{username}/status/{tweet_id}" if username else input_url
    preview_url = _preview_url(entry, download_url, media_type)
    preview_path = _cache_preview(preview_url, cache_dir / f"{tweet_id}_{index}", fetch_thumbnail) if preview_url else None
    width = _optional_int(entry.get("width") or entry.get("video_width"))
    height = _optional_int(entry.get("height") or entry.get("video_height"))
    description = str(entry.get("content") or entry.get("description") or entry.get("tweet_text") or f"X post {tweet_id}").strip()
    return {
        "id": f"x_{tweet_id}_{index}",
        "source_url": source_url,
        "display_name": description,
        "media_type": media_type,
        "download_url": download_url,
        "thumbnail_path": str(preview_path) if preview_path else None,
        "poster_path": str(preview_path) if preview_path and media_type == "video" else None,
        "width": width,
        "height": height,
        "duration": _optional_float(entry.get("duration")),
        "browser_source": browser,
        "extractor": "gallery-dl:twitter",
        "scan_surface": "timeline" if "/status/" not in input_url else "direct",
        "owner_username": username or None,
        "uploader_username": username or None,
        "uploader_display_name": _display_name(entry),
        "posted_at": posted_at.isoformat() if posted_at else None,
        "posted_timestamp": posted_at.timestamp() if posted_at else None,
        "audio_original": media_type == "video",
        "audio_kind": "original" if media_type == "video" else None,
        "audio_label": "Uploaded video audio" if media_type == "video" else None,
    }


def _preview_url(entry: dict[str, Any], download_url: str, media_type: str) -> str | None:
    for key in ("thumbnail", "thumbnail_url", "preview", "preview_url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    if media_type != "image" or "pbs.twimg.com" not in download_url:
        return None
    parsed = urlparse(download_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["name"] = "small"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _cache_preview(url: str, target_stem: Path, fetch_thumbnail: ThumbnailFetcher) -> Path | None:
    try:
        content, mime_type = fetch_thumbnail(url)
    except XBrowserScanError:
        return None
    suffix = ".png" if mime_type == "image/png" else ".webp" if mime_type == "image/webp" else ".jpg"
    target = target_stem.with_suffix(suffix)
    target.write_bytes(content)
    return target


def _fetch_thumbnail(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": WEB_USER_AGENT, "Accept": "image/avif,image/webp,image/png,image/jpeg"})
    try:
        with urlopen(request, timeout=45, context=ssl.create_default_context(cafile=certifi.where())) as response:
            content = response.read(12 * 1024 * 1024 + 1)
            mime_type = response.headers.get_content_type().lower()
    except Exception as error:
        raise error_from_url(XBrowserScanError, "X thumbnail request failed", error) from error
    if len(content) > 12 * 1024 * 1024 or mime_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
        raise XBrowserScanError("X thumbnail response was not a supported image")
    return content, mime_type


def _media_type(url: str, entry: dict[str, Any]) -> str | None:
    extension = str(entry.get("extension") or entry.get("ext") or Path(urlparse(url).path).suffix).lower()
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    if extension in VIDEO_SUFFIXES or str(entry.get("type") or "").lower() == "video":
        return "video"
    if extension in IMAGE_SUFFIXES or "pbs.twimg.com" in url:
        return "image"
    return None


def _posted_at(entry: dict[str, Any]) -> datetime | None:
    value = entry.get("date") or entry.get("created_at") or entry.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        cleaned = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _date_allowed(posted_at: datetime | None, date_from: date | None, date_to: date | None) -> bool:
    if posted_at is None:
        return date_from is None and date_to is None
    posted_date = posted_at.date()
    return (date_from is None or posted_date >= date_from) and (date_to is None or posted_date <= date_to)


def _username(entry: dict[str, Any]) -> str:
    author = entry.get("author") or entry.get("user")
    if isinstance(author, dict):
        return str(author.get("name") or author.get("username") or author.get("screen_name") or "").lstrip("@")
    return str(entry.get("username") or entry.get("user_name") or entry.get("author_name") or "").lstrip("@")


def _display_name(entry: dict[str, Any]) -> str | None:
    author = entry.get("author") or entry.get("user")
    if isinstance(author, dict):
        value = author.get("nick") or author.get("display_name")
    else:
        value = entry.get("author_display_name")
    return str(value) if value else None


def _validate_x_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        raise XBrowserScanError("Enter an https://x.com or https://twitter.com URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 1:
        parsed = parsed._replace(path=f"/{parts[0]}/media")
        return urlunparse(parsed)
    return normalized


def _validate_browser(browser: str) -> str:
    normalized = browser.strip().lower()
    if normalized not in SUPPORTED_BROWSER_COOKIE_SOURCES:
        raise XBrowserScanError(f"Unsupported browser cookie source: {browser}")
    return normalized


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > 100:
        raise XBrowserScanError("X scan limit must be between 1 and 100")
    return limit


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdigit() or int(cursor) < 0:
        raise XBrowserScanError("X batch cursor is invalid")
    return int(cursor)


def _validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise XBrowserScanError("X start date must be on or before end date")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clean_error(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:1000] if lines else "gallery-dl returned no error detail"
