from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.models import (
    CurationAnalysisEvidence,
    CaptionGenerationJob,
    DatasetSnapshotStatus,
    ProcessingJobStatus,
    VisionProviderAuthMode,
    utc_now,
)
from lorasuite_engine.processing import ProcessingService
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService
from lorasuite_engine.vision_caption import (
    PROVIDER_PRESETS,
    VisionCaptionProvider,
    VisionProviderConfig,
    auth_mode_for_provider,
    create_vision_provider,
    resolve_api_key,
)


ProviderFactory = Callable[[VisionProviderConfig], VisionCaptionProvider]
MAX_REPEATED_FAILURES = 3


class CaptionGenerationService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: ProviderFactory = create_vision_provider,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory

    @property
    def jobs_path(self) -> Path:
        return self.vault_root / "caption_jobs.json"

    def list_jobs(self, snapshot_id: str | None = None) -> list[CaptionGenerationJob]:
        jobs = self._read_jobs().values()
        if snapshot_id is not None:
            jobs = (job for job in jobs if job.snapshot_id == snapshot_id)
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def get_job(self, job_id: str) -> CaptionGenerationJob | None:
        return self._read_jobs().get(job_id)

    def cancel_job(
        self,
        job_id: str,
        reason: str = "Caption generation stopped by the user",
    ) -> CaptionGenerationJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in {
            ProcessingJobStatus.COMPLETE,
            ProcessingJobStatus.FAILED,
            ProcessingJobStatus.CANCELED,
        }:
            return job
        job.status = ProcessingJobStatus.CANCELED
        job.completed_at = utc_now()
        job.progress_message = reason
        self._save_job(job)
        return job

    def create_job(
        self,
        *,
        snapshot_id: str,
        item_ids: list[str],
        config: VisionProviderConfig,
    ) -> CaptionGenerationJob:
        snapshot = DatasetCompilerService(self.vault_root).get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        if snapshot.status != DatasetSnapshotStatus.DRAFT:
            raise ValueError("caption generation requires a draft dataset snapshot")
        unique_item_ids = list(dict.fromkeys(item_ids))
        if not unique_item_ids:
            raise ValueError("select at least one dataset item for caption generation")
        unknown_ids = set(unique_item_ids).difference(snapshot.items)
        if unknown_ids:
            raise ValueError(f"dataset item not found: {sorted(unknown_ids)[0]}")
        # Validate provider settings before the asynchronous job is accepted.
        self.provider_factory(config)
        job = CaptionGenerationJob(
            snapshot_id=snapshot_id,
            item_ids=unique_item_ids,
            provider_id=config.provider_id,
            provider_label=config.provider_label,
            model=config.model,
            provider_dialect=config.dialect,
            provider_base_url=config.base_url,
            provider_auth_mode=config.auth_mode,
            total_count=len(unique_item_ids),
        )
        jobs = self._read_jobs()
        jobs[job.id] = job
        self._write_jobs(jobs)
        return job

    def process_job(
        self,
        job_id: str,
        config: VisionProviderConfig,
    ) -> CaptionGenerationJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status == ProcessingJobStatus.CANCELED:
            return job
        if job.status == ProcessingJobStatus.COMPLETE:
            return job
        if job.status not in {
            ProcessingJobStatus.QUEUED,
            ProcessingJobStatus.RUNNING,
            ProcessingJobStatus.FAILED,
        }:
            return job
        provider = self.provider_factory(config)
        resume_index = min(
            max(job.next_item_index, job.completed_count + job.failed_count),
            len(job.item_ids),
        )
        job.status = ProcessingJobStatus.RUNNING
        if job.started_at is None:
            job.started_at = utc_now()
        job.completed_at = None
        job.next_item_index = resume_index
        job.progress_message = (
            f"Resuming at {resume_index} of {job.total_count} captions"
            if resume_index
            else f"Generating 0 of {job.total_count} captions"
        )
        if resume_index == 0:
            job.errors = []
            job.completed_count = 0
            job.failed_count = 0
        self._save_job(job)

        compiler = DatasetCompilerService(self.vault_root)
        vault = VaultService(self.vault_root)
        curation_context = _latest_curation_context(self.vault_root)
        repeated_error, repeated_failure_count = _trailing_error_streak(job.errors)
        if repeated_failure_count >= MAX_REPEATED_FAILURES:
            job.status = ProcessingJobStatus.FAILED
            job.completed_at = utc_now()
            job.progress_message = (
                f"Stopped after {repeated_failure_count} repeated failures: {repeated_error}"
            )
            self._save_job(job)
            return job
        for item_index in range(resume_index, len(job.item_ids)):
            latest_job = self.get_job(job.id)
            if latest_job is not None and latest_job.status == ProcessingJobStatus.CANCELED:
                return latest_job
            item_id = job.item_ids[item_index]
            try:
                snapshot = compiler.get_snapshot(job.snapshot_id)
                if snapshot is None:
                    raise ValueError("dataset snapshot no longer exists")
                record = snapshot.items.get(item_id)
                if record is None:
                    raise ValueError("dataset item no longer exists")
                media_item = vault.get_media_item(record.training_media_item_id)
                if media_item is None:
                    raise ValueError("training media no longer exists")
                analysis_context = (
                    curation_context.get(record.source_media_item_id)
                    or curation_context.get(record.training_media_item_id)
                )
                evidence = provider.caption(
                    media_item.raw_path,
                    snapshot.intent,
                    analysis_context,
                )
                compiler.apply_vision_evidence(
                    job.snapshot_id,
                    item_id,
                    evidence=evidence,
                    provider_label=config.provider_label,
                    model=config.model,
                )
                job.completed_count += 1
                repeated_error = ""
                repeated_failure_count = 0
            except (OSError, ValueError) as error:
                message = str(error)
                job.failed_count += 1
                job.errors.append({"item_id": item_id, "message": message})
                if message == repeated_error:
                    repeated_failure_count += 1
                else:
                    repeated_error = message
                    repeated_failure_count = 1
            job.next_item_index = item_index + 1
            if repeated_failure_count >= MAX_REPEATED_FAILURES:
                job.status = ProcessingJobStatus.FAILED
                job.completed_at = utc_now()
                job.progress_message = (
                    f"Stopped after {repeated_failure_count} repeated failures: {repeated_error}"
                )
                self._save_job(job)
                return job
            job.progress_message = (
                f"Generated {job.completed_count} of {job.total_count} captions"
                if not job.failed_count
                else f"Processed {job.next_item_index} of {job.total_count}; {job.failed_count} failed"
            )
            self._save_job(job)

        job.status = (
            ProcessingJobStatus.FAILED
            if job.completed_count == 0 and job.failed_count
            else ProcessingJobStatus.COMPLETE
        )
        job.completed_at = utc_now()
        job.progress_message = (
            f"Generated {job.completed_count} captions; {job.failed_count} failed"
        )
        self._save_job(job)
        return job

    def recover_interrupted_jobs(
        self,
    ) -> list[tuple[CaptionGenerationJob, VisionProviderConfig]]:
        recovered: list[tuple[CaptionGenerationJob, VisionProviderConfig]] = []
        jobs = self._read_jobs()
        changed = False
        for job in jobs.values():
            if job.status not in {
                ProcessingJobStatus.QUEUED,
                ProcessingJobStatus.RUNNING,
            }:
                continue
            try:
                config = self._recovery_config(job)
                self.provider_factory(config)
            except ValueError as error:
                job.status = ProcessingJobStatus.FAILED
                job.progress_message = f"Interrupted; provider must be reconnected: {error}"
                job.completed_at = utc_now()
                jobs[job.id] = job
                changed = True
                continue
            job.status = ProcessingJobStatus.QUEUED
            job.next_item_index = min(
                max(job.next_item_index, job.completed_count + job.failed_count),
                len(job.item_ids),
            )
            job.progress_message = (
                f"Recovered after engine restart at {job.next_item_index} of {job.total_count} captions"
            )
            job.completed_at = None
            jobs[job.id] = job
            recovered.append((job, config))
            changed = True
        if changed:
            self._write_jobs(jobs)
        return recovered

    def _recovery_config(self, job: CaptionGenerationJob) -> VisionProviderConfig:
        preset = next(
            (candidate for candidate in PROVIDER_PRESETS if candidate["id"] == job.provider_id),
            None,
        )
        dialect = job.provider_dialect or (preset["dialect"] if preset else None)
        base_url = job.provider_base_url or (str(preset["base_url"]) if preset else None)
        auth_mode = job.provider_auth_mode or auth_mode_for_provider(job.provider_id)
        if dialect is None or not base_url:
            raise ValueError("saved provider configuration is incomplete")
        api_key = (
            resolve_api_key(job.provider_id, None)
            if auth_mode == VisionProviderAuthMode.API_KEY
            else ""
        )
        return VisionProviderConfig(
            provider_id=job.provider_id,
            provider_label=job.provider_label,
            dialect=dialect,
            base_url=base_url,
            model=job.model,
            api_key=api_key,
            auth_mode=auth_mode,
        )

    def _save_job(self, job: CaptionGenerationJob) -> None:
        jobs = self._read_jobs()
        existing = jobs.get(job.id)
        if (
            existing is not None
            and existing.status == ProcessingJobStatus.CANCELED
            and job.status != ProcessingJobStatus.CANCELED
        ):
            return
        jobs[job.id] = job
        self._write_jobs(jobs)

    def _read_jobs(self) -> dict[str, CaptionGenerationJob]:
        with json_file_lock(self.jobs_path):
            if not self.jobs_path.exists():
                return {}
            payload = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            return {
                item["id"]: CaptionGenerationJob.model_validate(item)
                for item in payload.get("jobs", [])
            }

    def _write_jobs(self, jobs: dict[str, CaptionGenerationJob]) -> None:
        with json_file_lock(self.jobs_path):
            atomic_write_json(
                self.jobs_path,
                {
                    "version": 1,
                    "jobs": [job.model_dump(mode="json") for job in jobs.values()],
                },
            )


def _trailing_error_streak(errors: list[dict[str, str]]) -> tuple[str, int]:
    if not errors:
        return "", 0
    message = errors[-1].get("message", "")
    count = 0
    for error in reversed(errors):
        if error.get("message", "") != message:
            break
        count += 1
    return message, count


def _latest_curation_context(vault_root: Path) -> dict[str, CurationAnalysisEvidence]:
    context: dict[str, CurationAnalysisEvidence] = {}
    for job in ProcessingService(vault_root).list_jobs():
        if job.job_type != "curation_analysis" or job.status != ProcessingJobStatus.COMPLETE:
            continue
        for evidence in job.curation_analyses:
            context.setdefault(evidence.media_item_id, evidence)
    return context
