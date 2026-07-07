from pathlib import Path

from PIL import Image

from lorasuite_engine.ingress import IngressService
from lorasuite_engine.models import (
    AssetType,
    IngressCandidate,
    IngressCandidateStatus,
    IngressJob,
    IngressJobStatus,
    MediaType,
    SourceKind,
)


def test_ingress_candidate_serializes_preview_fields():
    candidate = IngressCandidate(
        source_kind=SourceKind.LOCAL,
        source_locator="/tmp/source/image.png",
        display_name="image.png",
        media_type=MediaType.IMAGE,
        size_bytes=123,
        width=64,
        height=48,
        thumbnail_path=Path("/tmp/vault/previews/thumb.jpg"),
        status=IngressCandidateStatus.READY,
        selected=True,
    )

    payload = candidate.model_dump(mode="json")

    assert payload["source_kind"] == "local"
    assert payload["source_locator"] == "/tmp/source/image.png"
    assert payload["thumbnail_path"] == "/tmp/vault/previews/thumb.jpg"
    assert payload["status"] == "ready"
    assert payload["selected"] is True


def test_ingress_job_tracks_counts_and_imported_items():
    job = IngressJob(
        source_kind=SourceKind.LOCAL,
        candidate_ids=["candidate_1", "candidate_2"],
        selected_count=2,
        status=IngressJobStatus.RUNNING,
        progress_message="Importing selected media",
    )

    assert job.status == IngressJobStatus.RUNNING
    assert job.candidate_count == 2
    assert job.selected_count == 2
    assert job.imported_count == 0


def test_asset_type_includes_thumbnail_and_poster():
    assert AssetType.THUMBNAIL == "thumbnail"
    assert AssetType.POSTER == "poster"


def test_scan_local_folder_returns_candidates_without_copying_raw_files(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    image_path = source_dir / "person.png"
    Image.new("RGB", (80, 60), color=(30, 60, 90)).save(image_path)
    vault_root = tmp_path / "vault"

    result = IngressService(vault_root).scan_local_roots([source_dir])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.display_name == "person.png"
    assert candidate.source_locator == str(image_path)
    assert candidate.media_type == MediaType.IMAGE
    assert candidate.width == 80
    assert candidate.height == 60
    assert candidate.thumbnail_path is not None
    assert Path(candidate.thumbnail_path).exists()
    assert not (vault_root / "raw").exists()


def test_scan_local_folder_marks_unsupported_files(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    unsupported = source_dir / "notes.txt"
    unsupported.write_text("not media", encoding="utf-8")

    result = IngressService(tmp_path / "vault").scan_local_roots([source_dir])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.status == IngressCandidateStatus.UNSUPPORTED
    assert candidate.error_message == "suffix is not supported"
    assert candidate.selected is False


def test_ingress_job_imports_only_selected_ready_candidates(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "first.png"
    second = source_dir / "second.png"
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(first)
    Image.new("RGB", (24, 24), color=(40, 50, 60)).save(second)
    service = IngressService(tmp_path / "vault")
    scan = service.scan_local_roots([source_dir])

    job = service.create_job(SourceKind.LOCAL, [scan.candidates[0].id])
    service.process_job(job.id)
    completed = service.get_job(job.id)

    assert completed is not None
    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.selected_count == 1
    assert completed.imported_count == 1
    assert completed.imported_media_items[0].metadata_json["original_path"] == str(first)
    raw_files = list((tmp_path / "vault" / "raw").iterdir())
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == first.read_bytes()
