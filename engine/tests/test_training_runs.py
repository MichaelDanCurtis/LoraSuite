import json
from pathlib import Path

import lorasuite_engine.training_runs as training_runs_module
from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.models import DatasetSnapshot, DatasetSnapshotStatus
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_runs import RunComfyProvider, TrainingRunService
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.vault import sha256_file
from lorasuite_engine.video_dataset import VideoDatasetSnapshot


class FakeRunComfyProvider:
    def __init__(self):
        self.uploaded: list[str] = []
        self.downloaded: list[str] = []
        self.job_checks = 0

    def create_dataset(self, name: str):
        return {"id": "dataset-1", "name": name, "status": "DRAFT"}

    def upload_file(self, dataset_id: str, path: Path):
        self.uploaded.append(path.name)
        return {"id": dataset_id, "filename": path.name}

    def dataset_status(self, dataset_id: str):
        return {"id": dataset_id, "name": "lorasuite-test", "status": "READY"}

    def submit_job(self, config_file: str, gpu_type: str):
        assert "/app/ai-toolkit/datasets/lorasuite-test" in config_file
        assert gpu_type == "ADA_80_PLUS"
        return {"id": "job-1"}

    def job_status(self, job_id: str):
        self.job_checks += 1
        if self.job_checks == 1:
            return {
                "id": job_id,
                "status": "RUNNING",
                "progress": {"current_step": 10, "total_steps": 20, "percent": 50},
            }
        return {
            "id": job_id,
            "status": "STOPPED",
            "progress": {"current_step": 20, "total_steps": 20, "percent": 100},
        }

    def job_result(self, job_id: str):
        return {
            "id": job_id,
            "artifacts": {
                "checkpoints": [{"path": "https://example.test/model.safetensors"}],
                "config": {"path": "https://example.test/config.yaml"},
                "samples": [{
                    "path": "https://example.test/sample.png",
                    "step": 10,
                    "prompt": "person_token portrait",
                    "sample_index": 0,
                }],
            },
        }

    def cancel_job(self, job_id: str):
        return {"id": job_id, "status": "CANCELED"}

    def resume_job(self, job_id: str):
        return {"id": job_id, "status": "IN_QUEUE"}

    def download(self, url: str, destination: Path):
        self.downloaded.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(url, encoding="utf-8")


