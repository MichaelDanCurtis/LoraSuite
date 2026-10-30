from __future__ import annotations

import json
import os
import ssl
import hashlib
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.storage import atomic_write_json, json_file_lock


RunPodRunStatus = Literal[
    "queued",
    "in_queue",
    "running",
    "completed",
    "failed",
    "canceled",
    "timed_out",
]


class RunPodRunArtifact(BaseModel):
    kind: str
    name: str
    remote_url: str | None = None
    volume_path: str | None = None
    local_path: Path | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    group_id: str | None = None


class RunPodTrainingRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_run"))
    provider: str = "runpod"
    bundle_path: Path
    bundle_fingerprint: str
    config_digest: str = ""
    modality: Literal["image", "video", "voice", "audio_visual"]
    training_target_profile_id: str
    action: Literal["train_lora", "run_id_lora"] = "train_lora"
    endpoint_id: str
    provider_job_id: str | None = None
    snapshot_id: str | None = None
    project_id: str | None = None
    parent_snapshot_id: str | None = None
    parent_dataset_fingerprint: str | None = None
    improvement_request_id: str | None = None
    parent_artifact_id: str | None = None
    parent_checkpoint_sha256: str | None = None
    status: RunPodRunStatus = "queued"
    progress_message: str = "Ready to submit"
    delay_time_ms: int | None = None
    execution_time_ms: int | None = None
    artifacts: list[RunPodRunArtifact] = Field(default_factory=list)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class RunPodPreflightCheck(BaseModel):
    id: str
    passed: bool
    detail: str
    size_bytes: int | None = None


class RunPodPreflightGpu(BaseModel):
    available: bool = False
    name: str = ""
    memory_gb: float = 0.0
    driver_version: str = ""


class RunPodPreflightReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_preflight"))
    provider: str = "runpod"
    bundle_path: Path
    bundle_fingerprint: str
    config_digest: str = ""
    training_target_profile_id: str
    endpoint_id: str
    worker_contract_version: int = 1
    ready: bool = False
    volume_root: str = ""
    platform: str = ""
    python_version: str = ""
    gpu: RunPodPreflightGpu = Field(default_factory=RunPodPreflightGpu)
    checks: list[RunPodPreflightCheck] = Field(default_factory=list)
    checked_at: Any = Field(default_factory=utc_now)


