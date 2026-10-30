import json
import subprocess
from pathlib import Path

import pytest

from lorasuite_engine.runpod_bundle import RunPodBundleService


def source_export(root: Path, modality: str) -> Path:
    source = root / f"{modality}-source"
    source.mkdir()
    manifest = {"created_by": "LoraSuite", "modality": modality}
    if modality == "image":
        (source / "model_card.json").write_text(json.dumps({
            "schema_version": "lorasuite.model-card.v1",
            "name": "person-flux1-character",
        }))
        manifest.update({
            "model_card_path": "model_card.json",
            "model_card": {
                "schema_version": "lorasuite.model-card.v1",
                "name": "person-flux1-character",
            },
        })
    (source / "manifest.json").write_text(json.dumps(manifest))
    if modality == "image":
        (source / "images").mkdir()
        (source / "images" / "000001.png").write_bytes(b"image")
        (source / "images" / "000001.txt").write_text("person_token, portrait\n")
    elif modality == "video":
        (source / "videos").mkdir()
        (source / "videos" / "train_000001.mp4").write_bytes(b"video")
        (source / "videos" / "train_000001.txt").write_text("person_token, walking\n")
    else:
        (source / "sample.wav").write_bytes(b"audio")
    return source


@pytest.mark.parametrize(
    ("modality", "profile_id", "ready", "config_name"),
    [
        ("image", "runcomfy_flux1_dev_character", True, "train.yaml"),
        ("video", "runcomfy_wan22_14b_t2v_character", True, "train.yaml"),
        ("voice", None, False, "worker_contract.json"),
        ("audio_visual", None, False, "worker_contract.json"),
    ],
)
def test_builds_runpod_network_volume_bundle_for_every_modality(
    tmp_path: Path,
    modality: str,
    profile_id: str | None,
    ready: bool,
    config_name: str,
) -> None:
    source = source_export(tmp_path, modality)

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / f"{modality}-runpod",
        modality=modality,
        trigger_token="person_token",
        fingerprint="abcdef0123456789",
        training_target_profile_id=profile_id,
        remote_root="/workspace/lorasuite",
        endpoint_id="endpoint-123",
    )

    assert bundle.ready is ready
    assert bundle.config_path.name == config_name
    assert bundle.archive_path.is_file()
    assert (bundle.output_path / "dataset" / "manifest.json").is_file()
    assert (bundle.output_path / "file_index.json").is_file()
    assert bundle.pod_template_path.is_file()
    assert bundle.pod_launcher_path.is_file()
    assert bundle.trainer_launcher_path.is_file()
    assert (bundle.output_path / "train_serverless.sh").is_file()
    request = json.loads(bundle.input_path.read_text())
    assert request["input"]["modality"] == modality
    assert request["input"]["training_target_profile_id"] == profile_id
    assert request["input"]["worker_contract_version"] == 1
    assert request["input"]["config_digest"] == bundle.config_digest
    assert len(bundle.config_digest) == 64
    assert request["input"]["dataset_path"].startswith("/runpod-volume/lorasuite/")
    assert request["input"]["pod_dataset_path"].startswith("/workspace/lorasuite/")
    expected_config = "serverless_train.yaml" if ready else "worker_contract.json"
    assert request["input"]["config_path"].endswith(f"/config/{expected_config}")
    if modality == "image":
        assert request["input"]["model_card_path"].endswith(
            "/dataset/model_card.json"
        )
        bundle_manifest = json.loads(bundle.manifest_path.read_text())
        assert bundle_manifest["model_card"]["name"] == "person-flux1-character"
        assert bundle_manifest["config_digest"] == bundle.config_digest
    else:
        assert request["input"]["model_card_path"] is None
    assert "endpoint-123" in (bundle.output_path / "submit_serverless.sh").read_text()
    assert "lorasuite/" in (bundle.output_path / "upload_to_volume.sh").read_text()
    pod_template = json.loads(bundle.pod_template_path.read_text())
    assert pod_template["imageName"] == "runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851"
    assert pod_template["networkVolumeId"] is None
    assert pod_template["volumeMountPath"] == "/workspace"
    assert pod_template["dockerStartCmd"] == ["bash", f"{bundle.remote_root}/train_ai_toolkit.sh"]
    assert "rest.runpod.io/v1/pods" in bundle.pod_launcher_path.read_text()
    assert "RUNPOD_API_KEY" not in json.dumps(bundle.model_dump(mode="json"))
    if ready:
        config = bundle.config_path.read_text()
        serverless_config = bundle.serverless_config_path.read_text()
        assert "/app/ai-toolkit/datasets/" not in config
        assert bundle.remote_dataset_path in config
        assert bundle.serverless_dataset_path in serverless_config
        assert bundle.serverless_root in serverless_config
        assert "64663c8575b7a9ac3b946611724f76d015c941bc" in bundle.trainer_launcher_path.read_text()
    else:
        assert "exit 2" in bundle.trainer_launcher_path.read_text()
        assert "exit 2" in bundle.pod_launcher_path.read_text()


