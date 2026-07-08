from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from lorasuite_engine.instagram_browser import (
    InstagramBrowserScanError,
    scan_instagram_url_with_browser_cookies,
)
from lorasuite_engine.models import MediaType, SourceKind


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (80, 120), color=(90, 40, 130)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_instagram_browser_scan_caches_thumbnail_candidates(tmp_path):
    calls: list[tuple[str, str]] = []

    def fake_metadata(url: str, browser: str) -> dict:
        calls.append((url, browser))
        return {
            "id": "C123",
            "title": "browser reel",
            "webpage_url": "https://www.instagram.com/reel/C123/",
            "duration": 8.4,
            "width": 1080,
            "height": 1920,
            "url": "https://cdninstagram.example/video.mp4",
            "thumbnail": "https://cdninstagram.example/poster.jpg",
        }

    def fake_thumbnail(url: str) -> tuple[bytes, str]:
        assert url == "https://cdninstagram.example/poster.jpg"
        return jpeg_bytes(), "image/jpeg"

    result = scan_instagram_url_with_browser_cookies(
        "https://www.instagram.com/reel/C123/",
        tmp_path / "vault",
        browser="chrome",
        metadata_extractor=fake_metadata,
        thumbnail_fetcher=fake_thumbnail,
    )

    assert calls == [("https://www.instagram.com/reel/C123/", "chrome")]
    assert len(result.candidates) == 2
    video = result.candidates[0]
    poster = result.candidates[1]
    assert video.source_kind == SourceKind.INSTAGRAM
    assert video.media_type == MediaType.VIDEO
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).exists()
    assert poster.media_type == MediaType.IMAGE
    assert poster.selected is True
    assert poster.metadata_json["local_import_path"] == str(video.poster_asset_path)
    assert video.metadata_json["browser_source"] == "chrome"


def test_instagram_browser_scan_rejects_non_instagram_urls(tmp_path):
    with pytest.raises(InstagramBrowserScanError, match="Instagram URL"):
        scan_instagram_url_with_browser_cookies(
            "https://example.com/reel/C123/",
            tmp_path / "vault",
            metadata_extractor=lambda _url, _browser: {},
        )
