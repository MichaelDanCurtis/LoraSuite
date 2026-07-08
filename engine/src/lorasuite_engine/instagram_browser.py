import json
import subprocess
import sys
from base64 import b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lorasuite_engine.models import IngressScanResult
from lorasuite_engine.social_helper import scan_instagram_helper_payload

MetadataExtractor = Callable[[str, str], dict[str, Any]]
ThumbnailFetcher = Callable[[str], tuple[bytes, str]]

SUPPORTED_BROWSER_COOKIE_SOURCES = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"}
)
SUPPORTED_THUMBNAIL_MIME_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})


class InstagramBrowserScanError(RuntimeError):
    pass


def scan_instagram_url_with_browser_cookies(
    url: str,
    vault_root: Path,
    *,
    browser: str = "chrome",
    metadata_extractor: MetadataExtractor | None = None,
    thumbnail_fetcher: ThumbnailFetcher | None = None,
) -> IngressScanResult:
    normalized_url = _validate_instagram_url(url)
    normalized_browser = _validate_browser(browser)
    extractor = metadata_extractor or _extract_metadata_with_ytdlp
    fetcher = thumbnail_fetcher or _fetch_thumbnail

    metadata = extractor(normalized_url, normalized_browser)
    payload = _helper_payload_from_ytdlp_metadata(
        metadata,
        browser=normalized_browser,
        thumbnail_fetcher=fetcher,
    )
    return scan_instagram_helper_payload(payload, vault_root)


def _extract_metadata_with_ytdlp(url: str, browser: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--cookies-from-browser",
        browser,
        url,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise InstagramBrowserScanError(
            _clean_ytdlp_error(completed.stderr or completed.stdout)
        )

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise InstagramBrowserScanError("yt-dlp returned invalid metadata JSON") from error


def _helper_payload_from_ytdlp_metadata(
    metadata: dict[str, Any],
    *,
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
) -> dict[str, Any]:
    media = [
        _media_item_from_ytdlp_entry(entry, browser, thumbnail_fetcher)
        for entry in _iter_entries(metadata)
    ]
    return {
        "helper_version": "lorasuite-ytdlp-browser-v0",
        "media": [item for item in media if item is not None],
    }


def _iter_entries(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    entries = metadata.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [metadata]


def _media_item_from_ytdlp_entry(
    entry: dict[str, Any],
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
) -> dict[str, Any] | None:
    media_id = str(entry.get("id") or entry.get("display_id") or "").strip()
    source_url = str(entry.get("webpage_url") or entry.get("original_url") or "").strip()
    if not media_id and not source_url:
        return None

    thumbnail_url = _best_thumbnail_url(entry)
    poster_data_url = _thumbnail_data_url(thumbnail_url, thumbnail_fetcher)
    media_type = "video" if entry.get("duration") or entry.get("url") else "image"

    item: dict[str, Any] = {
        "id": media_id or _fallback_media_id(source_url),
        "source_url": source_url,
        "display_name": str(entry.get("title") or media_id or source_url),
        "media_type": media_type,
        "download_url": entry.get("url") if media_type == "video" else None,
        "poster_url": thumbnail_url,
        "thumbnail_url": thumbnail_url,
        "poster_data_url": poster_data_url,
        "width": _optional_int(entry.get("width")),
        "height": _optional_int(entry.get("height")),
        "duration": _optional_float(entry.get("duration")),
        "browser_source": browser,
        "extractor": "yt-dlp",
    }
    return {key: value for key, value in item.items() if value is not None}


def _best_thumbnail_url(entry: dict[str, Any]) -> str | None:
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list) and thumbnails:
        sorted_thumbnails = sorted(
            (thumbnail for thumbnail in thumbnails if isinstance(thumbnail, dict)),
            key=lambda thumbnail: (
                _optional_int(thumbnail.get("width")) or 0
            )
            * (_optional_int(thumbnail.get("height")) or 0),
            reverse=True,
        )
        for thumbnail in sorted_thumbnails:
            url = thumbnail.get("url")
            if isinstance(url, str) and url:
                return url

    thumbnail = entry.get("thumbnail")
    return thumbnail if isinstance(thumbnail, str) and thumbnail else None


def _thumbnail_data_url(
    thumbnail_url: str | None,
    thumbnail_fetcher: ThumbnailFetcher,
) -> str | None:
    if not thumbnail_url:
        return None

    try:
        thumbnail_bytes, content_type = thumbnail_fetcher(thumbnail_url)
    except (OSError, URLError, ValueError):
        return None

    normalized_content_type = content_type.split(";", maxsplit=1)[0].lower()
    if normalized_content_type not in SUPPORTED_THUMBNAIL_MIME_TYPES:
        return None
    return (
        f"data:{normalized_content_type};base64,"
        f"{b64encode(thumbnail_bytes).decode('ascii')}"
    )


def _fetch_thumbnail(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get_content_type()
        data = response.read(5 * 1024 * 1024 + 1)

    if len(data) > 5 * 1024 * 1024:
        raise ValueError("thumbnail is larger than 5 MB")
    return data, content_type


def _validate_instagram_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        hostname == "instagram.com" or hostname.endswith(".instagram.com")
    ):
        raise InstagramBrowserScanError("Enter an Instagram URL.")
    return url


def _validate_browser(browser: str) -> str:
    normalized = browser.strip().lower()
    if normalized not in SUPPORTED_BROWSER_COOKIE_SOURCES:
        supported = ", ".join(sorted(SUPPORTED_BROWSER_COOKIE_SOURCES))
        raise InstagramBrowserScanError(f"Unsupported browser cookie source. Use one of: {supported}.")
    return normalized


def _fallback_media_id(source_url: str) -> str:
    parsed = urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"instagram_{parts[0]}_{parts[1]}"
    return "instagram_unknown"


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _clean_ytdlp_error(message: str) -> str:
    stripped = message.strip()
    if not stripped:
        return "yt-dlp could not scan the Instagram URL."
    return stripped.splitlines()[-1]
