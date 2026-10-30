from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from lorasuite_engine.runpod_runs import RunPodTrainingRunService
from lorasuite_engine.training_targets import (
    TrainingDurationBaseline,
    get_training_target_profile,
)


ProviderName = Literal["runcomfy", "runpod"]
EstimateConfidence = Literal["low", "medium", "high"]

RUNCOMFY_PRICING_URL = "https://www.runcomfy.com/pricing"
RUNPOD_PRICING_URL = "https://www.runpod.io/pricing"
PRICING_SNAPSHOT_DATE = "2026-07-16"

RUNCOMFY_HOURLY_RATES = {
    "pay_as_you_go": {"h100": 4.49, "h200": 5.75},
    "pro": {"h100": 3.59, "h200": 4.59},
}
RUNPOD_SERVERLESS_HOURLY_RATES = {
    "flex": {"h100": 4.55, "h200": 5.93},
    "active": {"h100": 3.35, "h200": 4.46},
}


class EstimateRange(BaseModel):
    low: float = Field(ge=0)
    expected: float = Field(ge=0)
    high: float = Field(ge=0)


class TrainingEstimateRequest(BaseModel):
    provider: ProviderName
    training_target_profile_id: str
    gpu_type: str
    pricing_tier: str | None = None
    config_file: str | None = None
    steps: int | None = Field(default=None, ge=1)
    dataset_item_count: int | None = Field(default=None, ge=0)
    hourly_rate_usd: float | None = Field(default=None, ge=0)


class TrainingCostEstimate(BaseModel):
    schema_version: str = "lorasuite.training-estimate.v1"
    available: bool = False
    provider: ProviderName
    training_target_profile_id: str
    training_target_label: str
    gpu_type: str
    gpu_family: str
    pricing_tier: str
    step_count: int | None = None
    dataset_item_count: int | None = None
    duration_hours: EstimateRange | None = None
    hourly_rate_usd: float | None = None
    cost_usd: EstimateRange | None = None
    confidence: EstimateConfidence = "low"
    historical_run_count: int = 0
    duration_basis: str = ""
    pricing_basis: str = ""
    pricing_source_url: str | None = None
    pricing_snapshot_date: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrainingEstimateService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def estimate(self, request: TrainingEstimateRequest) -> TrainingCostEstimate:
        profile = get_training_target_profile(request.training_target_profile_id)
        gpu_family = _gpu_family(request.gpu_type)
        pricing_tier = _pricing_tier(request.provider, request.pricing_tier)
        baseline = next(
            (
                candidate
                for candidate in profile.duration_baselines
                if candidate.gpu_family == gpu_family
            ),
            None,
        )
        step_count = (
            request.steps
            or _steps_from_config(request.config_file)
            or (
                profile.recipe.training.steps
                if profile.recipe is not None and profile.recipe.training is not None
                else None
            )
            or (baseline.baseline_steps if baseline is not None else None)
        )
        estimate = TrainingCostEstimate(
            provider=request.provider,
            training_target_profile_id=profile.profile_id,
            training_target_label=profile.label,
            gpu_type=request.gpu_type,
            gpu_family=gpu_family,
            pricing_tier=pricing_tier,
            step_count=step_count,
            dataset_item_count=request.dataset_item_count,
        )
        if baseline is None:
            estimate.warnings.append(
                f"No {gpu_family.upper()} duration baseline is defined for {profile.label}."
            )
            return estimate

        history = (
            self._runpod_history(request, gpu_family)
            if step_count == baseline.baseline_steps
            else []
        )
        if history:
            duration = EstimateRange(
                low=round(min(history), 2),
                expected=round(statistics.median(history), 2),
                high=round(max(history), 2),
            )
            confidence: EstimateConfidence = "high" if len(history) >= 5 else "medium"
            duration_basis = (
                f"{len(history)} completed LoraSuite RunPod run"
                f"{'s' if len(history) != 1 else ''} for this target and GPU family."
            )
        else:
            scale = (
                step_count / baseline.baseline_steps
                if step_count is not None
                else 1.0
            )
            duration = EstimateRange(
                low=round(baseline.low_hours * scale, 2),
                expected=round(baseline.expected_hours * scale, 2),
                high=round(baseline.high_hours * scale, 2),
            )
            confidence = baseline.confidence
            duration_basis = baseline.basis
            if request.provider == "runpod" and step_count != baseline.baseline_steps:
                estimate.warnings.append(
                    "Measured RunPod runtimes were not used because the configured step count differs from the recorded baseline."
                )

        hourly_rate, pricing_basis, pricing_url, pricing_date = _hourly_rate(
            request.provider,
            gpu_family,
            pricing_tier,
            request.hourly_rate_usd,
        )
        estimate.available = True
        estimate.duration_hours = duration
        estimate.hourly_rate_usd = hourly_rate
        estimate.confidence = confidence
        estimate.historical_run_count = len(history)
        estimate.duration_basis = duration_basis
        estimate.pricing_basis = pricing_basis
        estimate.pricing_source_url = pricing_url
        estimate.pricing_snapshot_date = pricing_date
        estimate.assumptions = list(baseline.assumptions)
        if request.dataset_item_count is not None:
            estimate.assumptions.append(
                f"Dataset contains {request.dataset_item_count} approved training item"
                f"{'s' if request.dataset_item_count != 1 else ''}; the configured step count, not raw item count, drives the runtime scale."
            )
        if hourly_rate is not None:
            estimate.cost_usd = EstimateRange(
                low=round(duration.low * hourly_rate, 2),
                expected=round(duration.expected * hourly_rate, 2),
                high=round(duration.high * hourly_rate, 2),
            )
        else:
            estimate.warnings.append(
                "No hourly provider rate is available for this GPU and pricing tier."
            )
        estimate.warnings.append(
            "This is a planning estimate, not a provider quote. Verify pricing before submission."
        )
        return estimate

    def _runpod_history(
        self,
        request: TrainingEstimateRequest,
        gpu_family: str,
    ) -> list[float]:
        if request.provider != "runpod":
            return []
        service = RunPodTrainingRunService(self.vault_root)
        reports = service.list_preflight_reports()
        report_gpu_by_bundle = {
            report.bundle_path: _gpu_family(report.gpu.name)
            for report in reports
            if report.ready and report.gpu.available and report.gpu.name
        }
        values: list[float] = []
        for run in service.list_runs():
            if (
                run.training_target_profile_id
                != request.training_target_profile_id
                or run.status != "completed"
                or not run.execution_time_ms
                or report_gpu_by_bundle.get(run.bundle_path) != gpu_family
            ):
                continue
            values.append(run.execution_time_ms / 3_600_000)
        return values


