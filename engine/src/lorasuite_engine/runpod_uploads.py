from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

import boto3
import certifi
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock


class RunPodBundleUploadJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_upload"))
    provider: str = "runpod"
    bundle_path: Path
    bundle_fingerprint: str
    training_target_profile_id: str
    volume_id: str
    endpoint_url: str
    datacenter: str
    remote_prefix: str
    status: Literal["queued", "running", "complete", "failed"] = "queued"
    files_total: int = 0
    files_uploaded: int = 0
    bytes_total: int = 0
    bytes_uploaded: int = 0
    current_file: str | None = None
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class S3UploadClient(Protocol):
    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...
    def upload_file(self, Filename: str, Bucket: str, Key: str, *, Config: TransferConfig) -> None: ...


class RunPodS3Uploader:
    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
    ):
        self.client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            endpoint_url=endpoint_url,
            verify=certifi.where(),
            config=Config(
                retries={"total_max_attempts": 10, "mode": "standard"},
                connect_timeout=15,
                read_timeout=120,
                max_pool_connections=10,
            ),
        )

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return self.client.head_object(Bucket=Bucket, Key=Key)

    def upload_file(self, Filename: str, Bucket: str, Key: str, *, Config: TransferConfig) -> None:
        self.client.upload_file(Filename, Bucket, Key, Config=Config)


UploaderFactory = Callable[..., S3UploadClient]


class RunPodBundleUploadService:
    def __init__(self, vault_root: Path, *, uploader_factory: UploaderFactory = RunPodS3Uploader):
        self.vault_root = Path(vault_root)
        self.uploader_factory = uploader_factory

    @property
    def jobs_path(self) -> Path:
        return self.vault_root / "runpod_bundle_upload_jobs.json"

    def list_jobs(self, bundle_path: Path | None = None) -> list[RunPodBundleUploadJob]:
        jobs = self._read().values()
        if bundle_path is not None:
            normalized = Path(bundle_path).expanduser().resolve(strict=False)
            jobs = (job for job in jobs if job.bundle_path == normalized)
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def get_job(self, job_id: str) -> RunPodBundleUploadJob | None:
        return self._read().get(job_id)

    def create_job(
        self,
        *,
        bundle_path: Path,
        volume_id: str,
        endpoint_url: str,
        datacenter: str,
    ) -> RunPodBundleUploadJob:
        bundle = Path(bundle_path).expanduser().resolve(strict=False)
        manifest = _bundle_manifest(bundle)
        bucket = volume_id.strip()
        endpoint = endpoint_url.strip()
        region = datacenter.strip()
        if not bucket or not endpoint or not region:
            raise ValueError("Network volume ID, S3 endpoint, and datacenter are required")
        files = _bundle_files(bundle)
        if not files:
            raise ValueError("RunPod bundle contains no uploadable files")
        fingerprint = str(manifest.get("fingerprint") or "")
        profile_id = str(manifest.get("training_target_profile_id") or "")
        remote_prefix = _remote_prefix(manifest)
        if not fingerprint or not profile_id:
            raise ValueError("RunPod bundle provenance is incomplete")
        jobs = self._read()
        existing = next((
            job for job in jobs.values()
            if job.bundle_fingerprint == fingerprint
            and job.training_target_profile_id == profile_id
            and job.volume_id == bucket
            and job.endpoint_url == endpoint
            and job.datacenter == region
            and job.remote_prefix == remote_prefix
            and job.status in {"queued", "running", "complete"}
        ), None)
        if existing:
            return existing
        job = RunPodBundleUploadJob(
            bundle_path=bundle,
            bundle_fingerprint=fingerprint,
            training_target_profile_id=profile_id,
            volume_id=bucket,
            endpoint_url=endpoint,
            datacenter=region,
            remote_prefix=remote_prefix,
            files_total=len(files),
            bytes_total=sum(path.stat().st_size for path in files),
        )
        jobs[job.id] = job
        self._write(jobs)
        return job

    def resume_job(self, job_id: str) -> RunPodBundleUploadJob:
        job = self._require(job_id)
        if job.status == "complete":
            return job
        job.status = "queued"
        job.error = None
        job.completed_at = None
        job.updated_at = utc_now()
        self._save(job)
        return job

    def process_job(self, job_id: str, access_key: str | None, secret_key: str | None) -> RunPodBundleUploadJob:
        job = self._require(job_id)
        if job.status == "complete":
            return job
        files = _bundle_files(job.bundle_path)
        job.status = "running"
        job.files_total = len(files)
        job.bytes_total = sum(path.stat().st_size for path in files)
        job.files_uploaded = 0
        job.bytes_uploaded = 0
        job.error = None
        job.updated_at = utc_now()
        self._save(job)
        try:
            resolved_access, resolved_secret = _credentials(access_key, secret_key)
            uploader = self.uploader_factory(
                endpoint_url=job.endpoint_url,
                region=job.datacenter,
                access_key=resolved_access,
                secret_key=resolved_secret,
            )
            transfer = TransferConfig(
                multipart_threshold=8 * 1024 * 1024,
                multipart_chunksize=8 * 1024 * 1024,
                max_concurrency=4,
                use_threads=True,
            )
            for path in files:
                relative = path.relative_to(job.bundle_path).as_posix()
                key = str(PurePosixPath(job.remote_prefix) / relative)
                job.current_file = relative
                job.updated_at = utc_now()
                self._save(job)
                size = path.stat().st_size
                if not _remote_matches(uploader, job.volume_id, key, size):
                    uploader.upload_file(str(path), job.volume_id, key, Config=transfer)
                    if not _remote_matches(uploader, job.volume_id, key, size):
                        raise RuntimeError(f"uploaded object size verification failed: {relative}")
                job.files_uploaded += 1
                job.bytes_uploaded += size
                job.updated_at = utc_now()
                self._save(job)
            job.status = "complete"
            job.current_file = None
            job.completed_at = utc_now()
        except Exception as error:
            job.status = "failed"
            job.error = str(error)
            job.completed_at = utc_now()
        job.updated_at = utc_now()
        self._save(job)
        return job

    def _require(self, job_id: str) -> RunPodBundleUploadJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _save(self, job: RunPodBundleUploadJob) -> None:
        jobs = self._read()
        jobs[job.id] = job
        self._write(jobs)

    def _read(self) -> dict[str, RunPodBundleUploadJob]:
        with json_file_lock(self.jobs_path):
            if not self.jobs_path.exists():
                return {}
            try:
                payload = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {
                item["id"]: RunPodBundleUploadJob.model_validate(item)
                for item in payload.get("jobs", [])
            }

    def _write(self, jobs: dict[str, RunPodBundleUploadJob]) -> None:
        with json_file_lock(self.jobs_path):
            atomic_write_json(self.jobs_path, {
                "version": 1,
                "jobs": [job.model_dump(mode="json") for job in jobs.values()],
            })


