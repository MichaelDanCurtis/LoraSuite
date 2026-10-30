from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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


def test_scan_and_import_local_dng_uses_a_jpeg_review_and_training_path(
    tmp_path, monkeypatch
):
    source_path = tmp_path / "portrait.dng"
    source_path.write_bytes(b"camera raw")

    monkeypatch.setattr(
        "lorasuite_engine.ingress.image_dimensions",
        lambda path: (4032, 3024),
    )
    monkeypatch.setattr(
        "lorasuite_engine.vault.raw_image_dimensions",
        lambda path: (4032, 3024),
    )

    def fake_materialize(source, output):
        assert source == source_path
        Image.new("RGB", (640, 480), color=(24, 48, 72)).save(output, "JPEG")
        return output

    monkeypatch.setattr("lorasuite_engine.ingress.materialize_raw_image", fake_materialize)
    monkeypatch.setattr("lorasuite_engine.vault.materialize_raw_image", fake_materialize)
    service = IngressService(tmp_path / "vault")

    scan = service.scan_local_roots([source_path])
    candidate = scan.candidates[0]

    assert candidate.status == IngressCandidateStatus.READY
    assert candidate.media_type == MediaType.IMAGE
    assert candidate.width == 4032
    assert candidate.height == 3024
    assert candidate.thumbnail_path is not None
    assert Path(candidate.thumbnail_path).suffix == ".jpg"
    assert Path(candidate.thumbnail_path).is_file()

    job = service.create_job(SourceKind.LOCAL, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    imported = completed.imported_media_items[0]
    assert imported.raw_path.suffix == ".jpg"
    assert imported.raw_path.is_file()
    assert imported.metadata_json["original_format"] == ".dng"
    assert imported.metadata_json["source_locator"] == str(source_path)


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


def test_ingress_job_counts_reviewed_but_unselected_candidates_as_deferred(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "first.png"
    second = source_dir / "second.png"
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(first)
    Image.new("RGB", (24, 24), color=(40, 50, 60)).save(second)
    service = IngressService(tmp_path / "vault")
    scan = service.scan_local_roots([source_dir])
    selected_candidate = scan.candidates[0]
    deferred_candidate = scan.candidates[1]

    job = service.create_job(
        SourceKind.LOCAL,
        [selected_candidate.id],
        reviewed_candidate_ids=[selected_candidate.id, deferred_candidate.id],
    )
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.candidate_count == 2
    assert completed.selected_count == 1
    assert completed.imported_count == 1
    assert completed.deferred_count == 1
    assert completed.failed_count == 0
    assert completed.skipped_count == 0
    assert completed.deferred_candidates == [
        {
            "candidate_id": deferred_candidate.id,
            "display_name": deferred_candidate.display_name,
            "media_type": "image",
            "source_kind": "local",
            "source_locator": str(second),
            "reason": "not selected for this ingress batch",
        }
    ]


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
    metadata = completed.imported_media_items[0].metadata_json
    assert metadata["original_path"] == str(poster)
    assert metadata["display_name"] == "example reel poster"
    assert metadata["source_kind"] == "instagram"
    assert metadata["curation_lane"] == "image"
    assert metadata["asset_role"] == "video_poster"
    assert metadata["source_bundle_key"] == "instagram:post:example"


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


def test_x_video_preview_downloads_once_and_reuses_cached_original(tmp_path, monkeypatch):
    video_bytes = b"fake x mp4 bytes"
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.X_TWITTER,
        source_locator="https://x.com/subject/status/123",
        display_name="X clip",
        media_type=MediaType.VIDEO,
        metadata_json={
            "download_url": "https://video.twimg.com/ext_tw_video/123/clip.mp4",
        },
    )
    service.store_candidates([candidate])
    requests = []

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

    def fake_urlopen(request, *, timeout: int, context):
        requests.append(request.full_url)
        assert timeout == 120
        assert context is not None
        return FakeResponse()

    monkeypatch.setattr(ingress_module, "urlopen", fake_urlopen)

    first = service.prepare_candidate_video_preview(candidate.id)
    second = service.prepare_candidate_video_preview(candidate.id)

    assert first == second
    assert first.read_bytes() == video_bytes
    assert first.parent.name == "x_twitter"
    assert requests == ["https://video.twimg.com/ext_tw_video/123/clip.mp4"]


def test_x_video_thumbnail_becomes_a_selectable_importable_image(tmp_path, monkeypatch):
    service = IngressService(tmp_path / "vault")
    video = IngressCandidate(
        source_kind=SourceKind.X_TWITTER,
        source_locator="https://x.com/subject/status/456",
        display_name="X clip",
        media_type=MediaType.VIDEO,
        metadata_json={
            "download_url": "https://video.twimg.com/ext_tw_video/456/clip.mp4",
        },
    )
    poster = IngressCandidate(
        source_kind=SourceKind.X_TWITTER,
        source_locator=f"{video.source_locator}#poster",
        display_name="X clip poster",
        media_type=MediaType.IMAGE,
        selected=True,
        metadata_json={
            "source_video_candidate_id": video.id,
            "asset_role": "video_poster",
            "materialize_from_video": True,
        },
    )
    service.store_candidates([video, poster])
    cached_video = tmp_path / "vault" / "downloads" / "x_twitter" / f"{video.id}.mp4"
    cached_video.parent.mkdir(parents=True)
    cached_video.write_bytes(b"cached x video")
    monkeypatch.setattr(service, "prepare_candidate_video_preview", lambda _candidate_id: cached_video)

    def fake_extract(_video_path, output_path, timestamp_seconds):
        assert timestamp_seconds == 0.1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 48), color=(60, 90, 120)).save(output_path, "PNG")
        return output_path

    monkeypatch.setattr(ingress_module, "extract_frame_at_timestamp", fake_extract)

    thumbnail = service.prepare_candidate_thumbnail(poster.id)
    stored = {candidate.id: candidate for candidate in service.list_candidates()}

    assert thumbnail.exists()
    assert stored[video.id].poster_asset_path == thumbnail
    assert stored[poster.id].thumbnail_path == thumbnail
    assert stored[poster.id].metadata_json["local_import_path"] == str(thumbnail)

    job = service.create_job(SourceKind.X_TWITTER, [poster.id])
    completed = service.process_job(job.id)
    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    assert completed.imported_media_items[0].media_type == MediaType.IMAGE


