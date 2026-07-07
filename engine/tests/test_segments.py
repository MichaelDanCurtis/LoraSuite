import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from lorasuite_engine.models import MediaItem, MediaType, Segment, SegmentCreate
from lorasuite_engine.segments import create_segment, guidance_for_segment, validate_segment_range


def test_segment_requires_positive_end_after_start():
    with pytest.raises(ValueError, match="end_seconds must be greater than start_seconds"):
        validate_segment_range(start_seconds=8.0, end_seconds=8.0)


def test_segment_range_rejects_non_finite_values():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="segment seconds must be finite"):
            validate_segment_range(start_seconds=value, end_seconds=2.0)


def test_segment_model_rejects_negative_start():
    with pytest.raises(ValidationError):
        SegmentCreate(media_item_id="media-1", start_seconds=-1.0, end_seconds=2.0)


def test_segment_model_rejects_end_at_start():
    with pytest.raises(ValidationError):
        SegmentCreate(media_item_id="media-1", start_seconds=8.0, end_seconds=8.0)


def test_segment_model_rejects_non_finite_values():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            SegmentCreate(media_item_id="media-1", start_seconds=value, end_seconds=2.0)


def test_segment_supports_any_intent_combination():
    segment = SegmentCreate(
        media_item_id="media-1",
        start_seconds=2.5,
        end_seconds=14.0,
        label="good face range",
        notes="clean lighting",
        use_for_image=True,
        use_for_video=False,
        use_for_voice=True,
    )

    assert segment.use_for_image is True
    assert segment.use_for_video is False
    assert segment.use_for_voice is True


def test_create_segment_generates_id_and_keeps_payload_fields():
    payload = SegmentCreate(
        media_item_id="media-1",
        start_seconds=1.5,
        end_seconds=6.0,
        label="usable motion",
        notes="steady camera",
        quality_flags=["clean"],
        use_for_image=True,
        use_for_video=True,
        use_for_voice=False,
    )

    segment = create_segment(payload)

    assert isinstance(segment, Segment)
    assert segment.id.startswith("segment_")
    assert segment.media_item_id == payload.media_item_id
    assert segment.start_seconds == payload.start_seconds
    assert segment.end_seconds == payload.end_seconds
    assert segment.label == payload.label
    assert segment.quality_flags == payload.quality_flags
    assert segment.use_for_image == payload.use_for_image
    assert segment.use_for_video == payload.use_for_video
    assert segment.use_for_voice == payload.use_for_voice


def test_guidance_mentions_enabled_intents():
    segment = SegmentCreate(
        media_item_id="media-1",
        start_seconds=0.0,
        end_seconds=12.0,
        use_for_image=True,
        use_for_video=True,
        use_for_voice=False,
    )

    guidance = guidance_for_segment(segment)

    assert any("Extract sparse keyframes" in line for line in guidance)
    assert any("Keep the clip coherent" in line for line in guidance)
    assert any("Voice export is off" in line for line in guidance)


def test_media_item_json_dump_uses_json_safe_values():
    item = MediaItem(
        source_id="source-1",
        raw_path=Path("vault/raw/image.png"),
        media_type=MediaType.IMAGE,
        sha256="abc123",
        created_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )

    dumped = item.model_dump(mode="json")

    json.dumps(dumped)
    assert dumped["raw_path"] == "vault/raw/image.png"
    assert dumped["media_type"] == "image"
    assert isinstance(dumped["created_at"], str)
