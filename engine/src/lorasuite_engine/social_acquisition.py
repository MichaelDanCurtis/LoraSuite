from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, RLock
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.ingress import IngressService
from lorasuite_engine.instagram_browser import scan_instagram_url_with_browser_cookies
from lorasuite_engine.models import IngressScanResult, utc_now
from lorasuite_engine.social_resilience import SocialProviderError
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.tiktok_browser import scan_tiktok_url_with_browser_cookies
from lorasuite_engine.x_browser import scan_x_url_with_browser_cookies


SocialProvider = Literal["instagram", "x", "tiktok"]
SocialAcquisitionStatus = Literal[
    "queued",
    "running",
    "cooldown",
    "complete",
    "failed",
    "canceled",
]
TERMINAL_STATUSES = frozenset({"complete", "failed", "canceled"})


class SocialAcquisitionRequest(BaseModel):
    provider: SocialProvider
    url: str
    browser: str = "chrome"
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None
    scan_mode: Literal["all", "feed", "reels", "tagged"] = "all"
    date_from: date | None = None
    date_to: date | None = None


class SocialAcquisitionJob(BaseModel):
    id: str
    request: SocialAcquisitionRequest
    request_fingerprint: str
    status: SocialAcquisitionStatus = "queued"
    attempt: int = 0
    max_attempts: int = 3
    progress_message: str = "Queued"
    retry_at: datetime | None = None
    retry_after_seconds: float | None = None
    cancel_requested: bool = False
    error: dict[str, Any] | None = None
    result: IngressScanResult | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


Scanner = Callable[[SocialAcquisitionRequest], IngressScanResult]
Clock = Callable[[], datetime]
Waiter = Callable[[Event, float], bool]


_PROCESS_LOCKS: dict[str, RLock] = {}
_PROCESS_LOCKS_LOCK = RLock()