def test_tiktok_video_preview_uses_cached_authenticated_download(tmp_path, monkeypatch):
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.TIKTOK,
        source_locator="https://www.tiktok.com/@subject/video/123",
        display_name="TikTok clip",
        media_type=MediaType.VIDEO,
        metadata_json={
            "source_url": "https://www.tiktok.com/@subject/video/123",
            "browser_source": "chrome",
            "platform_media_id": "tiktok_123",
        },
    )
    service.store_candidates([candidate])
    downloads = []

    def fake_download(download_candidate, target_dir):
        downloads.append(download_candidate.id)
        source_path = target_dir / "source_tiktok_123.mp4"
        source_path.write_bytes(b"tiktok preview")
        return source_path

    monkeypatch.setattr(service, "_download_tiktok_source", fake_download)

    first = service.prepare_candidate_video_preview(candidate.id)
    second = service.prepare_candidate_video_preview(candidate.id)

    assert first == second
    assert first.read_bytes() == b"tiktok preview"
    assert first.parent.name == "tiktok"
    assert downloads == [candidate.id]


def test_ingress_job_extracts_selected_social_audio_from_video(tmp_path, monkeypatch):
    video_bytes = b"fake mp4 bytes"
    audio_bytes = b"fake m4a bytes"
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/reel/example/#audio",
        display_name="example reel voice",
        media_type=MediaType.AUDIO,
        duration=9.5,
        selected=True,
        metadata_json={
            "download_url": "https://cdninstagram.example/video.mp4",
            "helper_version": "lorasuite-instagram-web-api-v0",
            "platform_media_id": "ig_video_1",
            "source_video_candidate_id": "candidate_video",
            "asset_role": "video_audio",
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

    def fake_extract_audio(
        _self: IngressService,
        video_path: Path,
        audio_path: Path,
    ) -> Path:
        assert video_path.name.endswith(".mp4")
        assert audio_path.name == f"{candidate.id}.m4a"
        audio_path.write_bytes(audio_bytes)
        return audio_path

    monkeypatch.setattr(ingress_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        IngressService,
        "_extract_audio_from_video",
        fake_extract_audio,
        raising=False,
    )

    job = service.create_job(SourceKind.INSTAGRAM, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    assert completed.failed_count == 0
    assert completed.deferred_count == 0
    imported = completed.imported_media_items[0]
    assert imported.media_type == MediaType.AUDIO
    assert imported.raw_path.read_bytes() == audio_bytes
    assert imported.metadata_json["original_path"].endswith(f"{candidate.id}.m4a")
    assert (tmp_path / "vault" / "downloads" / "instagram" / f"{candidate.id}.m4a").read_bytes() == audio_bytes


def test_ingress_job_downloads_selected_social_image_original(tmp_path, monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (48, 64), color=(30, 120, 200)).save(buffer, "JPEG")
    image_bytes = buffer.getvalue()
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/p/example/",
        display_name="example photo",
        media_type=MediaType.IMAGE,
        width=48,
        height=64,
        selected=True,
        metadata_json={
            "download_url": "https://cdninstagram.example/photo.jpg",
            "helper_version": "lorasuite-instagram-web-api-v0",
            "platform_media_id": "ig_photo_1",
        },
    )
    service.store_candidates([candidate])

    class FakeHeaders:
        def get(self, _name: str, _default=None):
            return str(len(image_bytes))

        def get_content_type(self) -> str:
            return "image/jpeg"

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
            return image_bytes

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
    assert imported.media_type == MediaType.IMAGE
    assert imported.raw_path.read_bytes() == image_bytes
    assert imported.metadata_json["original_path"].endswith(f"{candidate.id}.jpg")
    assert (tmp_path / "vault" / "downloads" / "instagram" / f"{candidate.id}.jpg").read_bytes() == image_bytes


def test_ingress_job_downloads_tiktok_video_once_and_extracts_selected_audio(
    tmp_path,
    monkeypatch,
):
    service = IngressService(tmp_path / "vault")
    shared_metadata = {
        "source_url": "https://www.tiktok.com/@subject/video/123",
        "browser_source": "chrome",
        "platform_media_id": "tiktok_123",
        "helper_version": "lorasuite-yt-dlp-tiktok-v1",
    }
    video = IngressCandidate(
        source_kind=SourceKind.TIKTOK,
        source_locator=shared_metadata["source_url"],
        display_name="TikTok clip",
        media_type=MediaType.VIDEO,
        selected=True,
        metadata_json=shared_metadata,
    )
    audio = IngressCandidate(
        source_kind=SourceKind.TIKTOK,
        source_locator=f"{shared_metadata['source_url']}#audio",
        display_name="TikTok clip voice",
        media_type=MediaType.AUDIO,
        selected=True,
        metadata_json={
            **shared_metadata,
            "source_video_candidate_id": video.id,
            "asset_role": "video_audio",
        },
    )
    service.store_candidates([video, audio])
    download_calls = []

    def fake_run(command, **options):
        download_calls.append(command)
        assert command[:3] == [ingress_module.sys.executable, "-m", "yt_dlp"]
        assert command[command.index("--cookies-from-browser") + 1] == "chrome"
        assert command[-1] == shared_metadata["source_url"]
        assert options["timeout"] == 900
        template = Path(command[command.index("--output") + 1])
        source_path = Path(str(template).replace("%(ext)s", "mp4"))
        source_path.write_bytes(b"tiktok video")
        return SimpleNamespace(returncode=0, stdout=f"{source_path}\n", stderr="")

    def fake_extract_audio(
        _self: IngressService,
        source_path: Path,
        audio_path: Path,
    ) -> Path:
        assert source_path.read_bytes() == b"tiktok video"
        audio_path.write_bytes(b"tiktok audio")
        return audio_path

    monkeypatch.setattr(ingress_module.subprocess, "run", fake_run)
    monkeypatch.setattr(IngressService, "_extract_audio_from_video", fake_extract_audio)

    job = service.create_job(SourceKind.TIKTOK, [video.id, audio.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 2
    assert completed.failed_count == 0
    assert len(download_calls) == 1
    imported_by_type = {item.media_type: item for item in completed.imported_media_items}
    assert imported_by_type[MediaType.VIDEO].raw_path.read_bytes() == b"tiktok video"
    assert imported_by_type[MediaType.AUDIO].raw_path.read_bytes() == b"tiktok audio"
