import json
import ssl
import subprocess
import sys
from base64 import b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    Request,
    build_opener,
    urlopen,
)

from yt_dlp.cookies import extract_cookies_from_browser

from lorasuite_engine.models import IngressScanResult
from lorasuite_engine.social_helper import scan_instagram_helper_payload

MetadataExtractor = Callable[[str, str], dict[str, Any]]
ProfileReelsFetcher = Callable[[str, str, int], dict[str, Any]]
ThumbnailFetcher = Callable[[str], tuple[bytes, str]]

INSTAGRAM_WEB_APP_ID = "936619743392459"
PROFILE_REELS_PAGE_SIZE = 24
SUPPORTED_BROWSER_COOKIE_SOURCES = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"}
)
SUPPORTED_THUMBNAIL_MIME_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class InstagramBrowserScanError(RuntimeError):
    pass


def scan_instagram_url_with_browser_cookies(
    url: str,
    vault_root: Path,
    *,
    browser: str = "chrome",
    metadata_extractor: MetadataExtractor | None = None,
    profile_reels_fetcher: ProfileReelsFetcher | None = None,
    thumbnail_fetcher: ThumbnailFetcher | None = None,
) -> IngressScanResult:
    normalized_url = _validate_instagram_url(url)
    normalized_browser = _validate_browser(browser)
    extractor = metadata_extractor or _extract_metadata_with_ytdlp
    reels_fetcher = profile_reels_fetcher or _fetch_profile_reels_with_browser_cookies
    fetcher = thumbnail_fetcher or _fetch_thumbnail

    profile_reels_username = _profile_reels_username(normalized_url)
    if profile_reels_username is not None:
        metadata = reels_fetcher(
            profile_reels_username,
            normalized_browser,
            PROFILE_REELS_PAGE_SIZE,
        )
        payload = _helper_payload_from_instagram_clips_payload(
            metadata,
            browser=normalized_browser,
            thumbnail_fetcher=fetcher,
        )
    else:
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


def _fetch_profile_reels_with_browser_cookies(
    username: str,
    browser: str,
    page_size: int,
) -> dict[str, Any]:
    cookie_jar = _extract_browser_cookies(browser)
    opener = build_opener(
        HTTPCookieProcessor(cookie_jar),
        HTTPSHandler(context=_ssl_context()),
    )
    referer = f"https://www.instagram.com/{username}/reels/"
    profile_payload = _request_instagram_json(
        opener,
        "https://www.instagram.com/api/v1/users/web_profile_info/?"
        + urlencode({"username": username}),
        headers=_instagram_json_headers(referer),
    )
    user = ((profile_payload.get("data") or {}).get("user") or {})
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise InstagramBrowserScanError(
            f"Could not resolve Instagram profile: {username}."
        )

    csrf_token = _cookie_value(cookie_jar, "csrftoken")
    if not csrf_token:
        raise InstagramBrowserScanError(
            f"No Instagram CSRF cookie found in {browser}. Log into Instagram in that browser first."
        )

    form_data = urlencode(
        {
            "target_user_id": user_id,
            "page_size": str(page_size),
            "include_feed_video": "true",
            "surface": "grid",
        }
    ).encode("utf-8")
    return _request_instagram_json(
        opener,
        "https://www.instagram.com/api/v1/clips/user/",
        data=form_data,
        headers={
            **_instagram_json_headers(referer),
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.instagram.com",
            "X-CSRFToken": csrf_token,
        },
        method="POST",
    )


def _helper_payload_from_instagram_clips_payload(
    metadata: dict[str, Any],
    *,
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
) -> dict[str, Any]:
    media = [
        _media_item_from_instagram_clip(entry, browser, thumbnail_fetcher)
        for entry in _iter_instagram_clip_media(metadata)
    ]
    return {
        "helper_version": "lorasuite-instagram-web-api-v0",
        "media": [item for item in media if item is not None],
    }


