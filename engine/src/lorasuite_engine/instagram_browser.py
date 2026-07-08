import json
import ssl
import subprocess
import sys
from binascii import Error as BinasciiError
from base64 import b64decode, b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast
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
ProfileFetcher = Callable[[str, str], dict[str, Any]]
ProfilePageFetcher = Callable[[str, str, int, str | None], dict[str, Any]]
ProfileReelsFetcher = Callable[[str, str, int, str | None], dict[str, Any]]
ProfileTaggedFetcher = Callable[[str, str, int, str | None], dict[str, Any]]
ThumbnailFetcher = Callable[[str], tuple[bytes, str]]
InstagramScanMode = Literal["all", "feed", "reels", "tagged"]

INSTAGRAM_WEB_APP_ID = "936619743392459"
INSTAGRAM_TAGGED_QUERY_HASH = "ff260833edf142911047af6024eb634a"
PROFILE_REELS_PAGE_SIZE = 24
MAX_PROFILE_REELS_PAGE_SIZE = 100
SUPPORTED_INSTAGRAM_SCAN_MODES = frozenset({"all", "feed", "reels", "tagged"})
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
    profile_fetcher: ProfileFetcher | None = None,
    profile_page_fetcher: ProfilePageFetcher | None = None,
    profile_reels_fetcher: ProfileReelsFetcher | None = None,
    profile_tagged_fetcher: ProfileTaggedFetcher | None = None,
    thumbnail_fetcher: ThumbnailFetcher | None = None,
    limit: int = PROFILE_REELS_PAGE_SIZE,
    cursor: str | None = None,
    scan_mode: InstagramScanMode = "all",
) -> IngressScanResult:
    normalized_url = _validate_instagram_url(url)
    normalized_browser = _validate_browser(browser)
    scan_limit = _validate_scan_limit(limit)
    normalized_scan_mode = _validate_scan_mode(scan_mode)
    cursor_state = _decode_scan_cursor(cursor)
    extractor = metadata_extractor or _extract_metadata_with_ytdlp
    profile_fetcher_impl = profile_fetcher or _fetch_profile_with_browser_cookies
    profile_page_fetcher_impl = profile_page_fetcher or _fetch_profile_page_with_browser_cookies
    reels_fetcher = profile_reels_fetcher or _fetch_profile_reels_with_browser_cookies
    tagged_fetcher = profile_tagged_fetcher or _fetch_profile_tagged_with_browser_cookies
    fetcher = thumbnail_fetcher or _fetch_thumbnail

    if (profile_username := _profile_surface_username(normalized_url)) is not None:
        return _scan_instagram_profile_surfaces(
            profile_username,
            vault_root,
            browser=normalized_browser,
            limit=scan_limit,
            cursor_state=cursor_state,
            scan_mode=normalized_scan_mode,
            profile_fetcher=profile_fetcher_impl if profile_fetcher is not None else None,
            profile_page_fetcher=profile_page_fetcher_impl,
            profile_reels_fetcher=reels_fetcher,
            profile_tagged_fetcher=tagged_fetcher,
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


def _scan_instagram_profile_surfaces(
    username: str,
    vault_root: Path,
    *,
    browser: str,
    limit: int,
    cursor_state: dict[str, str],
    scan_mode: InstagramScanMode,
    profile_fetcher: ProfileFetcher | None,
    profile_page_fetcher: ProfilePageFetcher,
    profile_reels_fetcher: ProfileReelsFetcher,
    profile_tagged_fetcher: ProfileTaggedFetcher,
    thumbnail_fetcher: ThumbnailFetcher,
) -> IngressScanResult:
    is_continuation = bool(cursor_state)
    payload_media: list[dict[str, Any]] = []
    metadata_by_surface: dict[str, dict[str, Any]] = {}

    if _should_fetch_surface(scan_mode, "feed", cursor_state, is_continuation):
        profile_metadata = _fetch_feed_surface(
            username,
            browser,
            limit,
            cursor_state.get("feed") or cursor_state.get("profile"),
            profile_fetcher=profile_fetcher,
            profile_page_fetcher=profile_page_fetcher,
        )
        metadata_by_surface["feed"] = profile_metadata
        feed_payload = _helper_payload_from_instagram_profile_payload(
            profile_metadata,
            {"items": []},
            browser=browser,
            thumbnail_fetcher=thumbnail_fetcher,
            limit=limit,
        )
        payload_media.extend(feed_payload["media"])

    if _should_fetch_surface(scan_mode, "reels", cursor_state, is_continuation):
        reels_metadata = profile_reels_fetcher(
            username,
            browser,
            limit,
            cursor_state.get("reels"),
        )
        metadata_by_surface["reels"] = reels_metadata
        reels_payload = _helper_payload_from_instagram_clips_payload(
            reels_metadata,
            browser=browser,
            thumbnail_fetcher=thumbnail_fetcher,
        )
        payload_media.extend(reels_payload["media"])

    if _should_fetch_surface(scan_mode, "tagged", cursor_state, is_continuation):
        tagged_metadata = profile_tagged_fetcher(
            username,
            browser,
            limit,
            cursor_state.get("tagged"),
        )
        metadata_by_surface["tagged"] = tagged_metadata
        tagged_payload = _helper_payload_from_instagram_profile_payload(
            tagged_metadata,
            {"items": []},
            browser=browser,
            thumbnail_fetcher=thumbnail_fetcher,
            limit=limit,
        )
        payload_media.extend(tagged_payload["media"])

    payload = {
        "helper_version": "lorasuite-instagram-web-api-v1",
        "media": _dedupe_media_items(payload_media),
    }
    result = scan_instagram_helper_payload(payload, vault_root)
    result.metadata_json = _profile_pagination_metadata(metadata_by_surface, limit)
    return result


def _should_fetch_surface(
    scan_mode: InstagramScanMode,
    surface: str,
    cursor_state: dict[str, str],
    is_continuation: bool,
) -> bool:
    if scan_mode == surface:
        return True
    if scan_mode != "all":
        return False
    return not is_continuation or surface in cursor_state


def _fetch_feed_surface(
    username: str,
    browser: str,
    limit: int,
    cursor: str | None,
    *,
    profile_fetcher: ProfileFetcher | None,
    profile_page_fetcher: ProfilePageFetcher,
) -> dict[str, Any]:
    if profile_fetcher is not None and cursor is None:
        return profile_fetcher(username, browser)
    return profile_page_fetcher(username, browser, limit, cursor)


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


def _fetch_profile_with_browser_cookies(username: str, browser: str) -> dict[str, Any]:
    cookie_jar = _extract_browser_cookies(browser)
    opener = build_opener(
        HTTPCookieProcessor(cookie_jar),
        HTTPSHandler(context=_ssl_context()),
    )
    referer = f"https://www.instagram.com/{username}/"
    profile_payload = _request_instagram_json(
        opener,
        "https://www.instagram.com/api/v1/users/web_profile_info/?"
        + urlencode({"username": username}),
        headers=_instagram_json_headers(referer),
    )
    if _iter_instagram_profile_media(profile_payload):
        return profile_payload

    user = ((profile_payload.get("data") or {}).get("user") or {})
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        return profile_payload

    try:
        feed_payload = _request_instagram_json(
            opener,
            f"https://www.instagram.com/api/v1/feed/user/{user_id}/?"
            + urlencode({"count": str(PROFILE_REELS_PAGE_SIZE)}),
            headers=_instagram_json_headers(referer),
        )
    except InstagramBrowserScanError:
        return profile_payload
    if _iter_instagram_profile_media(feed_payload):
        return feed_payload
    return profile_payload


def _fetch_profile_page_with_browser_cookies(
    username: str,
    browser: str,
    page_size: int,
    cursor: str | None,
) -> dict[str, Any]:
    cookie_jar = _extract_browser_cookies(browser)
    opener = build_opener(
        HTTPCookieProcessor(cookie_jar),
        HTTPSHandler(context=_ssl_context()),
    )
    referer = f"https://www.instagram.com/{username}/"
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

    query = {"count": str(page_size)}
    if cursor:
        query["max_id"] = cursor
    return _request_instagram_json(
        opener,
        f"https://www.instagram.com/api/v1/feed/user/{user_id}/?"
        + urlencode(query),
        headers=_instagram_json_headers(referer),
    )


def _fetch_profile_reels_with_browser_cookies(
    username: str,
    browser: str,
    page_size: int,
    cursor: str | None,
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

    form_fields = {
        "target_user_id": user_id,
        "page_size": str(page_size),
        "include_feed_video": "true",
        "surface": "grid",
    }
    if cursor:
        form_fields["max_id"] = cursor
    form_data = urlencode(form_fields).encode("utf-8")
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


def _fetch_profile_tagged_with_browser_cookies(
    username: str,
    browser: str,
    page_size: int,
    cursor: str | None,
) -> dict[str, Any]:
    cookie_jar = _extract_browser_cookies(browser)
    opener = build_opener(
        HTTPCookieProcessor(cookie_jar),
        HTTPSHandler(context=_ssl_context()),
    )
    referer = f"https://www.instagram.com/{username}/tagged/"
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

    variables: dict[str, Any] = {"id": user_id, "first": max(2, page_size)}
    if cursor:
        variables["after"] = cursor
    return _request_instagram_json(
        opener,
        "https://www.instagram.com/graphql/query/?"
        + urlencode(
            {
                "query_hash": INSTAGRAM_TAGGED_QUERY_HASH,
                "variables": json.dumps(variables, separators=(",", ":")),
            }
        ),
        headers=_instagram_json_headers(referer),
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


def _helper_payload_from_instagram_profile_payload(
    profile_metadata: dict[str, Any],
    reels_metadata: dict[str, Any],
    *,
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
    limit: int = PROFILE_REELS_PAGE_SIZE,
) -> dict[str, Any]:
    profile_media = [
        _media_item_from_instagram_profile_node(entry, browser, thumbnail_fetcher)
        for entry in _iter_instagram_profile_media(profile_metadata)[:limit]
    ]
    reel_media = [
        _media_item_from_instagram_clip(entry, browser, thumbnail_fetcher)
        for entry in _iter_instagram_clip_media(reels_metadata)[:limit]
    ]
    return {
        "helper_version": "lorasuite-instagram-web-api-v0",
        "media": _dedupe_media_items(
            [item for item in profile_media + reel_media if item is not None]
        ),
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


def _iter_instagram_profile_media(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    items = metadata.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]

    profile_grid_items = metadata.get("profile_grid_items")
    if isinstance(profile_grid_items, list):
        return [item for item in profile_grid_items if isinstance(item, dict)]

    user = ((metadata.get("data") or {}).get("user") or {})
    for edge_collection_name in (
        "edge_owner_to_timeline_media",
        "edge_user_to_photos_of_you",
    ):
        timeline = user.get(edge_collection_name)
        media = _iter_graphql_edge_media(timeline)
        if media:
            return media
    return []


def _iter_graphql_edge_media(timeline: Any) -> list[dict[str, Any]]:
    if not isinstance(timeline, dict):
        return []

    edges = timeline.get("edges")
    if not isinstance(edges, list):
        return []

    media: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if isinstance(node, dict):
            media.append(node)
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
    if media_type == "video":
        item.update(_instagram_audio_metadata(entry))
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
    media_type = "video" if _is_instagram_video_entry(entry) or duration else "image"

    item: dict[str, Any] = {
        "id": media_id or _fallback_media_id(source_url),
        "source_url": source_url,
        "display_name": _instagram_caption_text(entry)
        or (f"Instagram reel {shortcode}" if shortcode else media_id),
        "media_type": media_type,
        "download_url": _best_instagram_video_url(entry) if media_type == "video" else None,
        "poster_url": thumbnail_url,
        "thumbnail_url": thumbnail_url,
        "poster_data_url": poster_data_url,
        "width": _optional_int(entry.get("original_width") or entry.get("width")),
        "height": _optional_int(entry.get("original_height") or entry.get("height")),
        "duration": duration,
        "browser_source": browser,
        "extractor": "instagram-web-api",
    }
    if media_type == "video":
        item.update(_instagram_audio_metadata(entry))
    return {key: value for key, value in item.items() if value is not None}


def _media_item_from_instagram_profile_node(
    entry: dict[str, Any],
    browser: str,
    thumbnail_fetcher: ThumbnailFetcher,
) -> dict[str, Any] | None:
    media_id = str(entry.get("id") or entry.get("pk") or "").strip()
    shortcode = str(entry.get("shortcode") or entry.get("code") or "").strip()
    if not media_id and not shortcode:
        return None

    image_url = _best_instagram_profile_image_url(entry)
    poster_data_url = _thumbnail_data_url(image_url, thumbnail_fetcher)
    is_video = _is_instagram_video_entry(entry)
    source_path = "reel" if is_video else "p"
    source_url = f"https://www.instagram.com/{source_path}/{shortcode}/" if shortcode else ""
    dimensions = entry.get("dimensions") if isinstance(entry.get("dimensions"), dict) else {}

    item: dict[str, Any] = {
        "id": media_id or _fallback_media_id(source_url),
        "source_url": source_url,
        "display_name": _instagram_profile_caption_text(entry)
        or _instagram_caption_text(entry)
        or (f"Instagram photo {shortcode}" if shortcode else media_id),
        "media_type": "video" if is_video else "image",
        "download_url": _best_instagram_video_url(entry)
        or str(entry.get("video_url") or image_url)
        if is_video
        else image_url,
        "poster_url": image_url,
        "thumbnail_url": image_url,
        "poster_data_url": poster_data_url,
        "width": _optional_int(
            dimensions.get("width") or entry.get("original_width") or entry.get("width")
        ),
        "height": _optional_int(
            dimensions.get("height") or entry.get("original_height") or entry.get("height")
        ),
        "browser_source": browser,
        "extractor": "instagram-web-api",
    }
    if is_video:
        item.update(_instagram_audio_metadata(entry))
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


def _best_instagram_profile_image_url(entry: dict[str, Any]) -> str | None:
    resources = entry.get("display_resources")
    if isinstance(resources, list):
        sorted_resources = sorted(
            (resource for resource in resources if isinstance(resource, dict)),
            key=lambda resource: (
                _optional_int(resource.get("config_width") or resource.get("width")) or 0
            )
            * (
                _optional_int(resource.get("config_height") or resource.get("height")) or 0
            ),
            reverse=True,
        )
        for resource in sorted_resources:
            url = resource.get("src") or resource.get("url")
            if isinstance(url, str) and url:
                return url

    display_url = entry.get("display_url")
    if isinstance(display_url, str) and display_url:
        return display_url

    thumbnail_src = entry.get("thumbnail_src")
    if isinstance(thumbnail_src, str) and thumbnail_src:
        return thumbnail_src
    thumbnail_url = _best_instagram_thumbnail_url(entry)
    if thumbnail_url:
        return thumbnail_url
    return None


def _best_instagram_video_url(entry: dict[str, Any]) -> str | None:
    video_versions = entry.get("video_versions")
    if not isinstance(video_versions, list):
        return None

    sorted_versions = sorted(
        (version for version in video_versions if isinstance(version, dict)),
        key=lambda version: (
            _optional_int(version.get("width")) or 0
        )
        * (_optional_int(version.get("height")) or 0),
        reverse=True,
    )
    for version in sorted_versions:
        url = version.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _instagram_audio_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    clips_metadata = entry.get("clips_metadata")
    if not isinstance(clips_metadata, dict):
        clips_metadata = {}

    music_info = _first_dict(clips_metadata.get("music_info"), entry.get("music_info"))
    music_asset = (
        _first_dict(music_info.get("music_asset_info")) if music_info is not None else None
    )
    original_sound_info = _first_dict(
        clips_metadata.get("original_sound_info"),
        entry.get("original_sound_info"),
    )
    audio_type = _first_string(clips_metadata.get("audio_type"), entry.get("audio_type"))
    audio_original = _instagram_audio_original(audio_type, music_info, original_sound_info)
    audio_label = _instagram_audio_label(music_asset, original_sound_info)

    metadata: dict[str, Any] = {
        "audio_original": audio_original,
        "audio_kind": _instagram_audio_kind(audio_original),
        "audio_label": audio_label,
        "audio_type": audio_type,
    }
    return {key: value for key, value in metadata.items() if value is not None}


def _instagram_audio_original(
    audio_type: str | None,
    music_info: dict[str, Any] | None,
    original_sound_info: dict[str, Any] | None,
) -> bool | None:
    explicit_original = _first_bool(
        original_sound_info.get("is_original_audio") if original_sound_info else None,
        original_sound_info.get("is_creator_audio") if original_sound_info else None,
    )
    if explicit_original is not None:
        return explicit_original

    normalized_audio_type = audio_type.lower() if audio_type else ""
    if music_info is not None or "music" in normalized_audio_type or "licensed" in normalized_audio_type:
        return False
    if original_sound_info is not None or "original" in normalized_audio_type:
        return True
    return None


def _instagram_audio_kind(audio_original: bool | None) -> str | None:
    if audio_original is True:
        return "original"
    if audio_original is False:
        return "reused_or_music"
    return None


def _instagram_audio_label(
    music_asset: dict[str, Any] | None,
    original_sound_info: dict[str, Any] | None,
) -> str | None:
    source = music_asset or original_sound_info
    if source is None:
        return None

    title = _first_string(
        source.get("title"),
        source.get("audio_cluster_title"),
        source.get("original_audio_title"),
        source.get("display_name"),
    )
    artist = _first_string(
        source.get("artist_name"),
        source.get("display_artist"),
        source.get("username"),
    )
    ig_artist = source.get("ig_artist")
    if artist is None and isinstance(ig_artist, dict):
        artist = _first_string(ig_artist.get("full_name"), ig_artist.get("username"))

    if title and artist:
        return f"{title} - {artist}"
    return title or artist


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _is_instagram_video_entry(entry: dict[str, Any]) -> bool:
    media_type = entry.get("media_type")
    return (
        bool(entry.get("is_video"))
        or media_type == 2
        or str(media_type) == "2"
        or bool(entry.get("video_versions"))
    )


def _instagram_caption_text(entry: dict[str, Any]) -> str | None:
    caption = entry.get("caption")
    if isinstance(caption, dict):
        text = caption.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    return None


def _instagram_profile_caption_text(entry: dict[str, Any]) -> str | None:
    caption = entry.get("edge_media_to_caption")
    if not isinstance(caption, dict):
        return None
    edges = caption.get("edges")
    if not isinstance(edges, list):
        return None
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        text = node.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _dedupe_media_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identifiers = {
            str(value).strip()
            for value in (item.get("id"), item.get("source_url"))
            if str(value or "").strip()
        }
        if identifiers and identifiers.intersection(seen):
            continue
        seen.update(identifiers)
        deduped.append(item)
    return deduped


def _profile_pagination_metadata(
    metadata_by_surface: dict[str, dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    next_cursor_state = {
        surface: cursor
        for surface, metadata in metadata_by_surface.items()
        if (cursor := _next_profile_cursor(metadata)) is not None
    }
    pagination: dict[str, Any] = {
        "batch_size": limit,
        "scan_surfaces": list(metadata_by_surface.keys()),
        "has_next_batch": bool(next_cursor_state),
    }
    if next_cursor_state:
        pagination["next_cursor"] = _encode_scan_cursor(next_cursor_state)
    return pagination


def _next_profile_cursor(metadata: dict[str, Any]) -> str | None:
    if metadata.get("more_available") is True:
        for key in ("next_max_id", "profile_grid_items_cursor"):
            raw_cursor = metadata.get(key)
            if isinstance(raw_cursor, str) and raw_cursor.strip():
                return raw_cursor.strip()

    paging_info = metadata.get("paging_info")
    if isinstance(paging_info, dict) and paging_info.get("more_available") is True:
        raw_cursor = paging_info.get("max_id")
        if isinstance(raw_cursor, str) and raw_cursor.strip():
            return raw_cursor.strip()

    page_info = _graphql_page_info(metadata)
    if isinstance(page_info, dict) and page_info.get("has_next_page") is True:
        raw_cursor = page_info.get("end_cursor")
        if isinstance(raw_cursor, str) and raw_cursor.strip():
            return raw_cursor.strip()

    return None


def _graphql_page_info(metadata: dict[str, Any]) -> dict[str, Any] | None:
    user = ((metadata.get("data") or {}).get("user") or {})
    for edge_collection_name in (
        "edge_owner_to_timeline_media",
        "edge_user_to_photos_of_you",
    ):
        timeline = user.get(edge_collection_name)
        if not isinstance(timeline, dict):
            continue
        page_info = timeline.get("page_info")
        if isinstance(page_info, dict):
            return page_info

    page_info = metadata.get("page_info")
    if isinstance(page_info, dict):
        return page_info
    return None


def _encode_scan_cursor(cursor_state: dict[str, str]) -> str:
    payload = json.dumps(cursor_state, separators=(",", ":")).encode("utf-8")
    return b64encode(payload).decode("ascii")


def _decode_scan_cursor(cursor: str | None) -> dict[str, str]:
    if cursor is None or not cursor.strip():
        return {}

    try:
        raw_payload = b64decode(cursor.encode("ascii"), validate=True)
        payload = json.loads(raw_payload.decode("utf-8"))
    except (BinasciiError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise InstagramBrowserScanError("Invalid Instagram batch cursor.") from error

    if not isinstance(payload, dict):
        raise InstagramBrowserScanError("Invalid Instagram batch cursor.")

    cursor_state: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            cursor_state[key] = value.strip()
    return cursor_state


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


def _profile_tagged_username(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[1] == "tagged":
        return parts[0]
    return None


def _profile_surface_username(url: str) -> str | None:
    return (
        _profile_reels_username(url)
        or _profile_tagged_username(url)
        or _profile_username(url)
    )


def _profile_username(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 1:
        return None
    username = parts[0]
    if username.lower() in {
        "accounts",
        "direct",
        "explore",
        "p",
        "reel",
        "reels",
        "stories",
        "tv",
    }:
        return None
    return username


def _validate_browser(browser: str) -> str:
    normalized = browser.strip().lower()
    if normalized not in SUPPORTED_BROWSER_COOKIE_SOURCES:
        supported = ", ".join(sorted(SUPPORTED_BROWSER_COOKIE_SOURCES))
        raise InstagramBrowserScanError(
            f"Unsupported browser cookie source. Use one of: {supported}."
        )
    return normalized


def _validate_scan_mode(scan_mode: str) -> InstagramScanMode:
    normalized = scan_mode.strip().lower()
    if normalized not in SUPPORTED_INSTAGRAM_SCAN_MODES:
        supported = ", ".join(sorted(SUPPORTED_INSTAGRAM_SCAN_MODES))
        raise InstagramBrowserScanError(
            f"Unsupported Instagram scan target. Use one of: {supported}."
        )
    return cast(InstagramScanMode, normalized)


def _validate_scan_limit(limit: int) -> int:
    try:
        normalized = int(limit)
    except (TypeError, ValueError) as error:
        raise InstagramBrowserScanError("Instagram scan limit must be a number.") from error
    if normalized < 1 or normalized > MAX_PROFILE_REELS_PAGE_SIZE:
        raise InstagramBrowserScanError(
            f"Instagram scan limit must be between 1 and {MAX_PROFILE_REELS_PAGE_SIZE}."
        )
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
