import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

import lorasuite_engine.processing as processing_module
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
from lorasuite_engine.processing import ProcessingService
from lorasuite_engine.vault import VaultService


ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required",
)


def create_test_video(path: Path, *, duration_seconds: int = 2, rate: int = 4) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=32x32:rate={rate}:duration={duration_seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_seconds}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def create_fake_vault_video(vault: VaultService, path: Path) -> MediaItem:
    path.write_bytes(b"fake video bytes")
    media_item = MediaItem(
        source_id="source_1",
        raw_path=path,
        media_type=MediaType.VIDEO,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )
    vault.append_media_items([media_item])
    return media_item


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
    expected_derivative_sha256 = sha256(derivative_image.read_bytes()).hexdigest()
    derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=derivative_image,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={
            "asset_role": "source",
            "time_range": {"start_seconds": 0.0, "end_seconds": 0.0},
        },
    )

    vault.append_media_items([derivative])
    vault.append_media_items([derivative])
    manifest = json.loads(vault.manifest_path.read_text(encoding="utf-8"))
    all_items = vault.list_media_items()

    assert len(all_items) == 2
    assert len(manifest["sources"]) == 1
    assert all_items[1].sha256 == expected_derivative_sha256
    assert all_items[1].width == 16
    assert all_items[1].height == 16
    assert all_items[1].metadata_json["asset_role"] == AssetRole.DERIVATIVE
    assert all_items[1].metadata_json["derivative_type"] == DerivativeType.VIDEO_FRAME
    assert all_items[1].metadata_json["source_media_item_id"] == source_item.id
    assert all_items[1].metadata_json["time_range"] == {
        "start_seconds": 0.0,
        "end_seconds": 0.0,
    }


@ffmpeg
def test_video_breakdown_generates_frame_and_audio_derivatives(tmp_path):
    source_video = create_test_video(tmp_path / "source.mp4")
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_video]).media_items[0]
    service = ProcessingService(tmp_path / "vault")

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(max_frame_count=2),
    )
    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert completed.derived_media_items
    derivative_types = {
        item.metadata_json["derivative_type"]
        for item in completed.derived_media_items
    }
    assert DerivativeType.VIDEO_FRAME in derivative_types
    assert DerivativeType.AUDIO_CLIP in derivative_types
    assert all(item.raw_path.exists() for item in completed.derived_media_items)
    assert len(vault.list_media_items()) == 1 + len(completed.derived_media_items)
    for derived_item in completed.derived_media_items:
        assert derived_item.metadata_json["source_media_item_id"] == source_item.id
        assert derived_item.metadata_json["derivative_type"] in {
            DerivativeType.VIDEO_FRAME,
            DerivativeType.AUDIO_CLIP,
        }
        assert "generator" in derived_item.metadata_json
        assert "time_range" in derived_item.metadata_json


@ffmpeg
def test_video_breakdown_writes_only_manifested_frames(tmp_path):
    source_video = create_test_video(tmp_path / "source.mp4")
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_video]).media_items[0]
    service = ProcessingService(tmp_path / "vault")

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(
            extract_audio=False,
            frames_per_second=4,
            max_frame_count=2,
        ),
    )
    completed = service.process_job(job.id)

    frame_paths = [
        item.raw_path
        for item in completed.derived_media_items
        if item.metadata_json["derivative_type"] == DerivativeType.VIDEO_FRAME
    ]
    assert completed.status == ProcessingJobStatus.COMPLETE
    assert len(frame_paths) == 2
    assert len(list(frame_paths[0].parent.glob("frame_*.png"))) == len(frame_paths)


@ffmpeg
def test_video_breakdown_reprocessing_same_source_uses_disjoint_derivative_paths(tmp_path):
    source_video = create_test_video(tmp_path / "source.mp4")
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_video]).media_items[0]
    service = ProcessingService(tmp_path / "vault")

    first_job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(max_frame_count=1),
    )
    second_job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(max_frame_count=1),
    )

    first_completed = service.process_job(first_job.id)
    second_completed = service.process_job(second_job.id)

    first_paths = {item.raw_path for item in first_completed.derived_media_items}
    second_paths = {item.raw_path for item in second_completed.derived_media_items}
    assert first_completed.status == ProcessingJobStatus.COMPLETE
    assert second_completed.status == ProcessingJobStatus.COMPLETE
    assert first_paths
    assert second_paths
    assert first_paths.isdisjoint(second_paths)


