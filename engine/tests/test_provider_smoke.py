from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lorasuite_engine.provider_smoke import ProviderSmokeService
from lorasuite_engine.runpod_bundle import RunPodBundleService
from lorasuite_engine.models import DatasetSnapshot
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_targets import get_training_target_profile


def _image_export(root: Path, profile_id: str = "runcomfy_flux1_dev_character") -> Path:
    export = root / f"image-export-{profile_id}"
    images = export / "images"
    images.mkdir(parents=True)
    image = images / "000001.png"
    caption = images / "000001.txt"
    image.write_bytes(b"image")
    caption.write_text("person_token, portrait\n")
    (export / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "status": "complete",
        "character_project_id": "project-1",
        "dataset_fingerprint": "image-fingerprint",
        "training_target": {"profile_id": profile_id},
        "files": [{"image": str(image), "caption": str(caption), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}],
    }))
    return export


def _video_export(root: Path) -> Path:
    export = root / "video-export"
    videos = export / "videos"
    videos.mkdir(parents=True)
    video = videos / "train_000001.mp4"
    caption = videos / "train_000001.txt"
    video.write_bytes(b"video")
    caption.write_text("person_token, walking\n")
    (export / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "status": "complete",
        "project_id": "project-1",
        "dataset_fingerprint": "video-fingerprint",
        "training_target": {"profile_id": "runcomfy_wan22_14b_t2v_character"},
        "files": [{"video": "videos/train_000001.mp4", "caption": "videos/train_000001.txt", "sha256": hashlib.sha256(video.read_bytes()).hexdigest()}],
    }))
    return export


def _voice_export(root: Path) -> Path:
    export = root / "voice-export"
    speaker = export / "voice_cloning" / "fish_speech" / "project-1"
    speaker.mkdir(parents=True)
    for index in range(3):
        (speaker / f"{index:06d}.wav").write_bytes(b"voice")
        (speaker / f"{index:06d}.lab").write_text(f"Spoken line {index}.\n")
    (export / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "status": "complete",
        "character_project_id": "project-1",
        "training_target": {"profile_id": "runpod_fish_speech_s2_voice_lora", "ready": True, "dataset_root": "voice_cloning/fish_speech"},
    }))
    return export


def _id_lora_export(root: Path) -> Path:
    export = root / "id-lora-export"
    video = export / "validation" / "video" / "target.mp4"
    reference = export / "voice_references" / "validation" / "reference.wav"
    video.parent.mkdir(parents=True)
    reference.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    reference.write_bytes(b"reference")
    (export / "trainer_dataset.json").write_text(json.dumps([{
        "id": "validation-example",
        "caption": "[VISUAL]: A person speaks. [SPEECH]: Hello. [SOUNDS]: Calm voice.",
        "video": "validation/video/target.mp4",
        "audio": "voice_references/validation/reference.wav",
        "reference_audio": "voice_references/validation/reference.wav",
        "split": "validation",
    }]))
    (export / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "status": "complete",
        "project_id": "project-1",
        "format": "id-lora-av-v1",
        "inference_target": {"profile_id": "runpod_id_lora_ltx23_inference", "ready": True, "dataset": "trainer_dataset.json"},
    }))
    return export


def test_runcomfy_smoke_validates_actual_dataset_and_yaml(tmp_path: Path) -> None:
    source = _image_export(tmp_path)
    profile = get_training_target_profile("runcomfy_flux1_dev_character")
    config = profile.config_template.format(
        job_name="person-flux-v1",
        trigger_token="person_token",
        sample_prompt="person_token portrait",
        dataset_name="{dataset_name}",
    )

    run = ProviderSmokeService(tmp_path / "vault").run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config,
    )

    assert run.ready is True
    assert run.source_fingerprint == "image-fingerprint"
    assert run.config_file == config
    assert {check.id for check in run.checks} == {"profile", "modality", "manifest", "profile_match", "dataset_pairs", "checksums", "yaml", "trainer_contract"}
    assert ProviderSmokeService(tmp_path / "vault").get_run(run.id).ready is True


def test_runcomfy_smoke_rejects_tampered_dataset_and_resolved_placeholder(tmp_path: Path) -> None:
    source = _image_export(tmp_path)
    (source / "images" / "000001.png").write_bytes(b"tampered")
    profile = get_training_target_profile("runcomfy_flux1_dev_character")
    config = profile.config_template.format(job_name="job", trigger_token="token", sample_prompt="portrait", dataset_name="already-resolved")

    run = ProviderSmokeService(tmp_path / "vault").run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config,
    )

    assert run.ready is False
    failed = {check.id for check in run.checks if not check.passed}
    assert {"checksums", "trainer_contract"}.issubset(failed)


