from pathlib import Path

from PIL import Image

import lorasuite_engine.ingress as ingress_module
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


def test_ingress_job_imports_cached_social_poster_candidate(tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (32, 48), color=(120, 60, 20)).save(poster)
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/reel/example/#poster",
        display_name="example reel poster",
        media_type=MediaType.IMAGE,
        thumbnail_path=poster,
        selected=True,
        metadata_json={"local_import_path": str(poster), "asset_role": "video_poster"},
    )
    service._write_candidates({candidate.id: candidate})

    job = service.create_job(SourceKind.INSTAGRAM, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    assert completed.imported_media_items[0].metadata_json["original_path"] == str(poster)


def test_ingress_job_defers_social_video_original_download_without_direct_url(tmp_path):
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/reel/example/",
        display_name="example reel",
        media_type=MediaType.VIDEO,
        duration=9.5,
        selected=True,
        metadata_json={
            "helper_version": "lorasuite-session-helper-v0",
            "platform_media_id": "ig_video_1",
        },
    )
    service.store_candidates([candidate])

    job = service.create_job(SourceKind.INSTAGRAM, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 0
    assert completed.failed_count == 0
    assert completed.deferred_count == 1
    assert completed.deferred_candidates == [
        {
            "candidate_id": candidate.id,
            "display_name": "example reel",
            "media_type": "video",
            "source_kind": "instagram",
            "source_locator": "https://www.instagram.com/reel/example/",
            "download_url": None,
            "source_url": None,
            "reason": "original download requires session helper transfer",
        }
    ]


def test_ingress_job_downloads_selected_social_video_original(tmp_path, monkeypatch):
    video_bytes = b"fake mp4 bytes"
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/reel/example/",
        display_name="example reel",
        media_type=MediaType.VIDEO,
        duration=9.5,
        selected=True,
        metadata_json={
            "download_url": "https://cdninstagram.example/video.mp4",
            "helper_version": "lorasuite-instagram-web-api-v0",
            "platform_media_id": "ig_video_1",
        },
    )
    service.store_candidates([candidate])

    class FakeHeaders:
        def get(self, _name: str, _default=None):
            return str(len(video_bytes))

        def get_content_type(self) -> str:
            return "video/mp4"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def read(self, _size: int) -> bytes:
            if getattr(self, "sent", False):
                return b""
            self.sent = True
            return video_bytes

    def fake_urlopen(_request, *, timeout: int, context):
        assert timeout == 120
        assert context is not None
        return FakeResponse()

    monkeypatch.setattr(ingress_module, "urlopen", fake_urlopen)

    job = service.create_job(SourceKind.INSTAGRAM, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    assert completed.failed_count == 0
    assert completed.deferred_count == 0
    imported = completed.imported_media_items[0]
    assert imported.media_type == MediaType.VIDEO
    assert imported.raw_path.read_bytes() == video_bytes
    assert imported.metadata_json["original_path"].endswith(f"{candidate.id}.mp4")
    assert (tmp_path / "vault" / "downloads" / "instagram" / f"{candidate.id}.mp4").read_bytes() == video_bytes
