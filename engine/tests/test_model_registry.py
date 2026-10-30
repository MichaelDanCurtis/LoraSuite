import hashlib
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.model_registry import (
    ArtifactAcceptance,
    ArtifactEvaluation,
    ModelArtifactRecord,
    ModelRegistryService,
    resolve_comfy_installation,
)
from lorasuite_engine.models import DatasetSnapshot, DatasetSnapshotStatus
from lorasuite_engine.runpod_runs import RunPodRunArtifact, RunPodTrainingRun
from lorasuite_engine.safetensors_metadata import read_safetensors_metadata
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_runs import TrainingArtifact, TrainingRun
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.vault import sha256_file
from lorasuite_engine.video_dataset import VideoDatasetSnapshot


def test_registers_validates_and_installs_training_artifact(tmp_path):
    vault_root = tmp_path / "vault"
    artifact_root = vault_root / "training_artifacts" / "run-1"
    checkpoint = artifact_root / "checkpoint" / "person.safetensors"
    config = artifact_root / "config" / "resolved.yaml"
    sample = artifact_root / "sample" / "preview.png"
    _write_safetensors(checkpoint)
    source_checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    config.parent.mkdir(parents=True)
    config.write_text("model:\n  name_or_path: base-model.safetensors\n", encoding="utf-8")
    sample.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), "green").save(sample)
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="fingerprint-1",
        export_path=tmp_path / "dataset",
        parent_snapshot_id="dataset-snapshot-v1",
        parent_fingerprint="parent-fingerprint",
        improvement_request_id="improvement-request-1",
        source_artifact_id="artifact-v1",
        source_checkpoint_sha256="parent-checkpoint-sha",
        training_target=get_training_target_profile(
            "runcomfy_flux1_dev_character"
        ).spec(),
    )
    snapshot.intent.trigger_token = "person_token"
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )
    run = TrainingRun(
        id="run-1",
        snapshot_id=snapshot.id,
        dataset_fingerprint="fingerprint-1",
        config_digest="config-digest",
        config_file="dataset: {dataset_name}",
        status="completed",
        export_path=tmp_path / "dataset",
        artifact_dir=artifact_root,
        artifacts=[
            TrainingArtifact(kind="checkpoint", name=checkpoint.name, remote_url="https://example/checkpoint", local_path=checkpoint),
            TrainingArtifact(kind="config", name=config.name, remote_url="https://example/config", local_path=config),
            TrainingArtifact(kind="sample", name=sample.name, remote_url="https://example/sample", local_path=sample),
        ],
    )
    atomic_write_json(
        vault_root / "training_runs.json",
        {"version": 1, "runs": [run.model_dump(mode="json")]},
    )
    service = ModelRegistryService(vault_root)

    registered = service.register_training_run(run.id)

    assert len(registered) == 1
    record = registered[0]
    assert record.project_id == "project-1"
    assert record.parent_snapshot_id == "dataset-snapshot-v1"
    assert record.parent_dataset_fingerprint == "parent-fingerprint"
    assert record.improvement_request_id == "improvement-request-1"
    assert record.parent_artifact_id == "artifact-v1"
    assert record.parent_checkpoint_sha256 == "parent-checkpoint-sha"
    assert record.evaluation.status == "ready"
    assert record.evaluation.tensor_count == 1
    assert record.evaluation.parameter_count == 6
    assert record.trigger_token == "person_token"
    assert record.base_model == "base-model.safetensors"
    assert record.model_card is not None
    assert record.model_card.recipe_id == "flux1_dev_character"
    assert record.model_card.provenance["source_artifact_id"] == "artifact-v1"
    assert record.model_card.artifact["checkpoint_sha256"] == record.checkpoint_sha256
    assert record.model_card.artifact["source_checkpoint_sha256"] == source_checkpoint_sha256
    assert record.checkpoint_sha256 != source_checkpoint_sha256
    assert record.model_card_path is not None and record.model_card_path.is_file()
    embedded = read_safetensors_metadata(checkpoint)
    assert embedded["lorasuite.trigger_token"] == "person_token"
    assert embedded["lorasuite.dataset_fingerprint"] == "fingerprint-1"
    assert embedded["modelspec.title"] == "Person - FLUX.1 Dev Character"

    comfy_root = tmp_path / "ComfyUI"
    (comfy_root / "models").mkdir(parents=True)
    for relative_path in (
        "diffusion_models/flux1-dev.safetensors",
        "text_encoders/clip_l.safetensors",
        "text_encoders/t5xxl_fp16.safetensors",
        "vae/ae.safetensors",
    ):
        model_path = comfy_root / "models" / relative_path
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"model")
    installed = service.install_artifact(record.id, comfy_root)

    installed_checkpoint = comfy_root / "models" / "loras" / "person.safetensors"
    workflow = comfy_root / "user" / "default" / "workflows" / "LoraSuite" / "person-flux-evaluation.json"
    assert installed_checkpoint.read_bytes() == checkpoint.read_bytes()
    assert installed_checkpoint.with_suffix(".safetensors.lorasuite.json").is_file()
    handoff_path = installed_checkpoint.with_suffix(
        ".safetensors.lorasuite-handoff.json"
    )
    assert handoff_path.is_file()
    installed_model_card = installed_checkpoint.with_suffix(
        ".safetensors.model-card.json"
    )
    assert installed_model_card.is_file()
    assert json.loads(installed_model_card.read_text())["trigger_token"] == "person_token"
    payload = json.loads(workflow.read_text(encoding="utf-8"))
    assert payload["version"] == 0.4
    assert len(payload["nodes"]) == 12
    assert len(payload["links"]) == 12
    assert payload["nodes"][3]["type"] == "LoraSuiteArtifactLoaderModelOnly"
    assert payload["nodes"][3]["widgets_values"][0] == "person.safetensors"
    assert payload["nodes"][11]["type"] == "LoraSuiteEvaluationReport"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff["format"] == "lorasuite.comfy-handoff.v1"
    assert handoff["compatibility"]["status"] == "ready"
    assert handoff["inference"]["trigger_token"] == "person_token"
    assert sum(workflow["runnable"] for workflow in handoff["workflows"]) == 1
    extension = comfy_root / "custom_nodes" / "LoraSuite"
    assert (extension / "nodes.py").is_file()
    assert json.loads((extension / "install.json").read_text())["version"] == "0.1.0"
    assert installed.installed_paths == [installed_checkpoint, installed_model_card]
    assert installed.handoff_paths == [handoff_path]
    assert installed.comfy_installations[0].compatibility_status == "ready"
    assert installed.comfy_installations[0].runnable_workflow_count == 1


