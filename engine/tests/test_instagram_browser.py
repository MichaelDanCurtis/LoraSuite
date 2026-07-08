import ssl
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import lorasuite_engine.instagram_browser as instagram_browser
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
    assert len(result.candidates) == 3
    video = result.candidates[0]
    poster = result.candidates[1]
    audio = result.candidates[2]
    assert video.source_kind == SourceKind.INSTAGRAM
    assert video.media_type == MediaType.VIDEO
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).exists()
    assert poster.media_type == MediaType.IMAGE
    assert poster.selected is True
    assert poster.metadata_json["local_import_path"] == str(video.poster_asset_path)
    assert audio.media_type == MediaType.AUDIO
    assert audio.selected is False
    assert audio.metadata_json["source_video_candidate_id"] == video.id
    assert audio.metadata_json["asset_role"] == "video_audio"
    assert video.metadata_json["browser_source"] == "chrome"


def test_instagram_browser_scan_reads_profile_reels_tab_with_browser_cookies(tmp_path):
    calls: list[tuple[str, str, int]] = []

    def unsupported_ytdlp_metadata(_url: str, _browser: str) -> dict:
        raise AssertionError("profile reels scans should not use yt-dlp metadata")

    def fake_profile_reels(username: str, browser: str, page_size: int) -> dict:
        calls.append((username, browser, page_size))
        return {
            "items": [
                {
                    "media": {
                        "id": "3758183871762427742_33827583",
                        "code": "DQnwFHVAG9e",
                        "caption": {"text": "first reel caption"},
                        "media_type": 2,
                        "original_width": 720,
                        "original_height": 1280,
                        "video_duration": 12.75,
                        "video_versions": [
                            {
                                "url": "https://cdninstagram.example/reel-small.mp4",
                                "width": 360,
                                "height": 640,
                            },
                            {
                                "url": "https://cdninstagram.example/reel-large.mp4",
                                "width": 720,
                                "height": 1280,
                            },
                        ],
                        "image_versions2": {
                            "candidates": [
                                {
                                    "url": "https://cdninstagram.example/reel-small.jpg",
                                    "width": 320,
                                    "height": 568,
                                },
                                {
                                    "url": "https://cdninstagram.example/reel-large.jpg",
                                    "width": 720,
                                    "height": 1280,
                                },
                            ]
                        },
                    }
                }
            ]
        }

    def fake_thumbnail(url: str) -> tuple[bytes, str]:
        assert url == "https://cdninstagram.example/reel-large.jpg"
        return jpeg_bytes(), "image/jpeg"

    result = scan_instagram_url_with_browser_cookies(
        "https://www.instagram.com/marysuecurtis/reels/",
        tmp_path / "vault",
        browser="chrome",
        metadata_extractor=unsupported_ytdlp_metadata,
        profile_reels_fetcher=fake_profile_reels,
        thumbnail_fetcher=fake_thumbnail,
    )

    assert calls == [("marysuecurtis", "chrome", 24)]
    assert len(result.candidates) == 3
    video = result.candidates[0]
    poster = result.candidates[1]
    audio = result.candidates[2]
    assert video.source_kind == SourceKind.INSTAGRAM
    assert video.source_locator == "https://www.instagram.com/reel/DQnwFHVAG9e/"
    assert video.media_type == MediaType.VIDEO
    assert video.display_name == "first reel caption"
    assert video.width == 720
    assert video.height == 1280
    assert video.duration == 12.75
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).exists()
    assert video.metadata_json["browser_source"] == "chrome"
    assert video.metadata_json["extractor"] == "instagram-web-api"
    assert video.metadata_json["download_url"] == "https://cdninstagram.example/reel-large.mp4"
    assert poster.media_type == MediaType.IMAGE
    assert poster.selected is True
    assert audio.media_type == MediaType.AUDIO
    assert audio.selected is False
    assert audio.metadata_json["download_url"] == "https://cdninstagram.example/reel-large.mp4"


def test_instagram_browser_scan_reads_profile_photos_with_browser_cookies(tmp_path):
    profile_calls: list[tuple[str, str]] = []
    reels_calls: list[tuple[str, str, int]] = []

    def unsupported_ytdlp_metadata(_url: str, _browser: str) -> dict:
        raise AssertionError("profile scans should not use yt-dlp metadata")

    def fake_profile(username: str, browser: str) -> dict:
        profile_calls.append((username, browser))
        return {
            "data": {
                "user": {
                    "edge_owner_to_timeline_media": {
                        "edges": [
                            {
                                "node": {
                                    "id": "photo_1",
                                    "shortcode": "PHOTO123",
                                    "display_url": "https://cdninstagram.example/photo-large.jpg",
                                    "dimensions": {"width": 1080, "height": 1350},
                                    "is_video": False,
                                    "edge_media_to_caption": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "text": "profile photo caption",
                                                }
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    }
                }
            }
        }

    def fake_profile_reels(username: str, browser: str, page_size: int) -> dict:
        reels_calls.append((username, browser, page_size))
        return {"items": []}

    def fake_thumbnail(url: str) -> tuple[bytes, str]:
        assert url == "https://cdninstagram.example/photo-large.jpg"
        return jpeg_bytes(), "image/jpeg"

    result = scan_instagram_url_with_browser_cookies(
        "https://www.instagram.com/marysuecurtis/",
        tmp_path / "vault",
        browser="chrome",
        metadata_extractor=unsupported_ytdlp_metadata,
        profile_fetcher=fake_profile,
        profile_reels_fetcher=fake_profile_reels,
        thumbnail_fetcher=fake_thumbnail,
    )

    assert profile_calls == [("marysuecurtis", "chrome")]
    assert reels_calls == [("marysuecurtis", "chrome", 24)]
    assert len(result.candidates) == 1
    photo = result.candidates[0]
    assert photo.source_kind == SourceKind.INSTAGRAM
    assert photo.source_locator == "https://www.instagram.com/p/PHOTO123/"
    assert photo.media_type == MediaType.IMAGE
    assert photo.display_name == "profile photo caption"
    assert photo.width == 1080
    assert photo.height == 1350
    assert photo.thumbnail_path is not None
    assert Path(photo.thumbnail_path).exists()
    assert photo.selected is True
    assert photo.metadata_json["browser_source"] == "chrome"
    assert photo.metadata_json["extractor"] == "instagram-web-api"
    assert photo.metadata_json["download_url"] == "https://cdninstagram.example/photo-large.jpg"


def test_instagram_browser_scan_rejects_non_instagram_urls(tmp_path):
    with pytest.raises(InstagramBrowserScanError, match="Instagram URL"):
        scan_instagram_url_with_browser_cookies(
            "https://example.com/reel/C123/",
            tmp_path / "vault",
            metadata_extractor=lambda _url, _browser: {},
        )


def test_thumbnail_fetch_uses_engine_ssl_context(monkeypatch):
    seen: dict[str, object] = {}

    class FakeHeaders:
        def get_content_type(self) -> str:
            return "image/jpeg"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return jpeg_bytes()

    def fake_urlopen(_request, *, timeout: int, context: ssl.SSLContext):
        seen["timeout"] = timeout
        seen["context"] = context
        return FakeResponse()

    monkeypatch.setattr(instagram_browser, "urlopen", fake_urlopen)

    thumbnail_bytes, content_type = instagram_browser._fetch_thumbnail(
        "https://cdninstagram.example/poster.jpg"
    )

    assert thumbnail_bytes
    assert content_type == "image/jpeg"
    assert seen["timeout"] == 30
    assert isinstance(seen["context"], ssl.SSLContext)