class RunPodProvider(Protocol):
    def submit(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def run_sync(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def status(self, endpoint_id: str, job_id: str) -> dict[str, Any]: ...
    def cancel(self, endpoint_id: str, job_id: str) -> dict[str, Any]: ...


class RunPodArtifactDownloader(Protocol):
    def download_url(self, url: str, destination: Path) -> None: ...
    def download_volume(self, bucket: str, key: str, destination: Path) -> None: ...


class RunPodS3ArtifactDownloader:
    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        import boto3
        from botocore.config import Config

        resolved_access = (access_key or os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
        resolved_secret = (secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
        if not resolved_access or not resolved_secret:
            raise ValueError("RunPod S3 access key and secret are required")
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.client = boto3.client(
            "s3",
            aws_access_key_id=resolved_access,
            aws_secret_access_key=resolved_secret,
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(
                retries={"total_max_attempts": 10, "mode": "standard"},
                connect_timeout=15,
                read_timeout=120,
            ),
        )

    def download_url(self, url: str, destination: Path) -> None:
        request = Request(url, headers={"Accept": "application/octet-stream"})
        with urlopen(request, timeout=300, context=self.ssl_context) as response:
            with destination.open("wb") as handle:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    handle.write(chunk)

    def download_volume(self, bucket: str, key: str, destination: Path) -> None:
        self.client.download_file(bucket, key, str(destination))


class RunPodServerlessProvider:
    base_url = "https://api.runpod.ai/v2"

    def __init__(self, token: str):
        token = token.strip()
        if not token:
            raise ValueError("RunPod API key is required")
        self.token = token
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def submit(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", f"/{endpoint_id}/run", payload)

    def run_sync(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", f"/{endpoint_id}/runsync?wait=300000", payload, timeout=320)

    def status(self, endpoint_id: str, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/{endpoint_id}/status/{job_id}")

    def cancel(self, endpoint_id: str, job_id: str) -> dict[str, Any]:
        return self._json("POST", f"/{endpoint_id}/cancel/{job_id}", {})

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None, *, timeout: int = 120) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=timeout, context=self.ssl_context) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_http_error(error)) from error


class RunPodTrainingRunService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: Callable[[str], RunPodProvider] = RunPodServerlessProvider,
        downloader_factory: Callable[..., RunPodArtifactDownloader] = RunPodS3ArtifactDownloader,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory
        self.downloader_factory = downloader_factory

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "runpod_training_runs.json"

    @property
    def preflight_reports_path(self) -> Path:
        return self.vault_root / "runpod_preflight_reports.json"

    def list_preflight_reports(
        self,
        *,
        bundle_path: Path | None = None,
        endpoint_id: str | None = None,
    ) -> list[RunPodPreflightReport]:
        reports = self._read_preflight_reports().values()
        if bundle_path is not None:
            normalized = Path(bundle_path).expanduser().resolve(strict=False)
            reports = (report for report in reports if report.bundle_path == normalized)
        if endpoint_id:
            endpoint = endpoint_id.strip()
            reports = (report for report in reports if report.endpoint_id == endpoint)
        return sorted(reports, key=lambda report: report.checked_at, reverse=True)

    def preflight(self, *, bundle_path: Path, endpoint_id: str, token: str) -> RunPodPreflightReport:
        bundle = Path(bundle_path).expanduser().resolve(strict=False)
        manifest = _bundle_manifest(bundle)
        if manifest.get("ready") is not True:
            raise ValueError("RunPod bundle is not trainer-ready")
        endpoint = endpoint_id.strip()
        if not endpoint:
            raise ValueError("RunPod Serverless endpoint ID is required")
        try:
            source_payload = json.loads((bundle / "runpod_input.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("RunPod bundle input contract is unreadable") from error
        source_input = source_payload.get("input") if isinstance(source_payload, dict) else None
        if not isinstance(source_input, dict) or not isinstance(source_input.get("requirements"), dict):
            raise ValueError("RunPod bundle does not contain endpoint requirements")
        config_digest = _validate_bundle_config_digest(bundle, manifest, source_input)
        payload = {
            "input": {
                **source_input,
                "action": "preflight",
            },
            "policy": {"executionTimeout": 120_000, "ttl": 600_000},
        }
        response = self.provider_factory(token).run_sync(endpoint, payload)
        if str(response.get("status") or "").upper() != "COMPLETED":
            raise RuntimeError(f"RunPod preflight did not complete: {str(response.get('status') or 'unknown')}")
        output = response.get("output")
        preflight = output.get("preflight") if isinstance(output, dict) else None
        if (
            not isinstance(output, dict)
            or output.get("status") != "success"
            or output.get("bundle_format") != "lorasuite-runpod-v1"
            or output.get("worker_contract_version") != 1
            or not isinstance(preflight, dict)
        ):
            raise RuntimeError("RunPod endpoint does not implement the LoraSuite preflight contract")
        if str(preflight.get("config_digest") or "") != config_digest:
            raise RuntimeError("RunPod endpoint did not verify the submitted training configuration")
        checks_payload = preflight.get("checks")
        if not isinstance(checks_payload, list):
            raise RuntimeError("RunPod endpoint returned an invalid preflight report")
        checks = [RunPodPreflightCheck.model_validate(item) for item in checks_payload]
        fingerprint = str(manifest.get("fingerprint") or "")
        profile_id = str(manifest.get("training_target_profile_id") or "")
        if not fingerprint or not profile_id:
            raise ValueError("RunPod bundle provenance is incomplete")
        report = RunPodPreflightReport(
            bundle_path=bundle,
            bundle_fingerprint=fingerprint,
            config_digest=config_digest,
            training_target_profile_id=profile_id,
            endpoint_id=endpoint,
            ready=bool(preflight.get("ready")) and bool(checks) and all(check.passed for check in checks),
            volume_root=str(preflight.get("volume_root") or ""),
            platform=str(preflight.get("platform") or ""),
            python_version=str(preflight.get("python_version") or ""),
            gpu=RunPodPreflightGpu.model_validate(preflight.get("gpu") or {}),
            checks=checks,
        )
        reports = self._read_preflight_reports()
        reports = {
            report_id: candidate
            for report_id, candidate in reports.items()
            if not (
                candidate.bundle_fingerprint == fingerprint
                and candidate.training_target_profile_id == profile_id
                and candidate.endpoint_id == endpoint
            )
        }
        reports[report.id] = report
        self._write_preflight_reports(reports)
        return report

    def list_runs(self, bundle_path: Path | None = None) -> list[RunPodTrainingRun]:
        runs = self._read().values()
        if bundle_path is not None:
            normalized = Path(bundle_path).expanduser().resolve(strict=False)
            runs = (run for run in runs if run.bundle_path == normalized)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> RunPodTrainingRun | None:
        return self._read().get(run_id)

    def create_run(self, *, bundle_path: Path, endpoint_id: str) -> RunPodTrainingRun:
        bundle = Path(bundle_path).expanduser().resolve(strict=False)
        manifest = _bundle_manifest(bundle)
        if manifest.get("ready") is not True:
            raise ValueError("RunPod bundle is not trainer-ready")
        endpoint = endpoint_id.strip()
        if not endpoint:
            raise ValueError("RunPod Serverless endpoint ID is required")
        input_path = bundle / "runpod_input.json"
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("RunPod bundle input contract is unreadable") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("input"), dict):
            raise ValueError("RunPod bundle input contract must contain input")
        action = str(payload["input"].get("action") or "")
        if action not in {"train_lora", "run_id_lora"}:
            raise ValueError("RunPod bundle action is unsupported")
        source = manifest.get("source_manifest") if isinstance(manifest.get("source_manifest"), dict) else {}
        fingerprint = str(manifest.get("fingerprint") or "")
        profile_id = str(manifest.get("training_target_profile_id") or "")
        if not fingerprint or not profile_id:
            raise ValueError("RunPod bundle provenance is incomplete")
        config_digest = _validate_bundle_config_digest(bundle, manifest, payload["input"])
        runs = self._read()
        existing = next((
            run for run in runs.values()
            if run.bundle_fingerprint == fingerprint
            and run.training_target_profile_id == profile_id
            and run.endpoint_id == endpoint
            and run.status not in {"failed", "canceled", "timed_out"}
        ), None)
        if existing:
            return existing
        lineage = RevisionLineage.from_source_manifest(source)
        run = RunPodTrainingRun(
            bundle_path=bundle,
            bundle_fingerprint=fingerprint,
            config_digest=config_digest,
            modality=str(manifest.get("modality")),
            training_target_profile_id=profile_id,
            action=action,
            endpoint_id=endpoint,
            snapshot_id=_first_string(source, "dataset_snapshot_id", "snapshot_id", "video_snapshot_id"),
            project_id=_first_string(source, "project_id", "character_project_id"),
            **lineage.model_dump(),
        )
        runs[run.id] = run
        self._write(runs)
        return run

    def submit_run(self, run_id: str, token: str) -> RunPodTrainingRun:
        run = self._require(run_id)
        if run.provider_job_id:
            return self.refresh_run(run_id, token)
        report = next((
            candidate
            for candidate in self.list_preflight_reports(bundle_path=run.bundle_path, endpoint_id=run.endpoint_id)
            if candidate.ready
            and candidate.bundle_fingerprint == run.bundle_fingerprint
            and candidate.config_digest == run.config_digest
            and candidate.training_target_profile_id == run.training_target_profile_id
        ), None)
        if report is None:
            raise ValueError("Verify this RunPod endpoint against the current bundle before launch")
        payload = json.loads((run.bundle_path / "runpod_input.json").read_text(encoding="utf-8"))
        manifest = _bundle_manifest(run.bundle_path)
        current_digest = _validate_bundle_config_digest(run.bundle_path, manifest, payload.get("input"))
        if current_digest != run.config_digest:
            raise ValueError("RunPod bundle configuration changed after the run was created; recreate the run")
        try:
            result = self.provider_factory(token).submit(run.endpoint_id, payload)
            job_id = str(result.get("id") or "")
            if not job_id:
                raise RuntimeError("RunPod did not return a job ID")
            run.provider_job_id = job_id
            return self._save(run, status="in_queue", message="Waiting for a RunPod worker")
        except Exception as error:
            return self._save(run, status="failed", message="RunPod submission failed", error=str(error))

    def refresh_run(self, run_id: str, token: str) -> RunPodTrainingRun:
        run = self._require(run_id)
        if run.status in {"completed", "failed", "canceled", "timed_out"}:
            return run
        if not run.provider_job_id:
            return self.submit_run(run_id, token)
        try:
            payload = self.provider_factory(token).status(run.endpoint_id, run.provider_job_id)
            run.delay_time_ms = _optional_int(payload.get("delayTime"))
            run.execution_time_ms = _optional_int(payload.get("executionTime"))
            status = str(payload.get("status") or "").upper()
            if status == "IN_QUEUE":
                return self._save(run, status="in_queue", message=_progress(payload, "Waiting for a RunPod worker"))
            if status in {"IN_PROGRESS", "RUNNING"}:
                return self._save(run, status="running", message=_progress(payload, "Training on RunPod"))
            if status == "COMPLETED":
                output = payload.get("output")
                if not isinstance(output, dict) or output.get("status") != "success":
                    return self._save(run, status="failed", message="RunPod worker returned an invalid completion envelope", error=_error(payload))
                if str(output.get("fingerprint") or "") != run.bundle_fingerprint:
                    return self._save(run, status="failed", message="RunPod artifact provenance failed", error="Worker fingerprint does not match the submitted bundle")
                if str(output.get("config_digest") or "") != run.config_digest:
                    return self._save(run, status="failed", message="RunPod configuration provenance failed", error="Worker configuration digest does not match the submitted bundle")
                run.artifacts = _artifacts(output)
                run.completed_at = utc_now()
                message = f"Training completed with {len(run.artifacts)} artifact(s)"
                if not run.artifacts:
                    message = "RunPod completed but returned no artifact contract"
                return self._save(run, status="completed", message=message)
            if status in {"CANCELLED", "CANCELED"}:
                run.completed_at = utc_now()
                return self._save(run, status="canceled", message="RunPod training canceled")
            if status == "TIMED_OUT":
                run.completed_at = utc_now()
                return self._save(run, status="timed_out", message="RunPod training timed out", error=_error(payload))
            if status == "FAILED":
                return self._save(run, status="failed", message="RunPod training failed", error=_error(payload))
            return self._save(run, message=f"RunPod status: {status.lower() or 'unknown'}")
        except Exception as error:
            return self._save(run, status="failed", message="RunPod status check failed", error=str(error))

    def cancel_run(self, run_id: str, token: str) -> RunPodTrainingRun:
        run = self._require(run_id)
        if run.provider_job_id and run.status not in {"completed", "failed", "canceled", "timed_out"}:
            self.provider_factory(token).cancel(run.endpoint_id, run.provider_job_id)
        run.completed_at = utc_now()
        return self._save(run, status="canceled", message="RunPod training canceled")

    def download_artifacts(
        self,
        run_id: str,
        *,
        output_dir: Path,
        volume_id: str,
        endpoint_url: str,
        region: str,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> RunPodTrainingRun:
        run = self._require(run_id)
        if run.status != "completed":
            raise ValueError("RunPod training must complete before downloading artifacts")
        if not run.artifacts:
            raise ValueError("RunPod completed without artifact descriptors")
        bucket = volume_id.strip()
        endpoint = endpoint_url.strip()
        datacenter = region.strip()
        if not bucket or not endpoint or not datacenter:
            raise ValueError("Network volume ID, S3 endpoint, and datacenter are required")
        destination_root = Path(output_dir).expanduser().resolve(strict=False)
        destination_root.mkdir(parents=True, exist_ok=True)
        downloader = self.downloader_factory(
            endpoint_url=endpoint,
            region=datacenter,
            access_key=access_key,
            secret_key=secret_key,
        )
        for index, artifact in enumerate(run.artifacts, start=1):
            filename = _safe_artifact_name(artifact.name, index)
            group = _safe_group_name(artifact.group_id)
            destination = destination_root / artifact.kind / group / filename if group else destination_root / artifact.kind / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=destination.parent, prefix=f".{filename}.", delete=False) as handle:
                temporary = Path(handle.name)
            try:
                try:
                    if artifact.remote_url:
                        downloader.download_url(artifact.remote_url, temporary)
                    elif artifact.volume_path:
                        downloader.download_volume(bucket, _volume_key(artifact.volume_path), temporary)
                    else:
                        raise ValueError(f"artifact has no downloadable location: {artifact.name}")
                    _verify_download(temporary, artifact)
                    temporary.replace(destination)
                except Exception as error:
                    raise RuntimeError(f"RunPod artifact download failed for {artifact.name}: {error}") from error
            finally:
                if temporary.exists():
                    temporary.unlink()
            artifact.local_path = destination
        return self._save(run, message=f"Downloaded {len(run.artifacts)} RunPod artifact(s)")

    def _require(self, run_id: str) -> RunPodTrainingRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _save(
        self,
        run: RunPodTrainingRun,
        *,
        status: RunPodRunStatus | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> RunPodTrainingRun:
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

    def _read(self) -> dict[str, RunPodTrainingRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            try:
                payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {item["id"]: RunPodTrainingRun.model_validate(item) for item in payload.get("runs", [])}

    def _write(self, runs: dict[str, RunPodTrainingRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {
                "version": 1,
                "runs": [run.model_dump(mode="json") for run in runs.values()],
            })

    def _read_preflight_reports(self) -> dict[str, RunPodPreflightReport]:
        with json_file_lock(self.preflight_reports_path):
            if not self.preflight_reports_path.exists():
                return {}
            try:
                payload = json.loads(self.preflight_reports_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {
                item["id"]: RunPodPreflightReport.model_validate(item)
                for item in payload.get("reports", [])
            }

    def _write_preflight_reports(self, reports: dict[str, RunPodPreflightReport]) -> None:
        with json_file_lock(self.preflight_reports_path):
            atomic_write_json(self.preflight_reports_path, {
                "version": 1,
                "reports": [report.model_dump(mode="json") for report in reports.values()],
            })


def resolve_runpod_token(request_token: str | None) -> str:
    token = (request_token or os.environ.get("RUNPOD_API_KEY") or "").strip()
    if not token:
        raise ValueError("Enter a RunPod API key or set RUNPOD_API_KEY")
    return token


def _bundle_manifest(bundle: Path) -> dict[str, Any]:
    path = bundle / "bundle_manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("RunPod bundle manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("created_by") != "LoraSuite" or payload.get("format") != "lorasuite-runpod-v1":
        raise ValueError("folder is not a LoraSuite RunPod bundle")
    return payload


def _validate_bundle_config_digest(
    bundle: Path,
    manifest: dict[str, Any],
    source_input: Any,
) -> str:
    if not isinstance(source_input, dict):
        raise ValueError("RunPod bundle input contract must contain input")
    manifest_digest = str(manifest.get("config_digest") or "").strip()
    input_digest = str(source_input.get("config_digest") or "").strip()
    if not manifest_digest or not input_digest:
        raise ValueError("RunPod bundle predates immutable config verification; recreate the bundle")
    if manifest_digest != input_digest:
        raise ValueError("RunPod bundle configuration provenance is inconsistent")
    config_value = source_input.get("config_path")
    if not isinstance(config_value, str) or not config_value.strip():
        raise ValueError("RunPod bundle configuration path is missing")
    config_name = Path(config_value).name
    if not config_name or config_name in {".", ".."}:
        raise ValueError("RunPod bundle configuration path is invalid")
    config_path = bundle / "config" / config_name
    if not config_path.is_file():
        raise ValueError("RunPod bundle configuration is missing")
    actual_digest = _sha256(config_path)
    if actual_digest != manifest_digest:
        raise ValueError("RunPod bundle configuration failed digest verification")
    return manifest_digest


def _artifacts(output: Any) -> list[RunPodRunArtifact]:
    root = output if isinstance(output, dict) else {}
    values = root.get("artifacts")
    if isinstance(values, dict):
        values = [
            {**item, "kind": kind}
            for kind, entries in values.items()
            for item in (entries if isinstance(entries, list) else [entries])
            if isinstance(item, dict)
        ]
    if not isinstance(values, list):
        return []
    found = []
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            continue
        remote_url = item.get("url") or item.get("remote_url")
        volume_path = item.get("path") or item.get("volume_path")
        name = str(item.get("name") or Path(str(volume_path or remote_url or f"artifact-{index}")).name)
        found.append(RunPodRunArtifact(
            kind=str(item.get("kind") or "artifact"),
            name=name,
            remote_url=str(remote_url) if remote_url else None,
            volume_path=str(volume_path) if volume_path else None,
            size_bytes=_optional_int(item.get("size_bytes")),
            sha256=str(item["sha256"]) if item.get("sha256") else None,
            group_id=str(item["group_id"]) if item.get("group_id") else None,
        ))
    return found


def _progress(payload: dict[str, Any], fallback: str) -> str:
    value = payload.get("progress")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def _error(payload: dict[str, Any]) -> str:
    value = payload.get("error") or payload.get("output") or "unknown RunPod error"
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    return next((str(payload[key]) for key in keys if payload.get(key)), None)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _volume_key(value: str) -> str:
    path = value.strip()
    for prefix in ("/runpod-volume/", "/workspace/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    path = path.lstrip("/")
    parts = Path(path).parts
    if not path or ".." in parts:
        raise ValueError("artifact volume path is unsafe")
    return "/".join(parts)


def _safe_artifact_name(value: str, index: int) -> str:
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        return f"artifact-{index}"
    return name


def _safe_group_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(character if character.isalnum() or character in {"-", "_", "."} else "_" for character in value)
    cleaned = cleaned.strip("._")
    return cleaned[:120] or None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_download(path: Path, artifact: RunPodRunArtifact) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"downloaded artifact is empty: {artifact.name}")
    if artifact.size_bytes is not None and path.stat().st_size != artifact.size_bytes:
        raise ValueError(f"downloaded artifact size mismatch: {artifact.name}")
    if artifact.sha256:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != artifact.sha256.lower():
            raise ValueError(f"downloaded artifact checksum mismatch: {artifact.name}")


def _http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = error.read().decode("utf-8", errors="replace")
        except OSError:
            detail = ""
        return f"RunPod request failed with HTTP {error.code}: {detail or error.reason}"
    return f"RunPod request failed: {error}"
