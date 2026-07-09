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


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("frames_per_second", 9),
        ("max_frame_count", 601),
    ],
)
def test_video_breakdown_options_reject_unbounded_workloads(field_name, invalid_value):
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


def test_video_breakdown_fails_with_error_when_no_frames_are_extracted(
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
    monkeypatch.setattr(processing_module, "extract_frames", lambda **kwargs: [])

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=2),
    )
    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[0]["code"] == "no_frames_extracted"


def test_process_job_retries_stale_running_job(tmp_path, monkeypatch):
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

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    jobs = service._read_jobs()
    jobs[job.id].status = ProcessingJobStatus.RUNNING
    jobs[job.id].progress_message = "Breaking down video media"
    service._write_jobs(jobs)

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert completed.derived_media_items
    assert service.get_job(job.id) == completed


def test_running_retry_reuses_manifested_derivatives_for_same_raw_paths(
    tmp_path,
    monkeypatch,
):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    frame_path = (
        tmp_path
        / "vault"
        / "derivatives"
        / "video_breakdowns"
        / job.id
        / source_item.id
        / "frames"
        / "frame_00001.png"
    )
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=(20, 10, 40)).save(frame_path)
    existing_derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=frame_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={
            "time_range": {"start_seconds": 0.0, "end_seconds": 0.0},
            "generator": {"name": "ffmpeg", "settings": {"extract_audio": False}},
        },
    )
    vault.append_media_items([existing_derivative])
    manifest_count_after_previous_attempt = len(vault.list_media_items())

    monkeypatch.setattr(
        processing_module,
        "probe_video",
        lambda video_path: SimpleNamespace(duration_seconds=2.0),
    )
    monkeypatch.setattr(
        processing_module,
        "extract_frames",
        lambda **kwargs: [frame_path],
    )

    jobs = service._read_jobs()
    jobs[job.id].status = ProcessingJobStatus.RUNNING
    jobs[job.id].derived_media_items = []
    jobs[job.id].progress_message = "Breaking down video media"
    service._write_jobs(jobs)

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert len(vault.list_media_items()) == manifest_count_after_previous_attempt
    assert [item.id for item in completed.derived_media_items] == [
        existing_derivative.id
    ]


def test_running_retry_does_not_overwrite_manifested_frame_bytes(
    tmp_path,
    monkeypatch,
):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    frame_path = (
        tmp_path
        / "vault"
        / "derivatives"
        / "video_breakdowns"
        / job.id
        / source_item.id
        / "frames"
        / "frame_00001.png"
    )
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=(20, 10, 40)).save(frame_path)
    original_frame_bytes = frame_path.read_bytes()
    original_frame_sha256 = sha256(original_frame_bytes).hexdigest()
    existing_derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=frame_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={
            "time_range": {"start_seconds": 0.0, "end_seconds": 0.0},
            "generator": {"name": "ffmpeg", "settings": {"extract_audio": False}},
        },
    )
    vault.append_media_items([existing_derivative])

    monkeypatch.setattr(
        processing_module,
        "probe_video",
        lambda video_path: SimpleNamespace(duration_seconds=2.0),
    )

    def overwrite_existing_frame(
        video_path: Path,
        output_dir: Path,
        start_seconds: float,
        end_seconds: float,
        frames_per_second: int,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_frame = output_dir / "frame_00001.png"
        Image.new("RGB", (16, 16), color=(200, 10, 40)).save(generated_frame)
        return [generated_frame]

    monkeypatch.setattr(processing_module, "extract_frames", overwrite_existing_frame)

    jobs = service._read_jobs()
    jobs[job.id].status = ProcessingJobStatus.RUNNING
    jobs[job.id].derived_media_items = []
    jobs[job.id].progress_message = "Breaking down video media"
    service._write_jobs(jobs)

    completed = service.process_job(job.id)
    manifest_item = vault.get_media_item(existing_derivative.id)

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert frame_path.read_bytes() == original_frame_bytes
    assert sha256(frame_path.read_bytes()).hexdigest() == original_frame_sha256
    assert manifest_item is not None
    assert manifest_item.sha256 == original_frame_sha256
    assert [item.id for item in completed.derived_media_items] == [
        existing_derivative.id
    ]


def test_running_retry_append_failure_keeps_existing_manifested_files(
    tmp_path,
    monkeypatch,
):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(
            extract_audio=False,
            max_frame_count=2,
        ),
    )
    frames_dir = (
        tmp_path
        / "vault"
        / "derivatives"
        / "video_breakdowns"
        / job.id
        / source_item.id
        / "frames"
    )
    existing_frame_path = frames_dir / "frame_00001.png"
    new_frame_path = frames_dir / "frame_00002.png"
    existing_frame_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=(20, 10, 40)).save(existing_frame_path)
    existing_derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=existing_frame_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={
            "time_range": {"start_seconds": 0.0, "end_seconds": 0.0},
            "generator": {"name": "ffmpeg", "settings": {"extract_audio": False}},
        },
    )
    vault.append_media_items([existing_derivative])
    manifest_count_after_previous_attempt = len(vault.list_media_items())

    monkeypatch.setattr(
        processing_module,
        "probe_video",
        lambda video_path: SimpleNamespace(duration_seconds=2.0),
    )

    def extract_existing_and_new_frame(
        video_path: Path,
        output_dir: Path,
        start_seconds: float,
        end_seconds: float,
        frames_per_second: int,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), color=(20, 10, 40)).save(existing_frame_path)
        Image.new("RGB", (16, 16), color=(30, 10, 40)).save(new_frame_path)
        return [existing_frame_path, new_frame_path]

    monkeypatch.setattr(
        processing_module,
        "extract_frames",
        extract_existing_and_new_frame,
    )

    def fail_append_media_items(self: VaultService, media_items: list[MediaItem]) -> None:
        raise OSError("manifest write failed")

    monkeypatch.setattr(VaultService, "append_media_items", fail_append_media_items)

    jobs = service._read_jobs()
    jobs[job.id].status = ProcessingJobStatus.RUNNING
    jobs[job.id].derived_media_items = []
    jobs[job.id].progress_message = "Breaking down video media"
    service._write_jobs(jobs)

    completed = service.process_job(job.id)

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[-1]["code"] == "processing_failed"
    assert len(vault.list_media_items()) == manifest_count_after_previous_attempt
    assert existing_frame_path.exists()
    assert not new_frame_path.exists()


