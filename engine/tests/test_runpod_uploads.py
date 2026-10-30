import json
from pathlib import Path

from botocore.exceptions import ClientError

from lorasuite_engine.runpod_bundle import RunPodBundleService
from lorasuite_engine.runpod_uploads import RunPodBundleUploadService


class FakeS3Uploader:
    def __init__(self):
        self.objects: dict[tuple[str, str], int] = {}
        self.uploads: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str):
        size = self.objects.get((Bucket, Key))
        if size is None:
            raise ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")
        return {"ContentLength": size}

    def upload_file(self, Filename: str, Bucket: str, Key: str, *, Config):
        self.uploads.append((Bucket, Key))
        self.objects[(Bucket, Key)] = Path(Filename).stat().st_size


def test_uploads_bundle_to_network_volume_and_persists_progress_without_credentials(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    uploader = FakeS3Uploader()
    factory_options = {}

    def factory(**options):
        factory_options.update(options)
        return uploader

    service = RunPodBundleUploadService(tmp_path / "vault", uploader_factory=factory)
    job = service.create_job(
        bundle_path=bundle,
        volume_id="volume-1",
        endpoint_url="https://s3api-us-ca-2.runpod.io/",
        datacenter="US-CA-2",
    )
    completed = service.process_job(job.id, "access-key", "secret-key")

    assert completed.status == "complete"
    assert completed.files_uploaded == completed.files_total
    assert completed.bytes_uploaded == completed.bytes_total
    assert completed.remote_prefix.startswith("lorasuite/image-")
    assert any(key.endswith("bundle_manifest.json") for _bucket, key in uploader.uploads)
    assert factory_options["access_key"] == "access-key"
    persisted = service.jobs_path.read_text()
    assert "access-key" not in persisted
    assert "secret-key" not in persisted


def test_resume_skips_remote_objects_with_matching_size(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    uploader = FakeS3Uploader()
    service = RunPodBundleUploadService(tmp_path / "vault", uploader_factory=lambda **_options: uploader)
    job = service.create_job(bundle_path=bundle, volume_id="volume-1", endpoint_url="https://s3.example/", datacenter="US-CA-2")
    first = next(path for path in sorted(bundle.rglob("*")) if path.is_file())
    first_key = f"{job.remote_prefix}/{first.relative_to(bundle).as_posix()}"
    uploader.objects[("volume-1", first_key)] = first.stat().st_size

    completed = service.process_job(job.id, "key", "secret")

    assert completed.status == "complete"
    assert ("volume-1", first_key) not in uploader.uploads
    assert completed.files_uploaded == completed.files_total


def test_failed_upload_can_be_resumed_without_storing_missing_credentials(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    service = RunPodBundleUploadService(tmp_path / "vault", uploader_factory=lambda **_options: FakeS3Uploader())
    job = service.create_job(bundle_path=bundle, volume_id="volume-1", endpoint_url="https://s3.example/", datacenter="US-CA-2")

    failed = service.process_job(job.id, None, None)
    resumed = service.resume_job(job.id)

    assert failed.status == "failed"
    assert "access key" in (failed.error or "")
    assert resumed.status == "queued"
    assert resumed.error is None


def _bundle(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    images = source / "images"
    images.mkdir(parents=True)
    (images / "000001.png").write_bytes(b"image")
    (images / "000001.txt").write_text("person portrait\n")
    (source / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "dataset_snapshot_id": "snapshot-1",
        "project_id": "project-1",
        "modality": "image",
    }))
    return RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "bundle",
        modality="image",
        trigger_token="person",
        fingerprint="fingerprint-1",
        training_target_profile_id="runcomfy_flux1_dev_character",
        endpoint_id="endpoint-1",
    ).output_path