def _bundle_manifest(bundle: Path) -> dict[str, Any]:
    path = bundle / "bundle_manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("RunPod bundle manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("created_by") != "LoraSuite" or payload.get("format") != "lorasuite-runpod-v1":
        raise ValueError("folder is not a LoraSuite RunPod bundle")
    if payload.get("ready") is not True:
        raise ValueError("RunPod bundle is not trainer-ready")
    return payload


def _bundle_files(bundle: Path) -> list[Path]:
    if not bundle.is_dir():
        raise ValueError("RunPod bundle folder is missing")
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("RunPod bundle must not contain symbolic links")
        if path.is_file():
            files.append(path)
    return files


def _remote_prefix(manifest: dict[str, Any]) -> str:
    value = str(manifest.get("serverless_root") or "")
    root = PurePosixPath("/runpod-volume")
    path = PurePosixPath(value)
    if path == root or root not in path.parents or ".." in path.parts:
        raise ValueError("RunPod bundle serverless root is invalid")
    return str(path.relative_to(root))


def _credentials(access_key: str | None, secret_key: str | None) -> tuple[str, str]:
    access = (access_key or os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
    secret = (secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    if not access or not secret:
        raise ValueError("RunPod S3 access key and secret are required")
    return access, secret


def _remote_matches(client: S3UploadClient, bucket: str, key: str, size: int) -> bool:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return int(response.get("ContentLength", -1)) == size