def test_runcomfy_smoke_accepts_krea2_raw_contract_and_rejects_wrong_arch(tmp_path: Path) -> None:
    profile = get_training_target_profile("runcomfy_krea2_raw_character")
    source = _image_export(tmp_path, profile.profile_id)
    config = profile.config_template.format(
        job_name="person-krea2-v1",
        trigger_token="person_token",
        sample_prompt="person_token portrait",
        dataset_name="{dataset_name}",
    )
    service = ProviderSmokeService(tmp_path / "vault")

    valid = service.run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config,
    )
    invalid = service.run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config.replace('arch: "krea2"', 'arch: "flux"'),
    )

    assert valid.ready is True
    assert "KREA 2 Character" in next(
        check.detail for check in valid.checks if check.id == "trainer_contract"
    )
    assert invalid.ready is False
    assert "arch: krea2" in next(
        check.detail for check in invalid.checks if check.id == "trainer_contract"
    )


def test_runcomfy_smoke_migrates_verified_legacy_manifest_profile(tmp_path: Path) -> None:
    source = _image_export(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("training_target")
    manifest.update({
        "dataset_snapshot_id": "snapshot-legacy",
        "dataset_fingerprint": "legacy-fingerprint",
        "character_project_id": "project-1",
    })
    manifest_path.write_text(json.dumps(manifest))
    vault = tmp_path / "vault"
    snapshot = DatasetSnapshot(
        id="snapshot-legacy",
        project_id="project-1",
        project_name="Legacy Character",
        status="exported",
        fingerprint="legacy-fingerprint",
        export_path=source,
    )
    atomic_write_json(vault / "dataset_snapshots.json", {
        "version": 1,
        "snapshots": [snapshot.model_dump(mode="json")],
    })
    profile = get_training_target_profile("runcomfy_flux1_dev_character")
    config = profile.config_template.format(job_name="legacy", trigger_token="person_token", sample_prompt="portrait", dataset_name="{dataset_name}")

    run = ProviderSmokeService(vault).run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config,
    )

    migrated = json.loads(manifest_path.read_text())
    assert run.ready is True
    assert migrated["training_target"]["profile_id"] == profile.profile_id
    assert migrated["contract_migrations"][-1]["snapshot_id"] == snapshot.id
    assert "Recovered and embedded" in next(check.detail for check in run.checks if check.id == "profile_match")


def test_runcomfy_video_smoke_requires_wan_temporal_contract(tmp_path: Path) -> None:
    source = _video_export(tmp_path)
    profile = get_training_target_profile("runcomfy_wan22_14b_t2v_character")
    config = profile.config_template.format(job_name="video", trigger_token="person_token", sample_prompt="walking", dataset_name="{dataset_name}")

    run = ProviderSmokeService(tmp_path / "vault").run_runcomfy(
        project_id="project-1",
        source_export_path=source,
        training_target_profile_id=profile.profile_id,
        config_file=config,
    )

    assert run.ready is True
    assert next(check for check in run.checks if check.id == "trainer_contract").passed is True


def test_runpod_smoke_executes_worker_contract_for_all_runnable_modalities(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    bundle_service = RunPodBundleService(vault)
    cases = [
        ("image", "runcomfy_flux1_dev_character", _image_export(tmp_path)),
        ("video", "runcomfy_wan22_14b_t2v_character", _video_export(tmp_path)),
        ("voice", "runpod_fish_speech_s2_voice_lora", _voice_export(tmp_path)),
        ("audio_visual", "runpod_id_lora_ltx23_inference", _id_lora_export(tmp_path)),
    ]
    smoke_service = ProviderSmokeService(vault)

    for index, (modality, profile_id, source) in enumerate(cases):
        bundle = bundle_service.create_bundle(
            source_export_path=source,
            output_path=tmp_path / f"bundle-{index}",
            modality=modality,
            trigger_token="person_token",
            fingerprint=f"fingerprint-{index}",
            training_target_profile_id=profile_id,
        )
        run = smoke_service.run_runpod(bundle.id)
        assert run.ready is True, [(check.id, check.detail) for check in run.checks if not check.passed]
        assert run.source_fingerprint == f"fingerprint-{index}"
        assert next(check for check in run.checks if check.id == "profile_contract").passed is True


def test_runpod_smoke_detects_bundle_tampering(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    source = _image_export(tmp_path)
    bundle = RunPodBundleService(vault).create_bundle(
        source_export_path=source,
        output_path=tmp_path / "bundle",
        modality="image",
        trigger_token="person_token",
        fingerprint="fingerprint",
        training_target_profile_id="runcomfy_flux1_dev_character",
    )
    (bundle.output_path / "dataset" / "images" / "000001.png").write_bytes(b"tampered")

    run = ProviderSmokeService(vault).run_runpod(bundle.id)

    assert run.ready is False
    assert run.source_fingerprint == "fingerprint"
    assert next(check for check in run.checks if check.id == "bundle_integrity").passed is False
