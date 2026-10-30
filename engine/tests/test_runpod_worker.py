import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workers.runpod import handler as worker


def test_worker_executes_validated_bundle_and_returns_checksummed_artifacts(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    bundle = volume / "lorasuite" / "voice-job"
    dataset = bundle / "dataset"
    config = bundle / "config" / "serverless_train.yaml"
    manifest = dataset / "manifest.json"
    model_card = dataset / "model_card.json"
    output = bundle / "output"
    dataset.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    config.write_text("trainer: fish_speech_s2\n")
    manifest.write_text("{}")
    model_card.write_text(json.dumps({
        "schema_version": "lorasuite.model-card.v1",
        "name": "voice-person",
    }))
    launcher = bundle / "train_serverless.sh"
    launcher.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))

    def fake_run(command, **options):
        assert command == ["bash", str(launcher)]
        checkpoint = output / "checkpoints" / "voice_step_250.ckpt"
        sample = output / "evaluation" / "voice_step_250" / "phrase_01.wav"
        transcript = output / "evaluation" / "voice_step_250" / "phrase_01.txt"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        sample.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"checkpoint")
        sample.write_bytes(b"wave")
        transcript.write_text("Evaluation phrase.\n")
        return SimpleNamespace(returncode=0, stdout="trained", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.handler({"input": {
        "action": "train_lora",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "dataset_path": str(dataset),
        "manifest_path": str(manifest),
        "model_card_path": str(model_card),
        "config_path": str(config),
        "output_path": str(output),
        "fingerprint": "voice-fingerprint",
        "config_digest": hashlib.sha256(config.read_bytes()).hexdigest(),
    }})

    assert result["status"] == "success"
    assert result["fingerprint"] == "voice-fingerprint"
    assert result["config_digest"] == hashlib.sha256(config.read_bytes()).hexdigest()
    by_kind = {item["kind"] for item in result["artifacts"]}
    assert {"checkpoint", "sample", "config", "log", "model_card"}.issubset(by_kind)
    assert (output / "model_card.json").read_text() == model_card.read_text()
    sample_names = {item["name"] for item in result["artifacts"] if item["kind"] == "sample"}
    assert {"evaluation__voice_step_250__phrase_01.wav", "evaluation__voice_step_250__phrase_01.txt"}.issubset(sample_names)
    grouped = [item for item in result["artifacts"] if item.get("group_id") == "voice_step_250"]
    assert {item["kind"] for item in grouped} == {"checkpoint", "sample"}
    assert all(len(item["sha256"]) == 64 for item in result["artifacts"])
    assert all(item["path"].startswith(str(volume)) for item in result["artifacts"])


def test_worker_rejects_paths_outside_network_volume(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))

    with pytest.raises(ValueError, match="must stay under"):
        worker.handler({"input": {
            "action": "train_lora",
            "bundle_format": "lorasuite-runpod-v1",
            "worker_contract_version": 1,
            "dataset_path": str(tmp_path / "escape"),
            "manifest_path": str(volume / "manifest.json"),
            "config_path": str(volume / "config.yaml"),
            "output_path": str(volume / "output"),
        }})


