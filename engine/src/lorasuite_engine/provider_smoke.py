from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.runpod_bundle import RunPodBundleService
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import TrainingTargetProfile, get_training_target_profile


class ProviderSmokeCheck(BaseModel):
    id: str
    passed: bool
    detail: str


class ProviderSmokeRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("provider_smoke"))
    provider: Literal["runcomfy", "runpod"]
    modality: Literal["image", "video", "voice", "audio_visual"]
    training_target_profile_id: str
    project_id: str | None = None
    source_export_path: Path
    source_fingerprint: str = ""
    config_file: str = ""
    bundle_id: str | None = None
    status: Literal["complete", "failed"] = "complete"
    ready: bool = False
    checks: list[ProviderSmokeCheck] = Field(default_factory=list)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    completed_at: Any = Field(default_factory=utc_now)


class ProviderSmokeService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def registry_path(self) -> Path:
        return self.vault_root / "provider_smoke_runs.json"

    def list_runs(
        self,
        *,
        project_id: str | None = None,
        provider: str | None = None,
        training_target_profile_id: str | None = None,
        bundle_id: str | None = None,
    ) -> list[ProviderSmokeRun]:
        runs = self._read().values()
        if project_id is not None:
            runs = (run for run in runs if run.project_id == project_id)
        if provider is not None:
            runs = (run for run in runs if run.provider == provider)
        if training_target_profile_id is not None:
            runs = (run for run in runs if run.training_target_profile_id == training_target_profile_id)
        if bundle_id is not None:
            runs = (run for run in runs if run.bundle_id == bundle_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> ProviderSmokeRun | None:
        return self._read().get(run_id)

    def run_runcomfy(
        self,
        *,
        project_id: str,
        source_export_path: Path,
        training_target_profile_id: str,
        config_file: str,
    ) -> ProviderSmokeRun:
        source = Path(source_export_path).expanduser().resolve(strict=False)
        profile = get_training_target_profile(training_target_profile_id)
        checks: list[ProviderSmokeCheck] = []
        self._check(checks, "profile", profile.provider == "runcomfy" and profile.ready, f"{profile.label} is an executable RunComfy profile")
        self._check(checks, "modality", profile.modality in {"image", "video"}, f"{profile.modality} is supported by the RunComfy smoke harness")
        manifest = _read_json(source / "manifest.json")
        self._check(checks, "manifest", bool(manifest) and manifest.get("created_by") == "LoraSuite", "Dataset manifest has LoraSuite provenance")
        manifest, manifest_profile, profile_detail = self._resolve_runcomfy_manifest_profile(
            source,
            manifest or {},
            project_id,
            profile.profile_id,
        )
        self._check(checks, "profile_match", manifest_profile == profile.profile_id, profile_detail)
        pair_ready, pair_detail = _dataset_pairs(source, manifest or {}, profile.modality)
        self._check(checks, "dataset_pairs", pair_ready, pair_detail)
        checksum_ready, checksum_detail = _dataset_checksums(source, manifest or {}, profile.modality)
        self._check(checks, "checksums", checksum_ready, checksum_detail)
        yaml_ready, yaml_detail, config = _parse_runcomfy_config(config_file)
        self._check(checks, "yaml", yaml_ready, yaml_detail)
        contract_ready, contract_detail = _runcomfy_contract(config_file, config, profile)
        self._check(checks, "trainer_contract", contract_ready, contract_detail)
        run = ProviderSmokeRun(
            provider="runcomfy",
            modality=profile.modality,
            training_target_profile_id=profile.profile_id,
            project_id=project_id,
            source_export_path=source,
            source_fingerprint=str((manifest or {}).get("dataset_fingerprint") or ""),
            config_file=config_file,
            ready=all(check.passed for check in checks),
            checks=checks,
        )
        self._save(run)
        return run

    def _resolve_runcomfy_manifest_profile(
        self,
        source: Path,
        manifest: dict[str, Any],
        project_id: str,
        requested_profile_id: str,
    ) -> tuple[dict[str, Any], str, str]:
        target = manifest.get("training_target")
        manifest_profile = str(target.get("profile_id") or "") if isinstance(target, dict) else ""
        if manifest_profile:
            detail = "Dataset and trainer profile agree" if manifest_profile == requested_profile_id else f"Dataset targets {manifest_profile}"
            return manifest, manifest_profile, detail

        snapshot_id = str(manifest.get("dataset_snapshot_id") or "")
        snapshot = DatasetCompilerService(self.vault_root).get_snapshot(snapshot_id) if snapshot_id else None
        fingerprint = str(manifest.get("dataset_fingerprint") or "")
        project_matches = str(manifest.get("character_project_id") or "") == project_id
        export_matches = snapshot is not None and snapshot.export_path is not None and snapshot.export_path.expanduser().resolve(strict=False) == source
        fingerprint_matches = snapshot is not None and bool(snapshot.fingerprint) and snapshot.fingerprint == fingerprint
        profile_matches = snapshot is not None and snapshot.training_target.profile_id == requested_profile_id
        if not (snapshot and project_matches and export_matches and fingerprint_matches and profile_matches):
            return manifest, "", "Dataset targets no profile and its snapshot provenance could not be verified"

        migrated = dict(manifest)
        migrated["training_target"] = snapshot.training_target.model_dump(mode="json")
        migrations = list(manifest.get("contract_migrations") or [])
        migrations.append({
            "id": "training-target-from-snapshot-v1",
            "snapshot_id": snapshot.id,
            "migrated_at": utc_now().isoformat(),
        })
        migrated["contract_migrations"] = migrations
        atomic_write_json(source / "manifest.json", migrated)
        return migrated, requested_profile_id, "Recovered and embedded the verified training target from the immutable dataset snapshot"

    def run_runpod(self, bundle_id: str) -> ProviderSmokeRun:
        bundle = next((item for item in RunPodBundleService(self.vault_root).list_bundles() if item.id == bundle_id), None)
        if bundle is None:
            raise KeyError(bundle_id)
        if not bundle.training_target_profile_id:
            raise ValueError("RunPod bundle has no training target profile")
        try:
            worker = _load_runpod_worker()

            with TemporaryDirectory(prefix="lorasuite-provider-smoke-") as temporary:
                root = Path(temporary).resolve()
                relative_root = Path(bundle.serverless_root).relative_to("/runpod-volume")
                local_bundle = root / relative_root
                shutil.copytree(bundle.output_path, local_bundle)
                payload = json.loads((local_bundle / "runpod_input.json").read_text(encoding="utf-8"))["input"]
                target_action = str(payload["action"])
                payload["action"] = "smoke_test"
                payload["target_action"] = target_action
                for key in ("dataset_path", "manifest_path", "config_path", "output_path"):
                    payload[key] = str(root / Path(payload[key]).relative_to("/runpod-volume"))
                result = worker._smoke_test(payload, root=root)
            smoke = result["smoke"]
            checks = [ProviderSmokeCheck.model_validate(check) for check in smoke["checks"]]
            run = ProviderSmokeRun(
                provider="runpod",
                modality=bundle.modality,
                training_target_profile_id=bundle.training_target_profile_id,
                project_id=bundle.project_id,
                source_export_path=bundle.source_export_path,
                source_fingerprint=bundle.fingerprint,
                bundle_id=bundle.id,
                ready=bool(smoke["ready"]),
                checks=checks,
            )
        except Exception as error:
            run = ProviderSmokeRun(
                provider="runpod",
                modality=bundle.modality,
                training_target_profile_id=bundle.training_target_profile_id,
                project_id=bundle.project_id,
                source_export_path=bundle.source_export_path,
                source_fingerprint=bundle.fingerprint,
                bundle_id=bundle.id,
                status="failed",
                error=str(error),
            )
        self._save(run)
        return run

    @staticmethod
    def _check(checks: list[ProviderSmokeCheck], check_id: str, passed: bool, detail: str) -> None:
        checks.append(ProviderSmokeCheck(id=check_id, passed=passed, detail=detail))

    def _read(self) -> dict[str, ProviderSmokeRun]:
        with json_file_lock(self.registry_path):
            if not self.registry_path.is_file():
                return {}
            try:
                payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {key: ProviderSmokeRun.model_validate(value) for key, value in payload.items()}

    def _save(self, run: ProviderSmokeRun) -> None:
        with json_file_lock(self.registry_path):
            runs = self._read()
            runs[run.id] = run
            atomic_write_json(self.registry_path, {key: value.model_dump(mode="json") for key, value in runs.items()})


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _resolve_export_file(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    return candidate if candidate == root or root in candidate.parents else None


def _dataset_pairs(root: Path, manifest: dict[str, Any], modality: str) -> tuple[bool, str]:
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        return False, "Dataset manifest contains no training files"
    media_key = "image" if modality == "image" else "video"
    valid = 0
    for entry in entries:
        if not isinstance(entry, dict):
            return False, "Dataset manifest contains an invalid file entry"
        media = _resolve_export_file(root, entry.get(media_key))
        caption = _resolve_export_file(root, entry.get("caption"))
        if media is None or caption is None or not media.is_file() or not caption.is_file() or not caption.read_text(encoding="utf-8").strip():
            return False, f"A {media_key}/caption pair is missing, unsafe, or empty"
        if media.stem != caption.stem:
            return False, f"Pair basenames do not match: {media.name} and {caption.name}"
        valid += 1
    return True, f"Verified {valid} {media_key}/caption pairs"


def _dataset_checksums(root: Path, manifest: dict[str, Any], modality: str) -> tuple[bool, str]:
    media_key = "image" if modality == "image" else "video"
    entries = manifest.get("files") or []
    verified = 0
    for entry in entries:
        path = _resolve_export_file(root, entry.get(media_key)) if isinstance(entry, dict) else None
        expected = entry.get("sha256") if isinstance(entry, dict) else None
        if path is None or not path.is_file() or not isinstance(expected, str) or _sha256(path) != expected:
            return False, f"A {media_key} failed checksum verification"
        verified += 1
    return bool(verified), f"Verified {verified} media checksums"


def _parse_runcomfy_config(config_file: str) -> tuple[bool, str, dict[str, Any] | None]:
    if not config_file.strip():
        return False, "AI Toolkit YAML is empty", None
    try:
        value = yaml.safe_load(config_file.replace("{dataset_name}", "lorasuite-smoke-dataset"))
    except yaml.YAMLError as error:
        return False, f"AI Toolkit YAML is invalid: {error}", None
    if not isinstance(value, dict):
        return False, "AI Toolkit YAML must contain an object", None
    return True, "AI Toolkit YAML parses successfully", value


def _runcomfy_contract(
    config_file: str,
    config: dict[str, Any] | None,
    profile: TrainingTargetProfile,
) -> tuple[bool, str]:
    if config is None:
        return False, "Trainer contract cannot be inspected until YAML parses"
    if "{dataset_name}" not in config_file:
        return False, "Dataset folder must retain the {dataset_name} placeholder"
    processes = ((config.get("config") or {}).get("process") or [])
    if config.get("job") != "extension" or not isinstance(processes, list) or not processes:
        return False, "AI Toolkit extension process is missing"
    process = processes[0] if isinstance(processes[0], dict) else {}
    process_type = str(process.get("type") or "")
    if process_type not in {"sd_trainer", "diffusion_trainer"}:
        return False, "AI Toolkit process must use sd_trainer or diffusion_trainer"
    datasets = process.get("datasets") or []
    model = process.get("model") or {}
    if not datasets or not isinstance(datasets[0], dict) or "lorasuite-smoke-dataset" not in str(datasets[0].get("folder_path") or ""):
        return False, "AI Toolkit dataset binding is missing"
    if profile.modality == "video":
        dataset = datasets[0]
        if model.get("arch") != "wan22_14b" or int(dataset.get("num_frames") or 0) < 2 or int(dataset.get("fps") or 0) < 1:
            return False, "WAN video model, frame count, or FPS contract is incomplete"
    if profile.model_family == "krea2":
        train = process.get("train") or {}
        if model.get("arch") != "krea2":
            return False, "KREA 2 YAML must use model arch: krea2"
        if model.get("name_or_path") != profile.base_model:
            return False, f"KREA 2 YAML must train against {profile.base_model}"
        if train.get("timestep_type") != "linear":
            return False, "KREA 2 YAML must use linear timestep sampling"
    return True, f"Executable AI Toolkit {profile.label} contract is complete"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_runpod_worker():
    try:
        from workers.runpod import handler as worker

        return worker
    except ModuleNotFoundError:
        worker_path = Path(__file__).resolve().parents[3] / "workers" / "runpod" / "handler.py"
        if not worker_path.is_file():
            raise RuntimeError(f"RunPod worker source is unavailable at {worker_path}")
        spec = importlib.util.spec_from_file_location("lorasuite_runpod_smoke_worker", worker_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("RunPod worker smoke module could not be loaded")
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        return worker
