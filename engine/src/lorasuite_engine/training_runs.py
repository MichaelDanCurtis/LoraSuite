from __future__ import annotations

import hashlib
import http.client
import json
import mimetypes
import os
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import certifi
from pydantic import BaseModel, Field

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.models import DatasetSnapshotStatus, new_id, utc_now
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import get_training_target_profile


DIRECT_UPLOAD_LIMIT_BYTES = 150_000_000
SIGNED_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
ARTIFACT_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
ARTIFACT_DOWNLOAD_MAX_REDIRECTS = 5
_PROCESS_LOCKS: dict[str, RLock] = {}
_PROCESS_LOCKS_LOCK = RLock()


TrainingRunStatus = Literal[
    "queued",
    "uploading",
    "dataset_ready",
    "in_queue",
    "running",
    "stopped",
    "downloading",
    "completed",
    "failed",
    "canceled",
]


class TrainingArtifact(BaseModel):
    kind: str
    name: str
    remote_url: str
    local_path: Path | None = None
    step: int | None = None
    prompt: str | None = None
    sample_index: int | None = None


class TrainingUploadCheckpoint(BaseModel):
    relative_path: str
    provider_filename: str
    size_bytes: int
    sha256: str
    transport: str = "direct"
    uploaded_at: Any = Field(default_factory=utc_now)


class TrainingRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("training_run"))
    provider: str = "runcomfy"
    snapshot_id: str
    dataset_fingerprint: str
    parent_snapshot_id: str | None = None
    parent_dataset_fingerprint: str | None = None
    improvement_request_id: str | None = None
    parent_artifact_id: str | None = None
    parent_checkpoint_sha256: str | None = None
    config_digest: str
    config_file: str
    gpu_type: Literal["ADA_80_PLUS", "HOPPER_141"] = "ADA_80_PLUS"
    status: TrainingRunStatus = "queued"
    dataset_id: str | None = None
    dataset_name: str | None = None
    upload_manifest_digest: str | None = None
    uploaded_files: list[TrainingUploadCheckpoint] = Field(default_factory=list)
    provider_job_id: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    progress_percent: float = 0.0
    progress_message: str = "Queued"
    export_path: Path
    artifact_dir: Path | None = None
    artifacts: list[TrainingArtifact] = Field(default_factory=list)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class TrainingProvider(Protocol):
    def create_dataset(self, name: str) -> dict[str, Any]: ...
    def upload_file(self, dataset_id: str, path: Path) -> dict[str, Any]: ...
    def dataset_status(self, dataset_id: str) -> dict[str, Any]: ...
    def submit_job(self, config_file: str, gpu_type: str) -> dict[str, Any]: ...
    def job_status(self, job_id: str) -> dict[str, Any]: ...
    def job_result(self, job_id: str) -> dict[str, Any]: ...
    def cancel_job(self, job_id: str) -> dict[str, Any]: ...
    def resume_job(self, job_id: str) -> dict[str, Any]: ...
    def download(self, url: str, destination: Path) -> None: ...


@dataclass(frozen=True)
class _UploadFilePlan:
    path: Path
    relative_path: str
    provider_filename: str
    size_bytes: int
    sha256: str


