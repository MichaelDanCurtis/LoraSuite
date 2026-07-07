import pytest

from lorasuite_engine.models import SegmentCreate
from lorasuite_engine.segments import guidance_for_segment, validate_segment_range


def test_segment_requires_positive_end_after_start():
    with pytest.raises(ValueError, match="end_seconds must be greater than start_seconds"):
        validate_segment_range(start_seconds=8.0, end_seconds=8.0)


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
