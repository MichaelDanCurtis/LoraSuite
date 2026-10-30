from pathlib import Path
from base64 import b64encode
from io import BytesIO

import pytest
from PIL import Image

from lorasuite_engine.models import MediaType, SourceKind
from lorasuite_engine.social_helper import scan_instagram_helper_payload


def test_instagram_helper_rejects_token_like_payload_keys(tmp_path):
    payload = {
        "helper_version": "fixture",
        "headers": {"cookie": "sessionid=secret"},
        "media": [],
    }

    with pytest.raises(ValueError, match="token-like field"):
        scan_instagram_helper_payload(payload, tmp_path / "vault")


def test_instagram_helper_creates_video_poster_and_audio_candidates(tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (120, 160), color=(80, 40, 120)).save(poster)
    payload = {
        "helper_version": "fixture",
        "media": [
            {
                "id": "ig_video_1",
                "source_url": "https://www.instagram.com/reel/example/",
                "display_name": "example reel",
                "media_type": "video",
                "poster_path": str(poster),
                "download_url": "https://cdninstagram.example/video.mp4",
                "width": 1080,
                "height": 1920,
                "duration": 9.5,
                "audio_original": False,
                "audio_kind": "reused_or_music",
                "audio_label": "Trending sound",
            }
        ],
    }

    result = scan_instagram_helper_payload(
        payload,
        tmp_path / "vault",
        include_video_posters_as_image_candidates=True,
    )

    assert len(result.candidates) == 3
    video = result.candidates[0]
    poster_candidate = result.candidates[1]
    audio_candidate = result.candidates[2]
    assert video.source_kind == SourceKind.INSTAGRAM
    assert video.media_type == MediaType.VIDEO
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).exists()
    assert video.selected is False
    assert poster_candidate.media_type == MediaType.IMAGE
    assert poster_candidate.selected is True
    assert poster_candidate.metadata_json["local_import_path"] == str(
        video.poster_asset_path
    )
    assert poster_candidate.metadata_json["source_video_candidate_id"] == video.id
    assert audio_candidate.media_type == MediaType.AUDIO
    assert audio_candidate.duration == video.duration
    assert audio_candidate.thumbnail_path == video.poster_asset_path
    assert audio_candidate.selected is False
    assert audio_candidate.metadata_json["source_video_candidate_id"] == video.id
    assert audio_candidate.metadata_json["asset_role"] == "video_audio"
    assert audio_candidate.metadata_json["download_url"] == "https://cdninstagram.example/video.mp4"
    assert video.metadata_json["audio_original"] is False
    assert video.metadata_json["audio_kind"] == "reused_or_music"
    assert video.metadata_json["audio_label"] == "Trending sound"
    assert audio_candidate.metadata_json["audio_original"] is False
    assert video.metadata_json["source_bundle_key"] == "instagram:post:example"
    assert poster_candidate.metadata_json["source_bundle_key"] == "instagram:post:example"
    assert audio_candidate.metadata_json["source_bundle_key"] == "instagram:post:example"
    assert len({candidate.id for candidate in result.candidates}) == 3

    repeated = scan_instagram_helper_payload(
        payload,
        tmp_path / "vault",
        include_video_posters_as_image_candidates=True,
    )
    assert [candidate.id for candidate in repeated.candidates] == [
        candidate.id for candidate in result.candidates
    ]


def test_instagram_helper_caches_poster_data_url_without_persisting_data(tmp_path):
    poster_bytes = BytesIO()
    Image.new("RGB", (64, 96), color=(20, 90, 140)).save(poster_bytes, "JPEG")
    poster_data_url = (
        "data:image/jpeg;base64," + b64encode(poster_bytes.getvalue()).decode("ascii")
    )
    payload = {
        "helper_version": "session-helper-v0",
        "media": [
            {
                "id": "ig_data_url_video",
                "source_url": "https://www.instagram.com/reel/data-url/",
                "display_name": "data url reel",
                "media_type": "video",
                "poster_url": "https://cdninstagram.example/poster.jpg",
                "poster_data_url": poster_data_url,
                "width": 64,
                "height": 96,
                "duration": 4.0,
            }
        ],
    }

    result = scan_instagram_helper_payload(payload, tmp_path / "vault")

    assert len(result.candidates) == 3
    video = result.candidates[0]
    poster_candidate = result.candidates[1]
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).read_bytes() == poster_bytes.getvalue()
    assert poster_candidate.metadata_json["local_import_path"] == str(
        video.poster_asset_path
    )
    assert "poster_data_url" not in video.metadata_json
    assert "poster_data_url" not in poster_candidate.metadata_json
    assert video.metadata_json["poster_source_url"] == "https://cdninstagram.example/poster.jpg"
