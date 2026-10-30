import json
import hashlib
from pathlib import Path

import pytest

from lorasuite_engine.runpod_bundle import RunPodBundleService
from lorasuite_engine.runpod_runs import RunPodPreflightReport, RunPodTrainingRunService, resolve_runpod_token


class FakeRunPodProvider:
    def __init__(self):
        self.submitted = None
        self.checks = 0
        self.canceled = []

    def submit(self, endpoint_id: str, payload: dict):
        self.submitted = (endpoint_id, payload)
        return {"id": "serverless-job-1", "status": "IN_QUEUE"}

    def run_sync(self, endpoint_id: str, payload: dict):
        self.preflight = (endpoint_id, payload)
        return {
            "id": "sync-preflight-1",
            "status": "COMPLETED",
            "output": {
                "status": "success",
                "bundle_format": "lorasuite-runpod-v1",
                "worker_contract_version": 1,
                "preflight": {
                    "ready": True,
                    "volume_root": "/runpod-volume",
                    "platform": "Linux",
                    "python_version": "3.12.9",
                    "gpu": {"available": True, "name": "NVIDIA H100 80GB HBM3", "memory_gb": 80, "driver_version": "575.10"},
                    "config_digest": payload["input"]["config_digest"],
                    "checks": [
                        {"id": "network_volume", "passed": True, "detail": "mounted"},
                        {"id": "gpu", "passed": True, "detail": "H100 ready"},
                    ],
                },
            },
        }

    def status(self, endpoint_id: str, job_id: str):
        self.checks += 1
        if self.checks == 1:
            return {"id": job_id, "status": "IN_PROGRESS", "progress": "Step 120 / 2000", "delayTime": 500}
        return {
            "id": job_id,
            "status": "COMPLETED",
            "delayTime": 500,
            "executionTime": 123_000,
            "output": {
                "status": "success",
                "fingerprint": "fingerprint-1",
                "config_digest": self.submitted[1]["input"]["config_digest"],
                "artifacts": [
                    {
                        "kind": "checkpoint",
                        "name": "person.safetensors",
                        "path": "/runpod-volume/lorasuite/job/output/person.safetensors",
                        "sha256": "abc123",
                        "size_bytes": 42,
                    }
                ],
            },
        }

    def cancel(self, endpoint_id: str, job_id: str):
        self.canceled.append((endpoint_id, job_id))
        return {"id": job_id, "status": "CANCELLED"}


class FakeArtifactDownloader:
    def __init__(self):
        self.downloads = []

    def download_url(self, url: str, destination: Path):
        self.downloads.append(("url", url))
        destination.write_bytes(b"checkpoint-data")

    def download_volume(self, bucket: str, key: str, destination: Path):
        self.downloads.append((bucket, key))
        destination.write_bytes(b"checkpoint-data")