def test_custom_remote_root_maps_to_network_volume_key(tmp_path: Path) -> None:
    source = source_export(tmp_path, "image")

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "runpod-image",
        modality="image",
        trigger_token="person_token",
        fingerprint="abcdef0123456789",
        training_target_profile_id="runcomfy_flux1_dev_character",
        remote_root="/network-volume/jobs",
    )

    assert bundle.remote_root == "/network-volume/jobs/image-abcdef012345"
    assert "jobs/image-abcdef012345" in (bundle.output_path / "upload_to_volume.sh").read_text()
    assert json.loads(bundle.pod_template_path.read_text())["volumeMountPath"] == "/network-volume"


def test_builds_krea2_bundle_with_krea_arch_and_pinned_toolkit(tmp_path: Path) -> None:
    source = source_export(tmp_path, "image")

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "krea2-runpod",
        modality="image",
        trigger_token="person_token",
        fingerprint="krea2-fingerprint",
        training_target_profile_id="runcomfy_krea2_raw_character",
    )

    config = bundle.config_path.read_text()
    launcher = bundle.trainer_launcher_path.read_text()
    assert bundle.ready is True
    assert 'arch: "krea2"' in config
    assert 'name_or_path: "krea/Krea-2-Raw"' in config
    assert "c2864bba48a6f94ab1171d9df47b1335f8306355" in launcher
    assert "cat-file -e" in launcher
    assert "fetch --depth 1 origin" in launcher


def test_persists_and_restores_bundle_provenance(tmp_path: Path) -> None:
    source = source_export(tmp_path, "image")
    manifest = json.loads((source / "manifest.json").read_text())
    manifest.update({"project_id": "project-1", "dataset_snapshot_id": "snapshot-1"})
    (source / "manifest.json").write_text(json.dumps(manifest))
    service = RunPodBundleService(tmp_path / "vault")

    created = service.create_bundle(
        source_export_path=source,
        output_path=tmp_path / "runpod-image",
        modality="image",
        trigger_token="person_token",
        fingerprint="abcdef0123456789",
        training_target_profile_id="runcomfy_flux1_dev_character",
    )
    restored = service.list_bundles(project_id="project-1")

    assert len(restored) == 1
    assert restored[0].id == created.id
    assert restored[0].snapshot_id == "snapshot-1"
    assert restored[0].fingerprint == "abcdef0123456789"
    assert restored[0].available is True
    assert "person_token" not in service.registry_path.read_text()


def test_packages_id_lora_ltx23_research_config_but_blocks_per_person_training(tmp_path: Path) -> None:
    source = tmp_path / "id-lora-source"
    for relative, payload in {
        "train/video/target.mp4": b"video",
        "train/audio/target.wav": b"audio",
        "train/audio/reference.wav": b"reference",
        "validation/video/target.mp4": b"validation-video",
        "validation/audio/target.wav": b"validation-audio",
        "validation/audio/reference.wav": b"validation-reference",
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    entries = [
        {
            "id": split,
            "caption": "[VISUAL] person speaking [SPEECH] hello [SOUNDS] room tone",
            "video": f"{split}/video/target.mp4",
            "audio": f"{split}/audio/target.wav",
            "reference_audio": f"{split}/audio/reference.wav",
            "split": split,
        }
        for split in ("train", "validation")
    ]
    (source / "trainer_dataset.json").write_text(json.dumps(entries))
    (source / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "format": "id-lora-av-v1",
        "training_target": {
            "profile_id": "runpod_id_lora_ltx23",
            "ready": True,
            "trainer_dataset": "trainer_dataset.json",
        },
    }))

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "id-lora-runpod",
        modality="audio_visual",
        trigger_token="person_token",
        fingerprint="1234567890abcdef",
        training_target_profile_id="runpod_id_lora_ltx23",
    )

    assert bundle.ready is False
    assert bundle.trainer_launcher_path.name == "train_id_lora_ltx23.sh"
    config = bundle.config_path.read_text()
    launcher = bundle.trainer_launcher_path.read_text()
    assert "audio_ref_only_ic" in config
    assert f'{bundle.remote_dataset_path}/.precomputed' in config
    assert "No validated trainer" in launcher
    assert any("multi-identity adapter" in warning for warning in bundle.warnings)
    pod_template = json.loads(bundle.pod_template_path.read_text())
    assert pod_template["dockerStartCmd"] == ["bash", f"{bundle.remote_root}/train_id_lora_ltx23.sh"]


def test_blocks_id_lora_bundle_when_source_contract_is_not_validated(tmp_path: Path) -> None:
    source = source_export(tmp_path, "audio_visual")

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "blocked-id-lora-runpod",
        modality="audio_visual",
        trigger_token="person_token",
        fingerprint="1234567890abcdef",
        training_target_profile_id="runpod_id_lora_ltx23",
    )

    assert bundle.ready is False
    assert any("pairing and split-isolation gate" in warning for warning in bundle.warnings)
    assert "exit 2" in bundle.trainer_launcher_path.read_text()


