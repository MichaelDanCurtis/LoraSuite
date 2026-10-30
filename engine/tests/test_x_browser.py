from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import lorasuite_engine.x_browser as x_browser
from lorasuite_engine.models import MediaType, SourceKind
from lorasuite_engine.x_browser import XBrowserScanError, scan_x_url_with_browser_cookies


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (80, 120), color=(30, 80, 140)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_x_browser_scan_uses_low_bandwidth_previews_and_candidate_lanes(tmp_path: Path) -> None:
    calls = []

    def metadata(url: str, browser: str, offset: int, limit: int):
        calls.append((url, browser, offset, limit))
        return [
            {
                "tweet_id": "100",
                "download_url": "https://pbs.twimg.com/media/photo?format=jpg&name=orig",
                "extension": "jpg",
                "content": "portrait post",
                "author": {"name": "subject", "nick": "Subject"},
                "date": "2026-05-10T12:00:00+00:00",
                "width": 1600,
                "height": 2000,
            },
            {
                "tweet_id": "101",
                "download_url": "https://video.twimg.com/ext_tw_video/101/pu/vid/720x1280/clip.mp4",
                "thumbnail": "https://pbs.twimg.com/ext_tw_video_thumb/101/pu/img/poster.jpg",
                "extension": "mp4",
                "content": "speaking clip",
                "username": "subject",
                "date": "2026-05-11T12:00:00+00:00",
                "duration": 8.5,
            },
        ]

    fetched = []

    def thumbnail(url: str):
        fetched.append(url)
        return jpeg_bytes(), "image/jpeg"

    result = scan_x_url_with_browser_cookies(
        "https://x.com/subject",
        tmp_path / "vault",
        browser="chrome",
        limit=2,
        metadata_extractor=metadata,
        thumbnail_fetcher=thumbnail,
    )

    assert calls == [("https://x.com/subject/media", "chrome", 0, 2)]
    assert "name=small" in fetched[0]
    assert fetched[1].endswith("poster.jpg")
    assert result.metadata_json["next_cursor"] == "2"
    assert [candidate.media_type for candidate in result.candidates] == [
        MediaType.IMAGE,
        MediaType.VIDEO,
        MediaType.IMAGE,
        MediaType.AUDIO,
    ]
    assert all(candidate.source_kind == SourceKind.X_TWITTER for candidate in result.candidates)
    video = result.candidates[1]
    audio = result.candidates[3]
    assert video.metadata_json["download_url"].endswith("clip.mp4")
    assert audio.metadata_json["audio_original"] is True
    assert audio.selected is False


def test_x_browser_scan_pages_and_filters_dates_before_thumbnail_fetch(tmp_path: Path) -> None:
    fetched = []

    def metadata(_url: str, _browser: str, offset: int, limit: int):
        assert (offset, limit) == (24, 24)
        return [
            {"tweet_id": "old", "download_url": "https://pbs.twimg.com/media/old.jpg", "date": "2020-01-01T00:00:00Z"},
            {"tweet_id": "new", "download_url": "https://pbs.twimg.com/media/new.jpg", "date": "2026-06-01T00:00:00Z"},
        ]

    result = scan_x_url_with_browser_cookies(
        "https://twitter.com/subject",
        tmp_path / "vault",
        cursor="24",
        date_from=date(2026, 1, 1),
        metadata_extractor=metadata,
        thumbnail_fetcher=lambda url: (fetched.append(url) or jpeg_bytes(), "image/jpeg"),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "X post new"
    assert len(fetched) == 1
    assert result.metadata_json["batch_offset"] == 24
    assert result.metadata_json["next_cursor"] is None


def test_x_video_without_remote_thumbnail_still_gets_an_image_lane(tmp_path: Path) -> None:
    result = scan_x_url_with_browser_cookies(
        "https://x.com/subject",
        tmp_path / "vault",
        metadata_extractor=lambda *_args: [{
            "tweet_id": "video-only",
            "download_url": "https://video.twimg.com/ext_tw_video/video-only/clip.mp4",
            "extension": "mp4",
            "content": "video without poster metadata",
        }],
        thumbnail_fetcher=lambda _url: pytest.fail("no remote thumbnail should be fetched"),
    )

    assert [candidate.media_type for candidate in result.candidates] == [
        MediaType.VIDEO,
        MediaType.IMAGE,
        MediaType.AUDIO,
    ]
    video, poster, audio = result.candidates
    assert poster.metadata_json["source_video_candidate_id"] == video.id
    assert poster.metadata_json["asset_role"] == "video_poster"
    assert poster.metadata_json["materialize_from_video"] is True
    assert poster.thumbnail_path is None
    assert audio.metadata_json["source_video_candidate_id"] == video.id


def test_gallery_dl_metadata_command_uses_browser_cookie_and_range(monkeypatch) -> None:
    output = '[[3, "https://pbs.twimg.com/media/a.jpg", {"tweet_id":"1","extension":"jpg"}]]\n'

    def fake_run(command, **options):
        assert command[:3] == [x_browser.sys.executable, "-m", "gallery_dl"]
        assert command[command.index("--cookies-from-browser") + 1] == "firefox"
        assert command[command.index("--range") + 1] == "11-15"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(x_browser.subprocess, "run", fake_run)

    entries = x_browser._extract_gallery_metadata("https://x.com/subject/media", "firefox", 10, 5)

    assert entries[0]["tweet_id"] == "1"
    assert entries[0]["download_url"].endswith("a.jpg")


@pytest.mark.parametrize("url", ["http://x.com/name", "https://example.com/name", "javascript:alert(1)"])
def test_x_browser_scan_rejects_unsafe_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(XBrowserScanError, match="https://x.com"):
        scan_x_url_with_browser_cookies(url, tmp_path / "vault", metadata_extractor=lambda *_args: [])