def test_persists_runpod_serverless_lifecycle_without_api_key(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")

    queued = service.create_run(bundle_path=bundle, endpoint_id="endpoint-1")
    assert queued.parent_snapshot_id == "snapshot-v1"
    assert queued.parent_dataset_fingerprint == "fingerprint-v1"
    assert queued.improvement_request_id == "improvement-v2"
    assert queued.parent_artifact_id == "artifact-v1"
    assert queued.parent_checkpoint_sha256 == "checkpoint-v1-sha"
    submitted = service.submit_run(queued.id, "secret-api-key")
    running = service.refresh_run(submitted.id, "secret-api-key")
    completed = service.refresh_run(running.id, "secret-api-key")

    assert submitted.provider_job_id == "serverless-job-1"
    assert running.status == "running"
    assert running.progress_message == "Step 120 / 2000"
    assert completed.status == "completed"
    assert completed.execution_time_ms == 123_000
    assert completed.config_digest == provider.submitted[1]["input"]["config_digest"]
    assert completed.artifacts[0].kind == "checkpoint"
    assert completed.artifacts[0].volume_path.endswith("person.safetensors")
    assert provider.submitted[0] == "endpoint-1"
    assert provider.submitted[1]["input"]["action"] == "train_lora"
    assert "secret-api-key" not in service.runs_path.read_text()

    reused = service.create_run(bundle_path=bundle, endpoint_id="endpoint-1")
    assert reused.id == queued.id


def test_cancels_active_runpod_job(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: provider)
    _mark_preflight_ready(service, bundle, "endpoint-2")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-2").id, "token")

    canceled = service.cancel_run(run.id, "token")

    assert canceled.status == "canceled"
    assert provider.canceled == [("endpoint-2", "serverless-job-1")]


def test_rejects_completed_worker_output_with_wrong_fingerprint(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)

    class WrongFingerprintProvider(FakeRunPodProvider):
        def status(self, endpoint_id: str, job_id: str):
            payload = super().status(endpoint_id, job_id)
            if payload.get("status") == "COMPLETED":
                payload["output"]["fingerprint"] = "wrong-fingerprint"
            return payload

    provider = WrongFingerprintProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    service.refresh_run(run.id, "token")

    failed = service.refresh_run(run.id, "token")

    assert failed.status == "failed"
    assert failed.progress_message == "RunPod artifact provenance failed"
    assert failed.artifacts == []


def test_rejects_completed_worker_output_with_wrong_config_digest(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)

    class WrongConfigProvider(FakeRunPodProvider):
        def status(self, endpoint_id: str, job_id: str):
            payload = super().status(endpoint_id, job_id)
            if payload.get("status") == "COMPLETED":
                payload["output"]["config_digest"] = "wrong-config"
            return payload

    provider = WrongConfigProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    service.refresh_run(run.id, "token")

    failed = service.refresh_run(run.id, "token")

    assert failed.status == "failed"
    assert failed.progress_message == "RunPod configuration provenance failed"
    assert failed.artifacts == []


def test_downloads_volume_artifacts_atomically_and_verifies_provenance(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    downloader = FakeArtifactDownloader()
    service = RunPodTrainingRunService(
        tmp_path / "vault",
        provider_factory=lambda _token: provider,
        downloader_factory=lambda **_options: downloader,
    )
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    service.refresh_run(run.id, "token")
    completed = service.refresh_run(run.id, "token")
    payload = b"checkpoint-data"
    completed.artifacts[0].size_bytes = len(payload)
    completed.artifacts[0].sha256 = hashlib.sha256(payload).hexdigest()
    service._save(completed)

    downloaded = service.download_artifacts(
        run.id,
        output_dir=tmp_path / "downloads",
        volume_id="volume-1",
        endpoint_url="https://s3api-us-ca-2.runpod.io/",
        region="US-CA-2",
        access_key="user-key",
        secret_key="secret-key",
    )

    assert downloader.downloads == [("volume-1", "lorasuite/job/output/person.safetensors")]
    assert downloaded.artifacts[0].local_path.read_bytes() == payload
    persisted = service.runs_path.read_text()
    assert "user-key" not in persisted
    assert "secret-key" not in persisted


def test_rejects_blocked_bundle(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    manifest_path = bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["ready"] = False
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="not trainer-ready"):
        RunPodTrainingRunService(tmp_path / "vault").create_run(bundle_path=bundle, endpoint_id="endpoint")


def test_rejects_legacy_bundle_without_immutable_config_digest(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    manifest_path = bundle / "bundle_manifest.json"
    input_path = bundle / "runpod_input.json"
    manifest = json.loads(manifest_path.read_text())
    payload = json.loads(input_path.read_text())
    manifest.pop("config_digest")
    payload["input"].pop("config_digest")
    manifest_path.write_text(json.dumps(manifest))
    input_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="predates immutable config"):
        RunPodTrainingRunService(tmp_path / "vault").create_run(
            bundle_path=bundle,
            endpoint_id="endpoint",
        )


def test_resolves_runpod_token_without_persisting_it(monkeypatch) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "environment-key")
    assert resolve_runpod_token(None) == "environment-key"
    assert resolve_runpod_token("request-key") == "request-key"
    monkeypatch.delenv("RUNPOD_API_KEY")
    with pytest.raises(ValueError, match="RunPod API key"):
        resolve_runpod_token(None)


def test_reads_zero_shot_inference_action_from_bundle_contract(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    input_path = bundle / "runpod_input.json"
    payload = json.loads(input_path.read_text())
    payload["input"]["action"] = "run_id_lora"
    input_path.write_text(json.dumps(payload))

    run = RunPodTrainingRunService(tmp_path / "vault").create_run(bundle_path=bundle, endpoint_id="endpoint-1")

    assert run.action == "run_id_lora"


def test_persists_endpoint_preflight_without_api_key(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: provider)

    report = service.preflight(bundle_path=bundle, endpoint_id="endpoint-1", token="secret-key")

    assert report.ready is True
    assert report.gpu.name == "NVIDIA H100 80GB HBM3"
    assert report.bundle_fingerprint == "fingerprint-1"
    assert service.list_preflight_reports(bundle_path=bundle, endpoint_id="endpoint-1")[0].id == report.id
    assert provider.preflight[1]["input"]["action"] == "preflight"
    assert provider.preflight[1]["input"]["requirements"]["minimum_gpu_memory_gb"] == 48
    assert "secret-key" not in service.preflight_reports_path.read_text()


def test_rejects_endpoint_without_lorasuite_preflight_contract(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)

    class IncompatibleProvider(FakeRunPodProvider):
        def run_sync(self, endpoint_id: str, payload: dict):
            return {"status": "COMPLETED", "output": {"message": "some other worker"}}

    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: IncompatibleProvider())

    with pytest.raises(RuntimeError, match="does not implement"):
        service.preflight(bundle_path=bundle, endpoint_id="endpoint-1", token="token")


def test_refuses_training_submission_without_matching_ready_preflight(tmp_path: Path) -> None:
    bundle = _ready_bundle(tmp_path)
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _token: FakeRunPodProvider())
    run = service.create_run(bundle_path=bundle, endpoint_id="endpoint-1")

    with pytest.raises(ValueError, match="Verify this RunPod endpoint"):
        service.submit_run(run.id, "token")


