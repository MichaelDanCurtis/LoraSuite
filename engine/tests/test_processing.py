from pathlib import Path

import pytest
from pydantic import ValidationError

from lorasuite_engine.models import (
    AssetRole,
    DerivativeType,
    MediaItem,
    MediaType,
    ProcessingJob,
    ProcessingJobStatus,
    SourceKind,
    VideoBreakdownOptions,
)


def test_processing_job_serializes_derivative_outputs():
    derivative = MediaItem(
        source_id="source_1",
        raw_path=Path("/vault/derivatives/frames/frame_00001.png"),
        media_type=MediaType.IMAGE,
        sha256="frame_hash",
        metadata_json={
            "asset_role": AssetRole.DERIVATIVE,
            "derivative_type": DerivativeType.VIDEO_FRAME,
            "source_media_item_id": "media_video_1",
        },
    )
    job = ProcessingJob(
        job_type="video_breakdown",
        source_media_item_ids=["media_video_1"],
        status=ProcessingJobStatus.COMPLETE,
        derived_media_items=[derivative],
        progress_message="Video breakdown complete",
    )

    payload = job.model_dump(mode="json")

    assert payload["job_type"] == "video_breakdown"
    assert payload["status"] == "complete"
    assert payload["derived_media_items"][0]["metadata_json"]["asset_role"] == "derivative"
    assert payload["derived_media_items"][0]["metadata_json"]["derivative_type"] == "video_frame"


def test_video_breakdown_options_have_safe_defaults():
    options = VideoBreakdownOptions()

    assert options.frames_per_second == 1
    assert options.max_frame_count == 6
    assert options.extract_audio is True
    assert options.generate_frames is True


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("frames_per_second", True),
        ("frames_per_second", "2"),
        ("frames_per_second", 2.0),
        ("max_frame_count", True),
        ("max_frame_count", "2"),
        ("max_frame_count", 2.0),
    ],
)
def test_video_breakdown_options_reject_coerced_integer_values(field_name, invalid_value):
    with pytest.raises(ValidationError):
        VideoBreakdownOptions(**{field_name: invalid_value})