def test_builds_runnable_id_lora_zero_shot_inference_bundle(tmp_path: Path) -> None:
    source = tmp_path / "id-lora-inference-source"
    for relative, payload in {
        "validation/video/target.mp4": b"video",
        "voice_references/validation/reference.wav": b"reference",
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (source / "trainer_dataset.json").write_text(json.dumps([{
        "id": "validation-example",
        "caption": "[VISUAL]: A person speaks to camera. [SPEECH]: Hello. [SOUNDS]: Calm voice.",
        "video": "validation/video/target.mp4",
        "audio": "voice_references/validation/reference.wav",
        "reference_audio": "voice_references/validation/reference.wav",
        "split": "validation",
    }]))
    (source / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "format": "id-lora-av-v1",
        "inference_target": {
            "profile_id": "runpod_id_lora_ltx23_inference",
            "ready": True,
            "dataset": "trainer_dataset.json",
        },
    }))

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "id-lora-inference-runpod",
        modality="audio_visual",
        trigger_token="person_token",
        fingerprint="id-lora-fingerprint",
        training_target_profile_id="runpod_id_lora_ltx23_inference",
    )

    assert bundle.ready is True
    assert bundle.trainer_launcher_path.name == "run_id_lora_ltx23.sh"
    request = json.loads(bundle.input_path.read_text())["input"]
    assert request["action"] == "run_id_lora"
    launcher = bundle.trainer_launcher_path.read_text()
    assert "inference_two_stage_hq.py" in launcher
    assert "--prompts-file" in launcher
    assert "--quantize" in launcher
    assert "13dc9c286a2d3c1a21a7781f9ac0fe7727ec56cd" in launcher
    assert 'members = ["ID-LoRA-2.3/packages/*"]' in launcher
    assert "uv sync --frozen" not in launcher
    subprocess.run(["bash", "-n", str(bundle.trainer_launcher_path)], check=True)
    assert (bundle.output_path / "prepare_id_lora_inference.py").is_file()
    serverless = (bundle.output_path / "train_serverless.sh").read_text()
    assert "/runpod-volume/models/id-lora-ltx23" in serverless
    subprocess.run(["bash", "-n", str(bundle.output_path / "train_serverless.sh")], check=True)


def test_builds_runnable_fish_speech_voice_lora_bundle(tmp_path: Path) -> None:
    source = tmp_path / "fish-source"
    speaker = source / "voice_cloning/fish_speech/person"
    speaker.mkdir(parents=True)
    for index in range(3):
        (speaker / f"{index:06d}.wav").write_bytes(b"voice")
        (speaker / f"{index:06d}.lab").write_text(f"Spoken line {index}.\n")
    (source / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "export_type": "voice_handoff",
        "training_target": {
            "profile_id": "runpod_fish_speech_s2_voice_lora",
            "ready": True,
            "dataset_root": "voice_cloning/fish_speech",
        },
    }))

    bundle = RunPodBundleService().create_bundle(
        source_export_path=source,
        output_path=tmp_path / "fish-runpod",
        modality="voice",
        trigger_token="person_token",
        fingerprint="voice-fingerprint",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
    )

    assert bundle.ready is True
    assert bundle.trainer_launcher_path.name == "train_fish_speech_s2.sh"
    launcher = bundle.trainer_launcher_path.read_text()
    assert "e5e292632cb11e7a27b2b7487f58f612bc101e13" in launcher
    assert "extract_vq.py" in launcher
    assert "build_dataset.py" in launcher
    assert "+lora@model.model.lora_config=r_8_alpha_16" in launcher
    assert "merge_lora.py" in launcher
    assert "render_fish_speech_evaluation.py" in launcher
    assert "evaluation_phrases.json" in launcher
    assert (bundle.output_path / "render_fish_speech_evaluation.py").is_file()
    assert len(json.loads((bundle.output_path / "evaluation_phrases.json").read_text())["phrases"]) == 3
    serverless_launcher = (bundle.output_path / "train_serverless.sh").read_text()
    assert bundle.serverless_root in serverless_launcher
    assert bundle.remote_root not in serverless_launcher
    assert "/runpod-volume/models/fish-speech-s2" in serverless_launcher
    config = bundle.config_path.read_text()
    assert "r_8_alpha_16" in config
    assert f"{bundle.remote_dataset_path}/voice_cloning/fish_speech" in config
    pod_template = json.loads(bundle.pod_template_path.read_text())
    assert pod_template["dockerStartCmd"] == ["bash", f"{bundle.remote_root}/train_fish_speech_s2.sh"]


def test_refuses_to_replace_an_unrelated_output_folder(tmp_path: Path) -> None:
    source = source_export(tmp_path, "image")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "important.txt").write_text("keep")

    with pytest.raises(ValueError, match="not empty"):
        RunPodBundleService().create_bundle(
            source_export_path=source,
            output_path=output,
            modality="image",
            trigger_token="person_token",
            fingerprint="abc",
            training_target_profile_id="runcomfy_flux1_dev_character",
        )

    assert (output / "important.txt").read_text() == "keep"