def test_runcomfy_large_file_uses_streamed_signed_upload_without_bearer_token(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video-data")
    monkeypatch.setattr(training_runs_module, "DIRECT_UPLOAD_LIMIT_BYTES", 4)
    api_calls = []
    connection_calls = []

    class Response:
        status = 204
        reason = "No Content"

        @staticmethod
        def read(_limit):
            return b""

    class Connection:
        def __init__(self, host, port=None, **kwargs):
            self.record = {"host": host, "port": port, "kwargs": kwargs, "headers": {}, "body": bytearray()}
            connection_calls.append(self.record)

        def putrequest(self, method, target):
            self.record.update(method=method, target=target)

        def putheader(self, name, value):
            self.record["headers"][name] = value

        def endheaders(self):
            pass

        def send(self, chunk):
            self.record["body"].extend(chunk)

        def getresponse(self):
            return Response()

        def close(self):
            self.record["closed"] = True

    provider = RunComfyProvider("session-secret")

    def fake_json(method, path, payload=None, **_kwargs):
        api_calls.append((method, path, payload))
        return {"uploads": {
            "clip.mp4": {
                "upload_url": "https://storage.example/upload/clip.mp4?signature=abc",
                "method": "PUT",
                "headers": {"Content-Type": "video/mp4", "Authorization": "must-not-forward"},
            },
        }}

    monkeypatch.setattr(provider, "_json", fake_json)
    monkeypatch.setattr(training_runs_module.http.client, "HTTPSConnection", Connection)

    result = provider.upload_file("dataset-1", media)

    assert api_calls == [(
        "POST",
        "/prod/v1/trainers/datasets/dataset-1/get-upload-endpoint",
        {"filenameToByteSize": {"clip.mp4": len(b"video-data")}},
    )]
    assert result["upload"] == "signed"
    request = connection_calls[0]
    assert request["method"] == "PUT"
    assert request["target"] == "/upload/clip.mp4?signature=abc"
    assert request["headers"]["Content-Type"] == "video/mp4"
    assert request["headers"]["Content-Length"] == str(len(b"video-data"))
    assert "Authorization" not in request["headers"]
    assert bytes(request["body"]) == b"video-data"
    assert request["closed"] is True


def test_runcomfy_large_file_refreshes_an_expired_signed_url_once(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video-data")
    monkeypatch.setattr(training_runs_module, "DIRECT_UPLOAD_LIMIT_BYTES", 4)
    issued_urls = []
    statuses = iter([403, 200])

    class Connection:
        def __init__(self, *_args, **_kwargs):
            self.status = next(statuses)

        def putrequest(self, _method, target):
            issued_urls.append(target)

        def putheader(self, _name, _value):
            pass

        def endheaders(self):
            pass

        def send(self, _chunk):
            pass

        def getresponse(self):
            status = self.status
            return type("Response", (), {
                "status": status,
                "reason": "Expired" if status == 403 else "OK",
                "read": staticmethod(lambda _limit: b"expired" if status == 403 else b""),
            })()

        def close(self):
            pass

    provider = RunComfyProvider("session-secret")
    endpoint_calls = 0

    def fake_json(_method, _path, _payload=None, **_kwargs):
        nonlocal endpoint_calls
        endpoint_calls += 1
        return {"uploads": {"clip.mp4": {
            "upload_url": f"https://storage.example/upload/clip.mp4?attempt={endpoint_calls}",
            "method": "PUT",
            "headers": {"Content-Type": "video/mp4"},
        }}}

    monkeypatch.setattr(provider, "_json", fake_json)
    monkeypatch.setattr(training_runs_module.http.client, "HTTPSConnection", Connection)

    result = provider.upload_file("dataset-1", media)

    assert result["upload"] == "signed"
    assert endpoint_calls == 2
    assert issued_urls == ["/upload/clip.mp4?attempt=1", "/upload/clip.mp4?attempt=2"]


def test_runcomfy_provider_resumes_existing_job(monkeypatch):
    provider = RunComfyProvider("session-secret")
    calls = []
    monkeypatch.setattr(provider, "_json", lambda method, path, payload=None: calls.append((method, path, payload)) or {"status": "IN_QUEUE"})

    result = provider.resume_job("job/1")

    assert result["status"] == "IN_QUEUE"
    assert calls == [("POST", "/prod/v1/trainers/ai-toolkit/jobs/job/1/resume", {})]


def test_runcomfy_artifact_download_streams_without_forwarding_bearer_token(tmp_path, monkeypatch):
    destination = tmp_path / "model.safetensors"
    requests = []

    class Response:
        status = 200
        reason = "OK"

        def __init__(self):
            self.chunks = iter([b"model-", b"weights", b""])

        def getheader(self, name):
            return str(len(b"model-weights")) if name == "Content-Length" else None

        def read(self, _size=None):
            return next(self.chunks)

    class Connection:
        def __init__(self, host, port=None, **_kwargs):
            self.host = host
            self.port = port

        def request(self, method, target, headers):
            requests.append((self.host, method, target, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(training_runs_module.http.client, "HTTPSConnection", Connection)

    RunComfyProvider("session-secret").download(
        "https://storage.example/output/model.safetensors?signature=abc",
        destination,
    )

    assert destination.read_bytes() == b"model-weights"
    assert requests == [(
        "storage.example",
        "GET",
        "/output/model.safetensors?signature=abc",
        {"Accept": "application/octet-stream"},
    )]
    assert list(tmp_path.glob("*.part")) == []


def test_runcomfy_artifact_redirect_strips_bearer_token_on_external_host(tmp_path, monkeypatch):
    destination = tmp_path / "sample.png"
    requests = []

    class Response:
        reason = "Found"

        def __init__(self, status, body=b"", location=None):
            self.status = status
            self.body = body
            self.location = location
            self.offset = 0

        def getheader(self, name):
            if name == "Location":
                return self.location
            if name == "Content-Length" and self.status == 200:
                return str(len(self.body))
            return None

        def read(self, size=None):
            if size is None:
                self.offset = len(self.body)
                return self.body
            chunk = self.body[self.offset:self.offset + size]
            self.offset += len(chunk)
            return chunk

    class Connection:
        def __init__(self, host, port=None, **_kwargs):
            self.host = host

        def request(self, method, target, headers):
            requests.append((self.host, method, target, headers))

        def getresponse(self):
            if self.host == "trainer-api.runcomfy.net":
                return Response(302, location="https://cdn.example/signed/sample.png")
            return Response(200, body=b"png")

        def close(self):
            pass

    monkeypatch.setattr(training_runs_module.http.client, "HTTPSConnection", Connection)

    RunComfyProvider("session-secret").download(
        "https://trainer-api.runcomfy.net/artifacts/sample.png",
        destination,
    )

    assert requests[0][3]["Authorization"] == "Bearer session-secret"
    assert "Authorization" not in requests[1][3]
    assert destination.read_bytes() == b"png"


def test_runcomfy_truncated_artifact_keeps_existing_file_and_removes_partial(tmp_path, monkeypatch):
    destination = tmp_path / "model.safetensors"
    destination.write_bytes(b"existing-model")

    class Response:
        status = 200
        reason = "OK"
        reads = 0

        @staticmethod
        def getheader(name):
            return "10" if name == "Content-Length" else None

        def read(self, _size=None):
            self.reads += 1
            return b"tiny" if self.reads == 1 else b""

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, _method, _target, headers):
            assert "Authorization" not in headers

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(training_runs_module.http.client, "HTTPSConnection", Connection)

    try:
        RunComfyProvider("session-secret").download("https://storage.example/model.safetensors", destination)
    except RuntimeError as error:
        assert "truncated" in str(error)
    else:
        raise AssertionError("Expected a truncated artifact download to fail")

    assert destination.read_bytes() == b"existing-model"
    assert list(tmp_path.glob("*.part")) == []


def test_runcomfy_training_run_persists_full_lifecycle(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "dataset"
    images_path = export_path / "images"
    images_path.mkdir(parents=True)
    (images_path / "000001.png").write_bytes(b"image")
    (images_path / "000001.txt").write_text("person portrait\n", encoding="utf-8")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="abcdef1234567890",
        export_path=export_path,
        parent_snapshot_id="dataset-snapshot-v1",
        parent_fingerprint="parent-fingerprint",
        improvement_request_id="improvement-request-1",
        source_artifact_id="artifact-v1",
        source_checkpoint_sha256="parent-checkpoint-sha",
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )
    provider = FakeRunComfyProvider()
    service = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: provider,
        sleep=lambda _seconds: None,
    )
    config = 'datasets:\n  folder_path: "/app/ai-toolkit/datasets/{dataset_name}"'

    queued = service.create_run(
        snapshot_id=snapshot.id,
        config_file=config,
        gpu_type="ADA_80_PLUS",
    )
    observed_during_training = []
    service.sleep = lambda _seconds: observed_during_training.append(service.get_run(queued.id))
    assert queued.parent_snapshot_id == "dataset-snapshot-v1"
    assert queued.parent_dataset_fingerprint == "parent-fingerprint"
    assert queued.improvement_request_id == "improvement-request-1"
    assert queued.parent_artifact_id == "artifact-v1"
    assert queued.parent_checkpoint_sha256 == "parent-checkpoint-sha"
    completed = service.process_run(queued.id, "session-token")

    assert completed.status == "completed"
    assert completed.dataset_id == "dataset-1"
    assert completed.provider_job_id == "job-1"
    assert completed.progress_percent == 100
    assert provider.uploaded == ["000001.png", "000001.txt"]
    assert {artifact.kind for artifact in completed.artifacts} == {
        "checkpoint",
        "config",
        "sample",
    }
    assert all(artifact.local_path and artifact.local_path.exists() for artifact in completed.artifacts)
    assert len(provider.downloaded) == 3
    assert observed_during_training
    assert {artifact.kind for artifact in observed_during_training[0].artifacts} == {
        "checkpoint",
        "config",
        "sample",
    }
    sample = next(artifact for artifact in completed.artifacts if artifact.kind == "sample")
    assert sample.step == 10
    assert sample.prompt == "person_token portrait"
    assert sample.sample_index == 0
    assert service.get_run(queued.id).status == "completed"

    reused = service.create_run(
        snapshot_id=snapshot.id,
        config_file=config,
        gpu_type="ADA_80_PLUS",
    )
    assert reused.id == queued.id


def test_runcomfy_upload_resumes_from_persisted_file_checkpoint_after_restart(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "dataset"
    images_path = export_path / "images"
    images_path.mkdir(parents=True)
    (images_path / "000001.png").write_bytes(b"image")
    (images_path / "000001.txt").write_text("person portrait\n", encoding="utf-8")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="abcdef1234567890",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )

    class InterruptedProvider(FakeRunComfyProvider):
        def upload_file(self, dataset_id: str, path: Path):
            if self.uploaded:
                raise RuntimeError("connection interrupted")
            return super().upload_file(dataset_id, path)

    first_provider = InterruptedProvider()
    first_service = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: first_provider,
        sleep=lambda _seconds: None,
    )
    run = first_service.create_run(
        snapshot_id=snapshot.id,
        config_file='datasets:\n  folder_path: "/app/ai-toolkit/datasets/{dataset_name}"',
        gpu_type="ADA_80_PLUS",
    )

    interrupted = first_service.process_run(run.id, "session-token")

    assert interrupted.status == "failed"
    assert interrupted.dataset_id == "dataset-1"
    assert interrupted.upload_manifest_digest
    assert [item.relative_path for item in interrupted.uploaded_files] == [
        "images/000001.png"
    ]
    assert first_provider.uploaded == ["000001.png"]

    second_provider = FakeRunComfyProvider()
    restarted_service = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: second_provider,
        sleep=lambda _seconds: None,
    )
    completed = restarted_service.refresh_run(run.id, "session-token")

    assert completed.status == "completed"
    assert completed.dataset_id == "dataset-1"
    assert second_provider.uploaded == ["000001.txt"]
    assert [item.relative_path for item in completed.uploaded_files] == [
        "images/000001.png",
        "images/000001.txt",
    ]
    assert completed.error is None