def test_registers_training_artifact_against_verified_recovered_export(tmp_path):
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
    artifact_root = vault_root / "training_artifacts" / "recovered-run"
    checkpoint = artifact_root / "checkpoint" / "person.safetensors"
    config = artifact_root / "config" / "resolved.yaml"
    _write_safetensors(checkpoint)
    config.parent.mkdir(parents=True)
    config.write_text(
        "model:\n  name_or_path: black-forest-labs/FLUX.1-dev\n",
        encoding="utf-8",
    )
    run = TrainingRun(
        id="recovered-run",
        snapshot_id=recovered.snapshot_id,
        dataset_fingerprint=recovered.fingerprint,
        config_digest="config-digest",
        config_file="dataset: {dataset_name}",
        status="completed",
        export_path=export_path,
        artifact_dir=artifact_root,
        artifacts=[
            TrainingArtifact(
                kind="checkpoint",
                name=checkpoint.name,
                remote_url="https://example/checkpoint",
                local_path=checkpoint,
            ),
            TrainingArtifact(
                kind="config",
                name=config.name,
                remote_url="https://example/config",
                local_path=config,
            ),
        ],
    )
    atomic_write_json(
        vault_root / "training_runs.json",
        {"version": 1, "runs": [run.model_dump(mode="json")]},
    )

    record = ModelRegistryService(vault_root).register_training_run(run.id)[0]

    assert record.project_id == "project-recovered"
    assert record.snapshot_id == "snapshot-recovered"
    assert record.dataset_fingerprint == "recovered-fingerprint"
    assert record.trigger_token == "person_token"
    assert record.evaluation.provenance_valid is True


def test_resolves_wrapper_and_direct_comfy_roots(tmp_path):
    wrapper = tmp_path / "portable"
    direct = wrapper / "ComfyUI"
    (direct / "models").mkdir(parents=True)

    assert resolve_comfy_installation(wrapper, require_existing=True).root == direct
    assert resolve_comfy_installation(direct, require_existing=True).root == direct
    assert resolve_comfy_installation(direct / "models", require_existing=True).root == direct


