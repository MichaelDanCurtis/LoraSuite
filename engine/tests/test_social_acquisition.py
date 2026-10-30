from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from lorasuite_engine.instagram_browser import InstagramBrowserScanError
from lorasuite_engine.models import IngressCandidate, IngressScanResult, SourceKind
from lorasuite_engine.social_acquisition import (
    SocialAcquisitionRequest,
    SocialAcquisitionService,
)
from lorasuite_engine.x_browser import XBrowserScanError


def empty_result() -> IngressScanResult:
    return IngressScanResult(metadata_json={"has_more": False})


def test_authentication_failure_does_not_retry(tmp_path: Path) -> None:
    calls = 0

    def scan(_request: SocialAcquisitionRequest) -> IngressScanResult:
        nonlocal calls
        calls += 1
        raise InstagramBrowserScanError(
            "Instagram request failed with HTTP 401.",
            category="authentication",
            status_code=401,
            retryable=False,
        )

    service = SocialAcquisitionService(
        tmp_path,
        scanners={"instagram": scan, "x": scan, "tiktok": scan},
        waiter=lambda _event, _seconds: False,
    )
    job = service.create_job(
        SocialAcquisitionRequest(provider="instagram", url="https://www.instagram.com/person")
    )

    finished = service.process_job(job.id)

    assert calls == 1
    assert finished.status == "failed"
    assert finished.attempt == 1
    assert finished.error is not None
    assert finished.error["category"] == "authentication"
    assert "Refresh" in finished.progress_message


def test_transient_failures_retry_and_commit_candidates_once(tmp_path: Path) -> None:
    calls = 0
    waits: list[float] = []
    candidate = IngressCandidate(
        id="candidate-one",
        source_kind=SourceKind.X_TWITTER,
        source_locator="https://x.com/person/status/1",
        display_name="portrait",
    )

    def scan(_request: SocialAcquisitionRequest) -> IngressScanResult:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise XBrowserScanError(
                "X scan timed out",
                category="transient_network",
                retryable=True,
            )
        return IngressScanResult(candidates=[candidate])

    service = SocialAcquisitionService(
        tmp_path,
        scanners={"instagram": scan, "x": scan, "tiktok": scan},
        waiter=lambda _event, seconds: waits.append(seconds) or False,
    )
    job = service.create_job(
        SocialAcquisitionRequest(provider="x", url="https://x.com/person")
    )

    finished = service.process_job(job.id)

    assert finished.status == "complete"
    assert finished.attempt == 3
    assert waits == [1.0, 2.0]
    stored = service.get_job(job.id)
    assert stored is not None and stored.result is not None
    assert [item.id for item in stored.result.candidates] == ["candidate-one"]
    assert (tmp_path / "ingress_candidates.json").read_text().count("candidate-one") == 1


def test_rate_limit_cooldown_is_persisted_and_honored(tmp_path: Path) -> None:
    current = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    calls = 0
    waits: list[float] = []
    persisted_during_wait: list[str] = []

    def clock() -> datetime:
        return current

    def wait(_event, seconds: float) -> bool:
        nonlocal current
        waits.append(seconds)
        persisted_during_wait.append(
            (tmp_path / "social_acquisition_cooldowns.json").read_text()
        )
        current += timedelta(seconds=seconds)
        return False

    def scan(_request: SocialAcquisitionRequest) -> IngressScanResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise InstagramBrowserScanError(
                "Instagram request failed with HTTP 429.",
                category="rate_limited",
                status_code=429,
                retryable=True,
                retry_after_seconds=12,
            )
        return empty_result()

    service = SocialAcquisitionService(
        tmp_path,
        scanners={"instagram": scan, "x": scan, "tiktok": scan},
        clock=clock,
        waiter=wait,
    )
    job = service.create_job(
        SocialAcquisitionRequest(provider="instagram", url="https://www.instagram.com/person")
    )

    finished = service.process_job(job.id)

    assert finished.status == "complete"
    assert calls == 2
    assert waits == [12.0]
    assert "instagram:chrome" in persisted_during_wait[0]


def test_cancel_before_processing_never_calls_provider(tmp_path: Path) -> None:
    calls = 0

    def scan(_request: SocialAcquisitionRequest) -> IngressScanResult:
        nonlocal calls
        calls += 1
        return empty_result()

    service = SocialAcquisitionService(
        tmp_path,
        scanners={"instagram": scan, "x": scan, "tiktok": scan},
    )
    job = service.create_job(
        SocialAcquisitionRequest(provider="tiktok", url="https://www.tiktok.com/@person")
    )

    canceled = service.cancel_job(job.id)
    finished = service.process_job(job.id)

    assert canceled.status == "canceled"
    assert finished.status == "canceled"
    assert calls == 0


def test_interrupted_job_recovers_after_service_restart(tmp_path: Path) -> None:
    request = SocialAcquisitionRequest(provider="x", url="https://x.com/person")
    first = SocialAcquisitionService(tmp_path)
    job = first.create_job(request)
    first._save(job, status="running", progress_message="Retrieving")

    second = SocialAcquisitionService(
        tmp_path,
        scanners={
            "instagram": lambda _request: empty_result(),
            "x": lambda _request: empty_result(),
            "tiktok": lambda _request: empty_result(),
        },
    )
    recovered = second.recover_interrupted_jobs()

    assert [item.id for item in recovered] == [job.id]
    assert recovered[0].status == "queued"
    assert second.process_job(job.id).status == "complete"