def test_cleanup_keeps_manifested_files_when_manifest_read_fails(
    tmp_path,
    monkeypatch,
):
    vault = VaultService(tmp_path / "vault")
    source_item = create_fake_vault_video(vault, tmp_path / "source.mp4")
    service = ProcessingService(tmp_path / "vault")
    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    frame_path = (
        tmp_path
        / "vault"
        / "derivatives"
        / "video_breakdowns"
        / job.id
        / source_item.id
        / "frames"
        / "frame_00001.png"
    )
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=(20, 10, 40)).save(frame_path)
    existing_derivative = vault.build_derivative_media_item(
        source_item=source_item,
        derivative_path=frame_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
        metadata={
            "time_range": {"start_seconds": 0.0, "end_seconds": 0.0},
            "generator": {"name": "ffmpeg", "settings": {"extract_audio": False}},
        },
    )
    vault.append_media_items([existing_derivative])

    def fail_list_media_items(self: VaultService) -> list[MediaItem]:
        raise RuntimeError("manifest unavailable")

    monkeypatch.setattr(VaultService, "list_media_items", fail_list_media_items)

    service._delete_unmanifested_job_derivatives(job.id)

    assert frame_path.exists()


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
    derivative_root = tmp_path / "vault" / "derivatives" / "video_breakdowns" / job.id

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[-1]["code"] == "processing_failed"
    assert "manifest write failed" in completed.errors[-1]["message"]
    assert not [path for path in derivative_root.rglob("*") if path.is_file()]
    assert persisted == completed


def test_video_breakdown_cleans_generated_files_when_derivative_build_fails(
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

    def fail_build_derivative(
        self: VaultService,
        *,
        source_item: MediaItem,
        derivative_path: Path,
        media_type: MediaType,
        derivative_type: DerivativeType,
        metadata: dict[str, object] | None = None,
    ) -> MediaItem:
        raise RuntimeError("derivative metadata failed")

    monkeypatch.setattr(
        VaultService,
        "build_derivative_media_item",
        fail_build_derivative,
    )

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    completed = service.process_job(job.id)
    derivative_root = tmp_path / "vault" / "derivatives" / "video_breakdowns" / job.id

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[-1]["code"] == "processing_failed"
    assert "derivative metadata failed" in completed.errors[-1]["message"]
    assert not [path for path in derivative_root.rglob("*") if path.is_file()]


def test_video_breakdown_keeps_manifested_files_when_final_job_persistence_fails(
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

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(extract_audio=False, max_frame_count=1),
    )
    monkeypatch.setattr(processing_module, "extract_frames", extract_single_frame)
    real_write_jobs = service._write_jobs
    write_call_count = 0

    def fail_final_job_write(jobs: dict[str, ProcessingJob]) -> None:
        nonlocal write_call_count
        write_call_count += 1
        if write_call_count == 2:
            raise OSError("job persistence failed")
        real_write_jobs(jobs)

    monkeypatch.setattr(service, "_write_jobs", fail_final_job_write)

    completed = service.process_job(job.id)
    derivative_items = [
        item
        for item in vault.list_media_items()
        if item.metadata_json.get("derivative_type") == DerivativeType.VIDEO_FRAME
    ]

    assert completed.status == ProcessingJobStatus.FAILED
    assert completed.errors[-1]["code"] == "processing_failed"
    assert "job persistence failed" in completed.errors[-1]["message"]
    assert derivative_items
    assert all(item.raw_path.exists() for item in derivative_items)


def test_video_breakdown_keeps_frame_derivatives_when_audio_extraction_fails(
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

    def fail_audio(video_path: Path, output_path: Path) -> Path:
        raise RuntimeError("audio stream missing")

    monkeypatch.setattr(processing_module, "extract_audio", fail_audio)

    job = service.create_video_breakdown_job(
        source_media_item_ids=[source_item.id],
        options=VideoBreakdownOptions(max_frame_count=1),
    )
    completed = service.process_job(job.id)

    frame_items = [
        item
        for item in completed.derived_media_items
        if item.metadata_json["derivative_type"] == DerivativeType.VIDEO_FRAME
    ]
    manifest_item_ids = {item.id for item in vault.list_media_items()}

    assert completed.status == ProcessingJobStatus.FAILED
    assert any(error["code"] == "audio_extraction_failed" for error in completed.errors)
    assert frame_items
    assert all(item.raw_path.exists() for item in frame_items)
    assert all(item.id in manifest_item_ids for item in frame_items)


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