def test_registers_wan_video_artifact_without_generating_image_workflow(tmp_path):
    vault_root = tmp_path / "vault"
    artifact_root = vault_root / "training_artifacts" / "video-run"
    checkpoint = artifact_root / "checkpoint" / "wan-person.safetensors"
    config = artifact_root / "config" / "resolved.yaml"
    _write_safetensors(checkpoint)
    config.parent.mkdir(parents=True)
    config.write_text(
        "model:\n  name_or_path: ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16\n  arch: wan22_14b\n",
        encoding="utf-8",
    )
    snapshot = VideoDatasetSnapshot(
        project_id="video-project",
        project_name="Video Person",
        trigger_token="video_person",
        status="exported",
        fingerprint="video-fingerprint",
        export_path=tmp_path / "video-dataset",
    )
    atomic_write_json(
        vault_root / "video_dataset_snapshots.json",
        {"version": 1, "snapshots": [snapshot.model_dump(mode="json")]},
    )
    run = TrainingRun(
        id="video-run",
        snapshot_id=snapshot.id,
        dataset_fingerprint="video-fingerprint",
        config_digest="video-config",
        config_file="dataset: {dataset_name}",
        status="completed",
        export_path=tmp_path / "video-dataset",
        artifact_dir=artifact_root,
        artifacts=[
            TrainingArtifact(kind="checkpoint", name=checkpoint.name, remote_url="https://example/checkpoint", local_path=checkpoint),
            TrainingArtifact(kind="config", name=config.name, remote_url="https://example/config", local_path=config),
        ],
    )
    atomic_write_json(
        vault_root / "training_runs.json",
        {"version": 1, "runs": [run.model_dump(mode="json")]},
    )
    service = ModelRegistryService(vault_root)

    record = service.register_training_run(run.id)[0]

    assert record.modality == "video"
    assert record.project_id == "video-project"
    assert record.model_family == "wan22_14b_t2v"
    assert record.base_model == "ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16"
    comfy_root = tmp_path / "ComfyUI"
    (comfy_root / "models").mkdir(parents=True)
    for relative_path in (
        "diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
        "diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
        "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "vae/wan_2.1_vae.safetensors",
    ):
        model_path = comfy_root / "models" / relative_path
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"model")
    installed = service.install_artifact(record.id, comfy_root)
    assert installed.installed_paths
    assert [path.name for path in installed.workflow_paths] == [
        "wan-person-loader.json",
        "wan-person-wan22-evaluation.json",
    ]
    assert installed.comfy_installations[0].compatibility_status == "ready"
    assert installed.comfy_installations[0].runnable_workflow_count == 1
    handoff = json.loads(installed.handoff_paths[0].read_text(encoding="utf-8"))
    assert handoff["compatibility"]["status"] == "ready"
    assert handoff["workflows"][0]["purpose"] == "component"
    workflow = json.loads(installed.workflow_paths[1].read_text(encoding="utf-8"))
    assert [node["type"] for node in workflow["nodes"]].count(
        "LoraSuiteArtifactLoaderModelOnly"
    ) == 2
    assert workflow["nodes"][-1]["type"] == "LoraSuiteEvaluationReport"


def test_registers_downloaded_runpod_checkpoint_with_bundle_provenance(tmp_path):
    vault_root = tmp_path / "vault"
    bundle = tmp_path / "runpod-bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config" / "serverless_train.yaml").write_text(
        "model:\n  name_or_path: black-forest-labs/FLUX.1-dev\n",
        encoding="utf-8",
    )
    (bundle / "bundle_manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "format": "lorasuite-runpod-v1",
        "fingerprint": "runpod-fingerprint",
        "trigger_token": "runpod_person",
    }))
    checkpoint = tmp_path / "downloads" / "person.safetensors"
    sample = tmp_path / "downloads" / "sample.png"
    _write_safetensors(checkpoint)
    sample.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), "blue").save(sample)
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="RunPod Person",
        status=DatasetSnapshotStatus.EXPORTED,
        fingerprint="runpod-fingerprint",
        export_path=tmp_path / "dataset",
    )
    snapshot.intent.trigger_token = "runpod_person"
    atomic_write_json(vault_root / "dataset_snapshots.json", {
        "version": 1,
        "snapshots": [snapshot.model_dump(mode="json")],
    })
    run = RunPodTrainingRun(
        id="runpod-run-1",
        bundle_path=bundle,
        bundle_fingerprint="runpod-fingerprint",
        modality="image",
        training_target_profile_id="runcomfy_flux1_dev_character",
        endpoint_id="endpoint-1",
        snapshot_id=snapshot.id,
        status="completed",
        artifacts=[
            RunPodRunArtifact(kind="checkpoint", name=checkpoint.name, local_path=checkpoint),
            RunPodRunArtifact(kind="sample", name=sample.name, local_path=sample),
        ],
    )
    atomic_write_json(vault_root / "runpod_training_runs.json", {
        "version": 1,
        "runs": [run.model_dump(mode="json")],
    })

    record = ModelRegistryService(vault_root).register_runpod_run(run.id)[0]

    assert record.training_run_id == run.id
    assert record.project_id == "project-1"
    assert record.evaluation.status == "ready"
    assert record.evaluation.provenance_valid is True
    assert record.trigger_token == "runpod_person"
    assert record.model_family == "flux1"


