from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECKPOINT_SUFFIXES = {".ckpt", ".safetensors", ".pt", ".pth"}
SAMPLE_SUFFIXES = {".wav", ".flac", ".mp3", ".txt", ".lab", ".png", ".jpg", ".jpeg", ".mp4", ".webm"}
MODEL_BOOTSTRAP_VERSION = 1
MODEL_BOOTSTRAP_PROFILES = {
    "runpod_fish_speech_s2_voice_lora": {
        "minimum_free_gb": 20,
        "assets": [
            {
                "repository": "fishaudio/s2-pro",
                "revision": "1de9996b6be38b745688de084d87a5633f714e4e",
                "files": [],
                "destination": "models/fish-speech-s2",
            },
        ],
        "required": ["models/fish-speech-s2/codec.pth"],
    },
    "runpod_id_lora_ltx23_inference": {
        "minimum_free_gb": 90,
        "assets": [
            {
                "repository": "Lightricks/LTX-2.3",
                "revision": "4229404625088d21c4f112eb640fb04a0900ee25",
                "files": [
                    "ltx-2.3-22b-dev.safetensors",
                    "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
                    "ltx-2.3-22b-distilled-lora-384.safetensors",
                ],
                "destination": "models/id-lora-ltx23",
            },
            {
                "repository": "google/gemma-3-12b-it-qat-q4_0-unquantized",
                "revision": "68f7ee4fbd59087436ada77ed2d62f373fdd4482",
                "files": [],
                "destination": "models/id-lora-ltx23/gemma-3-12b-it-qat-q4_0-unquantized",
            },
            {
                "repository": "AviadDahan/LTX-2.3-ID-LoRA-CelebVHQ-3K",
                "revision": "157ba32d119709f0b769d9dab068cd540a286139",
                "files": ["lora_weights.safetensors"],
                "destination": "models/id-lora-ltx23/id-lora-celebvhq-ltx2.3",
            },
        ],
        "required": [
            "models/id-lora-ltx23/id-lora-celebvhq-ltx2.3/lora_weights.safetensors",
            "models/id-lora-ltx23/ltx-2.3-22b-dev.safetensors",
            "models/id-lora-ltx23/gemma-3-12b-it-qat-q4_0-unquantized",
            "models/id-lora-ltx23/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            "models/id-lora-ltx23/ltx-2.3-22b-distilled-lora-384.safetensors",
        ],
    },
}


