from __future__ import annotations

from pathlib import Path

from lorasuite_engine.cloud_providers import CloudProviderService
from lorasuite_engine.models import DatasetSnapshot
from lorasuite_engine.runpod_runs import RunPodRunArtifact, RunPodTrainingRun
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_runs import TrainingArtifact, TrainingRun


def test_provider_descriptors_publish_truthful_versioned_capabilities(tmp_path: Path) -> None:
    descriptors = {item.id: item for item in CloudProviderService(tmp_path).descriptors()}

    assert set(descriptors) == {"runcomfy", "runpod"}
    assert descriptors["runcomfy"].contract_version == "lorasuite.cloud-provider.v1"
    assert "runcomfy_flux1_dev_character" in descriptors["runcomfy"].target_profile_ids
    assert "runpod_fish_speech_s2_voice_lora" in descriptors["runpod"].target_profile_ids
    runcomfy_features = {item.id: item.support for item in descriptors["runcomfy"].features}
    runpod_features = {item.id: item.support for item in descriptors["runpod"].features}
    assert runcomfy_features["checkpoint_resume"] == "native"
    assert runcomfy_features["upload_resume"] == "adapter"
    upload_resume = next(
        item for item in descriptors["runcomfy"].features if item.id == "upload_resume"
    )
    assert "SHA-256 checkpoint" in upload_resume.detail
    assert runpod_features["immutable_config"] == "native"
    assert runpod_features["checkpoint_resume"] == "unavailable"
    assert runpod_features["artifact_checksums"] == "native"


def test_normalizes_runcomfy_and_runpod_runs_with_legal_next_actions(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    snapshot = DatasetSnapshot(
        id="snapshot-1",
        project_id="project-1",
        project_name="Person",
        status="exported",
        fingerprint="dataset-fingerprint",
        export_path=tmp_path / "export",
    )
    atomic_write_json(vault / "dataset_snapshots.json", {
        "version": 1,
        "snapshots": [snapshot.model_dump(mode="json")],
    })
    runcomfy = TrainingRun(
        id="runcomfy-1",
        snapshot_id=snapshot.id,
        dataset_fingerprint=snapshot.fingerprint,
        config_digest="config-digest",
        config_file="job: extension",
        status="stopped",
        progress_current=750,
        progress_total=2000,
        progress_percent=37.5,
        progress_message="Stopped at checkpoint",
        export_path=tmp_path / "export",
        artifacts=[TrainingArtifact(kind="checkpoint", name="step.safetensors", remote_url="https://example.test/step")],
    )
    runpod = RunPodTrainingRun(
        id="runpod-1",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="bundle-fingerprint",
        config_digest="runpod-config",
        modality="voice",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
        endpoint_id="endpoint-1",
        project_id="project-1",
        status="completed",
        artifacts=[
            RunPodRunArtifact(
                kind="checkpoint",
                name="voice.safetensors",
                volume_path="/runpod-volume/output/voice.safetensors",
                sha256="abc",
            ),
        ],
    )
    atomic_write_json(vault / "training_runs.json", {
        "version": 1,
        "runs": [runcomfy.model_dump(mode="json")],
    })
    atomic_write_json(vault / "runpod_training_runs.json", {
        "version": 1,
        "runs": [runpod.model_dump(mode="json")],
    })

    records = {item.id: item for item in CloudProviderService(vault).list_runs(project_id="project-1")}

    assert records["runcomfy-1"].state == "paused"
    assert records["runcomfy-1"].available_actions == ["resume", "cancel"]
    assert records["runcomfy-1"].training_target_profile_id == "runcomfy_flux1_dev_character"
    assert records["runpod-1"].state == "completed"
    assert records["runpod-1"].available_actions == ["download_artifacts", "evaluate"]
    assert records["runpod-1"].checksum_artifact_count == 1


def test_normalized_run_filters_provider_and_classifies_failure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    failed = RunPodTrainingRun(
        id="runpod-failed",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="fingerprint",
        config_digest="digest",
        modality="image",
        training_target_profile_id="runcomfy_flux1_dev_character",
        endpoint_id="endpoint",
        project_id="project-2",
        status="failed",
        error="Worker configuration digest does not match",
    )
    atomic_write_json(vault / "runpod_training_runs.json", {
        "version": 1,
        "runs": [failed.model_dump(mode="json")],
    })

    records = CloudProviderService(vault).list_runs(provider="runpod")

    assert len(records) == 1
    assert records[0].state == "failed"
    assert records[0].failure_category == "configuration"
    assert records[0].available_actions == ["retry"]