def test_runcomfy_upload_rejects_export_changes_after_checkpoint(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "dataset"
    images_path = export_path / "images"
    images_path.mkdir(parents=True)
    (images_path / "000001.png").write_bytes(b"image")
    caption = images_path / "000001.txt"
    caption.write_text("person portrait\n", encoding="utf-8")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="abcdef1234567890",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )

    class InterruptedProvider(FakeRunComfyProvider):
        def upload_file(self, dataset_id: str, path: Path):
            if self.uploaded:
                raise RuntimeError("connection interrupted")
            return super().upload_file(dataset_id, path)

    service = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: InterruptedProvider(),
        sleep=lambda _seconds: None,
    )
    run = service.create_run(
        snapshot_id=snapshot.id,
        config_file='datasets:\n  folder_path: "/app/ai-toolkit/datasets/{dataset_name}"',
        gpu_type="ADA_80_PLUS",
    )
    assert service.process_run(run.id, "session-token").status == "failed"
    caption.write_text("changed caption\n", encoding="utf-8")

    retried = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: FakeRunComfyProvider(),
        sleep=lambda _seconds: None,
    ).refresh_run(run.id, "session-token")

    assert retried.status == "failed"
    assert "exported dataset changed" in (retried.error or "").lower()


def test_runcomfy_training_can_resume_from_verified_recovered_export(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "recovered-dataset"
    images_path = export_path / "images"
    images_path.mkdir(parents=True)
    image_path = images_path / "000001.png"
    caption_path = images_path / "000001.txt"
    image_path.write_bytes(b"image")
    caption_path.write_text("person_token, person, portrait\n", encoding="utf-8")
    (export_path / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "export_type": "runcomfy_image",
        "character_project_id": "project-recovered",
        "dataset_snapshot_id": "snapshot-recovered",
        "dataset_fingerprint": "recovered-fingerprint",
        "training_target": {
            "profile_id": "runcomfy_flux1_dev_character",
        },
        "files": [{
            "image": str(image_path),
            "caption": str(caption_path),
            "caption_text": caption_path.read_text(encoding="utf-8").strip(),
            "sha256": sha256_file(image_path),
        }],
    }), encoding="utf-8")
    recovered = RecoveredDatasetService(vault_root).register(export_path)

    run = TrainingRunService(vault_root).create_run(
        snapshot_id=recovered.snapshot_id,
        config_file='datasets:\n  folder_path: "/app/ai-toolkit/datasets/{dataset_name}"',
        gpu_type="ADA_80_PLUS",
    )

    assert run.snapshot_id == "snapshot-recovered"
    assert run.dataset_fingerprint == "recovered-fingerprint"
    assert run.export_path == export_path