def handler(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("input") if isinstance(job, dict) else None
    if not isinstance(payload, dict):
        raise ValueError("RunPod request must contain an input object")
    action = payload.get("action")
    if action not in {"preflight", "smoke_test", "bootstrap_models", "train_lora", "run_id_lora"}:
        raise ValueError("unsupported RunPod action")
    if payload.get("bundle_format") != "lorasuite-runpod-v1" or payload.get("worker_contract_version") != 1:
        raise ValueError("unsupported LoraSuite worker contract")
    if action == "preflight":
        return _preflight(payload)
    if action == "smoke_test":
        return _smoke_test(payload)
    if action == "bootstrap_models":
        return _bootstrap_models(job, payload)

    root = _volume_root()
    dataset_path = _volume_path(payload.get("dataset_path"), root, "dataset")
    manifest_path = _volume_path(payload.get("manifest_path"), root, "manifest")
    config_path = _volume_path(payload.get("config_path"), root, "config")
    output_path = _volume_path(payload.get("output_path"), root, "output")
    model_card_path = (
        _volume_path(payload.get("model_card_path"), root, "model card")
        if payload.get("model_card_path")
        else None
    )
    if not dataset_path.is_dir() or not manifest_path.is_file() or not config_path.is_file():
        raise ValueError("bundle dataset, manifest, or configuration is missing")
    config_digest = _require_config_digest(payload, config_path)
    if model_card_path is not None and not model_card_path.is_file():
        raise ValueError("bundle model card is missing")
    bundle_root = config_path.parent.parent
    launcher = bundle_root / "train_serverless.sh"
    if not launcher.is_file() or bundle_root != _volume_path(bundle_root, root, "bundle"):
        raise ValueError("validated Serverless launcher is missing")

    output_path.mkdir(parents=True, exist_ok=True)
    log_path = output_path / "serverless-worker.log"
    timeout = max(60, int(os.environ.get("LORASUITE_TRAIN_TIMEOUT_SECONDS", "86400")))
    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=bundle_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log_path.write_text(
        f"exit_code={result.returncode}\n\n[stdout]\n{result.stdout}\n\n[stderr]\n{result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"trainer failed with exit code {result.returncode}; log: {log_path}")
    if model_card_path is not None:
        shutil.copy2(model_card_path, output_path / "model_card.json")
    artifacts = _artifacts(output_path)
    artifacts.append(_artifact("config", config_path))
    artifacts.append(_artifact("log", log_path))
    required_kind = "sample" if action == "run_id_lora" else "checkpoint"
    if not any(item["kind"] == required_kind for item in artifacts):
        raise RuntimeError(f"worker completed without a {required_kind} artifact")
    if action == "run_id_lora" and not any(item["kind"] == "contract" for item in artifacts):
        raise RuntimeError("ID-LoRA worker completed without an inference contract")
    return {
        "status": "success",
        "bundle_format": "lorasuite-runpod-v1",
        "fingerprint": str(payload.get("fingerprint") or ""),
        "config_digest": config_digest,
        "artifacts": artifacts,
    }


def _bootstrap_models(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(payload.get("training_target_profile_id") or "").strip()
    plan = MODEL_BOOTSTRAP_PROFILES.get(profile_id)
    if plan is None:
        raise ValueError("unsupported model bootstrap profile")
    root = _volume_root()
    if not root.is_dir() or not _writable(root):
        raise ValueError(f"network volume is not writable at {root}")
    manifest_path = root / "models" / ".lorasuite" / f"{profile_id}.json"
    required = [_volume_path(str(root / relative), root, "model") for relative in plan["required"]]
    existing = _read_bootstrap_manifest(manifest_path)
    if existing and existing.get("contract_version") == MODEL_BOOTSTRAP_VERSION and all(path.exists() for path in required):
        return _bootstrap_result(profile_id, manifest_path, required, reused=True)

    free_gb = shutil.disk_usage(root).free / (1024 ** 3)
    minimum_free_gb = int(plan["minimum_free_gb"])
    if free_gb < minimum_free_gb:
        raise ValueError(f"model bootstrap requires at least {minimum_free_gb} GB free; {free_gb:.1f} GB available")
    if not shutil.which("hf"):
        raise RuntimeError("Hugging Face CLI is not installed in the worker")

    log_path = root / "models" / ".lorasuite" / f"{profile_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed_assets: list[dict[str, Any]] = []
    with log_path.open("a", encoding="utf-8") as log:
        for index, asset in enumerate(plan["assets"], start=1):
            destination = _volume_path(str(root / asset["destination"]), root, "model destination")
            destination.mkdir(parents=True, exist_ok=True)
            message = f'Downloading {index}/{len(plan["assets"])}: {asset["repository"]}'
            _progress(job, message)
            command = [
                "hf", "download", str(asset["repository"]),
                *[str(value) for value in asset["files"]],
                "--revision", str(asset["revision"]),
                "--local-dir", str(destination),
            ]
            result = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=max(600, int(os.environ.get("LORASUITE_MODEL_BOOTSTRAP_TIMEOUT_SECONDS", "43200"))),
                env={**os.environ, "HF_HUB_ENABLE_HF_TRANSFER": "1"},
            )
            if result.returncode != 0:
                raise RuntimeError(f'model download failed for {asset["repository"]}; log: {log_path}')
            completed_assets.append({
                "repository": asset["repository"],
                "revision": asset["revision"],
                "files": asset["files"],
                "destination": str(destination),
            })

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"model bootstrap completed with missing required paths: {', '.join(missing)}")
    manifest_path.write_text(json.dumps({
        "contract_version": MODEL_BOOTSTRAP_VERSION,
        "training_target_profile_id": profile_id,
        "assets": completed_assets,
        "required_paths": [str(path) for path in required],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n", encoding="utf-8")
    _progress(job, "Required models are ready")
    return _bootstrap_result(profile_id, manifest_path, required, reused=False)


def _read_bootstrap_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _bootstrap_result(profile_id: str, manifest_path: Path, required: list[Path], *, reused: bool) -> dict[str, Any]:
    return {
        "status": "success",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "action": "bootstrap_models",
        "training_target_profile_id": profile_id,
        "reused": reused,
        "manifest_path": str(manifest_path),
        "required_paths": [str(path) for path in required],
    }


def _progress(job: dict[str, Any], message: str) -> None:
    try:
        import runpod

        runpod.serverless.progress_update(job, message)
    except (ImportError, AttributeError, RuntimeError):
        pass


def _preflight(payload: dict[str, Any]) -> dict[str, Any]:
    root = _volume_root()
    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError("preflight requirements are missing")
    commands = _string_list(requirements.get("commands"), "commands")
    environment = _string_list(requirements.get("environment"), "environment")
    model_paths = _string_list(requirements.get("model_paths"), "model paths")
    minimum_gpu_memory_gb = max(0, int(requirements.get("minimum_gpu_memory_gb") or 0))
    checks: list[dict[str, Any]] = []

    volume_ready = root.is_dir() and _writable(root)
    _check(checks, "network_volume", volume_ready, "Network volume is mounted and writable" if volume_ready else f"Network volume is not writable at {root}")

    for key, label, expected in (
        ("dataset_path", "bundle_dataset", "directory"),
        ("manifest_path", "bundle_manifest", "file"),
        ("config_path", "bundle_config", "file"),
    ):
        try:
            path = _volume_path(payload.get(key), root, label)
            exists = path.is_dir() if expected == "directory" else path.is_file()
            _check(checks, label, exists, f"{path} is ready" if exists else f"{path} is missing")
        except ValueError as error:
            _check(checks, label, False, str(error))

    config_value = payload.get("config_path")
    try:
        config_path = _volume_path(config_value, root, "config")
        config_ready, config_detail, config_digest = _config_digest_check(payload, config_path)
        _check(checks, "config_digest", config_ready, config_detail)
        bundle_root = config_path.parent.parent
        launcher = bundle_root / "train_serverless.sh"
        launcher_ready = launcher.is_file() and os.access(launcher, os.R_OK)
        _check(checks, "worker_launcher", launcher_ready, f"{launcher} is ready" if launcher_ready else f"{launcher} is missing")
        integrity_ready, integrity_detail = _verify_bundle_index(bundle_root)
        _check(checks, "bundle_integrity", integrity_ready, integrity_detail)
    except ValueError as error:
        config_digest = ""
        _check(checks, "config_digest", False, str(error))
        _check(checks, "worker_launcher", False, str(error))
        _check(checks, "bundle_integrity", False, str(error))

    for command in commands:
        location = shutil.which(command)
        _check(checks, f"command:{command}", bool(location), location or f"{command} is not installed")
    for name in environment:
        present = bool(os.environ.get(name, "").strip())
        _check(checks, f"environment:{name}", present, f"{name} is configured" if present else f"{name} is not configured")
    for value in model_paths:
        try:
            path = _volume_path(value, root, "model")
            present = path.is_file() or path.is_dir()
            size = path.stat().st_size if path.is_file() else None
            detail = f"{path} is ready" if present else f"{path} is missing"
            _check(checks, f"model:{path.name}", present, detail, size_bytes=size)
        except ValueError as error:
            _check(checks, f"model:{Path(value).name}", False, str(error))

    gpu = _gpu_details()
    gpu_ready = gpu["available"] and gpu["memory_gb"] >= minimum_gpu_memory_gb
    gpu_detail = (
        f'{gpu["name"]} with {gpu["memory_gb"]:.1f} GB; requires {minimum_gpu_memory_gb} GB'
        if gpu["available"] else "No NVIDIA GPU is visible to the worker"
    )
    _check(checks, "gpu", gpu_ready, gpu_detail)
    return {
        "status": "success",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "preflight": {
            "ready": all(check["passed"] for check in checks),
            "volume_root": str(root),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "gpu": gpu,
            "config_digest": config_digest,
            "checks": checks,
        },
    }


def _smoke_test(payload: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = (root or _volume_root()).expanduser().resolve(strict=False)
    checks: list[dict[str, Any]] = []
    try:
        dataset_path = _volume_path(payload.get("dataset_path"), root, "dataset")
        manifest_path = _volume_path(payload.get("manifest_path"), root, "manifest")
        config_path = _volume_path(payload.get("config_path"), root, "config")
        _volume_path(payload.get("output_path"), root, "output")
    except ValueError as error:
        _check(checks, "safe_paths", False, str(error))
        return _smoke_result(checks)
    _check(checks, "safe_paths", True, "All worker paths stay inside the network volume")
    _check(checks, "bundle_dataset", dataset_path.is_dir(), f"{dataset_path} is ready" if dataset_path.is_dir() else f"{dataset_path} is missing")
    _check(checks, "bundle_manifest", manifest_path.is_file(), f"{manifest_path} is ready" if manifest_path.is_file() else f"{manifest_path} is missing")
    _check(checks, "bundle_config", config_path.is_file(), f"{config_path} is ready" if config_path.is_file() else f"{config_path} is missing")
    config_ready, config_detail, _ = _config_digest_check(payload, config_path)
    _check(checks, "config_digest", config_ready, config_detail)
    bundle_root = config_path.parent.parent
    launcher = bundle_root / "train_serverless.sh"
    _check(checks, "worker_launcher", launcher.is_file(), f"{launcher} is ready" if launcher.is_file() else f"{launcher} is missing")
    integrity_ready, integrity_detail = _verify_bundle_index(bundle_root)
    _check(checks, "bundle_integrity", integrity_ready, integrity_detail)

    manifest = _read_json_object(manifest_path)
    manifest_ready = bool(manifest) and manifest.get("created_by") == "LoraSuite" and str(manifest.get("status") or "").lower() not in {"blocked", "failed"}
    _check(checks, "manifest_contract", manifest_ready, "Dataset manifest is a ready LoraSuite export" if manifest_ready else "Dataset manifest is missing LoraSuite readiness provenance")
    config_text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.is_file() else ""
    _check(checks, "config_contract", bool(config_text.strip()), "Trainer configuration is present" if config_text.strip() else "Trainer configuration is empty")
    if launcher.is_file() and shutil.which("bash"):
        syntax = subprocess.run(["bash", "-n", str(launcher)], capture_output=True, text=True, check=False, timeout=20)
        _check(checks, "launcher_syntax", syntax.returncode == 0, "Serverless launcher shell syntax is valid" if syntax.returncode == 0 else syntax.stderr.strip() or "Serverless launcher shell syntax failed")
    else:
        _check(checks, "launcher_syntax", False, "bash or the Serverless launcher is unavailable")

    profile_id = str(payload.get("training_target_profile_id") or "")
    target_action = str(payload.get("target_action") or "train_lora")
    profile_ready, profile_detail = _profile_smoke(profile_id, target_action, bundle_root, config_text)
    _check(checks, "profile_contract", profile_ready, profile_detail)
    return _smoke_result(checks)


def _smoke_result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "success",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "action": "smoke_test",
        "smoke": {"ready": bool(checks) and all(check["passed"] for check in checks), "checks": checks},
    }


def _profile_smoke(profile_id: str, target_action: str, bundle_root: Path, config_text: str) -> tuple[bool, str]:
    launcher = (bundle_root / "train_serverless.sh").read_text(encoding="utf-8", errors="replace") if (bundle_root / "train_serverless.sh").is_file() else ""
    if profile_id in {"runcomfy_flux1_dev_character", "runcomfy_qwen_image_character", "runcomfy_wan22_14b_t2v_character"}:
        ready = "ai-toolkit" in launcher and "job: extension" in config_text and "{dataset_name}" not in config_text
        return ready, "AI Toolkit launcher and resolved trainer configuration agree" if ready else "AI Toolkit launcher or resolved configuration is incomplete"
    if profile_id == "runpod_fish_speech_s2_voice_lora":
        helpers = [
            bundle_root / "train_fish_speech_s2.sh",
            bundle_root / "render_fish_speech_evaluation.py",
            bundle_root / "evaluation_phrases.json",
        ]
        ready = target_action == "train_lora" and "fish_speech_s2" in config_text and all(path.is_file() for path in helpers)
        return ready, "Fish Speech trainer and evaluation helpers are packaged" if ready else "Fish Speech package is missing its trainer or helpers"
    if profile_id == "runpod_id_lora_ltx23_inference":
        ready = target_action == "run_id_lora" and "id_lora_ltx23_zero_shot" in config_text and (bundle_root / "prepare_id_lora_inference.py").is_file()
        return ready, "ID-LoRA zero-shot inference contract and preparation helper are packaged" if ready else "ID-LoRA inference package is incomplete"
    return False, f"Unsupported executable training profile: {profile_id or 'missing'}"


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 64 or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"preflight {label} must be a list of strings")
    return [item.strip() for item in value]


def _writable(root: Path) -> bool:
    if not root.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(prefix=".lorasuite-preflight-", dir=root, delete=True):
            return True
    except OSError:
        return False


def _gpu_details() -> dict[str, Any]:
    command = shutil.which("nvidia-smi")
    if not command:
        return {"available": False, "name": "", "memory_gb": 0.0, "driver_version": ""}
    try:
        result = subprocess.run(
            [command, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        first = next((line for line in result.stdout.splitlines() if line.strip()), "")
        name, memory_mb, driver = (part.strip() for part in first.split(",", maxsplit=2))
        return {
            "available": result.returncode == 0,
            "name": name,
            "memory_gb": float(round(float(memory_mb) / 1024)),
            "driver_version": driver,
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"available": False, "name": "", "memory_gb": 0.0, "driver_version": ""}


def _verify_bundle_index(bundle_root: Path) -> tuple[bool, str]:
    index_path = bundle_root / "file_index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, f"Bundle file index is unreadable at {index_path}"
    entries = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries or len(entries) > 100_000:
        return False, "Bundle file index is empty or invalid"
    for item in entries:
        if not isinstance(item, dict):
            return False, "Bundle file index contains an invalid entry"
        relative = item.get("path")
        expected_size = item.get("size_bytes")
        expected_digest = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_size, int) or not isinstance(expected_digest, str):
            return False, "Bundle file index contains incomplete provenance"
        path = (bundle_root / relative).resolve(strict=False)
        if path == bundle_root or bundle_root not in path.parents or not path.is_file():
            return False, f"Indexed bundle file is missing or unsafe: {relative}"
        if path.stat().st_size != expected_size or _sha256(path) != expected_digest:
            return False, f"Indexed bundle file failed size or checksum verification: {relative}"
    return True, f"Verified {len(entries)} indexed bundle files"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_digest_check(payload: dict[str, Any], config_path: Path) -> tuple[bool, str, str]:
    expected = str(payload.get("config_digest") or "").strip()
    if not expected:
        return False, "Training configuration digest is missing", ""
    if not config_path.is_file():
        return False, f"Training configuration is missing at {config_path}", ""
    actual = _sha256(config_path)
    if actual != expected:
        return False, "Training configuration digest does not match the submitted contract", actual
    return True, f"Verified immutable training configuration {actual[:12]}", actual


def _require_config_digest(payload: dict[str, Any], config_path: Path) -> str:
    ready, detail, actual = _config_digest_check(payload, config_path)
    if not ready:
        raise ValueError(detail)
    return actual


def _check(checks: list[dict[str, Any]], check_id: str, passed: bool, detail: str, **metadata: Any) -> None:
    checks.append({"id": check_id, "passed": bool(passed), "detail": detail, **metadata})


def _volume_root() -> Path:
    return Path(os.environ.get("RUNPOD_VOLUME_ROOT", "/runpod-volume")).expanduser().resolve(strict=False)


def _volume_path(value: Any, root: Path, label: str) -> Path:
    if isinstance(value, Path):
        candidate = value.expanduser().resolve(strict=False)
    elif isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser().resolve(strict=False)
    else:
        raise ValueError(f"{label} path is required")
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"{label} path must stay under the RunPod network volume")
    return candidate


def _artifacts(output_path: Path) -> list[dict[str, Any]]:
    limit = max(1, int(os.environ.get("LORASUITE_ARTIFACT_LIMIT", "500")))
    found = []
    for path in sorted(item for item in output_path.rglob("*") if item.is_file()):
        if path.name == "serverless-worker.log" or ".codes" in path.parts:
            continue
        suffix = path.suffix.lower()
        group_id = None
        relative = path.relative_to(output_path)
        if path.name == "model_card.json":
            kind = "model_card"
        elif path.name == "inference_contract.json":
            kind = "contract"
        elif suffix in CHECKPOINT_SUFFIXES:
            if suffix == ".pth" and (path.name != "model.pth" or "merged" not in relative.parts):
                continue
            if suffix == ".pth":
                kind = "model"
                group_id = relative.parts[1] if len(relative.parts) > 2 else None
            else:
                kind = "checkpoint"
                group_id = path.stem
        elif suffix in SAMPLE_SUFFIXES:
            kind = "sample"
            group_id = relative.parts[1] if len(relative.parts) > 2 and relative.parts[0] == "evaluation" else None
        else:
            continue
        name = "__".join(relative.parts)
        found.append(_artifact(kind, path, name=name, group_id=group_id))
        if len(found) >= limit:
            raise RuntimeError(f"artifact limit exceeded ({limit})")
    return found


def _artifact(kind: str, path: Path, *, name: str | None = None, group_id: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    payload = {
        "kind": kind,
        "name": name or path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }
    if group_id:
        payload["group_id"] = group_id
    return payload


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
