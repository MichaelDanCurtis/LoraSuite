from pathlib import Path

import pytest
from PIL import Image
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
from lorasuite_engine.vault import VaultService


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


def test_vault_can_retrieve_imported_media_item_by_id(tmp_path):
    source_image = tmp_path / "source.png"
    Image.new("RGB", (32, 32), color=(90, 20, 120)).save(source_image)
    vault = VaultService(tmp_path / "vault")
    imported = vault.import_local_paths([source_image]).media_items[0]

    found = vault.get_media_item(imported.id)

    assert found == imported


def test_vault_appends_derivative_media_items_without_new_source(tmp_path):
    source_image = tmp_path / "source.png"
    derivative_image = tmp_path / "frame.png"
    Image.new("RGB", (32, 32), color=(90, 20, 120)).save(source_image)
    Image.new("RGB", (16, 16), color=(10, 130, 40)).save(derivative_image)
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_image]).media_items[0]
    derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=derivative_image,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={"time_range": {"start_seconds": 0.0, "end_seconds": 0.0}},
    )

    vault.append_media_items([derivative])
    all_items = vault.list_media_items()

    assert len(all_items) == 2
    assert all_items[1].metadata_json["asset_role"] == AssetRole.DERIVATIVE
    assert all_items[1].metadata_json["source_media_item_id"] == source_item.id