def test_runcomfy_preempted_job_exports_available_artifacts_then_resumes_same_job(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "dataset"
    images_path = export_path / "images"
    images_path.mkdir(parents=True)
    (images_path / "000001.png").write_bytes(b"image")
    (images_path / "000001.txt").write_text("person portrait\n", encoding="utf-8")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="preempted123456",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )

    class PreemptedProvider(FakeRunComfyProvider):
        def __init__(self):
            super().__init__()
            self.resumed: list[str] = []
            self.downloads = 0

        def job_status(self, job_id: str):
            self.job_checks += 1
            if self.job_checks == 1:
                return {"id": job_id, "status": "STOPPED", "progress": {"current_step": 10, "total_steps": 20, "percent": 50}}
            return {"id": job_id, "status": "STOPPED", "progress": {"current_step": 20, "total_steps": 20, "percent": 100}}

        def resume_job(self, job_id: str):
            self.resumed.append(job_id)
            return {"id": job_id, "status": "IN_QUEUE"}

        def download(self, url: str, destination: Path):
            self.downloads += 1
            super().download(url, destination)

    provider = PreemptedProvider()
    service = TrainingRunService(vault_root, provider_factory=lambda _token: provider, sleep=lambda _seconds: None)
    queued = service.create_run(
        snapshot_id=snapshot.id,
        config_file='datasets:\n  folder_path: "/app/ai-toolkit/datasets/{dataset_name}"',
        gpu_type="ADA_80_PLUS",
    )

    stopped = service.process_run(queued.id, "session-token")

    assert stopped.status == "stopped"
    assert stopped.provider_job_id == "job-1"
    assert stopped.progress_current == 10
    assert stopped.progress_total == 20
    assert {artifact.kind for artifact in stopped.artifacts} == {"checkpoint", "config", "sample"}
    assert all(artifact.local_path and artifact.local_path.exists() for artifact in stopped.artifacts)
    assert stopped.completed_at is None
    assert provider.downloads == 3

    completed = service.resume_run(stopped.id, "session-token")

    assert provider.resumed == ["job-1"]
    assert completed.status == "completed"
    assert completed.provider_job_id == "job-1"
    assert completed.progress_percent == 100
    assert provider.downloads == 3


