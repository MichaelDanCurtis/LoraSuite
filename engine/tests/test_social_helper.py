from pathlib import Path

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


def test_instagram_helper_creates_video_and_poster_candidates(tmp_path):
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
                "width": 1080,
                "height": 1920,
                "duration": 9.5,
            }
        ],
    }

    result = scan_instagram_helper_payload(
        payload,
        tmp_path / "vault",
        include_video_posters_as_image_candidates=True,
    )

    assert len(result.candidates) == 2
    video = result.candidates[0]
    poster_candidate = result.candidates[1]
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