def test_video_breakdown_deletes_unmanifested_overproduced_frames(tmp_path, monkeypatch):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")

    monkeypatch.setattr(
        processing_module,
        "probe_video",
        lambda video_path: SimpleNamespace(duration_seconds=2.0),
    )

    def overproduce_frames(
        video_path: Path,
        output_dir: Path,
        start_seconds: float,
        end_seconds: float,
        frames_per_second: int,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_paths = []
        for index in range(1, 5):
            frame_path = output_dir / f"frame_{index:05d}.png"
            Image.new("RGB", (16, 16), color=(index * 20, 10, 40)).save(frame_path)
            frame_paths.append(frame_path)
        return frame_paths

    monkeypatch.setattr(processing_module, "extract_frames", overproduce_frames)

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(
            extract_audio=False,
            frames_per_second=4,
            max_frame_count=2,
        ),
    )
    completed = service.process_job(job.id)

    frame_paths = [
        item.raw_path
        for item in completed.derived_media_items
        if item.metadata_json["derivative_type"] == DerivativeType.VIDEO_FRAME
    ]
    assert completed.status == ProcessingJobStatus.COMPLETE
    assert len(frame_paths) == 2
    assert len(list(frame_paths[0].parent.glob("frame_*.png"))) == len(frame_paths)


@ffmpeg
def test_process_job_returns_terminal_job_without_duplicate_manifest_rows(tmp_path):
    source_video = create_test_video(tmp_path / "source.mp4")
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_video]).media_items[0]
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(max_frame_count=1),
    )

    first_completed = service.process_job(job.id)
    manifest_count_after_first_run = len(vault.list_media_items())
    second_completed = service.process_job(job.id)

    assert first_completed.status == ProcessingJobStatus.COMPLETE
    assert second_completed == first_completed
    assert len(vault.list_media_items()) == manifest_count_after_first_run
    assert [item.id for item in second_completed.derived_media_items] == [
        item.id for item in first_completed.derived_media_items
    ]


def test_video_breakdown_persists_failed_job_for_unexpected_processing_error(
    tmp_path,
    monkeypatch,
):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")

    monkeypatch.setattr(
        processing_module,
        "probe_video",
        lambda video_path: SimpleNamespace(duration_seconds=2.0),
    )

    def extract_single_frame(
        video_path: Path,
        output_dir: Path,
        start_seconds: float,
        end_seconds: float,
        frames_per_second: int,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_path = output_dir / "frame_00001.png"
        Image.new("RGB", (16, 16), color=(20, 10, 40)).save(frame_path)
        return [frame_path]

    monkeypatch.setattr(processing_module, "extract_frames", extract_single_frame)

    def fail_append_media_items(self: VaultService, media_items: list[MediaItem]) -> None:
        raise OSError("manifest write failed")

    monkeypatch.setattr(VaultService, "append_media_items", fail_append_media_items)

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    completed = service.process_job(job.id)
    persisted = service.get_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[-1]["code"] == "processing_failed"
    assert "manifest write failed" in completed.errors[-1]["message"]
    assert persisted == completed


def test_video_breakdown_fails_for_missing_source_media(tmp_path):
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=["missing_media"],
        options=VideoBreakdownOptions(max_frame_count=1),
    )

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[0]["code"] == "missing_source_media"


def test_video_breakdown_fails_for_empty_source_media_list(tmp_path):
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[],
        options=VideoBreakdownOptions(max_frame_count=1),
    )

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[0]["code"] == "no_source_media"


@ffmpeg
def test_video_breakdown_fails_when_no_derivatives_requested(tmp_path):
    source_video = create_test_video(tmp_path / "source.mp4")
    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_video]).media_items[0]
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(generate_frames=False, extract_audio=False),
    )

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[0]["code"] == "no_derivatives_requested"