def test_training_yaml_requires_dataset_placeholder(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "dataset"
    (export_path / "images").mkdir(parents=True)
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="abcdef1234567890",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )

    service = TrainingRunService(vault_root)
    try:
        service.create_run(
            snapshot_id=snapshot.id,
            config_file="datasets: []",
            gpu_type="ADA_80_PLUS",
        )
    except ValueError as error:
        assert "{dataset_name}" in str(error)
    else:
        raise AssertionError("Expected missing dataset placeholder to fail")


def test_video_training_uploads_only_train_split_and_accepts_wan22_profile(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "video-dataset"
    videos_path = export_path / "videos"
    videos_path.mkdir(parents=True)
    for split in ("train", "validation"):
        (videos_path / f"{split}_000001.mp4").write_bytes(split.encode())
        (videos_path / f"{split}_000001.txt").write_text(f"{split} caption\n", encoding="utf-8")
    (export_path / "manifest.json").write_text(
        """{
  "files": [
    {"video": "videos/train_000001.mp4", "caption": "videos/train_000001.txt", "split": "train"},
    {"video": "videos/validation_000001.mp4", "caption": "videos/validation_000001.txt", "split": "validation"}
  ]
}\n""",
        encoding="utf-8",
    )
    snapshot = VideoDatasetSnapshot(
        project_id="project-video",
        project_name="Video Person",
        trigger_token="video_person",
        status="exported",
        fingerprint="fedcba9876543210",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "video_dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )
    provider = FakeRunComfyProvider()
    service = TrainingRunService(
        vault_root,
        provider_factory=lambda _token: provider,
        sleep=lambda _seconds: None,
    )
    config = get_training_target_profile(snapshot.target_profile_id).config_template

    queued = service.create_run(
        snapshot_id=snapshot.id,
        config_file=config,
        gpu_type="ADA_80_PLUS",
    )
    completed = service.process_run(queued.id, "session-token")

    assert completed.status == "completed"
    assert provider.uploaded == ["train_000001.mp4", "train_000001.txt"]


def test_video_training_rejects_single_frame_wan_config(tmp_path):
    vault_root = tmp_path / "vault"
    export_path = tmp_path / "video-dataset"
    (export_path / "videos").mkdir(parents=True)
    snapshot = VideoDatasetSnapshot(
        project_id="project-video",
        project_name="Video Person",
        trigger_token="video_person",
        status="exported",
        fingerprint="fedcba9876543210",
        export_path=export_path,
    )
    atomic_write_json(
        vault_root / "video_dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )
    config = """datasets:\n  - folder_path: /app/ai-toolkit/datasets/{dataset_name}\n    num_frames: 1\nmodel:\n  arch: wan22_14b\n"""

    try:
        TrainingRunService(vault_root).create_run(
            snapshot_id=snapshot.id,
            config_file=config,
            gpu_type="ADA_80_PLUS",
        )
    except ValueError as error:
        assert "more than one frame" in str(error)
    else:
        raise AssertionError("Expected single-frame WAN video training config to fail")