class SocialAcquisitionService:
    def __init__(
        self,
        vault_root: Path,
        *,
        scanners: dict[SocialProvider, Scanner] | None = None,
        clock: Clock | None = None,
        waiter: Waiter | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.waiter = waiter or (lambda event, seconds: event.wait(seconds))
        self.scanners = scanners or {
            "instagram": self._scan_instagram,
            "x": self._scan_x,
            "tiktok": self._scan_tiktok,
        }
        self._cancel_events: dict[str, Event] = {}

    @property
    def jobs_path(self) -> Path:
        return self.vault_root / "social_acquisition_jobs.json"

    @property
    def cooldowns_path(self) -> Path:
        return self.vault_root / "social_acquisition_cooldowns.json"

    def create_job(self, request: SocialAcquisitionRequest) -> SocialAcquisitionJob:
        with json_file_lock(self.jobs_path):
            fingerprint = _request_fingerprint(request)
            jobs = self._read_jobs()
            existing = next(
                (
                    job
                    for job in jobs.values()
                    if job.request_fingerprint == fingerprint
                    and job.status not in TERMINAL_STATUSES
                ),
                None,
            )
            if existing is not None:
                return existing

            now = self.clock()
            job = SocialAcquisitionJob(
                id=f"social_acquisition_{hashlib.sha256(f'{fingerprint}:{now.isoformat()}'.encode()).hexdigest()[:24]}",
                request=request,
                request_fingerprint=fingerprint,
                created_at=now,
                updated_at=now,
            )
            jobs[job.id] = job
            self._write_jobs(jobs)
            return job

    def list_jobs(self) -> list[SocialAcquisitionJob]:
        return sorted(
            self._read_jobs().values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def get_job(self, job_id: str) -> SocialAcquisitionJob | None:
        return self._read_jobs().get(job_id)

    def process_job(self, job_id: str) -> SocialAcquisitionJob:
        with _process_lock(job_id):
            while True:
                job = self._require_job(job_id)
                if job.status in {"complete", "canceled"}:
                    return job
                if job.cancel_requested:
                    return self._save(
                        job,
                        status="canceled",
                        progress_message="Acquisition canceled",
                        completed_at=self.clock(),
                    )

                cooldown_seconds = self._cooldown_remaining(job.request)
                if cooldown_seconds > 0:
                    retry_at = self.clock() + timedelta(seconds=cooldown_seconds)
                    job = self._save(
                        job,
                        status="cooldown",
                        retry_at=retry_at,
                        retry_after_seconds=cooldown_seconds,
                        progress_message=f"Provider cooldown: retrying in {max(1, round(cooldown_seconds))}s",
                    )
                    if self.waiter(self._cancel_event(job.id), cooldown_seconds):
                        continue

                job = self._require_job(job_id)
                if job.cancel_requested:
                    continue
                job.attempt += 1
                job = self._save(
                    job,
                    status="running",
                    retry_at=None,
                    retry_after_seconds=None,
                    error=None,
                    progress_message=f"Retrieving {job.request.provider} previews (attempt {job.attempt} of {job.max_attempts})",
                )

                try:
                    result = self.scanners[job.request.provider](job.request)
                except SocialProviderError as error:
                    job = self._require_job(job_id)
                    if job.cancel_requested:
                        continue
                    if not error.retryable or job.attempt >= job.max_attempts:
                        return self._save(
                            job,
                            status="failed",
                            error=error.detail(),
                            retry_at=None,
                            retry_after_seconds=None,
                            progress_message=_failure_message(error),
                            completed_at=self.clock(),
                        )

                    delay = _retry_delay(job.attempt, error.retry_after_seconds)
                    retry_at = self.clock() + timedelta(seconds=delay)
                    if error.category == "rate_limited":
                        self._set_cooldown(job.request, retry_at)
                    job = self._save(
                        job,
                        status="cooldown",
                        error=error.detail(),
                        retry_at=retry_at,
                        retry_after_seconds=delay,
                        progress_message=f"{_retry_reason(error)} Retrying in {max(1, round(delay))}s",
                    )
                    if self.waiter(self._cancel_event(job.id), delay):
                        continue
                    continue
                except Exception as error:
                    return self._save(
                        job,
                        status="failed",
                        error={
                            "provider": job.request.provider,
                            "category": "internal",
                            "message": str(error),
                            "retryable": False,
                        },
                        progress_message=f"Acquisition failed: {error}",
                        completed_at=self.clock(),
                    )

                job = self._require_job(job_id)
                if job.cancel_requested:
                    continue
                IngressService(self.vault_root).store_candidates(result.candidates)
                return self._save(
                    job,
                    status="complete",
                    result=result,
                    error=None,
                    retry_at=None,
                    retry_after_seconds=None,
                    progress_message=f"Retrieved {len(result.candidates)} candidate records",
                    completed_at=self.clock(),
                )

    def cancel_job(self, job_id: str) -> SocialAcquisitionJob:
        job = self._require_job(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        job.cancel_requested = True
        self._cancel_event(job.id).set()
        if job.status in {"queued", "cooldown"}:
            return self._save(
                job,
                status="canceled",
                progress_message="Acquisition canceled",
                completed_at=self.clock(),
            )
        return self._save(
            job,
            progress_message="Cancellation requested; waiting for the active provider request to stop",
        )

    def resume_job(self, job_id: str) -> SocialAcquisitionJob:
        job = self._require_job(job_id)
        if job.status == "complete":
            return job
        self._cancel_event(job.id).clear()
        job.cancel_requested = False
        job.status = "queued"
        job.progress_message = "Queued to resume"
        job.completed_at = None
        if job.attempt >= job.max_attempts or (job.error or {}).get("category") == "authentication":
            job.attempt = 0
        return self._save(job)

    def recover_interrupted_jobs(self) -> list[SocialAcquisitionJob]:
        with json_file_lock(self.jobs_path):
            recovered: list[SocialAcquisitionJob] = []
            jobs = self._read_jobs()
            changed = False
            for job in jobs.values():
                if job.status not in {"running", "cooldown", "queued"} or job.cancel_requested:
                    continue
                job.status = "queued"
                job.progress_message = "Recovered after engine restart"
                job.updated_at = self.clock()
                jobs[job.id] = job
                recovered.append(job)
                changed = True
            if changed:
                self._write_jobs(jobs)
            return recovered

    def _scan_instagram(self, request: SocialAcquisitionRequest) -> IngressScanResult:
        return scan_instagram_url_with_browser_cookies(
            request.url,
            self.vault_root,
            browser=request.browser,
            limit=request.limit,
            cursor=request.cursor,
            scan_mode=request.scan_mode,
            date_from=request.date_from,
            date_to=request.date_to,
        )

    def _scan_x(self, request: SocialAcquisitionRequest) -> IngressScanResult:
        return scan_x_url_with_browser_cookies(
            request.url,
            self.vault_root,
            browser=request.browser,
            limit=request.limit,
            cursor=request.cursor,
            date_from=request.date_from,
            date_to=request.date_to,
        )

    def _scan_tiktok(self, request: SocialAcquisitionRequest) -> IngressScanResult:
        return scan_tiktok_url_with_browser_cookies(
            request.url,
            self.vault_root,
            browser=request.browser,
            limit=request.limit,
            cursor=request.cursor,
            date_from=request.date_from,
            date_to=request.date_to,
        )

    def _cooldown_remaining(self, request: SocialAcquisitionRequest) -> float:
        with json_file_lock(self.cooldowns_path):
            cooldowns = self._read_cooldowns()
            retry_at = cooldowns.get(_cooldown_key(request))
            if retry_at is None:
                return 0.0
            remaining = (retry_at - self.clock()).total_seconds()
            if remaining <= 0:
                cooldowns.pop(_cooldown_key(request), None)
                self._write_cooldowns(cooldowns)
                return 0.0
            return remaining

    def _set_cooldown(self, request: SocialAcquisitionRequest, retry_at: datetime) -> None:
        with json_file_lock(self.cooldowns_path):
            cooldowns = self._read_cooldowns()
            key = _cooldown_key(request)
            existing = cooldowns.get(key)
            if existing is None or retry_at > existing:
                cooldowns[key] = retry_at
                self._write_cooldowns(cooldowns)

    def _cancel_event(self, job_id: str) -> Event:
        return self._cancel_events.setdefault(job_id, Event())

    def _require_job(self, job_id: str) -> SocialAcquisitionJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _save(self, job: SocialAcquisitionJob, **updates: Any) -> SocialAcquisitionJob:
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = self.clock()
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs()
            jobs[job.id] = job
            self._write_jobs(jobs)
        return job

    def _read_jobs(self) -> dict[str, SocialAcquisitionJob]:
        if not self.jobs_path.exists():
            return {}
        with json_file_lock(self.jobs_path):
            try:
                payload = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        if not isinstance(payload, dict):
            return {}
        jobs: dict[str, SocialAcquisitionJob] = {}
        for job_id, value in payload.items():
            try:
                jobs[str(job_id)] = SocialAcquisitionJob.model_validate(value)
            except (TypeError, ValueError):
                continue
        return jobs

    def _write_jobs(self, jobs: dict[str, SocialAcquisitionJob]) -> None:
        with json_file_lock(self.jobs_path):
            atomic_write_json(
                self.jobs_path,
                {job_id: job.model_dump(mode="json") for job_id, job in jobs.items()},
            )

    def _read_cooldowns(self) -> dict[str, datetime]:
        if not self.cooldowns_path.exists():
            return {}
        with json_file_lock(self.cooldowns_path):
            try:
                payload = json.loads(self.cooldowns_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        if not isinstance(payload, dict):
            return {}
        cooldowns: dict[str, datetime] = {}
        for key, value in payload.items():
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                continue
            cooldowns[str(key)] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return cooldowns

    def _write_cooldowns(self, cooldowns: dict[str, datetime]) -> None:
        with json_file_lock(self.cooldowns_path):
            atomic_write_json(
                self.cooldowns_path,
                {key: value.isoformat() for key, value in cooldowns.items()},
            )


def _request_fingerprint(request: SocialAcquisitionRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cooldown_key(request: SocialAcquisitionRequest) -> str:
    return f"{request.provider}:{request.browser.lower()}"


def _retry_delay(attempt: int, provider_delay: float | None) -> float:
    if provider_delay is not None:
        return min(300.0, max(1.0, provider_delay))
    return min(30.0, float(2 ** max(0, attempt - 1)))


def _retry_reason(error: SocialProviderError) -> str:
    if error.category == "rate_limited":
        return "Provider rate limit reached."
    return "Temporary provider failure."


def _failure_message(error: SocialProviderError) -> str:
    if error.category == "authentication":
        return f"Browser session expired or was rejected. Refresh the {error.provider} login and resume."
    return f"Acquisition failed: {error}"


def _process_lock(job_id: str) -> RLock:
    with _PROCESS_LOCKS_LOCK:
        return _PROCESS_LOCKS.setdefault(job_id, RLock())