def _ready_bundle(tmp_path: Path) -> Path:
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
        "revision_lineage": {
            "parent_snapshot_id": "snapshot-v1",
            "parent_dataset_fingerprint": "fingerprint-v1",
            "improvement_request_id": "improvement-v2",
            "parent_artifact_id": "artifact-v1",
            "parent_checkpoint_sha256": "checkpoint-v1-sha",
        },
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


def _mark_preflight_ready(service: RunPodTrainingRunService, bundle: Path, endpoint_id: str) -> None:
    manifest = json.loads((bundle / "bundle_manifest.json").read_text())
    report = RunPodPreflightReport(
        bundle_path=bundle,
        bundle_fingerprint=manifest["fingerprint"],
        config_digest=manifest["config_digest"],
        training_target_profile_id=manifest["training_target_profile_id"],
        endpoint_id=endpoint_id,
        ready=True,
        checks=[{"id": "gpu", "passed": True, "detail": "ready"}],
    )
    service._write_preflight_reports({report.id: report})


@pytest.mark.parametrize("initial_status", ["in_queue", "running"])
@pytest.mark.parametrize("next_action", ["refresh", "cancel"])
def test_polling_failure_remains_recoverable_after_restart(tmp_path, monkeypatch, initial_status, next_action):
    from unittest.mock import Mock

    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    if initial_status == "running":
        service.refresh_run(run.id, "token")
    original_status = provider.status
    monkeypatch.setattr(provider, "status", Mock(side_effect=TimeoutError("temporary timeout")))

    interrupted = service.refresh_run(run.id, "token")
    assert interrupted.status == initial_status
    assert interrupted.completed_at is None
    assert interrupted.error == "temporary timeout"
    assert interrupted.provider_job_id == "serverless-job-1"

    restarted = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _: provider)
    assert restarted.get_run(run.id).model_dump(mode="json") == interrupted.model_dump(mode="json")
    monkeypatch.setattr(provider, "status", original_status)
    if next_action == "cancel":
        recovered = restarted.cancel_run(run.id, "token")
        assert recovered.status == "canceled"
        assert provider.canceled == [("endpoint-1", "serverless-job-1")]
    else:
        recovered = restarted.refresh_run(run.id, "token")
        if recovered.status == "running":
            recovered = restarted.refresh_run(run.id, "token")
        assert recovered.status == "completed"
        assert recovered.artifacts[0].kind == "checkpoint"
    assert recovered.error is None
    assert recovered.completed_at is not None