def test_registers_voice_checkpoint_for_review_but_blocks_comfy_install(tmp_path):
    vault_root = tmp_path / "vault"
    bundle = tmp_path / "voice-bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config" / "serverless_train.yaml").write_text("trainer: fish_speech_s2\n", encoding="utf-8")
    (bundle / "bundle_manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "format": "lorasuite-runpod-v1",
        "fingerprint": "voice-fingerprint",
        "trigger_token": "voice_person",
    }))
    checkpoint = tmp_path / "downloads" / "voice.ckpt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"fish-speech-checkpoint")
    sample_audio = tmp_path / "downloads" / "voice_step_250" / "phrase_01.wav"
    sample_text = sample_audio.with_suffix(".txt")
    sample_audio.parent.mkdir(parents=True)
    sample_audio.write_bytes(b"rendered-voice")
    sample_text.write_text("Evaluation phrase.\n")
    run = RunPodTrainingRun(
        id="voice-runpod-run",
        bundle_path=bundle,
        bundle_fingerprint="voice-fingerprint",
        modality="voice",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
        endpoint_id="endpoint-1",
        project_id="project-1",
        status="completed",
        artifacts=[
            RunPodRunArtifact(kind="checkpoint", name=checkpoint.name, local_path=checkpoint, group_id="voice_step_250"),
            RunPodRunArtifact(kind="sample", name=sample_audio.name, local_path=sample_audio, group_id="voice_step_250"),
            RunPodRunArtifact(kind="sample", name=sample_text.name, local_path=sample_text, group_id="voice_step_250"),
        ],
    )
    atomic_write_json(vault_root / "runpod_training_runs.json", {
        "version": 1,
        "runs": [run.model_dump(mode="json")],
    })
    service = ModelRegistryService(vault_root)

    record = service.register_runpod_run(run.id)[0]

    assert record.modality == "voice"
    assert record.project_id == "project-1"
    assert record.evaluation.status == "review"
    assert record.evaluation.checkpoint_valid is True
    assert record.sample_paths == [sample_audio, sample_text]
    comfy_root = tmp_path / "ComfyUI"
    (comfy_root / "models").mkdir(parents=True)
    with pytest.raises(ValueError, match="not ComfyUI"):
        service.install_artifact(record.id, comfy_root)


def test_ranks_and_selects_one_release_candidate_per_project_modality(tmp_path):
    vault_root = tmp_path / "vault"
    records = [
        _release_record("artifact-a", identity=0.72, stability=0.78),
        _release_record("artifact-b", identity=0.88, stability=0.84),
        _release_record("artifact-review", identity=0.95, stability=0.92, release_ready=False),
    ]
    atomic_write_json(vault_root / "model_artifacts.json", {
        "version": 1,
        "artifacts": [record.model_dump(mode="json") for record in records],
    })
    service = ModelRegistryService(vault_root)

    candidates = service.release_candidates("project-1", "video")

    assert [candidate.artifact.id for candidate in candidates] == ["artifact-b", "artifact-a", "artifact-review"]
    assert candidates[0].eligible is True
    assert candidates[2].eligible is False
    selected = service.select_release("artifact-b")
    assert selected.selected_for_release is True
    service.select_release("artifact-a")
    restored = {record.id: record for record in service.list_artifacts()}
    assert restored["artifact-a"].selected_for_release is True
    assert restored["artifact-b"].selected_for_release is False
    with pytest.raises(ValueError, match="release-ready"):
        service.select_release("artifact-review")


def _release_record(artifact_id: str, *, identity: float, stability: float, release_ready: bool = True):
    return ModelArtifactRecord(
        id=artifact_id,
        project_id="project-1",
        training_run_id=f"run-{artifact_id}",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name=f"{artifact_id}.safetensors",
        checkpoint_path=Path(f"/tmp/{artifact_id}.safetensors"),
        checkpoint_sha256=artifact_id,
        checkpoint_size_bytes=1024,
        modality="video",
        model_family="wan22_14b_t2v",
        evaluation=ArtifactEvaluation(status="ready", checkpoint_valid=True, provenance_valid=True, config_present=True),
        acceptance=ArtifactAcceptance(
            status="certified" if release_ready else "screening_passed",
            screening_ready=True,
            release_ready=release_ready,
            passed_count=4,
            identity_similarity=identity,
            temporal_stability=stability,
            speaker_similarity=0.8,
            av_sync_proxy=0.7,
        ),
    )


def _write_safetensors(path: Path):
    path.parent.mkdir(parents=True)
    header = json.dumps({"tensor": {"dtype": "F32", "shape": [2, 3], "data_offsets": [0, 24]}}).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + (b"\0" * 24))