def test_worker_accepts_id_lora_inference_outputs_without_checkpoint(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    bundle = volume / "lorasuite" / "id-lora-job"
    dataset = bundle / "dataset"
    config = bundle / "config" / "serverless_train.yaml"
    manifest = dataset / "manifest.json"
    output = bundle / "output"
    dataset.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    config.write_text("mode: id_lora_ltx23_zero_shot\n")
    manifest.write_text("{}")
    (bundle / "train_serverless.sh").write_text("#!/usr/bin/env bash\n")
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))

    def fake_run(command, **options):
        output.mkdir(parents=True, exist_ok=True)
        (output / "id_lora_01.mp4").write_bytes(b"audio-visual-output")
        (output / "inference_contract.json").write_text('[{"prompt":"[SPEECH]: Hello. [SOUNDS]: Calm.","output_name":"id_lora_01"}]')
        return SimpleNamespace(returncode=0, stdout="generated", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.handler({"input": {
        "action": "run_id_lora",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "dataset_path": str(dataset),
        "manifest_path": str(manifest),
        "config_path": str(config),
        "output_path": str(output),
        "fingerprint": "id-fingerprint",
        "config_digest": hashlib.sha256(config.read_bytes()).hexdigest(),
    }})

    assert result["status"] == "success"
    assert any(item["kind"] == "sample" and item["name"] == "id_lora_01.mp4" for item in result["artifacts"])
    assert any(item["kind"] == "contract" for item in result["artifacts"])


def test_worker_preflight_reports_bundle_models_commands_environment_and_gpu(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    bundle = volume / "lorasuite" / "id-lora-job"
    dataset = bundle / "dataset"
    config = bundle / "config" / "serverless_train.yaml"
    manifest = dataset / "manifest.json"
    model = volume / "models" / "id-lora" / "adapter.safetensors"
    dataset.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    config.write_text("mode: zero_shot\n")
    manifest.write_text("{}")
    model.write_bytes(b"weights")
    (bundle / "train_serverless.sh").write_text("#!/usr/bin/env bash\n")
    (bundle / "file_index.json").write_text(json.dumps({"files": [{
        "path": "dataset/manifest.json",
        "size_bytes": manifest.stat().st_size,
        "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }]}))
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))
    monkeypatch.setenv("HF_TOKEN", "secret")
    original_which = worker.shutil.which
    original_run = worker.subprocess.run
    monkeypatch.setattr(worker.shutil, "which", lambda command: f"/usr/bin/{command}" if command in {"nvidia-smi", "bash", "python"} else original_which(command))

    def fake_run(command, **options):
        if "--query-gpu=name,memory.total,driver_version" in command:
            return SimpleNamespace(returncode=0, stdout="NVIDIA H100 80GB HBM3, 81559, 575.10\n", stderr="")
        return original_run(command, **options)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.handler({"input": {
        "action": "preflight",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "dataset_path": str(dataset),
        "manifest_path": str(manifest),
        "config_path": str(config),
        "config_digest": hashlib.sha256(config.read_bytes()).hexdigest(),
        "requirements": {
            "commands": ["bash", "python"],
            "environment": ["HF_TOKEN"],
            "model_paths": [str(model)],
            "minimum_gpu_memory_gb": 80,
        },
    }})

    assert result["status"] == "success"
    assert result["preflight"]["ready"] is True
    assert result["preflight"]["gpu"]["name"] == "NVIDIA H100 80GB HBM3"
    assert result["preflight"]["config_digest"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert all(check["passed"] for check in result["preflight"]["checks"])


def test_worker_rejects_tampered_training_configuration(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    bundle = volume / "lorasuite" / "image-job"
    dataset = bundle / "dataset"
    config = bundle / "config" / "serverless_train.yaml"
    manifest = dataset / "manifest.json"
    dataset.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    config.write_text("job: original\n")
    expected = hashlib.sha256(config.read_bytes()).hexdigest()
    config.write_text("job: tampered\n")
    manifest.write_text("{}")
    (bundle / "train_serverless.sh").write_text("#!/usr/bin/env bash\n")
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))

    with pytest.raises(ValueError, match="digest does not match"):
        worker.handler({"input": {
            "action": "train_lora",
            "bundle_format": "lorasuite-runpod-v1",
            "worker_contract_version": 1,
            "dataset_path": str(dataset),
            "manifest_path": str(manifest),
            "config_path": str(config),
            "output_path": str(bundle / "output"),
            "fingerprint": "image-fingerprint",
            "config_digest": expected,
        }})


def test_worker_preflight_returns_failures_without_starting_training(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(worker.shutil, "which", lambda _command: None)

    result = worker.handler({"input": {
        "action": "preflight",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "dataset_path": str(volume / "missing-dataset"),
        "manifest_path": str(volume / "missing-manifest.json"),
        "config_path": str(volume / "config" / "missing.yaml"),
        "requirements": {
            "commands": ["bash"],
            "environment": ["HF_TOKEN"],
            "model_paths": [str(volume / "models" / "missing.safetensors")],
            "minimum_gpu_memory_gb": 80,
        },
    }})

    assert result["preflight"]["ready"] is False
    failed = {check["id"] for check in result["preflight"]["checks"] if not check["passed"]}
    assert {"bundle_dataset", "bundle_manifest", "bundle_config", "worker_launcher", "command:bash", "environment:HF_TOKEN", "model:missing.safetensors", "gpu"}.issubset(failed)


def test_worker_bootstraps_pinned_fish_speech_models_and_reuses_manifest(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))
    monkeypatch.setattr(worker.shutil, "which", lambda command: "/usr/local/bin/hf" if command == "hf" else None)
    monkeypatch.setattr(worker.shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * 1024 ** 3))
    commands = []

    def fake_run(command, **_options):
        commands.append(command)
        destination = Path(command[command.index("--local-dir") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "codec.pth").write_bytes(b"codec")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    payload = {"input": {
        "action": "bootstrap_models",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "training_target_profile_id": "runpod_fish_speech_s2_voice_lora",
    }}

    created = worker.handler(payload)
    reused = worker.handler(payload)

    assert created["status"] == "success"
    assert created["reused"] is False
    assert reused["reused"] is True
    assert len(commands) == 1
    assert commands[0][:3] == ["hf", "download", "fishaudio/s2-pro"]
    assert "1de9996b6be38b745688de084d87a5633f714e4e" in commands[0]
    manifest = json.loads(Path(created["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["contract_version"] == 1
    assert "HF_TOKEN" not in json.dumps(manifest)


def test_worker_bootstraps_only_allowlisted_id_lora_assets(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))
    monkeypatch.setattr(worker.shutil, "which", lambda command: "/usr/local/bin/hf" if command == "hf" else None)
    monkeypatch.setattr(worker.shutil, "disk_usage", lambda _path: SimpleNamespace(free=120 * 1024 ** 3))
    repositories = []

    def fake_run(command, **_options):
        repositories.append(command[2])
        destination = Path(command[command.index("--local-dir") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        filenames = command[3:command.index("--revision")]
        for filename in filenames:
            (destination / filename).write_bytes(b"weights")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.handler({"input": {
        "action": "bootstrap_models",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "training_target_profile_id": "runpod_id_lora_ltx23_inference",
    }})

    assert result["status"] == "success"
    assert repositories == [
        "Lightricks/LTX-2.3",
        "google/gemma-3-12b-it-qat-q4_0-unquantized",
        "AviadDahan/LTX-2.3-ID-LoRA-CelebVHQ-3K",
    ]
    assert all(Path(path).exists() for path in result["required_paths"])


def test_worker_rejects_unknown_model_bootstrap_profile(tmp_path: Path, monkeypatch) -> None:
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setenv("RUNPOD_VOLUME_ROOT", str(volume))

    with pytest.raises(ValueError, match="unsupported model bootstrap profile"):
        worker.handler({"input": {
            "action": "bootstrap_models",
            "bundle_format": "lorasuite-runpod-v1",
            "worker_contract_version": 1,
            "training_target_profile_id": "attacker-controlled-profile",
        }})