def _steps_from_config(config_file: str | None) -> int | None:
    content = (config_file or "").strip()
    if not content:
        return None
    try:
        payload = yaml.safe_load(content.replace("{dataset_name}", "estimate-dataset"))
    except yaml.YAMLError:
        return None
    return _find_steps(payload)


def _find_steps(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("steps", "max_steps"):
            candidate = value.get(key)
            if isinstance(candidate, int) and candidate > 0:
                return candidate
        for candidate in value.values():
            found = _find_steps(candidate)
            if found is not None:
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _find_steps(candidate)
            if found is not None:
                return found
    return None


def _gpu_family(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"ada_80_plus", "ada_80_pro"} or "h100" in normalized:
        return "h100"
    if normalized == "hopper_141" or "h200" in normalized:
        return "h200"
    return normalized.replace(" ", "_") or "unknown"


def _pricing_tier(provider: ProviderName, value: str | None) -> str:
    normalized = (value or "").strip().casefold().replace(" ", "_")
    if provider == "runcomfy":
        return normalized if normalized in RUNCOMFY_HOURLY_RATES else "pay_as_you_go"
    return normalized if normalized in RUNPOD_SERVERLESS_HOURLY_RATES else "flex"


def _hourly_rate(
    provider: ProviderName,
    gpu_family: str,
    pricing_tier: str,
    override: float | None,
) -> tuple[float | None, str, str | None, str | None]:
    if override is not None:
        return (
            override,
            "User-supplied hourly rate.",
            None,
            None,
        )
    if provider == "runcomfy":
        rate = RUNCOMFY_HOURLY_RATES.get(pricing_tier, {}).get(gpu_family)
        return (
            rate,
            "RunComfy Trainer pricing snapshot.",
            RUNCOMFY_PRICING_URL,
            PRICING_SNAPSHOT_DATE,
        )
    rate = RUNPOD_SERVERLESS_HOURLY_RATES.get(pricing_tier, {}).get(gpu_family)
    return (
        rate,
        "RunPod Serverless pricing snapshot.",
        RUNPOD_PRICING_URL,
        PRICING_SNAPSHOT_DATE,
    )
