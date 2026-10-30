from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.runpod_runs import RunPodProvider, RunPodRunStatus, RunPodServerlessProvider
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import get_training_target_profile


BOOTSTRAP_PROFILE_IDS = {
    "runpod_fish_speech_s2_voice_lora",
    "runpod_id_lora_ltx23_inference",
}


class RunPodModelBootstrapRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_model_bootstrap"))
    provider: str = "runpod"
    training_target_profile_id: str
    endpoint_id: str
    provider_job_id: str | None = None
    status: RunPodRunStatus = "queued"
    progress_message: str = "Ready to install required models"
    required_paths: list[str] = Field(default_factory=list)
    manifest_path: str | None = None
    reused: bool = False
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class RunPodModelBootstrapService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: Callable[[str], RunPodProvider] = RunPodServerlessProvider,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "runpod_model_bootstrap_runs.json"

    def list_runs(
        self,
        *,
        endpoint_id: str | None = None,
        training_target_profile_id: str | None = None,
    ) -> list[RunPodModelBootstrapRun]:
        runs = self._read().values()
        if endpoint_id:
            endpoint = endpoint_id.strip()
            runs = (run for run in runs if run.endpoint_id == endpoint)
        if training_target_profile_id:
            profile_id = training_target_profile_id.strip()
            runs = (run for run in runs if run.training_target_profile_id == profile_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> RunPodModelBootstrapRun | None:
        return self._read().get(run_id)

    def create_run(self, *, endpoint_id: str, training_target_profile_id: str) -> RunPodModelBootstrapRun:
        endpoint = endpoint_id.strip()
        if not endpoint:
            raise ValueError("RunPod Serverless endpoint ID is required")
        profile_id = training_target_profile_id.strip()
        if profile_id not in BOOTSTRAP_PROFILE_IDS:
            raise ValueError("training target does not support automatic model bootstrap")
        profile = get_training_target_profile(profile_id)
        if not profile.ready or not profile.required_model_paths:
            raise ValueError("training target has no validated model bootstrap contract")
        required_paths = [_serverless_model_path(path) for path in profile.required_model_paths]
        runs = self._read()
        existing = next((
            run for run in runs.values()
            if run.endpoint_id == endpoint
            and run.training_target_profile_id == profile_id
            and run.status not in {"failed", "canceled", "timed_out"}
        ), None)
        if existing:
            return existing
        run = RunPodModelBootstrapRun(
            endpoint_id=endpoint,
            training_target_profile_id=profile_id,
            required_paths=required_paths,
        )
        runs[run.id] = run
        self._write(runs)
        return run

    def submit_run(self, run_id: str, token: str) -> RunPodModelBootstrapRun:
        run = self._require(run_id)
        if run.provider_job_id:
            return self.refresh_run(run_id, token)
        payload = {
            "input": {
                "action": "bootstrap_models",
                "bundle_format": "lorasuite-runpod-v1",
                "worker_contract_version": 1,
                "training_target_profile_id": run.training_target_profile_id,
            },
            "policy": {"executionTimeout": 43_200_000, "ttl": 86_400_000},
        }
        try:
            response = self.provider_factory(token).submit(run.endpoint_id, payload)
            job_id = str(response.get("id") or "").strip()
            if not job_id:
                raise RuntimeError("RunPod did not return a model-bootstrap job ID")
            run.provider_job_id = job_id
            return self._save(run, status="in_queue", message="Waiting for a RunPod worker")
        except Exception as error:
            return self._save(run, status="failed", message="Model bootstrap submission failed", error=str(error))

    def refresh_run(self, run_id: str, token: str) -> RunPodModelBootstrapRun:
        run = self._require(run_id)
        if run.status in {"completed", "failed", "canceled", "timed_out"}:
            return run
        if not run.provider_job_id:
            return self.submit_run(run_id, token)
        try:
            payload = self.provider_factory(token).status(run.endpoint_id, run.provider_job_id)
            status = str(payload.get("status") or "").upper()
            if status == "IN_QUEUE":
                return self._save(run, status="in_queue", message=_progress(payload, "Waiting for a RunPod worker"))
            if status in {"IN_PROGRESS", "RUNNING"}:
                return self._save(run, status="running", message=_progress(payload, "Downloading required models"))
            if status == "COMPLETED":
                output = payload.get("output")
                error = _validate_completion(output, run)
                if error:
                    return self._save(run, status="failed", message="Model bootstrap validation failed", error=error)
                run.required_paths = [str(path) for path in output.get("required_paths", [])]
                run.manifest_path = str(output.get("manifest_path") or "") or None
                run.reused = bool(output.get("reused"))
                run.completed_at = utc_now()
                return self._save(run, status="completed", message="Required model files are ready")
            if status in {"CANCELLED", "CANCELED"}:
                run.completed_at = utc_now()
                return self._save(run, status="canceled", message="Model bootstrap canceled")
            if status == "TIMED_OUT":
                run.completed_at = utc_now()
                return self._save(run, status="timed_out", message="Model bootstrap timed out", error=_error(payload))
            if status == "FAILED":
                return self._save(run, status="failed", message="Model bootstrap failed", error=_error(payload))
            return self._save(run, message=f"RunPod status: {status.lower() or 'unknown'}")
        except Exception as error:
            return self._save(run, status="failed", message="Model bootstrap status check failed", error=str(error))

    def cancel_run(self, run_id: str, token: str) -> RunPodModelBootstrapRun:
        run = self._require(run_id)
        if run.provider_job_id and run.status not in {"completed", "failed", "canceled", "timed_out"}:
            self.provider_factory(token).cancel(run.endpoint_id, run.provider_job_id)
        run.completed_at = utc_now()
        return self._save(run, status="canceled", message="Model bootstrap canceled")

    def _require(self, run_id: str) -> RunPodModelBootstrapRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _save(
        self,
        run: RunPodModelBootstrapRun,
        *,
        status: RunPodRunStatus | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> RunPodModelBootstrapRun:
        runs = self._read()
        if status is not None:
            run.status = status
        if message is not None:
            run.progress_message = message
        if error is not None:
            run.error = error
            run.completed_at = utc_now()
        run.updated_at = utc_now()
        runs[run.id] = run
        self._write(runs)
        return run

    def _read(self) -> dict[str, RunPodModelBootstrapRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            try:
                payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {
                item["id"]: RunPodModelBootstrapRun.model_validate(item)
                for item in payload.get("runs", [])
            }

    def _write(self, runs: dict[str, RunPodModelBootstrapRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {
                "version": 1,
                "runs": [run.model_dump(mode="json") for run in runs.values()],
            })


def _serverless_model_path(value: str) -> str:
    source = PurePosixPath(value)
    try:
        relative = source.relative_to("/workspace/models")
    except ValueError as error:
        raise ValueError(f"model path is outside /workspace/models: {value}") from error
    return str(PurePosixPath("/runpod-volume/models") / relative)


def _validate_completion(output: Any, run: RunPodModelBootstrapRun) -> str | None:
    if not isinstance(output, dict):
        return "RunPod worker returned no model-bootstrap output"
    if output.get("status") != "success" or output.get("action") != "bootstrap_models":
        return "RunPod worker returned an invalid model-bootstrap envelope"
    if output.get("bundle_format") != "lorasuite-runpod-v1" or output.get("worker_contract_version") != 1:
        return "RunPod worker model-bootstrap contract version does not match"
    if output.get("training_target_profile_id") != run.training_target_profile_id:
        return "RunPod worker model-bootstrap profile does not match"
    values = output.get("required_paths")
    if not isinstance(values, list) or not values or any(not _safe_model_path(value) for value in values):
        return "RunPod worker returned unsafe or missing model paths"
    if set(values) != set(run.required_paths):
        return "RunPod worker required model paths do not match the training target"
    manifest = output.get("manifest_path")
    if not _safe_model_path(manifest, manifest=True):
        return "RunPod worker returned an unsafe model manifest path"
    return None


def _safe_model_path(value: Any, *, manifest: bool = False) -> bool:
    if not isinstance(value, str) or not value.startswith("/runpod-volume/models/"):
        return False
    path = PurePosixPath(value)
    if ".." in path.parts:
        return False
    return not manifest or path.suffix == ".json"


def _progress(payload: dict[str, Any], fallback: str) -> str:
    value = payload.get("progress")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("message"), str) and value["message"].strip():
        return value["message"].strip()
    return fallback


def _error(payload: dict[str, Any]) -> str:
    value = payload.get("error") or payload.get("output") or "unknown RunPod error"
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)
