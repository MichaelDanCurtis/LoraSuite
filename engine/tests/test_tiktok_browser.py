from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import lorasuite_engine.tiktok_browser as tiktok_browser
from lorasuite_engine.models import MediaType, SourceKind
from lorasuite_engine.tiktok_browser import (
    TikTokBrowserScanError,
    scan_tiktok_url_with_browser_cookies,
)


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (80, 120), color=(80, 30, 140)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_tiktok_scan_builds_video_poster_and_original_audio_lanes(tmp_path: Path) -> None:
    calls = []

    def metadata(url: str, browser: str, offset: int, limit: int):
        calls.append((url, browser, offset, limit))
        return [
            {
                "id": "123",
                "url": "https://www.tiktok.com/@subject/video/123",
                "uploader": "subject",
                "channel": "Subject",
                "description": "speaking to camera",
                "timestamp": 1781000000,
                "duration": 12.5,
                "track": "original sound - Subject",
                "artists": ["Subject"],
                "thumbnails": [{"id": "cover", "url": "https://cdn.example/cover.jpg"}],
            }
        ]

    result = scan_tiktok_url_with_browser_cookies(
        "https://www.tiktok.com/@subject",
        tmp_path / "vault",
        browser="chrome",
        limit=1,
        metadata_extractor=metadata,
        thumbnail_fetcher=lambda _url: (jpeg_bytes(), "image/jpeg"),
    )

    assert calls == [("https://www.tiktok.com/@subject", "chrome", 0, 1)]
    assert result.metadata_json["next_cursor"] == "1"
    assert [candidate.media_type for candidate in result.candidates] == [
        MediaType.VIDEO,
        MediaType.IMAGE,
        MediaType.AUDIO,
    ]
    assert all(candidate.source_kind == SourceKind.TIKTOK for candidate in result.candidates)
    video, poster, audio = result.candidates
    assert video.metadata_json["download_url"] is None
    assert video.metadata_json["source_url"].endswith("/video/123")
    assert poster.selected is True
    assert audio.selected is False
    assert audio.metadata_json["audio_original"] is True
    assert audio.metadata_json["audio_kind"] == "original"


def test_tiktok_scan_marks_reused_music_audio_and_filters_dates(tmp_path: Path) -> None:
    fetched = []

    def metadata(_url: str, _browser: str, offset: int, limit: int):
        assert (offset, limit) == (24, 24)
        return [
            {
                "id": "old",
                "url": "https://www.tiktok.com/@subject/video/old",
                "timestamp": 1577836800,
                "thumbnails": [{"url": "https://cdn.example/old.jpg"}],
            },
            {
                "id": "new",
                "url": "https://www.tiktok.com/@subject/video/new",
                "timestamp": 1780272000,
                "track": "popular song",
                "artists": ["Someone Else"],
                "thumbnails": [{"url": "https://cdn.example/new.jpg"}],
            },
        ]

    result = scan_tiktok_url_with_browser_cookies(
        "https://www.tiktok.com/@subject",
        tmp_path / "vault",
        cursor="24",
        date_from=date(2026, 1, 1),
        metadata_extractor=metadata,
        thumbnail_fetcher=lambda url: (fetched.append(url) or jpeg_bytes(), "image/jpeg"),
    )

    assert len(result.candidates) == 3
    assert fetched == ["https://cdn.example/new.jpg"]
    audio = result.candidates[2]
    assert audio.metadata_json["audio_original"] is False
    assert audio.metadata_json["audio_kind"] == "reused_or_music"
    assert audio.metadata_json["audio_label"] == "popular song"
    assert result.metadata_json["batch_offset"] == 24
    assert result.metadata_json["next_cursor"] is None


def test_yt_dlp_metadata_command_uses_flat_playlist_cookie_and_range(monkeypatch) -> None:
    output = '{"entries":[{"id":"1","url":"https://www.tiktok.com/@subject/video/1"}]}'

    def fake_run(command, **options):
        assert command[:3] == [tiktok_browser.sys.executable, "-m", "yt_dlp"]
        assert "--flat-playlist" in command
        assert command[command.index("--cookies-from-browser") + 1] == "firefox"
        assert command[command.index("--playlist-start") + 1] == "11"
        assert command[command.index("--playlist-end") + 1] == "15"
        assert options["timeout"] == 180
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(tiktok_browser.subprocess, "run", fake_run)

    entries = tiktok_browser.extract_yt_dlp_metadata(
        "https://www.tiktok.com/@subject",
        "firefox",
        10,
        5,
    )

    assert entries[0]["id"] == "1"


@pytest.mark.parametrize(
    "url",
    ["http://www.tiktok.com/@name", "https://example.com/@name", "javascript:alert(1)"],
)
def test_tiktok_scan_rejects_unsafe_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(TikTokBrowserScanError, match="https://www.tiktok.com"):
        scan_tiktok_url_with_browser_cookies(
            url,
            tmp_path / "vault",
            metadata_extractor=lambda *_args: [],
        )