def _extract_browser_cookies(browser: str):
    try:
        return extract_cookies_from_browser(browser)
    except Exception as error:
        raise InstagramBrowserScanError(
            f"Could not read {browser} browser cookies. Log into Instagram in that browser first."
        ) from error


def _request_instagram_json(
    opener,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
    method: str = "GET",
) -> dict[str, Any]:
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            raw_payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        raise InstagramBrowserScanError(
            f"Instagram request failed with HTTP {error.code}."
        ) from error
    except URLError as error:
        raise InstagramBrowserScanError(f"Instagram request failed: {error.reason}.") from error

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise InstagramBrowserScanError("Instagram returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise InstagramBrowserScanError("Instagram returned an unexpected response.")
    return payload


def _instagram_json_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": WEB_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "X-IG-App-ID": INSTAGRAM_WEB_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
    }


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _cookie_value(cookie_jar: Any, name: str) -> str | None:
    for cookie in cookie_jar:
        if cookie.name == name and "instagram.com" in cookie.domain:
            return str(cookie.value)
    return None


def _iter_entries(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    entries = metadata.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [metadata]


def _iter_instagram_clip_media(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    items = metadata.get("items")
    if not isinstance(items, list):
        clips = metadata.get("clips")
        items = clips if isinstance(clips, list) else []

    media: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        child = item.get("media")
        if isinstance(child, dict):
            media.append(child)
        else:
            media.append(item)
    return media


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


def _media_item_from_instagram_clip(
    entry: dict[str, Any],
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
) -> dict[str, Any] | None:
    media_id = str(entry.get("id") or entry.get("pk") or "").strip()
    shortcode = str(entry.get("code") or entry.get("shortcode") or "").strip()
    if not media_id and not shortcode:
        return None

    thumbnail_url = _best_instagram_thumbnail_url(entry)
    poster_data_url = _thumbnail_data_url(thumbnail_url, thumbnail_fetcher)
    source_url = f"https://www.instagram.com/reel/{shortcode}/" if shortcode else ""
    duration = _optional_float(entry.get("video_duration") or entry.get("duration"))
    media_type = (
        "video"
        if entry.get("media_type") == 2 or entry.get("video_versions") or duration
        else "image"
    )

    item: dict[str, Any] = {
        "id": media_id or _fallback_media_id(source_url),
        "source_url": source_url,
        "display_name": _instagram_caption_text(entry)
        or (f"Instagram reel {shortcode}" if shortcode else media_id),
        "media_type": media_type,
        "poster_url": thumbnail_url,
        "thumbnail_url": thumbnail_url,
        "poster_data_url": poster_data_url,
        "width": _optional_int(entry.get("original_width") or entry.get("width")),
        "height": _optional_int(entry.get("original_height") or entry.get("height")),
        "duration": duration,
        "browser_source": browser,
        "extractor": "instagram-web-api",
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


def _best_instagram_thumbnail_url(entry: dict[str, Any]) -> str | None:
    image_versions = entry.get("image_versions2")
    if not isinstance(image_versions, dict):
        return None

    candidates = image_versions.get("candidates")
    if not isinstance(candidates, list):
        return None

    sorted_candidates = sorted(
        (candidate for candidate in candidates if isinstance(candidate, dict)),
        key=lambda candidate: (
            _optional_int(candidate.get("width")) or 0
        )
        * (_optional_int(candidate.get("height")) or 0),
        reverse=True,
    )
    for candidate in sorted_candidates:
        url = candidate.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _instagram_caption_text(entry: dict[str, Any]) -> str | None:
    caption = entry.get("caption")
    if isinstance(caption, dict):
        text = caption.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    return None


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
    request = Request(url, headers={"User-Agent": WEB_USER_AGENT})
    with urlopen(request, timeout=30, context=_ssl_context()) as response:
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


def _profile_reels_username(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[1] == "reels":
        return parts[0]
    return None


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