@pytest.mark.parametrize("response", [{}, {"status": "IN_PROGRESS"}])
def test_cancel_acknowledgment_waits_for_provider_confirmation(tmp_path, monkeypatch, response):
    from unittest.mock import Mock

    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    service.refresh_run(run.id, "token")
    cancel = Mock(return_value=response)
    monkeypatch.setattr(provider, "cancel", cancel)

    pending = service.cancel_run(run.id, "token")
    cancel.assert_called_once_with("endpoint-1", "serverless-job-1")
    assert pending.status == "running"
    assert pending.completed_at is None
    assert "waiting for RunPod confirmation" in pending.progress_message
    monkeypatch.setattr(provider, "status", Mock(return_value={"status": "CANCELLED"}))
    confirmed = service.refresh_run(run.id, "token")
    assert confirmed.status == "canceled"
    assert confirmed.completed_at is not None


def test_cancellation_failure_can_be_retried(tmp_path, monkeypatch):
    from unittest.mock import Mock

    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    cancel = Mock(side_effect=[TimeoutError("cancel timeout"), {"status": "CANCELLED"}])
    monkeypatch.setattr(provider, "cancel", cancel)
    uncertain = service.cancel_run(run.id, "token")
    assert uncertain.status == "in_queue"
    assert uncertain.completed_at is None
    assert uncertain.error == "cancel timeout"
    assert "not confirmed" in uncertain.progress_message
    canceled = service.cancel_run(run.id, "token")
    assert canceled.status == "canceled"
    assert canceled.error is None
    assert cancel.call_count == 2


@pytest.mark.parametrize("status", ["completed", "failed", "canceled", "timed_out"])
def test_cancel_preserves_terminal_run(tmp_path, status):
    from lorasuite_engine.runpod_runs import RunPodTrainingRun
    from unittest.mock import Mock

    factory = Mock(side_effect=AssertionError("Terminal job must not contact provider"))
    service = RunPodTrainingRunService(tmp_path, provider_factory=factory)
    run = RunPodTrainingRun(bundle_path=tmp_path, bundle_fingerprint="fingerprint", modality="image",
                            training_target_profile_id="profile", endpoint_id="endpoint", provider_job_id="job")
    terminal = service._save(run, status=status, message="Provider terminal result", error="reason" if status == "failed" else None)
    assert service.cancel_run(run.id, "token").model_dump(mode="json") == terminal.model_dump(mode="json")
    factory.assert_not_called()


def test_cancel_unsubmitted_run_does_not_contact_provider(tmp_path):
    from unittest.mock import Mock

    provider = Mock(side_effect=AssertionError("No job exists to cancel"))
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=provider)
    run = service.create_run(bundle_path=_ready_bundle(tmp_path), endpoint_id="endpoint")
    canceled = service.cancel_run(run.id, "token")
    assert canceled.status == "canceled"
    assert canceled.completed_at is not None
    assert canceled.progress_message == "Canceled before submission to RunPod"
    provider.assert_not_called()


def test_cancel_that_races_with_completion_preserves_results(tmp_path, monkeypatch):
    bundle = _ready_bundle(tmp_path)
    provider = FakeRunPodProvider()
    service = RunPodTrainingRunService(tmp_path / "vault", provider_factory=lambda _: provider)
    _mark_preflight_ready(service, bundle, "endpoint-1")
    run = service.submit_run(service.create_run(bundle_path=bundle, endpoint_id="endpoint-1").id, "token")
    service.refresh_run(run.id, "token")
    monkeypatch.setattr(provider, "cancel", provider.status)
    finished = service.cancel_run(run.id, "token")
    assert finished.status == "completed"
    assert finished.artifacts[0].kind == "checkpoint"
    assert finished.completed_at is not None
    assert finished.error is None
