import hashlib
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import lorasuite_engine.api as api_module
from lorasuite_engine.api import create_app
from lorasuite_engine.comfyui_handoff import ComfyRuntimeStatus
from lorasuite_engine.models import (
    IngressCandidate,
    IngressScanResult,
    MediaType,
    ProcessingJob,
    VisionCaptionEvidence,
)
from lorasuite_engine.vision_caption import OpenAICompatibleVisionProvider
from lorasuite_engine.runpod_runs import RunPodPreflightReport, RunPodTrainingRun
from lorasuite_engine.runpod_bootstrap import RunPodModelBootstrapRun
from lorasuite_engine.runpod_uploads import RunPodBundleUploadJob
from lorasuite_engine.voice_evaluation import VoiceArtifactEvaluationRun
from lorasuite_engine.id_lora_evaluation import IdLoraEvaluationRun
from lorasuite_engine.model_registry import ArtifactAcceptance, ArtifactEvaluation, ModelArtifactRecord
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.social_acquisition import SocialAcquisitionService
from lorasuite_engine.training_targets import get_training_target_profile


def test_social_acquisition_api_persists_and_polls_job(tmp_path, monkeypatch) -> None:
    def complete_without_network(self: SocialAcquisitionService, job_id: str):
        job = self.get_job(job_id)
        assert job is not None
        return self._save(
            job,
            status="complete",
            progress_message="Retrieved 0 candidate records",
            result=IngressScanResult(metadata_json={"has_more": False}),
        )

    monkeypatch.setattr(SocialAcquisitionService, "process_job", complete_without_network)
    app = create_app(vault_root=tmp_path / "vault")
    with TestClient(app) as test_client:
        created = test_client.post(
            "/ingress/social-acquisitions",
            json={
                "provider": "instagram",
                "url": "https://www.instagram.com/subject",
                "browser": "chrome",
                "limit": 24,
                "scan_mode": "all",
            },
        )
        job_id = created.json()["id"]
        fetched = test_client.get(f"/ingress/social-acquisitions/{job_id}")
        listed = test_client.get("/ingress/social-acquisitions")

    assert created.status_code == 200
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "complete"
    assert fetched.json()["result"]["metadata_json"]["has_more"] is False
    assert [job["id"] for job in listed.json()] == [job_id]
    assert (tmp_path / "vault" / "social_acquisition_jobs.json").is_file()


def test_native_folder_selector_returns_selected_path(tmp_path, monkeypatch) -> None:
    selected = tmp_path / "package-output"
    selected.mkdir()
    monkeypatch.setattr(api_module, "pick_native_directory", lambda: selected)
    app = create_app(vault_root=tmp_path / "vault")

    with TestClient(app) as test_client:
        response = test_client.post("/system/folders/select", json={})

    assert response.status_code == 200
    assert response.json() == {"path": str(selected)}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allow_runpod_smoke(monkeypatch, bundle_path: Path) -> None:
    normalized = bundle_path.resolve(strict=False)

    class Bundle:
        id = "bundle-smoke-1"
        output_path = normalized

    class BundleService:
        def list_bundles(self):
            return [Bundle()]

    class Smoke:
        ready = True
        checks = []
        error = None

    class SmokeService:
        def run_runpod(self, bundle_id):
            assert bundle_id == Bundle.id
            return Smoke()

    monkeypatch.setattr(api_module, "RunPodBundleService", lambda _root: BundleService())
    monkeypatch.setattr(api_module, "ProviderSmokeService", lambda _root: SmokeService())


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lorasuite-engine"}


def test_state_migration_routes_preview_and_apply_legacy_vault(client, tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    (vault_root / "vault.json").write_text(
        json.dumps({"sources": [], "media_items": []}),
        encoding="utf-8",
    )

    preview = client.get("/state-migrations")

    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["pending_count"] == 1
    assert json.loads((vault_root / "vault.json").read_text(encoding="utf-8")).get("version") is None

    applied = client.post("/state-migrations/apply", json={})

    assert applied.status_code == 200
    assert applied.json()["ready"] is True
    assert applied.json()["updated_count"] == 1
    assert json.loads((vault_root / "vault.json").read_text(encoding="utf-8"))["version"] == 1
    assert (vault_root / "state_schema.json").is_file()


def test_diagnostic_bundle_routes_create_list_and_download(client):
    created = client.post("/diagnostic-bundles", json={})

    assert created.status_code == 200
    payload = created.json()
    assert payload["format"] == "lorasuite.diagnostic-bundle.v1"
    assert payload["included_files"] == [
        "diagnostic_report.json",
        "partner_readiness.json",
        "README.txt",
    ]
    listed = client.get("/diagnostic-bundles")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [payload["id"]]
    downloaded = client.get(f"/diagnostic-bundles/{payload['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert downloaded.content.startswith(b"PK")


def test_comfyui_handoff_preview_and_evaluation_report_routes(client, tmp_path, monkeypatch):
    artifact = ModelArtifactRecord(
        id="artifact-1",
        project_id="project-1",
        training_run_id="run-1",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name="person.safetensors",
        checkpoint_path=tmp_path / "person.safetensors",
        checkpoint_sha256="checkpoint-sha",
        checkpoint_size_bytes=1,
        trigger_token="person_token",
        base_model="black-forest-labs/FLUX.1-dev",
        modality="image",
        model_family="flux1",
        evaluation=ArtifactEvaluation(
            status="ready",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )
    atomic_write_json(
        client.app.state.vault_root / "model_artifacts.json",
        {"version": 1, "artifacts": [artifact.model_dump(mode="json")]},
    )
    comfy_root = tmp_path / "ComfyUI"
    (comfy_root / "models").mkdir(parents=True)

    preview = client.get(
        f"/model-artifacts/{artifact.id}/comfyui-handoff",
        params={"comfy_root": str(comfy_root)},
    )

    assert preview.status_code == 200
    assert preview.json()["format"] == "lorasuite.comfy-handoff.v1"
    assert preview.json()["compatibility"]["status"] == "review"
    assert preview.json()["workflows"][0]["purpose"] == "component"
    assert preview.json()["extension"]["runtime_verified"] is False
    assert preview.json()["extension"]["restart_required"] is None

    monkeypatch.setattr(
        api_module,
        "inspect_comfy_runtime",
        lambda root, base_url: ComfyRuntimeStatus(
            root=root,
            base_url=base_url,
            reachable=True,
            extension_installed=True,
            extension_version="0.1.0",
            loaded_nodes=[],
            restart_required=True,
        ),
    )
    runtime = client.get(
        "/comfyui/runtime-status",
        params={
            "comfy_root": str(comfy_root),
            "base_url": "http://127.0.0.1:8188",
        },
    )
    assert runtime.status_code == 200
    assert runtime.json()["restart_required"] is True

    created = client.post(
        "/comfyui/evaluation-reports",
        json={
            "artifact_id": artifact.id,
            "checkpoint_sha256": artifact.checkpoint_sha256,
            "workflow_id": "workflow-1",
            "verdict": "pass",
            "rating": 5,
            "prompt": "person_token, portrait",
            "seed": 42,
            "output_paths": [str(tmp_path / "output.png")],
            "notes": "Identity held.",
            "metrics": {"identity_similarity": 0.9},
        },
    )

    assert created.status_code == 200
    assert created.json()["project_id"] == "project-1"
    reports = client.get(
        "/comfyui/evaluation-reports",
        params={"artifact_id": artifact.id},
    )
    assert reports.status_code == 200
    assert reports.json()[0]["id"] == created.json()["id"]
    rejected = client.post(
        "/comfyui/evaluation-reports",
        json={
            "artifact_id": artifact.id,
            "checkpoint_sha256": "wrong",
        },
    )
    assert rejected.status_code == 400


def test_recovered_dataset_export_routes_preserve_manifest_provenance(client, tmp_path):
    export_path = tmp_path / "recovered-export"
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
            "sha256": file_sha256(image_path),
        }],
    }), encoding="utf-8")

    registered = client.post(
        "/recovered-dataset-exports",
        json={"export_path": str(export_path)},
    )

    assert registered.status_code == 200
    payload = registered.json()
    assert payload["ready"] is True
    assert payload["snapshot_id"] == "snapshot-recovered"
    assert payload["fingerprint"] == "recovered-fingerprint"
    assert payload["trigger_token"] == "person_token"
    listed = client.get("/recovered-dataset-exports")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [payload["id"]]
    verified = client.post(
        f"/recovered-dataset-exports/{payload['id']}/verify",
        json={},
    )
    assert verified.status_code == 200
    assert verified.json()["verified_file_count"] == 1


def test_training_estimate_api_reports_duration_pricing_and_cost(client):
    response = client.post(
        "/training-estimates",
        json={
            "provider": "runcomfy",
            "training_target_profile_id": "runcomfy_flux1_dev_character",
            "gpu_type": "ADA_80_PLUS",
            "pricing_tier": "pro",
            "config_file": "train:\n  steps: 1000\n",
            "dataset_item_count": 35,
        },
    )

    assert response.status_code == 200
    estimate = response.json()
    assert estimate["available"] is True
    assert estimate["duration_hours"]["expected"] == 0.85
    assert estimate["hourly_rate_usd"] == 3.59
    assert estimate["cost_usd"]["expected"] == 3.05
    assert estimate["pricing_snapshot_date"] == "2026-07-16"