class RunComfyProvider:
    base_url = "https://trainer-api.runcomfy.net"

    def __init__(self, token: str):
        token = token.strip()
        if not token:
            raise ValueError("RunComfy API token is required")
        self.token = token
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def create_dataset(self, name: str) -> dict[str, Any]:
        return self._json("POST", "/prod/v1/trainers/datasets", {"name": name})

    def upload_file(self, dataset_id: str, path: Path) -> dict[str, Any]:
        size = path.stat().st_size
        if size > DIRECT_UPLOAD_LIMIT_BYTES:
            return self._upload_signed_file(dataset_id, path, size)
        boundary = f"----LoraSuite{new_id('upload').replace('_', '')}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        body = prefix + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self._json(
            "POST",
            f"/prod/v1/trainers/datasets/{dataset_id}/upload",
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def _upload_signed_file(self, dataset_id: str, path: Path, size: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for _attempt in range(2):
            payload = self._json(
                "POST",
                f"/prod/v1/trainers/datasets/{dataset_id}/get-upload-endpoint",
                {"filenameToByteSize": {path.name: size}},
            )
            uploads = payload.get("uploads")
            upload = uploads.get(path.name) if isinstance(uploads, dict) else None
            if not isinstance(upload, dict):
                raise RuntimeError(f"RunComfy did not return a signed upload for {path.name}")
            url = str(upload.get("upload_url") or "").strip()
            method = str(upload.get("method") or "PUT").upper()
            headers = upload.get("headers")
            if not url or method != "PUT" or not isinstance(headers, dict):
                raise RuntimeError(f"RunComfy returned an invalid signed upload contract for {path.name}")
            try:
                self._put_signed_file(url, path, headers)
                return {
                    "id": dataset_id,
                    "filename": path.name,
                    "bytes": size,
                    "object": "file",
                    "upload": "signed",
                }
            except RuntimeError as error:
                last_error = error
        raise RuntimeError(f"RunComfy signed upload failed for {path.name}: {last_error}")

    def _put_signed_file(self, url: str, path: Path, headers: dict[str, Any]) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise RuntimeError("RunComfy returned an unsafe signed upload URL")
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection_kwargs: dict[str, Any] = {"timeout": 120}
        if parsed.scheme == "https":
            connection_kwargs["context"] = self.ssl_context
        connection = connection_type(parsed.hostname, parsed.port, **connection_kwargs)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        try:
            connection.putrequest("PUT", target)
            for name, value in headers.items():
                normalized = str(name).strip()
                if not normalized or normalized.lower() in {"authorization", "cookie", "host", "content-length"}:
                    continue
                connection.putheader(normalized, str(value))
            connection.putheader("Content-Length", str(path.stat().st_size))
            connection.endheaders()
            with path.open("rb") as stream:
                while chunk := stream.read(SIGNED_UPLOAD_CHUNK_BYTES):
                    connection.send(chunk)
            response = connection.getresponse()
            detail = response.read(16_384).decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"signed storage returned HTTP {response.status}: {detail or response.reason}")
        except (OSError, http.client.HTTPException, TimeoutError) as error:
            raise RuntimeError(f"signed storage request failed: {error}") from error
        finally:
            connection.close()

    def dataset_status(self, dataset_id: str) -> dict[str, Any]:
        return self._json("GET", f"/prod/v1/trainers/datasets/{dataset_id}/status")

    def submit_job(self, config_file: str, gpu_type: str) -> dict[str, Any]:
        return self._json(
            "POST",
            "/prod/v1/trainers/ai-toolkit/jobs",
            {
                "config_file_format": "yaml",
                "config_file": config_file,
                "gpu_type": gpu_type,
                "gpu_count": 1,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/prod/v1/trainers/ai-toolkit/jobs/{job_id}/status")

    def job_result(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/prod/v1/trainers/ai-toolkit/jobs/{job_id}/result")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._json("POST", f"/prod/v1/trainers/ai-toolkit/jobs/{job_id}/cancel", {})

    def resume_job(self, job_id: str) -> dict[str, Any]:
        return self._json("POST", f"/prod/v1/trainers/ai-toolkit/jobs/{job_id}/resume", {})

    def download(self, url: str, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f".{destination.name}.{new_id('download')}.part")
        current_url = url
        try:
            for redirect_count in range(ARTIFACT_DOWNLOAD_MAX_REDIRECTS + 1):
                parsed = urlparse(current_url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise RuntimeError("RunComfy returned an unsafe artifact URL")
                try:
                    connection = http.client.HTTPSConnection(
                        parsed.hostname,
                        parsed.port,
                        timeout=120,
                        context=self.ssl_context,
                    )
                except (OSError, ValueError) as error:
                    raise RuntimeError(f"artifact connection failed: {error}") from error
                target = parsed.path or "/"
                if parsed.query:
                    target = f"{target}?{parsed.query}"
                headers = {"Accept": "application/octet-stream"}
                if parsed.hostname.lower() == urlparse(self.base_url).hostname:
                    headers["Authorization"] = f"Bearer {self.token}"
                try:
                    connection.request("GET", target, headers=headers)
                    response = connection.getresponse()
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.getheader("Location")
                        response.read()
                        if not location:
                            raise RuntimeError("artifact redirect omitted its destination")
                        if redirect_count >= ARTIFACT_DOWNLOAD_MAX_REDIRECTS:
                            raise RuntimeError("artifact download exceeded the redirect limit")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status < 200 or response.status >= 300:
                        detail = response.read(16_384).decode("utf-8", errors="replace")
                        raise RuntimeError(f"artifact host returned HTTP {response.status}: {detail or response.reason}")
                    expected = response.getheader("Content-Length")
                    expected_bytes = int(expected) if expected and expected.isdigit() else None
                    written = 0
                    with partial.open("wb") as stream:
                        while chunk := response.read(ARTIFACT_DOWNLOAD_CHUNK_BYTES):
                            stream.write(chunk)
                            written += len(chunk)
                    if expected_bytes is not None and written != expected_bytes:
                        raise RuntimeError(f"artifact download was truncated: expected {expected_bytes} bytes, received {written}")
                    os.replace(partial, destination)
                    return
                except (OSError, http.client.HTTPException, TimeoutError) as error:
                    raise RuntimeError(f"artifact download failed: {error}") from error
                finally:
                    connection.close()
            raise RuntimeError("artifact download exceeded the redirect limit")
        finally:
            partial.unlink(missing_ok=True)

    def _json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        body = raw_body
        if body is None and payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": content_type,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=120, context=self.ssl_context) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_http_error(error)) from error


class TrainingRunService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: Callable[[str], TrainingProvider] = RunComfyProvider,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory
        self.sleep = sleep

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "training_runs.json"

    def list_runs(self, snapshot_id: str | None = None) -> list[TrainingRun]:
        runs = self._read_runs().values()
        if snapshot_id:
            runs = (run for run in runs if run.snapshot_id == snapshot_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> TrainingRun | None:
        return self._read_runs().get(run_id)

    def create_run(
        self,
        *,
        snapshot_id: str,
        config_file: str,
        gpu_type: Literal["ADA_80_PLUS", "HOPPER_141"],
    ) -> TrainingRun:
        snapshot = DatasetCompilerService(self.vault_root).get_snapshot(snapshot_id)
        is_video_snapshot = False
        recovered = None
        if snapshot is None:
            from lorasuite_engine.video_dataset import VideoDatasetService

            snapshot = VideoDatasetService(self.vault_root).get_snapshot(snapshot_id)
            is_video_snapshot = snapshot is not None
        if snapshot is None:
            recovered = RecoveredDatasetService(self.vault_root).find_by_snapshot_id(
                snapshot_id
            )
        if snapshot is None and recovered is None:
            raise KeyError(snapshot_id)
        if recovered is not None:
            if not recovered.ready or not recovered.source_available:
                raise ValueError("recovered dataset export must pass integrity verification before cloud training")
            profile = get_training_target_profile(recovered.training_target.profile_id)
            if profile.provider != "runcomfy" or profile.modality not in {"image", "video"}:
                raise ValueError("recovered dataset target is not executable by RunComfy")
            export_path = recovered.export_path
            fingerprint = recovered.fingerprint
            run_snapshot_id = recovered.snapshot_id
            lineage = recovered.revision_lineage
            is_video_snapshot = recovered.modality == "video"
        else:
            if str(snapshot.status) not in {DatasetSnapshotStatus.EXPORTED.value, "exported"} or not snapshot.export_path:
                raise ValueError("export the frozen dataset before starting cloud training")
            export_path = Path(snapshot.export_path)
            fingerprint = snapshot.fingerprint or ""
            run_snapshot_id = snapshot.id
            lineage = RevisionLineage.from_snapshot(snapshot)
        if not export_path.is_dir():
            raise ValueError("exported dataset folder is no longer available")
        config_file = config_file.strip()
        if not config_file:
            raise ValueError("AI Toolkit YAML configuration is required")
        if "{dataset_name}" not in config_file:
            raise ValueError("training YAML must contain the {dataset_name} placeholder")
        if is_video_snapshot:
            profile = profile if recovered is not None else get_training_target_profile(snapshot.target_profile_id)
            if not profile.ready or profile.modality != "video":
                raise ValueError("the selected video training target is not ready for cloud submission")
            _validate_video_training_config(config_file, profile.model_family)
        digest = hashlib.sha256(config_file.encode("utf-8")).hexdigest()
        runs = self._read_runs()
        existing = next(
            (
                run
                for run in runs.values()
                if run.dataset_fingerprint == fingerprint
                and run.config_digest == digest
                and run.gpu_type == gpu_type
                and run.status not in {"failed", "canceled"}
            ),
            None,
        )
        if existing:
            return existing
        run = TrainingRun(
            snapshot_id=run_snapshot_id,
            dataset_fingerprint=fingerprint,
            **lineage.model_dump(),
            config_digest=digest,
            config_file=config_file,
            gpu_type=gpu_type,
            export_path=export_path,
        )
        runs[run.id] = run
        self._write_runs(runs)
        return run

    def process_run(self, run_id: str, token: str) -> TrainingRun:
        with self._process_lock(run_id):
            return self._process_run(run_id, token)

    def _process_run(self, run_id: str, token: str) -> TrainingRun:
        provider = self.provider_factory(token)
        try:
            run = self._require_run(run_id)
            if run.status in {"completed", "canceled", "stopped"}:
                return run
            if not run.provider_job_id:
                upload_plan = _upload_plan(run.export_path)
                upload_digest = _upload_manifest_digest(upload_plan)
                if run.upload_manifest_digest is None:
                    if run.dataset_id:
                        raise RuntimeError(
                            "This RunComfy upload began before restart-safe file checkpoints were available. "
                            "Start a new training run to avoid mixing an unknown partial dataset."
                        )
                    run.upload_manifest_digest = upload_digest
                    self._save(
                        run,
                        status="uploading",
                        message=f"Prepared {len(upload_plan)} immutable upload files",
                    )
                elif run.upload_manifest_digest != upload_digest:
                    raise RuntimeError(
                        "The exported dataset changed after the RunComfy upload began. "
                        "Create a new frozen dataset version before retrying."
                    )
                _validate_upload_checkpoints(run.uploaded_files, upload_plan)

            if not run.dataset_id:
                dataset_name = _dataset_name(run)
                created = provider.create_dataset(dataset_name)
                run.dataset_id = str(created.get("id") or "")
                run.dataset_name = str(created.get("name") or dataset_name)
                if not run.dataset_id:
                    raise RuntimeError("RunComfy did not return a dataset id")
                self._save(run, status="uploading", message="Uploading dataset files")

            if not run.provider_job_id:
                completed = {
                    checkpoint.relative_path: checkpoint
                    for checkpoint in run.uploaded_files
                }
                run.error = None
                run.completed_at = None
                for entry in upload_plan:
                    if entry.relative_path in completed:
                        continue
                    result = provider.upload_file(run.dataset_id or "", entry.path)
                    transport = (
                        str(result.get("upload") or "direct")
                        if isinstance(result, dict)
                        else "direct"
                    )
                    run.uploaded_files.append(
                        TrainingUploadCheckpoint(
                            relative_path=entry.relative_path,
                            provider_filename=entry.provider_filename,
                            size_bytes=entry.size_bytes,
                            sha256=entry.sha256,
                            transport=transport,
                        )
                    )
                    completed[entry.relative_path] = run.uploaded_files[-1]
                    uploaded_count = len(completed)
                    run.progress_current = uploaded_count
                    run.progress_total = len(upload_plan)
                    run.progress_percent = round(
                        uploaded_count / max(len(upload_plan), 1) * 100,
                        1,
                    )
                    self._save(
                        run,
                        status="uploading",
                        message=f"Uploaded {uploaded_count} of {len(upload_plan)} files",
                    )
                self._save(
                    run,
                    status="uploading",
                    message=f"Dataset upload complete: {len(upload_plan)} files",
                )

            if not run.provider_job_id:
                dataset = self._wait_for_dataset(provider, run)
                run.dataset_name = str(dataset.get("name") or run.dataset_name or "")
                self._save(run, status="dataset_ready", message="Dataset ready; submitting training")
                config = run.config_file.replace("{dataset_name}", run.dataset_name)
                submitted = provider.submit_job(config, run.gpu_type)
                run.provider_job_id = str(submitted.get("id") or "")
                if not run.provider_job_id:
                    raise RuntimeError("RunComfy did not return a training job id")
                self._save(run, status="in_queue", message="Training queued")

            return self._wait_for_job(provider, run)
        except Exception as error:
            run = self._require_run(run_id)
            return self._save(run, status="failed", message="Training run failed", error=str(error))

    def refresh_run(self, run_id: str, token: str) -> TrainingRun:
        run = self._require_run(run_id)
        if run.status in {"completed", "canceled", "stopped"}:
            return run
        if run.status == "failed":
            self.prepare_retry(run_id)
        return self.process_run(run_id, token)

    def prepare_retry(self, run_id: str) -> TrainingRun:
        run = self._require_run(run_id)
        if run.status != "failed":
            return run
        run.error = None
        run.completed_at = None
        return self._save(
            run,
            status="uploading" if run.dataset_id else "queued",
            message="Retrying the persisted RunComfy run",
        )

    def resume_run(self, run_id: str, token: str) -> TrainingRun:
        run = self._require_run(run_id)
        if run.status != "stopped":
            raise ValueError("only a stopped RunComfy training job can be resumed")
        if not run.provider_job_id:
            raise ValueError("stopped RunComfy training run has no provider job id")
        provider = self.provider_factory(token)
        try:
            payload = provider.resume_job(run.provider_job_id)
            provider_status = str(payload.get("status") or "IN_QUEUE").upper()
            run.error = None
            run.completed_at = None
            next_status: TrainingRunStatus = "running" if provider_status == "RUNNING" else "in_queue"
            message = "Training resumed on RunComfy" if next_status == "running" else "Training resumed; waiting for RunComfy GPU"
            self._save(run, status=next_status, message=message)
            return self._wait_for_job(provider, run)
        except Exception as error:
            run = self._require_run(run_id)
            return self._save(run, status="failed", message="Training resume failed", error=str(error))

    def cancel_run(self, run_id: str, token: str) -> TrainingRun:
        run = self._require_run(run_id)
        if run.provider_job_id:
            self.provider_factory(token).cancel_job(run.provider_job_id)
        run.completed_at = utc_now()
        return self._save(run, status="canceled", message="Training canceled")

    def _wait_for_dataset(self, provider: TrainingProvider, run: TrainingRun) -> dict[str, Any]:
        for _ in range(300):
            payload = provider.dataset_status(run.dataset_id or "")
            status = str(payload.get("status") or "").upper()
            if status == "READY":
                return payload
            if status == "FAILED":
                raise RuntimeError(f"RunComfy dataset failed: {payload.get('error') or 'unknown error'}")
            self._save(run, status="uploading", message=f"Dataset {status.lower() or 'processing'}")
            self.sleep(2)
        raise TimeoutError("RunComfy dataset did not become ready within 10 minutes")

    def _wait_for_job(self, provider: TrainingProvider, run: TrainingRun) -> TrainingRun:
        for _ in range(4320):
            payload = provider.job_status(run.provider_job_id or "")
            status = str(payload.get("status") or "").upper()
            progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
            run.progress_current = int(progress.get("current_step") or 0)
            run.progress_total = int(progress.get("total_steps") or 0)
            run.progress_percent = float(progress.get("percent") or 0.0)
            if status == "IN_QUEUE":
                self._save(run, status="in_queue", message="Waiting for RunComfy GPU")
            elif status == "RUNNING":
                added = self._sync_available_artifacts(provider, run)
                exported = len([artifact for artifact in run.artifacts if artifact.local_path])
                message = (
                    f"Training on RunComfy · auto-exported {added} new preview artifact"
                    f"{'' if added == 1 else 's'}"
                    if added
                    else (
                        f"Training on RunComfy · {exported} preview artifact"
                        f"{'' if exported == 1 else 's'} exported"
                        if exported
                        else "Training on RunComfy · waiting for the first checkpoint preview"
                    )
                )
                self._save(run, status="running", message=message)
            elif status == "FAILED":
                self._sync_available_artifacts(provider, run)
                raise RuntimeError(f"RunComfy training failed: {payload.get('error') or 'unknown error'}")
            elif status == "CANCELED":
                self._sync_available_artifacts(provider, run)
                run.completed_at = utc_now()
                return self._save(run, status="canceled", message="Training canceled")
            elif status == "STOPPED":
                self._sync_available_artifacts(provider, run)
                if run.progress_total > 0 and run.progress_current < run.progress_total:
                    return self._save(
                        run,
                        status="stopped",
                        message=(
                            f"Training stopped at {run.progress_current} of {run.progress_total} steps; "
                            "resume from the latest RunComfy checkpoint"
                        ),
                    )
                return self._download_results(provider, run)
            self.sleep(10)
        raise TimeoutError("RunComfy training exceeded the 12 hour monitoring window")

    def _download_results(self, provider: TrainingProvider, run: TrainingRun) -> TrainingRun:
        self._save(run, status="downloading", message="Downloading training artifacts")
        payload = provider.job_result(run.provider_job_id or "")
        self._sync_available_artifacts(provider, run, payload=payload, strict=True)
        if not any(
            artifact.kind == "checkpoint" and artifact.local_path
            for artifact in run.artifacts
        ):
            raise RuntimeError("RunComfy stopped without producing a checkpoint")
        run.progress_percent = 100.0
        run.completed_at = utc_now()
        return self._save(run, status="completed", message="Training artifacts ready")

    def _sync_available_artifacts(
        self,
        provider: TrainingProvider,
        run: TrainingRun,
        *,
        payload: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> int:
        try:
            available = _artifact_urls(
                payload if payload is not None else provider.job_result(run.provider_job_id or "")
            )
        except Exception:
            if strict:
                raise
            return 0

        artifact_dir = self.vault_root / "training_artifacts" / run.id
        existing = {artifact.remote_url: artifact for artifact in run.artifacts}
        added = 0
        for artifact in available:
            known = existing.get(artifact.remote_url)
            if known is not None:
                known.step = artifact.step if artifact.step is not None else known.step
                known.prompt = artifact.prompt or known.prompt
                known.sample_index = (
                    artifact.sample_index
                    if artifact.sample_index is not None
                    else known.sample_index
                )
                if known.local_path and known.local_path.exists():
                    continue
                artifact = known
            destination = artifact_dir / artifact.kind / artifact.name
            try:
                provider.download(artifact.remote_url, destination)
            except Exception:
                if strict:
                    raise
                continue
            artifact.local_path = destination
            if known is None:
                run.artifacts.append(artifact)
                existing[artifact.remote_url] = artifact
            added += 1

        if any(artifact.local_path for artifact in run.artifacts):
            run.artifact_dir = artifact_dir
        return added

    def _require_run(self, run_id: str) -> TrainingRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _process_lock(self, run_id: str) -> RLock:
        key = f"{self.runs_path.resolve(strict=False)}::{run_id}"
        with _PROCESS_LOCKS_LOCK:
            return _PROCESS_LOCKS.setdefault(key, RLock())

    def _save(
        self,
        run: TrainingRun,
        *,
        status: TrainingRunStatus | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> TrainingRun:
        runs = self._read_runs()
        if status is not None:
            run.status = status
        if message is not None:
            run.progress_message = message
        if error is not None:
            run.error = error
            run.completed_at = utc_now()
        run.updated_at = utc_now()
        runs[run.id] = run
        self._write_runs(runs)
        return run

    def _read_runs(self) -> dict[str, TrainingRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            return {item["id"]: TrainingRun.model_validate(item) for item in payload.get("runs", [])}

    def _write_runs(self, runs: dict[str, TrainingRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(
                self.runs_path,
                {"version": 1, "runs": [run.model_dump(mode="json") for run in runs.values()]},
            )


def resolve_runcomfy_token(request_token: str | None) -> str:
    token = (request_token or os.environ.get("RUNCOMFY_TOKEN") or "").strip()
    if not token:
        raise ValueError("Enter a RunComfy token or set RUNCOMFY_TOKEN")
    return token


def _dataset_name(run: TrainingRun) -> str:
    return f"lorasuite-{run.dataset_fingerprint[:12]}-{run.config_digest[:8]}".lower()


def _upload_plan(export_path: Path) -> list[_UploadFilePlan]:
    root = Path(export_path).resolve()
    files = _training_files(root)
    provider_names: set[str] = set()
    plan: list[_UploadFilePlan] = []
    for path in files:
        resolved = path.resolve()
        relative_path = resolved.relative_to(root).as_posix()
        provider_filename = resolved.name
        if provider_filename in provider_names:
            raise ValueError(
                f"RunComfy requires unique training filenames; duplicate: {provider_filename}"
            )
        provider_names.add(provider_filename)
        plan.append(
            _UploadFilePlan(
                path=resolved,
                relative_path=relative_path,
                provider_filename=provider_filename,
                size_bytes=resolved.stat().st_size,
                sha256=_sha256_file(resolved),
            )
        )
    return plan


def _upload_manifest_digest(plan: list[_UploadFilePlan]) -> str:
    payload = [
        {
            "relative_path": entry.relative_path,
            "provider_filename": entry.provider_filename,
            "size_bytes": entry.size_bytes,
            "sha256": entry.sha256,
        }
        for entry in plan
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_upload_checkpoints(
    checkpoints: list[TrainingUploadCheckpoint],
    plan: list[_UploadFilePlan],
) -> None:
    expected = {entry.relative_path: entry for entry in plan}
    seen: set[str] = set()
    for checkpoint in checkpoints:
        entry = expected.get(checkpoint.relative_path)
        if entry is None:
            raise RuntimeError(
                f"RunComfy upload checkpoint no longer exists in the export: {checkpoint.relative_path}"
            )
        if checkpoint.relative_path in seen:
            raise RuntimeError(
                f"RunComfy upload checkpoint is duplicated: {checkpoint.relative_path}"
            )
        seen.add(checkpoint.relative_path)
        if (
            checkpoint.provider_filename != entry.provider_filename
            or checkpoint.size_bytes != entry.size_bytes
            or checkpoint.sha256 != entry.sha256
        ):
            raise RuntimeError(
                f"RunComfy upload checkpoint no longer matches the frozen file: {checkpoint.relative_path}"
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _training_files(export_path: Path) -> list[Path]:
    manifest_path = Path(export_path) / "manifest.json"
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        entries = payload.get("files") if isinstance(payload, dict) else None
        if isinstance(entries, list) and any(isinstance(item, dict) and "split" in item for item in entries):
            relative_paths = {
                str(item[key])
                for item in entries
                if isinstance(item, dict) and item.get("split") == "train"
                for key in ("video", "caption")
                if item.get(key)
            }
            files = sorted(
                path
                for relative in relative_paths
                if (path := (Path(export_path) / relative).resolve()).is_file()
                and Path(export_path).resolve() in path.parents
            )
            if not files:
                raise ValueError("exported video dataset contains no training split files")
            return files
    media_dir = next(
        (candidate for name in ("images", "videos") if (candidate := Path(export_path) / name).is_dir()),
        None,
    )
    files = sorted(path for path in media_dir.iterdir() if path.is_file()) if media_dir else []
    if not files:
        raise ValueError("exported dataset contains no training files")
    return files


def _validate_video_training_config(config_file: str, model_family: str) -> None:
    if model_family == "wan22_14b_t2v":
        if not re.search(r"\barch\s*:\s*['\"]?wan22_14b['\"]?", config_file):
            raise ValueError("WAN 2.2 video YAML must use arch: wan22_14b")
        frame_counts = [int(value) for value in re.findall(r"\bnum_frames\s*:\s*(\d+)", config_file)]
        if not frame_counts or min(frame_counts) <= 1:
            raise ValueError("WAN 2.2 video YAML must train and sample more than one frame")


def _artifact_urls(payload: dict[str, Any]) -> list[TrainingArtifact]:
    root = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    found: list[TrainingArtifact] = []
    groups = (("checkpoint", root.get("checkpoints")), ("sample", root.get("samples")))
    for kind, values in groups:
        for index, value in enumerate(values or [], start=1):
            if not isinstance(value, dict) or not value.get("path"):
                continue
            url = str(value["path"])
            found.append(
                TrainingArtifact(
                    kind=kind,
                    name=_artifact_name(url, kind, index),
                    remote_url=url,
                    step=_artifact_int(value.get("step")),
                    prompt=str(value["prompt"]) if value.get("prompt") else None,
                    sample_index=_artifact_int(value.get("sample_index")),
                )
            )
    config = root.get("config")
    if isinstance(config, dict) and config.get("path"):
        url = str(config["path"])
        found.append(TrainingArtifact(kind="config", name=_artifact_name(url, "config", 1), remote_url=url))
    return found


def _artifact_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _artifact_name(url: str, kind: str, index: int) -> str:
    name = Path(urlparse(url).path).name or f"{kind}-{index}"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = error.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return f"RunComfy HTTP {error.code}: {detail or error.reason}"
    return f"RunComfy request failed: {error}"