def test_runcomfy_resume_api_reuses_stopped_run(client, monkeypatch):
    monkeypatch.setenv("RUNCOMFY_TOKEN", "session-token")
    resumed = []

    class Run:
        id = "training-run-1"
        status = "stopped"

        def model_dump(self, mode="json"):
            assert mode == "json"
            return {"id": self.id, "status": self.status}

    run = Run()

    class FakeService:
        def get_run(self, run_id):
            return run if run_id == run.id else None

        def resume_run(self, run_id, token):
            resumed.append((run_id, token))
            return run

    monkeypatch.setattr(api_module, "TrainingRunService", lambda _root: FakeService())

    response = client.post(f"/training-runs/{run.id}/resume", json={})

    assert response.status_code == 200
    assert response.json() == {"id": run.id, "status": "stopped"}
    assert resumed == [(run.id, "session-token")]


def test_provider_smoke_api_runs_and_restores_runcomfy_contract(client, tmp_path):
    export = tmp_path / "image-export"
    images = export / "images"
    images.mkdir(parents=True)
    image = images / "000001.png"
    caption = images / "000001.txt"
    image.write_bytes(b"image")
    caption.write_text("person_token, portrait\n")
    (export / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "status": "complete",
        "training_target": {"profile_id": "runcomfy_flux1_dev_character"},
        "files": [{"image": str(image), "caption": str(caption), "sha256": file_sha256(image)}],
    }))
    profile = get_training_target_profile("runcomfy_flux1_dev_character")
    config = profile.config_template.format(
        job_name="person-flux-v1",
        trigger_token="person_token",
        sample_prompt="person portrait",
        dataset_name="{dataset_name}",
    )

    created = client.post("/provider-smoke-runs/runcomfy", json={
        "project_id": "project-1",
        "source_export_path": str(export),
        "training_target_profile_id": profile.profile_id,
        "config_file": config,
    })
    listed = client.get("/provider-smoke-runs", params={"project_id": "project-1", "provider": "runcomfy"})
    restored = client.get(f"/provider-smoke-runs/{created.json()['id']}")

    assert created.status_code == 200
    assert created.json()["ready"] is True
    assert listed.json()[0]["id"] == created.json()["id"]
    assert restored.json() == created.json()


def test_runpod_cloud_submission_requires_registered_smoke_tested_bundle(client, tmp_path):
    response = client.post("/runpod-bundle-upload-jobs", json={
        "bundle_path": str(tmp_path / "unregistered-bundle"),
        "volume_id": "volume-1",
        "s3_endpoint": "https://s3.example/",
        "datacenter": "US-CA-2",
    })

    assert response.status_code == 400
    assert "must be registered" in response.json()["detail"]


def test_model_release_candidates_are_ranked_and_selected_durably(client):
    artifact = ModelArtifactRecord(
        id="release-artifact-1",
        project_id="release-project-1",
        training_run_id="training-1",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name="person-step-1000.safetensors",
        checkpoint_path=Path("/tmp/person-step-1000.safetensors"),
        checkpoint_sha256="abc123",
        checkpoint_size_bytes=1024,
        modality="video",
        model_family="wan22_14b_t2v",
        evaluation=ArtifactEvaluation(status="ready", checkpoint_valid=True, provenance_valid=True, config_present=True),
        acceptance=ArtifactAcceptance(status="certified", screening_ready=True, release_ready=True, passed_count=4, identity_similarity=0.84, temporal_stability=0.79),
    )
    atomic_write_json(client.app.state.vault_root / "model_artifacts.json", {
        "version": 1,
        "artifacts": [artifact.model_dump(mode="json")],
    })

    candidates = client.get("/model-artifacts/release-candidates", params={"project_id": "release-project-1", "modality": "video"})
    selected = client.post(f"/model-artifacts/{artifact.id}/select-release")
    restored = client.get("/model-artifacts/release-candidates", params={"project_id": "release-project-1", "modality": "video"})

    assert candidates.status_code == 200
    assert candidates.json()[0]["eligible"] is True
    assert candidates.json()[0]["score"] > 0
    assert selected.status_code == 200
    assert selected.json()["selected_for_release"] is True
    assert restored.json()[0]["selected"] is True


def test_runpod_infrastructure_profile_adopts_existing_resources_without_persisting_secrets(client):
    response = client.post(
        "/runpod-infrastructure-profiles/provision",
        json={
            "name": "Existing RunPod",
            "image_name": "docker.io/example/lorasuite-worker:sha-123",
            "data_center_id": "US-KS-2",
            "network_volume_id": "volume-existing",
            "template_id": "template-existing",
            "endpoint_id": "endpoint-existing",
            "runtime_environment": {"HF_TOKEN": "secret-hf-token"},
            "api_token": "secret-runpod-token",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["endpoint_id"] == "endpoint-existing"
    listed = client.get("/runpod-infrastructure-profiles")
    assert listed.status_code == 200
    assert listed.json()[0]["network_volume_id"] == "volume-existing"
    profiles_path = client.app.state.vault_root / "runpod_infrastructure_profiles.json"
    persisted = profiles_path.read_text(encoding="utf-8")
    assert "secret-hf-token" not in persisted
    assert "secret-runpod-token" not in persisted


def test_training_targets_expose_runcomfy_model_profiles(client):
    response = client.get("/training-targets")

    assert response.status_code == 200
    profiles = {item["profile_id"]: item for item in response.json()}
    assert profiles["runcomfy_flux1_dev_character"]["base_model"] == "black-forest-labs/FLUX.1-dev"
    assert profiles["runcomfy_qwen_image_character"]["base_model"] == "Qwen/Qwen-Image"
    assert "{dataset_name}" in profiles["runcomfy_flux1_dev_character"]["config_template"]
    assert profiles["runcomfy_krea2_raw_character"]["ready"] is True
    assert 'arch: "krea2"' in profiles["runcomfy_krea2_raw_character"]["config_template"]
    assert profiles["runcomfy_wan22_14b_t2v_character"]["ready"] is True
    assert "num_frames: 41" in profiles["runcomfy_wan22_14b_t2v_character"]["config_template"]
    assert profiles["runpod_id_lora_ltx23"]["ready"] is False
    assert profiles["runpod_id_lora_ltx23"]["launcher_kind"] == "id_lora_ltx23"
    assert profiles["runcomfy_flux1_dev_character"]["required_environment"] == ["HF_TOKEN"]
    assert profiles["runpod_fish_speech_s2_voice_lora"]["required_model_paths"] == ["/workspace/models/fish-speech-s2/codec.pth"]
    assert profiles["runpod_id_lora_ltx23_inference"]["minimum_gpu_memory_gb"] == 80
    assert profiles["runcomfy_flux1_dev_character"]["recipe_id"] == "flux1_dev_character"
    assert profiles["runcomfy_flux1_dev_character"]["recipe"]["training"]["steps"] == 2000

    recipes = client.get("/model-intent-recipes")
    assert recipes.status_code == 200
    assert recipes.json()[0]["recipe_id"] == "flux1_dev_character"
    assert recipes.json()[0]["metadata"]["schema_version"] == "lorasuite.model-card.v1"


def test_cloud_provider_contract_and_normalized_run_routes(client):
    providers = client.get("/cloud-providers")
    runs = client.get("/cloud-runs", params={"provider": "runpod"})

    assert providers.status_code == 200
    by_id = {item["id"]: item for item in providers.json()}
    assert by_id["runcomfy"]["contract_version"] == "lorasuite.cloud-provider.v1"
    assert next(
        feature
        for feature in by_id["runpod"]["features"]
        if feature["id"] == "immutable_config"
    )["support"] == "native"
    assert runs.status_code == 200
    assert runs.json() == []


def test_syncnet_capability_route_reports_release_certification_readiness(client, monkeypatch, tmp_path):
    monkeypatch.delenv("LORASUITE_SYNCNET_COMMAND", raising=False)
    monkeypatch.delenv("LORASUITE_SYNCNET_REPO", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    response = client.get("/evaluation/capabilities/syncnet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "unconfigured"
    assert payload["ready"] is False
    assert payload["problems"]


def test_runpod_training_routes_launch_refresh_and_cancel(client, monkeypatch, tmp_path):
    allow_runpod_smoke(monkeypatch, tmp_path / "bundle")
    run = RunPodTrainingRun(
        id="runpod-run-1",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="fingerprint",
        modality="image",
        training_target_profile_id="runcomfy_flux1_dev_character",
        endpoint_id="endpoint-1",
    )

    class FakeService:
        def list_runs(self, bundle_path=None):
            return [run]

        def get_run(self, run_id):
            return run if run_id == run.id else None

        def create_run(self, bundle_path, endpoint_id):
            assert bundle_path == tmp_path / "bundle"
            assert endpoint_id == "endpoint-1"
            return run

        def submit_run(self, run_id, token):
            assert token == "session-key"
            run.provider_job_id = "job-1"
            run.status = "in_queue"
            return run

        def refresh_run(self, run_id, token):
            run.status = "running"
            return run

        def cancel_run(self, run_id, token):
            run.status = "canceled"
            return run

        def download_artifacts(self, run_id, **options):
            assert options["volume_id"] == "volume-1"
            assert options["region"] == "US-CA-2"
            run.progress_message = "Downloaded 1 RunPod artifact(s)"
            return run

    service = FakeService()
    monkeypatch.setattr(api_module, "RunPodTrainingRunService", lambda _root: service)
    class FakeRegistry:
        def register_runpod_run(self, run_id):
            assert run_id == run.id
            return []

    monkeypatch.setattr(api_module, "ModelRegistryService", lambda _root: FakeRegistry())
    monkeypatch.setattr(api_module, "resolve_runpod_token", lambda token: token or "environment-key")

    launched = client.post("/runpod-training-runs", json={
        "bundle_path": str(tmp_path / "bundle"),
        "endpoint_id": "endpoint-1",
        "api_token": "session-key",
    })
    assert launched.status_code == 200
    assert launched.json()["provider_job_id"] == "job-1"
    assert client.get("/runpod-training-runs").json()[0]["id"] == run.id
    assert client.get(f"/runpod-training-runs/{run.id}").json()["status"] == "in_queue"
    assert client.post(f"/runpod-training-runs/{run.id}/refresh", json={"api_token": "session-key"}).json()["status"] == "running"
    downloaded = client.post(f"/runpod-training-runs/{run.id}/download-artifacts", json={
        "output_dir": str(tmp_path / "downloads"),
        "volume_id": "volume-1",
        "s3_endpoint": "https://s3api-us-ca-2.runpod.io/",
        "datacenter": "US-CA-2",
        "access_key": "user-key",
        "secret_key": "secret-key",
    })
    assert downloaded.json()["progress_message"] == "Downloaded 1 RunPod artifact(s)"
    registered = client.post(f"/runpod-training-runs/{run.id}/register-artifacts")
    assert registered.status_code == 200
    assert registered.json() == []
    assert client.post(f"/runpod-training-runs/{run.id}/cancel", json={"api_token": "session-key"}).json()["status"] == "canceled"


def test_runpod_model_bootstrap_routes_launch_refresh_and_cancel(client, monkeypatch):
    run = RunPodModelBootstrapRun(
        id="bootstrap-1",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
        endpoint_id="endpoint-1",
    )

    class FakeService:
        def list_runs(self, endpoint_id=None, training_target_profile_id=None):
            assert endpoint_id in {None, "endpoint-1"}
            assert training_target_profile_id in {None, "runpod_fish_speech_s2_voice_lora"}
            return [run]

        def get_run(self, run_id):
            return run if run_id == run.id else None

        def create_run(self, endpoint_id, training_target_profile_id):
            assert endpoint_id == "endpoint-1"
            assert training_target_profile_id == "runpod_fish_speech_s2_voice_lora"
            return run

        def submit_run(self, run_id, token):
            assert token == "session-key"
            run.provider_job_id = "provider-1"
            run.status = "in_queue"
            return run

        def refresh_run(self, run_id, token):
            assert token == "session-key"
            run.status = "running"
            return run

        def cancel_run(self, run_id, token):
            assert token == "session-key"
            run.status = "canceled"
            return run

    monkeypatch.setattr(api_module, "RunPodModelBootstrapService", lambda _root: FakeService())
    monkeypatch.setattr(api_module, "resolve_runpod_token", lambda token: token or "environment-key")

    listed = client.get("/runpod-model-bootstrap-runs?endpoint_id=endpoint-1&training_target_profile_id=runpod_fish_speech_s2_voice_lora")
    created = client.post("/runpod-model-bootstrap-runs", json={
        "endpoint_id": "endpoint-1",
        "training_target_profile_id": "runpod_fish_speech_s2_voice_lora",
        "api_token": "session-key",
    })
    refreshed = client.post("/runpod-model-bootstrap-runs/bootstrap-1/refresh", json={"api_token": "session-key"})
    canceled = client.post("/runpod-model-bootstrap-runs/bootstrap-1/cancel", json={"api_token": "session-key"})

    assert listed.status_code == 200
    assert created.json()["provider_job_id"] == "provider-1"
    assert refreshed.json()["status"] == "running"
    assert canceled.json()["status"] == "canceled"


def test_runpod_preflight_routes_persist_endpoint_readiness(client, monkeypatch, tmp_path):
    report = RunPodPreflightReport(
        id="preflight-1",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="fingerprint",
        training_target_profile_id="runcomfy_flux1_dev_character",
        endpoint_id="endpoint-1",
        ready=True,
        volume_root="/runpod-volume",
        gpu={"available": True, "name": "NVIDIA H100 80GB HBM3", "memory_gb": 80, "driver_version": "575.10"},
        checks=[{"id": "gpu", "passed": True, "detail": "H100 ready"}],
    )

    class FakeService:
        def list_preflight_reports(self, **options):
            assert options["endpoint_id"] == "endpoint-1"
            return [report]

        def preflight(self, **options):
            assert options["bundle_path"] == tmp_path / "bundle"
            assert options["endpoint_id"] == "endpoint-1"
            assert options["token"] == "session-key"
            return report

    monkeypatch.setattr(api_module, "RunPodTrainingRunService", lambda _root: FakeService())
    monkeypatch.setattr(api_module, "resolve_runpod_token", lambda token: token or "environment-key")

    created = client.post("/runpod-preflight-reports", json={
        "bundle_path": str(tmp_path / "bundle"),
        "endpoint_id": "endpoint-1",
        "api_token": "session-key",
    })
    listed = client.get("/runpod-preflight-reports", params={
        "bundle_path": str(tmp_path / "bundle"),
        "endpoint_id": "endpoint-1",
    })

    assert created.status_code == 200
    assert created.json()["ready"] is True
    assert listed.status_code == 200
    assert listed.json()[0]["gpu"]["memory_gb"] == 80


def test_runpod_bundle_upload_routes_queue_monitor_and_resume(client, monkeypatch, tmp_path):
    allow_runpod_smoke(monkeypatch, tmp_path / "bundle")
    job = RunPodBundleUploadJob(
        id="upload-1",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="fingerprint",
        training_target_profile_id="runcomfy_flux1_dev_character",
        volume_id="volume-1",
        endpoint_url="https://s3.example/",
        datacenter="US-CA-2",
        remote_prefix="lorasuite/image-fingerprint",
        files_total=4,
        bytes_total=100,
    )

    class FakeService:
        def list_jobs(self, bundle_path=None):
            assert bundle_path == tmp_path / "bundle"
            return [job]

        def get_job(self, job_id):
            return job if job_id == job.id else None

        def create_job(self, **options):
            assert options["volume_id"] == "volume-1"
            return job

        def resume_job(self, job_id):
            job.status = "queued"
            return job

        def process_job(self, job_id, access_key, secret_key):
            assert access_key == "access-key"
            assert secret_key == "secret-key"
            job.status = "complete"
            job.files_uploaded = job.files_total
            job.bytes_uploaded = job.bytes_total
            return job

    monkeypatch.setattr(api_module, "RunPodBundleUploadService", lambda _root: FakeService())

    created = client.post("/runpod-bundle-upload-jobs", json={
        "bundle_path": str(tmp_path / "bundle"),
        "volume_id": "volume-1",
        "s3_endpoint": "https://s3.example/",
        "datacenter": "US-CA-2",
        "access_key": "access-key",
        "secret_key": "secret-key",
    })
    listed = client.get("/runpod-bundle-upload-jobs", params={"bundle_path": str(tmp_path / "bundle")})
    fetched = client.get(f"/runpod-bundle-upload-jobs/{job.id}")
    resumed = client.post(f"/runpod-bundle-upload-jobs/{job.id}/resume", json={"access_key": "access-key", "secret_key": "secret-key"})

    assert created.status_code == 200
    assert listed.json()[0]["status"] == "complete"
    assert fetched.json()["files_uploaded"] == 4
    assert resumed.status_code == 200


def test_voice_artifact_evaluation_routes_create_monitor_and_select(client, monkeypatch, tmp_path):
    run = VoiceArtifactEvaluationRun(
        id="voice-evaluation-1",
        project_id="project-1",
        artifact_id="artifact-1",
        checkpoint_name="voice_step_250.ckpt",
        checkpoint_step=250,
        samples_dir=tmp_path / "samples",
    )

    class FakeService:
        def list_runs(self, project_id=None):
            return [run]

        def get_run(self, run_id):
            return run if run_id == run.id else None

        def recommended_run(self, project_id):
            return run

        def create_run(self, **options):
            assert options["artifact_id"] == "artifact-1"
            return run

        def process_run(self, run_id):
            run.status = "complete"
            run.summary.screening_ready = True
            return run

        def select_for_release(self, run_id):
            run.selected_for_release = True
            return run

    monkeypatch.setattr(api_module, "VoiceArtifactEvaluationService", lambda _root: FakeService())

    created = client.post("/voice-artifact-evaluations", json={
        "project_id": "project-1",
        "artifact_id": "artifact-1",
        "samples_dir": str(tmp_path / "samples"),
    })
    assert created.status_code == 200
    assert created.json()["id"] == run.id
    assert client.get("/voice-artifact-evaluations?project_id=project-1").json()[0]["id"] == run.id
    assert client.get("/voice-artifact-evaluations/recommended?project_id=project-1").json()["checkpoint_step"] == 250
    assert client.get(f"/voice-artifact-evaluations/{run.id}").json()["status"] == "complete"
    selected = client.post(f"/voice-artifact-evaluations/{run.id}/select")
    assert selected.json()["selected_for_release"] is True


def test_id_lora_evaluation_routes_create_and_monitor(client, monkeypatch, tmp_path):
    run = IdLoraEvaluationRun(
        id="id-lora-evaluation-1",
        project_id="project-1",
        runpod_run_id="runpod-inference-1",
        contract_path=tmp_path / "contract.json",
    )

    class FakeService:
        def list_runs(self, project_id=None):
            return [run]

        def get_run(self, run_id):
            return run if run_id == run.id else None

        def create_run(self, runpod_run_id):
            assert runpod_run_id == "runpod-inference-1"
            return run

        def process_run(self, run_id):
            run.status = "complete"
            run.summary.screening_ready = True
            return run

    monkeypatch.setattr(api_module, "IdLoraEvaluationService", lambda _root: FakeService())

    created = client.post("/id-lora-evaluations", json={"runpod_run_id": "runpod-inference-1"})
    assert created.status_code == 200
    assert created.json()["id"] == run.id
    assert client.get("/id-lora-evaluations?project_id=project-1").json()[0]["id"] == run.id
    assert client.get(f"/id-lora-evaluations/{run.id}").json()["status"] == "complete"


def test_training_workflow_endpoint_returns_ai_next_action(client):
    project = client.post(
        "/character-projects",
        json={"name": "Workflow Character", "intent": {"subject_name": "Subject", "trigger_token": "subject_token"}},
    ).json()

    response = client.get(f"/training-workflow/{project['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_lane"] == "image"
    assert payload["recommendation"] == "Image LoRA: Review identity candidates"
    assert [lane["id"] for lane in payload["lanes"]] == ["image", "video", "voice", "id_lora", "evaluate"]


def test_provider_readiness_endpoint_returns_supported_handoff_matrix(client):
    project = client.post("/character-projects", json={"name": "Provider Character"}).json()

    response = client.get(f"/provider-readiness/{project['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 6
    assert {(item["lane"], item["provider"]) for item in payload["items"]} == {
        ("image", "runcomfy"), ("image", "runpod"),
        ("video", "runcomfy"), ("video", "runpod"),
        ("voice", "runpod"), ("id_lora", "runpod"),
    }
    assert all(item["state"] == "blocked" for item in payload["items"])


def test_partner_qualification_endpoint_returns_machine_readable_evidence(client):
    project = client.post("/character-projects", json={"name": "Partner Character"}).json()

    response = client.get(f"/partner-qualification/{project['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "lorasuite.partner-qualification.v1"
    assert payload["status"] == "in_progress"
    assert payload["passed_count"] == 0
    assert payload["total_count"] == 52
    assert {lane["partner"] for lane in payload["lanes"]} == {
        "runcomfy",
        "runpod",
        "comfyui",
    }
    assert response.json()["next_actions"]


def test_identity_status_reports_model_install_state(client):
    response = client.get("/identity/status")

    assert response.status_code == 200
    assert response.json() == {
        "backend": "opencv-sface",
        "model_version": "opencv-sface-2021dec-yunet-2023mar",
        "installed": False,
        "ready": False,
        "download_size_bytes": 39_000_000,
        "message": "Identity models are not installed",
    }


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
    ],
)
def test_engine_allows_local_browser_origins(client, origin):
    preflight = client.options(
        "/ingress/instagram/browser-scan",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    response = client.get("/health", headers={"Origin": origin})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-origin"] == origin


def test_vault_asset_endpoint_serves_files_under_vault(client, tmp_path):
    preview_path = tmp_path / "vault" / "previews" / "thumb.jpg"
    preview_path.parent.mkdir(parents=True)
    Image.new("RGB", (11, 13), color=(20, 40, 60)).save(preview_path)

    response = client.get("/assets/file", params={"path": str(preview_path)})

    assert response.status_code == 200
    assert response.content == preview_path.read_bytes()
    assert response.headers["content-type"] == "image/jpeg"


def test_vault_asset_endpoint_rejects_files_outside_vault(client, tmp_path):
    outside_path = tmp_path / "outside.jpg"
    Image.new("RGB", (11, 13), color=(20, 40, 60)).save(outside_path)

    response = client.get("/assets/file", params={"path": str(outside_path)})

    assert response.status_code == 404


def test_x_video_preview_endpoint_supports_byte_ranges(client, tmp_path, monkeypatch):
    preview_path = tmp_path / "vault" / "downloads" / "x_twitter" / "candidate.mp4"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"0123456789")

    monkeypatch.setattr(
        api_module.IngressService,
        "prepare_candidate_video_preview",
        lambda _service, candidate_id: preview_path if candidate_id == "candidate" else None,
    )

    response = client.get(
        "/ingress/candidates/candidate/video-preview",
        headers={"Range": "bytes=2-5"},
    )

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_x_thumbnail_endpoint_serves_materialized_video_poster(client, tmp_path, monkeypatch):
    preview_path = tmp_path / "vault" / "previews" / "x_twitter" / "candidate.png"
    preview_path.parent.mkdir(parents=True)
    Image.new("RGB", (20, 30), color=(20, 60, 100)).save(preview_path)
    monkeypatch.setattr(
        api_module.IngressService,
        "prepare_candidate_thumbnail",
        lambda _service, candidate_id: preview_path if candidate_id == "candidate" else None,
    )

    response = client.get("/ingress/candidates/candidate/thumbnail")

    assert response.status_code == 200
    assert response.content == preview_path.read_bytes()
    assert response.headers["content-type"] == "image/png"


def test_create_app_uses_env_vault_root(monkeypatch, tmp_path):
    vault_root = tmp_path / "env-vault"
    monkeypatch.setenv("LORASUITE_VAULT_ROOT", str(vault_root))

    app = create_app()

    assert app.state.vault_root == vault_root


def test_import_local_image_endpoint_copies_file_and_returns_media_items(client, tmp_path):
    image_path = tmp_path / "api-image.png"
    Image.new("RGB", (17, 29), color=(93, 10, 47)).save(image_path)
    expected_sha256 = file_sha256(image_path)

    response = client.post("/vault/import/local", json={"paths": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["errors"] == []
    assert len(payload["media_items"]) == 1
    media_item = payload["media_items"][0]
    raw_path = Path(media_item["raw_path"])
    assert raw_path.name == f"{expected_sha256}.png"
    assert raw_path.read_bytes() == image_path.read_bytes()
    assert media_item["media_type"] == "image"
    assert media_item["sha256"] == expected_sha256
    assert media_item["width"] == 17
    assert media_item["height"] == 29
    assert media_item["metadata_json"]["original_path"] == str(image_path)


def test_rotate_vault_image_endpoint_preserves_media_identity(client, tmp_path):
    image_path = tmp_path / "sideways.png"
    Image.new("RGB", (40, 20), color=(93, 10, 47)).save(image_path)
    imported = client.post(
        "/vault/import/local",
        json={"paths": [str(image_path)]},
    ).json()["media_items"][0]

    response = client.post(
        f"/vault/media/{imported['id']}/rotate",
        json={"degrees": 90},
    )

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["id"] == imported["id"]
    assert (rotated["width"], rotated["height"]) == (20, 40)
    assert rotated["metadata_json"]["orientation_corrected"] is True
    assert client.get("/vault/media").json()[0]["raw_path"] == rotated["raw_path"]


def test_duplicate_cluster_endpoint_reports_retained_source_paths(client, tmp_path):
    first_path = tmp_path / "duplicate-a.png"
    second_path = tmp_path / "duplicate-b.png"
    Image.new("RGB", (19, 27), color=(20, 80, 120)).save(first_path)
    second_path.write_bytes(first_path.read_bytes())

    client.post("/vault/import/local", json={"paths": [str(first_path)]})
    client.post("/vault/import/local", json={"paths": [str(second_path)]})
    response = client.get("/vault/duplicate-clusters")

    assert response.status_code == 200
    clusters = response.json()
    assert len(clusters) == 1
    assert clusters[0]["duplicate_count"] == 1
    assert clusters[0]["original_paths"] == sorted([str(first_path), str(second_path)])


def test_vault_media_page_endpoint_filters_and_rejects_stale_snapshots(client, tmp_path):
    first_path = tmp_path / "page-a.png"
    second_path = tmp_path / "page-b.png"
    Image.new("RGB", (19, 27), color=(20, 80, 120)).save(first_path)
    Image.new("RGB", (21, 29), color=(120, 40, 20)).save(second_path)
    first = client.post("/vault/import/local", json={"paths": [str(first_path)]}).json()
    page = client.get("/vault/media-page", params={"limit": 1, "media_type": "image"})

    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == first["media_items"][0]["id"]
    assert payload["has_more"] is False
    assert len(payload["snapshot"]) == 64

    client.post("/vault/import/local", json={"paths": [str(second_path)]})
    stale = client.get(
        "/vault/media-page",
        params={"offset": 1, "limit": 1, "snapshot": payload["snapshot"]},
    )
    assert stale.status_code == 409
    assert "changed" in stale.json()["detail"]


def test_clear_all_media_endpoint_requires_confirmation_and_clears_vault(client, tmp_path):
    image_path = tmp_path / "clear-me.png"
    Image.new("RGB", (20, 20), color=(93, 10, 47)).save(image_path)
    imported = client.post(
        "/vault/import/local",
        json={"paths": [str(image_path)]},
    ).json()["media_items"]
    assert len(imported) == 1

    rejected = client.post(
        "/vault/media/clear",
        json={"confirmation": "clear"},
    )
    response = client.post(
        "/vault/media/clear",
        json={"confirmation": "CLEAR ALL MEDIA"},
    )

    assert rejected.status_code == 400
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"
    assert response.json()["files_removed"] >= 2
    assert client.get("/vault/media").json() == []


def test_import_local_endpoint_returns_errors_for_invalid_paths(client, tmp_path):
    missing_path = tmp_path / "missing.png"

    response = client.post("/vault/import/local", json={"paths": [str(missing_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["media_items"] == []
    assert payload["errors"][0]["path"] == str(missing_path)
    assert payload["errors"][0]["code"] == "missing_path"
    assert not (tmp_path / "vault" / "raw").exists()
    assert not (tmp_path / "vault" / "vault.json").exists()


def test_dataset_snapshot_api_compiles_reviews_freezes_and_exports(client, tmp_path):
    image_path = tmp_path / "dataset-source.png"
    Image.new("RGB", (320, 480), color=(80, 40, 120)).save(image_path)
    media_item = client.post(
        "/vault/import/local", json={"paths": [str(image_path)]}
    ).json()["media_items"][0]
    project = client.post(
        "/character-projects",
        json={
            "name": "API Character",
            "intent": {
                "target_type": "character",
                "subject_name": "Mary",
                "trigger_token": "example_person",
                "description": "",
                "learned_attributes": ["identity"],
                "controllable_attributes": ["expression", "pose"],
                "excluded_attributes": ["background"],
            },
        },
    ).json()
    client.post(
        f"/character-projects/{project['id']}/candidates",
        json={"media_item_ids": [media_item["id"]]},
    )
    client.patch(
        f"/character-projects/{project['id']}/observations/{media_item['id']}",
        json={"review_status": "accepted", "view": "face"},
    )

    compiled_response = client.post(
        f"/character-projects/{project['id']}/dataset/compile", json={}
    )
    assert compiled_response.status_code == 200
    snapshot = compiled_response.json()
    item = next(iter(snapshot["items"].values()))
    assert item["caption"] == "example_person, person, close-up portrait"
    assert item["status"] == "needs_review"

    reviewed = client.patch(
        f"/dataset-snapshots/{snapshot['id']}/items/{item['id']}",
        json={
            "caption": "example_person, smiling person, close-up portrait",
            "status": "approved",
        },
    )
    assert reviewed.status_code == 200
    frozen = client.post(f"/dataset-snapshots/{snapshot['id']}/freeze", json={})
    assert frozen.status_code == 200
    assert frozen.json()["fingerprint"]

    output_dir = tmp_path / "api-dataset-export"
    exported = client.post(
        f"/dataset-snapshots/{snapshot['id']}/export/runcomfy",
        json={"output_dir": str(output_dir)},
    )
    assert exported.status_code == 200
    assert exported.json()["snapshot"]["status"] == "exported"
    assert (output_dir / "images" / "000001.txt").read_text(
        encoding="utf-8"
    ) == "example_person, smiling person, close-up portrait\n"
    metadata = client.patch(
        f"/dataset-snapshots/{snapshot['id']}/model-card",
        json={
            "display_name": "API Character Release",
            "license": "CC-BY-4.0",
            "recommended_strength": 0.85,
        },
    )
    assert metadata.status_code == 200
    assert metadata.json()["model_card"]["display_name"] == "API Character Release"
    assert metadata.json()["model_card"]["license"] == "CC-BY-4.0"
    assert metadata.json()["model_card"]["usage"]["recommended_strength"] == 0.85
    assert json.loads(
        (output_dir / "model_card.json").read_text(encoding="utf-8")
    )["display_name"] == "API Character Release"
    listed = client.get(
        "/dataset-snapshots", params={"project_id": project["id"]}
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == snapshot["id"]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed",
)
def test_video_dataset_api_compiles_reviews_freezes_and_exports(client, tmp_path):
    source_path = tmp_path / "video-source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x96:rate=16:duration=3",
            "-pix_fmt", "yuv420p", str(source_path),
        ],
        check=True,
    )
    media_item = client.post(
        "/vault/import/local", json={"paths": [str(source_path)]}
    ).json()["media_items"][0]
    client.post(
        "/curation/handoff", json={"media_item_ids": [media_item["id"]]}
    )
    client.patch(
        f"/curation/handoff/{media_item['id']}", json={"review_status": "accepted"}
    )
    project = client.post(
        "/character-projects",
        json={
            "name": "API Video Character",
            "intent": {
                "target_type": "character",
                "subject_name": "Mary",
                "trigger_token": "example_person",
                "description": "",
                "learned_attributes": ["identity", "motion"],
                "controllable_attributes": ["expression"],
                "excluded_attributes": ["background"],
            },
        },
    ).json()

    candidates = client.get("/video-dataset/candidates")
    assert candidates.status_code == 200
    assert [item["id"] for item in candidates.json()] == [media_item["id"]]

    compiled = client.post(
        "/video-dataset-snapshots/compile",
        json={"project_id": project["id"], "media_item_ids": [media_item["id"]]},
    )
    assert compiled.status_code == 200
    snapshot = compiled.json()
    item = next(iter(snapshot["items"].values()))
    assert item["caption"].startswith("example_person")

    reviewed = client.patch(
        f"/video-dataset-snapshots/{snapshot['id']}/items/{item['id']}",
        json={"status": "approved"},
    )
    assert reviewed.status_code == 200
    frozen = client.post(f"/video-dataset-snapshots/{snapshot['id']}/freeze", json={})
    assert frozen.status_code == 200
    assert frozen.json()["fingerprint"]

    output_dir = tmp_path / "api-video-export"
    exported = client.post(
        f"/video-dataset-snapshots/{snapshot['id']}/export",
        json={"output_dir": str(output_dir)},
    )
    assert exported.status_code == 200
    assert exported.json()["snapshot"]["status"] == "exported"
    assert list((output_dir / "videos").glob("*.mp4"))
    assert list((output_dir / "videos").glob("*.txt"))
    manifest = (output_dir / "manifest.json").read_text(encoding="utf-8")
    assert '"ready": true' in manifest


def test_id_lora_api_reports_prerequisites_before_compilation(client):
    project = client.post(
        "/character-projects",
        json={
            "name": "ID-LoRA API Character",
            "intent": {
                "target_type": "character",
                "subject_name": "Mary",
                "trigger_token": "example_person",
                "description": "",
                "learned_attributes": ["identity"],
                "controllable_attributes": ["expression"],
                "excluded_attributes": ["background"],
            },
        },
    ).json()

    listed = client.get("/id-lora-manifests", params={"project_id": project["id"]})
    compiled = client.post(
        "/id-lora-manifests/compile",
        json={"project_id": project["id"]},
    )

    assert listed.status_code == 200
    assert listed.json() == []
    assert compiled.status_code == 400
    assert "freeze a reviewed video dataset" in compiled.json()["detail"]


def test_benchmark_api_exposes_suite_and_validates_named_inputs(client, tmp_path):
    project = client.post("/character-projects", json={"name": "Benchmark Character"}).json()
    suite = client.get("/benchmark-suite")
    prepared = client.post(
        "/benchmark-suite/prepare",
        json={"project_id": project["id"], "output_dir": str(tmp_path / "evaluation")},
    )
    response = client.post(
        "/benchmark-runs",
        json={
            "project_id": project["id"],
            "baseline_dir": str(tmp_path / "baseline"),
            "lora_dir": str(tmp_path / "lora"),
        },
    )

    assert suite.status_code == 200
    assert [item["filename"] for item in suite.json()] == [
        "identity_closeup.mp4",
        "full_body_motion.mp4",
        "camera_motion.mp4",
        "speech_closeup.mp4",
    ]
    assert prepared.status_code == 200
    assert Path(prepared.json()["contract_path"]).is_file()
    assert response.status_code == 400
    assert "identity_closeup.mp4" in response.json()["detail"]


def test_benchmark_generation_api_queues_runcomfy_model_outputs(client, tmp_path, monkeypatch):
    project = client.post(
        "/character-projects",
        json={"name": "Generation Character", "intent": {"trigger_token": "person_token"}},
    ).json()
    monkeypatch.setenv("RUNCOMFY_TOKEN", "session-token")
    monkeypatch.setattr(
        api_module.BenchmarkGenerationService,
        "process_run",
        lambda service, run_id, _token: service.get_run(run_id),
    )

    response = client.post(
        "/benchmark-generation-runs/runcomfy",
        json={
            "project_id": project["id"],
            "workspace_root": str(tmp_path / "evaluation"),
            "model_id": "provider/video-model",
            "lora_path": "person-video-lora.safetensors",
            "seed_base": 1200,
        },
    )

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "queued"
    assert len(run["items"]) == 8
    assert run["items"][0]["seed"] == 1200
    listed = client.get("/benchmark-generation-runs", params={"project_id": project["id"]})
    restored = client.get(f"/benchmark-generation-runs/{run['id']}")
    assert listed.json()[0]["id"] == run["id"]
    assert restored.json()["lora_path"] == "person-video-lora.safetensors"


def test_benchmark_generation_api_queues_runpod_serverless_outputs(client, tmp_path, monkeypatch):
    project = client.post(
        "/character-projects",
        json={"name": "RunPod Generation Character", "intent": {"trigger_token": "person_token"}},
    ).json()
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-secret")
    monkeypatch.setattr(
        api_module.BenchmarkGenerationService,
        "process_run",
        lambda service, run_id, _token: service.get_run(run_id),
    )

    response = client.post(
        "/benchmark-generation-runs/runpod",
        json={
            "project_id": project["id"],
            "workspace_root": str(tmp_path / "evaluation"),
            "endpoint_id": "endpoint-video-1",
            "lora_path": "https://assets.test/person.safetensors",
            "seed_base": 1300,
        },
    )

    assert response.status_code == 200
    run = response.json()
    assert run["provider"] == "runpod_serverless"
    assert run["endpoint_id"] == "endpoint-video-1"
    assert run["items"][0]["seed"] == 1300
    assert run["baseline_payload"] == {"input": {"prompt": "$PROMPT", "seed": "$SEED"}}
    assert run["lora_payload"]["input"]["lora"]["path"] == "$LORA_PATH"


def test_image_benchmark_api_exposes_suite_and_both_generation_providers(client, tmp_path, monkeypatch):
    project = client.post(
        "/character-projects",
        json={"name": "Image Benchmark Character", "intent": {"trigger_token": "person_token"}},
    ).json()
    monkeypatch.setenv("RUNCOMFY_TOKEN", "runcomfy-secret")
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-secret")
    monkeypatch.setattr(
        api_module.BenchmarkGenerationService,
        "process_run",
        lambda service, run_id, _token: service.get_run(run_id),
    )

    suite = client.get("/image-benchmark-suite")
    prepared = client.post("/image-benchmark-suite/prepare", json={
        "project_id": project["id"],
        "output_dir": str(tmp_path / "image-evaluation"),
    })
    runcomfy = client.post("/image-benchmark-generation-runs/runcomfy", json={
        "project_id": project["id"],
        "workspace_root": str(tmp_path / "runcomfy-image"),
        "model_id": "provider/image-model",
        "lora_path": "person.safetensors",
    })
    runpod = client.post("/image-benchmark-generation-runs/runpod", json={
        "project_id": project["id"],
        "workspace_root": str(tmp_path / "runpod-image"),
        "endpoint_id": "endpoint-image-1",
        "lora_path": "https://assets.test/person.safetensors",
    })

    assert suite.status_code == 200
    assert len(suite.json()) == 6
    assert prepared.status_code == 200
    assert Path(prepared.json()["contract_path"]).name == "image_evaluation_contract.json"
    assert runcomfy.status_code == 200
    assert runcomfy.json()["benchmark_kind"] == "image"
    assert len(runcomfy.json()["items"]) == 12
    assert runpod.status_code == 200
    assert runpod.json()["provider"] == "runpod_serverless"
    filtered = client.get("/benchmark-generation-runs", params={
        "project_id": project["id"],
        "benchmark_kind": "image",
    })
    assert len(filtered.json()) == 2


def test_runpod_bundle_api_packages_a_lorasuite_export(client, tmp_path):
    source = tmp_path / "image-export"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"created_by": "LoraSuite", "modality": "image"}))
    (source / "images").mkdir()
    (source / "images" / "000001.png").write_bytes(b"image")
    (source / "images" / "000001.txt").write_text("person_token, portrait\n")

    response = client.post(
        "/runpod-bundles",
        json={
            "source_export_path": str(source),
            "output_path": str(tmp_path / "runpod-bundle"),
            "modality": "image",
            "trigger_token": "person_token",
            "fingerprint": "abcdef012345",
            "training_target_profile_id": "runcomfy_flux1_dev_character",
            "remote_root": "/workspace/lorasuite",
            "endpoint_id": "endpoint-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "runpod"
    assert payload["ready"] is True
    assert Path(payload["archive_path"]).is_file()
    assert Path(payload["config_path"]).is_file()


def test_caption_job_api_generates_review_evidence_without_persisting_key(
    client, tmp_path, monkeypatch
):
    image_path = tmp_path / "caption-source.png"
    Image.new("RGB", (320, 480), color=(80, 40, 120)).save(image_path)
    media_item = client.post(
        "/vault/import/local", json={"paths": [str(image_path)]}
    ).json()["media_items"][0]
    project = client.post(
        "/character-projects",
        json={
            "name": "Caption Character",
            "intent": {
                "target_type": "character",
                "subject_name": "Mary",
                "trigger_token": "example_person",
                "description": "",
                "learned_attributes": ["identity"],
                "controllable_attributes": ["expression", "pose"],
                "excluded_attributes": ["background"],
            },
        },
    ).json()
    client.post(
        f"/character-projects/{project['id']}/candidates",
        json={"media_item_ids": [media_item["id"]]},
    )
    client.patch(
        f"/character-projects/{project['id']}/observations/{media_item['id']}",
        json={"review_status": "accepted", "view": "full_body"},
    )
    snapshot = client.post(
        f"/character-projects/{project['id']}/dataset/compile", json={}
    ).json()
    item = next(iter(snapshot["items"].values()))

    monkeypatch.setattr(
        OpenAICompatibleVisionProvider,
        "caption",
        lambda self, image_path, intent, analysis_context=None: VisionCaptionEvidence(
            expression="smiling",
            pose="standing with one hand raised",
            clothing="red sleeveless dress",
            environment="indoors near windows",
            camera="eye-level full-body view",
            confidence=0.93,
        ),
    )

    response = client.post(
        f"/dataset-snapshots/{snapshot['id']}/caption-jobs",
        json={
            "item_ids": [item["id"]],
            "provider_id": "openai",
            "provider_label": "OpenAI",
            "dialect": "responses",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5",
            "api_key": "must-not-persist",
        },
    )
    assert response.status_code == 200
    job = client.get(f"/caption-jobs/{response.json()['id']}").json()
    assert job["status"] == "complete"
    assert job["completed_count"] == 1
    persisted_jobs = (tmp_path / "vault" / "caption_jobs.json").read_text(
        encoding="utf-8"
    )
    assert "must-not-persist" not in persisted_jobs

    updated = client.get(f"/dataset-snapshots/{snapshot['id']}").json()
    updated_item = updated["items"][item["id"]]
    assert updated_item["caption_source"] == "vision"
    assert updated_item["caption_provider"] == "OpenAI"
    assert updated_item["caption_confidence"] == 0.93
    assert updated_item["status"] == "needs_review"

    providers = client.get("/caption/providers")
    assert providers.status_code == 200
    assert {provider["id"] for provider in providers.json()} == {
        "apple_local",
        "openai",
        "grok",
        "grok_oauth",
        "kimi_code",
        "kimi_platform",
    }


def test_grok_oauth_login_endpoint_starts_local_cli(client, monkeypatch):
    monkeypatch.setattr(
        api_module,
        "start_grok_oauth_login",
        lambda: "Grok OAuth sign-in opened in your browser. Finish it, then refresh providers.",
    )

    response = client.post("/caption/providers/grok-oauth/login", json={})

    assert response.status_code == 200
    assert response.json() == {
        "started": True,
        "message": "Grok OAuth sign-in opened in your browser. Finish it, then refresh providers.",
    }








def test_local_ingress_scan_endpoint_returns_candidates(client, tmp_path):
    image_path = tmp_path / "scan-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)

    response = client.post("/ingress/local/scan", json={"roots": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["display_name"] == "scan-image.png"
    assert candidate["status"] == "ready"
    assert candidate["selected"] is True
    assert candidate["thumbnail_path"]


def test_local_ingress_upload_scan_endpoint_returns_candidates(client, tmp_path):
    image_path = tmp_path / "upload-image.png"
    Image.new("RGB", (29, 31), color=(15, 90, 120)).save(image_path)

    response = client.post(
        "/ingress/local/upload-scan",
        files={
            "files": (
                "browser/session/upload-image.png",
                image_path.read_bytes(),
                "image/png",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["errors"] == []
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["display_name"] == "upload-image.png"
    assert candidate["source_kind"] == "local"
    assert candidate["status"] == "ready"
    assert candidate["selected"] is True
    source_path = Path(candidate["source_locator"])
    assert source_path.name == "upload-image.png"
    assert source_path.read_bytes() == image_path.read_bytes()
    assert "uploads" in source_path.parts


def test_instagram_helper_scan_endpoint_returns_poster_candidates(client, tmp_path):
    poster = tmp_path / "api-poster.jpg"
    Image.new("RGB", (44, 66), color=(80, 20, 140)).save(poster)

    response = client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_api_video",
                        "source_url": "https://www.instagram.com/reel/api/",
                        "display_name": "api reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            },
            "include_video_posters_as_image_candidates": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 3
    assert body["candidates"][0]["source_kind"] == "instagram"
    assert body["candidates"][1]["media_type"] == "image"
    assert body["candidates"][2]["media_type"] == "audio"


def test_instagram_helper_scan_endpoint_stores_poster_candidates_for_jobs(
    client, tmp_path
):
    poster = tmp_path / "api-job-poster.jpg"
    Image.new("RGB", (44, 66), color=(30, 120, 80)).save(poster)
    scan = client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_api_job_video",
                        "source_url": "https://www.instagram.com/reel/api-job/",
                        "display_name": "api job reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            }
        },
    ).json()
    poster_candidate = [
        candidate
        for candidate in scan["candidates"]
        if candidate["media_type"] == "image"
    ][0]

    response = client.post(
        "/ingress/jobs",
        json={
            "source_kind": "instagram",
            "candidate_ids": [poster_candidate["id"]],
            "options": {},
        },
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["status"] == "complete"
    assert detail["imported_count"] == 1
    assert detail["imported_media_items"][0]["metadata_json"]["original_path"] == (
        poster_candidate["metadata_json"]["local_import_path"]
    )


def test_ingress_candidates_endpoint_filters_instagram_candidates(client, tmp_path):
    local_image = tmp_path / "local-candidate.png"
    Image.new("RGB", (12, 18), color=(10, 40, 90)).save(local_image)
    client.post("/ingress/local/scan", json={"roots": [str(local_image)]})

    poster = tmp_path / "instagram-poster.jpg"
    Image.new("RGB", (44, 66), color=(30, 120, 80)).save(poster)
    client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_filter_video",
                        "source_url": "https://www.instagram.com/reel/filter/",
                        "display_name": "filter reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            }
        },
    )

    response = client.get("/ingress/candidates", params={"source_kind": "instagram"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 3
    assert {candidate["source_kind"] for candidate in body["candidates"]} == {
        "instagram"
    }
    assert body["errors"] == []


def test_instagram_browser_scan_endpoint_stores_thumbnail_candidates(
    client, monkeypatch
):
    def fake_scan(
        url,
        vault_root,
        *,
        browser,
        limit,
        cursor,
        scan_mode,
        date_from,
        date_to,
    ):
        assert url == "https://www.instagram.com/reel/browser/"
        assert browser == "chrome"
        assert limit == 8
        assert cursor == "cursor_2"
        assert scan_mode == "tagged"
        assert date_from is None
        assert date_to is None
        return IngressScanResult(
            candidates=[
                IngressCandidate(
                    source_kind=api_module.SourceKind.INSTAGRAM,
                    source_locator=url,
                    display_name="browser reel",
                    media_type=MediaType.VIDEO,
                    selected=False,
                )
            ]
        )

    monkeypatch.setattr(api_module, "scan_instagram_url_with_browser_cookies", fake_scan)

    response = client.post(
        "/ingress/instagram/browser-scan",
        json={
            "url": "https://www.instagram.com/reel/browser/",
            "browser": "chrome",
            "limit": 8,
            "cursor": "cursor_2",
            "scan_mode": "tagged",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    listed = client.get("/ingress/candidates", params={"source_kind": "instagram"}).json()
    assert listed["candidates"][0]["display_name"] == "browser reel"


def test_x_browser_scan_endpoint_uses_browser_cookies_and_stores_candidates(client, monkeypatch):
    def fake_scan(url, vault_root, *, browser, limit, cursor, date_from, date_to):
        assert url == "https://x.com/subject"
        assert browser == "firefox"
        assert limit == 12
        assert cursor == "24"
        assert date_from == date(2026, 1, 1)
        assert date_to is None
        return IngressScanResult(
            candidates=[IngressCandidate(
                source_kind=api_module.SourceKind.X_TWITTER,
                source_locator="https://x.com/subject/status/1",
                display_name="X portrait",
                media_type=MediaType.IMAGE,
                selected=True,
            )],
            metadata_json={"next_cursor": "36", "has_more": True},
        )

    monkeypatch.setattr(api_module, "scan_x_url_with_browser_cookies", fake_scan)

    response = client.post("/ingress/x/browser-scan", json={
        "url": "https://x.com/subject",
        "browser": "firefox",
        "limit": 12,
        "cursor": "24",
        "date_from": "2026-01-01",
    })

    assert response.status_code == 200
    assert response.json()["metadata_json"]["next_cursor"] == "36"
    listed = client.get("/ingress/candidates", params={"source_kind": "x_twitter"}).json()
    assert listed["candidates"][0]["display_name"] == "X portrait"


def test_tiktok_browser_scan_endpoint_uses_browser_cookies_and_stores_candidates(
    client,
    monkeypatch,
):
    def fake_scan(url, vault_root, *, browser, limit, cursor, date_from, date_to):
        assert url == "https://www.tiktok.com/@subject"
        assert browser == "firefox"
        assert limit == 12
        assert cursor == "24"
        assert date_from == date(2026, 1, 1)
        assert date_to is None
        return IngressScanResult(
            candidates=[
                IngressCandidate(
                    source_kind=api_module.SourceKind.TIKTOK,
                    source_locator="https://www.tiktok.com/@subject/video/1",
                    display_name="TikTok clip",
                    media_type=MediaType.VIDEO,
                    selected=False,
                )
            ],
            metadata_json={"next_cursor": "36", "has_more": True},
        )

    monkeypatch.setattr(api_module, "scan_tiktok_url_with_browser_cookies", fake_scan)

    response = client.post(
        "/ingress/tiktok/browser-scan",
        json={
            "url": "https://www.tiktok.com/@subject",
            "browser": "firefox",
            "limit": 12,
            "cursor": "24",
            "date_from": "2026-01-01",
        },
    )

    assert response.status_code == 200
    assert response.json()["metadata_json"]["next_cursor"] == "36"
    listed = client.get("/ingress/candidates", params={"source_kind": "tiktok"}).json()
    assert listed["candidates"][0]["display_name"] == "TikTok clip"


def test_ingress_job_endpoint_processes_selected_candidates(client, tmp_path):
    image_path = tmp_path / "job-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]

    response = client.post(
        "/ingress/jobs",
        json={"source_kind": "local", "candidate_ids": [candidate_id], "options": {}},
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["status"] == "complete"
    assert detail["imported_count"] == 1
    assert detail["imported_media_items"][0]["metadata_json"]["original_path"] == str(
        image_path
    )


def test_ingress_job_endpoint_counts_unselected_reviewed_candidates_as_deferred(
    client, tmp_path
):
    source_dir = tmp_path / "reviewed-job"
    source_dir.mkdir()
    selected_path = source_dir / "selected.png"
    deferred_path = source_dir / "deferred.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(selected_path)
    Image.new("RGB", (29, 35), color=(100, 80, 90)).save(deferred_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(source_dir)]}).json()
    selected_id = scan["candidates"][0]["id"]
    deferred_id = scan["candidates"][1]["id"]

    response = client.post(
        "/ingress/jobs",
        json={
            "source_kind": "local",
            "candidate_ids": [selected_id],
            "reviewed_candidate_ids": [selected_id, deferred_id],
        },
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["candidate_count"] == 2
    assert detail["selected_count"] == 1
    assert detail["imported_count"] == 1
    assert detail["deferred_count"] == 1
    assert detail["failed_count"] == 0
    assert detail["deferred_candidates"][0]["candidate_id"] == deferred_id


def test_ingress_job_endpoint_imports_to_requested_destination_root(client, tmp_path):
    image_path = tmp_path / "destination-image.png"
    destination_root = tmp_path / "custom-vault"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]

    response = client.post(
        "/ingress/jobs",
        json={
            "source_kind": "local",
            "candidate_ids": [candidate_id],
            "options": {"destination_root": str(destination_root)},
        },
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    imported_path = Path(detail["imported_media_items"][0]["raw_path"])
    assert imported_path.is_relative_to(destination_root)
    assert imported_path.exists()


def test_ingress_jobs_endpoint_lists_recent_jobs(client, tmp_path):
    image_path = tmp_path / "listed-image.png"
    Image.new("RGB", (12, 14), color=(10, 20, 30)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]
    client.post("/ingress/jobs", json={"source_kind": "local", "candidate_ids": [candidate_id]})

    response = client.get("/ingress/jobs")

    assert response.status_code == 200
    assert response.json()[0]["source_kind"] == "local"


def test_create_processing_job_queues_video_breakdown(client, monkeypatch):
    scheduled_tasks = []

    def capture_task(self, func, *args, **kwargs):
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr(api_module.BackgroundTasks, "add_task", capture_task)

    response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": ["media_video_1"],
            "options": {
                "generate_frames": True,
                "extract_audio": True,
                "frames_per_second": 1,
                "max_frame_count": 2,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "video_breakdown"
    assert payload["status"] == "queued"
    assert payload["source_media_item_ids"] == ["media_video_1"]
    assert payload["options"]["max_frame_count"] == 2
    assert len(scheduled_tasks) == 1
    scheduled_func, scheduled_args, scheduled_kwargs = scheduled_tasks[0]
    assert scheduled_func.__name__ == "process_job"
    assert scheduled_args == (payload["id"],)
    assert scheduled_kwargs == {}


def test_create_audio_cleaning_job_queues_isolated_batch(client, monkeypatch):
    scheduled_tasks = []

    def capture_task(self, func, *args, **kwargs):
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr(api_module.BackgroundTasks, "add_task", capture_task)

    response = client.post(
        "/curation/audio/cleaning-jobs",
        json={
            "media_item_ids": ["media_voice_1", "media_voice_2"],
            "force_voice_isolation": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "audio_cleaning"
    assert payload["status"] == "queued"
    assert payload["source_media_item_ids"] == ["media_voice_1", "media_voice_2"]
    assert payload["options"] == {"force_voice_isolation": True}
    assert len(scheduled_tasks) == 1
    scheduled_func, scheduled_args, scheduled_kwargs = scheduled_tasks[0]
    assert scheduled_func.__name__ == "process_job"
    assert scheduled_args == (payload["id"],)
    assert scheduled_kwargs == {}


def test_create_processing_job_rejects_empty_source_media_item_ids(
    client, monkeypatch
):
    scheduled_tasks = []

    def capture_task(self, func, *args, **kwargs):
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr(api_module.BackgroundTasks, "add_task", capture_task)

    response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": [],
            "options": {"max_frame_count": 2},
        },
    )

    assert response.status_code == 422
    assert scheduled_tasks == []


def test_create_processing_job_rejects_unbounded_video_options(client):
    response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": ["media_video_1"],
            "options": {
                "frames_per_second": 9,
                "max_frame_count": 601,
            },
        },
    )

    assert response.status_code == 422


def test_processing_job_detail_returns_404_for_missing_job(client):
    response = client.get("/processing/jobs/missing_job")

    assert response.status_code == 404
    assert response.json()["detail"] == "Processing job not found"


def test_processing_job_process_endpoint_schedules_existing_job(client, monkeypatch):
    scheduled_tasks = []

    def capture_task(self, func, *args, **kwargs):
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr(api_module.BackgroundTasks, "add_task", capture_task)
    create_response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": ["media_video_1"],
            "options": {"max_frame_count": 2},
        },
    )
    job_id = create_response.json()["id"]
    scheduled_tasks.clear()

    response = client.post(f"/processing/jobs/{job_id}/process")

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert len(scheduled_tasks) == 1
    scheduled_func, scheduled_args, scheduled_kwargs = scheduled_tasks[0]
    assert scheduled_func.__name__ == "process_job"
    assert scheduled_args == (job_id,)
    assert scheduled_kwargs == {}


def test_processing_job_process_endpoint_returns_404_for_missing_job(client):
    response = client.post("/processing/jobs/missing_job/process")

    assert response.status_code == 404
    assert response.json()["detail"] == "Processing job not found"


def test_processing_job_commit_endpoint_accepts_trimmed_clips(client, monkeypatch):
    captured = {}

    def commit_video_breakdown(self, job_id, request):
        captured["job_id"] = job_id
        captured["request"] = request
        return ProcessingJob(
            id=job_id,
            job_type="video_breakdown",
            progress_message="Committed 0 frames and 1 video clips",
        )

    monkeypatch.setattr(
        api_module.ProcessingService,
        "commit_video_breakdown",
        commit_video_breakdown,
    )

    response = client.post(
        "/processing/jobs/processing_1/commit",
        json={
            "frame_ids": [],
            "clips": [
                {
                    "clip_id": "clip_1",
                    "start_seconds": 1.2,
                    "end_seconds": 3.8,
                    "decision": "keep",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert captured["job_id"] == "processing_1"
    assert captured["request"].clips[0].clip_id == "clip_1"
    assert response.json()["progress_message"] == "Committed 0 frames and 1 video clips"


def test_processing_jobs_endpoint_lists_created_jobs(client, monkeypatch):
    monkeypatch.setattr(
        api_module.BackgroundTasks,
        "add_task",
        lambda self, func, *args, **kwargs: None,
    )
    first_response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": ["media_video_1"],
            "options": {"max_frame_count": 2},
        },
    )
    second_response = client.post(
        "/processing/jobs",
        json={
            "job_type": "video_breakdown",
            "source_media_item_ids": ["media_video_2"],
            "options": {"max_frame_count": 3},
        },
    )

    response = client.get("/processing/jobs")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert response.status_code == 200
    listed_jobs = response.json()
    assert [job["id"] for job in listed_jobs] == [
        second_response.json()["id"],
        first_response.json()["id"],
    ]
    assert listed_jobs[0]["job_type"] == "video_breakdown"


def test_curation_api_groups_sources_and_persists_cross_media_handoff(client, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    import_response = client.post("/vault/import/local", json={"paths": [str(video_path)]})
    media_item_id = import_response.json()["media_items"][0]["id"]

    bundles_response = client.get("/curation/bundles")
    handoff_response = client.post(
        "/curation/handoff",
        json={"media_item_ids": [media_item_id]},
    )
    review_response = client.patch(
        f"/curation/handoff/{media_item_id}",
        json={"review_status": "accepted"},
    )
    restored_response = client.get("/curation/handoff")

    assert import_response.status_code == 200
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["intent_lanes"] == ["video"]
    assert handoff_response.json()["items"][0]["lane"] == "video"
    assert review_response.json()["items"][0]["review_status"] == "accepted"
    assert restored_response.json() == review_response.json()


def test_voice_confirmation_atomically_anchors_accepts_and_labels_sample(client, tmp_path):
    audio_path = tmp_path / "mary-voice.wav"
    audio_path.write_bytes(b"voice")
    media_item = client.post(
        "/vault/import/local",
        json={"paths": [str(audio_path)]},
    ).json()["media_items"][0]
    project = client.post(
        "/character-projects",
        json={"name": "Voice Dataset"},
    ).json()
    client.post(
        "/curation/handoff",
        json={
            "media_item_ids": [media_item["id"]],
            "project_id": project["id"],
            "requested_output": "voice",
        },
    )

    response = client.post(
        f"/character-projects/{project['id']}/voice-identity/confirm",
        json={
            "media_item_id": media_item["id"],
            "subject_label": "Mary",
            "requested_output": "voice",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["intent"]["subject_name"] == "Mary"
    assert "voice" in payload["project"]["intent"]["requested_outputs"]
    assert payload["profile"]["anchor_media_item_ids"] == [media_item["id"]]
    assert payload["handoff"]["items"] == [
        {
            **payload["handoff"]["items"][0],
            "media_item_id": media_item["id"],
            "project_id": project["id"],
            "requested_output": "voice",
            "review_status": "accepted",
            "speaker_confirmation": "anchor",
        }
    ]
    scoped = client.get(
        "/curation/handoff",
        params={"project_id": project["id"], "requested_output": "voice"},
    )
    assert scoped.json() == payload["handoff"]


def test_character_project_api_persists_intent_candidates_and_review(client, tmp_path):
    image_path = tmp_path / "identity.png"
    Image.new("RGB", (240, 360), color=(85, 110, 135)).save(image_path)
    import_response = client.post("/vault/import/local", json={"paths": [str(image_path)]})
    media_item_id = import_response.json()["media_items"][0]["id"]

    create_response = client.post(
        "/character-projects",
        json={
            "name": "Mary Sue Character",
            "intent": {
                "target_type": "character",
                "subject_name": "Mary Sue",
                "trigger_token": "example_person",
                "description": "Reusable identity",
                "learned_attributes": ["identity", "face", "body"],
                "controllable_attributes": ["expression", "pose", "clothing"],
                "excluded_attributes": ["background", "other people"],
            },
        },
    )
    project_id = create_response.json()["id"]
    candidates_response = client.post(
        f"/character-projects/{project_id}/candidates",
        json={"media_item_ids": [media_item_id]},
    )
    anchors_response = client.post(
        f"/character-projects/{project_id}/anchors",
        json={"media_item_ids": [media_item_id]},
    )
    analyze_response = client.post(f"/character-projects/{project_id}/analyze", json={})
    review_response = client.patch(
        f"/character-projects/{project_id}/observations/{media_item_id}",
        json={"review_status": "accepted", "view": "full_body"},
    )
    restored_response = client.get(f"/character-projects/{project_id}")
    media_response = client.get("/vault/media")

    assert import_response.status_code == 200
    assert create_response.status_code == 200
    assert candidates_response.status_code == 200
    assert anchors_response.status_code == 200
    assert analyze_response.status_code == 200
    assert review_response.status_code == 200
    assert restored_response.status_code == 200
    assert restored_response.json()["intent"]["trigger_token"] == "example_person"
    assert restored_response.json()["candidate_media_item_ids"] == [media_item_id]
    assert restored_response.json()["observations"][media_item_id]["view"] == "full_body"
    assert restored_response.json()["health"]["accepted_count"] == 1
    assert media_response.json()[0]["id"] == media_item_id


def test_raw_export_is_retired_with_actionable_migration(tmp_path):
    with TestClient(create_app(vault_root=tmp_path)) as client:
        response = client.post('/exports/runcomfy-image', json={})
        assert response.status_code == 410
        assert 'freeze a dataset' in response.json()['detail']


def test_engine_rejects_cross_site_requests_before_handlers(client):
    response = client.post("/character-projects", json={"name": "Must not be created"}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert all(project["name"] != "Must not be created" for project in client.get("/character-projects").json())
    assert client.get("/health", headers={"Origin": "null"}).status_code == 403


def test_engine_supports_native_tauri_origins(client):
    for origin in ("http://tauri.localhost", "https://tauri.localhost"):
        response = client.get("/health", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
