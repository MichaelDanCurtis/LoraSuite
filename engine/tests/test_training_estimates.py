from pathlib import Path

from lorasuite_engine.runpod_runs import (
    RunPodPreflightGpu,
    RunPodPreflightReport,
    RunPodTrainingRun,
)
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_estimates import (
    TrainingEstimateRequest,
    TrainingEstimateService,
)


def test_estimates_runcomfy_duration_and_current_pricing(tmp_path: Path):
    estimate = TrainingEstimateService(tmp_path).estimate(
        TrainingEstimateRequest(
            provider="runcomfy",
            training_target_profile_id="runcomfy_flux1_dev_character",
            gpu_type="ADA_80_PLUS",
            pricing_tier="pay_as_you_go",
            config_file="train:\n  steps: 2000\n",
            dataset_item_count=35,
        )
    )

    assert estimate.available is True
    assert estimate.gpu_family == "h100"
    assert estimate.step_count == 2000
    assert estimate.duration_hours is not None
    assert estimate.duration_hours.expected == 1.7
    assert estimate.hourly_rate_usd == 4.49
    assert estimate.cost_usd is not None
    assert estimate.cost_usd.expected == 7.63
    assert estimate.pricing_snapshot_date == "2026-07-16"
    assert "35 approved training items" in " ".join(estimate.assumptions)


def test_scales_duration_by_yaml_steps_and_accepts_rate_override(tmp_path: Path):
    estimate = TrainingEstimateService(tmp_path).estimate(
        TrainingEstimateRequest(
            provider="runpod",
            training_target_profile_id="runcomfy_qwen_image_character",
            gpu_type="NVIDIA H100 80GB HBM3",
            pricing_tier="flex",
            config_file="config:\n  train:\n    steps: 1000\n",
            hourly_rate_usd=5.0,
        )
    )

    assert estimate.duration_hours is not None
    assert estimate.duration_hours.expected == 1.25
    assert estimate.hourly_rate_usd == 5.0
    assert estimate.cost_usd is not None
    assert estimate.cost_usd.expected == 6.25
    assert estimate.pricing_basis == "User-supplied hourly rate."
    assert estimate.pricing_source_url is None


def test_estimates_krea2_with_provisional_h100_baseline(tmp_path: Path):
    estimate = TrainingEstimateService(tmp_path).estimate(
        TrainingEstimateRequest(
            provider="runcomfy",
            training_target_profile_id="runcomfy_krea2_raw_character",
            gpu_type="H100",
            pricing_tier="pay_as_you_go",
            config_file="config:\n  process:\n    - train:\n        steps: 2000\n",
            dataset_item_count=218,
        )
    )

    assert estimate.available is True
    assert estimate.confidence == "low"
    assert estimate.duration_hours is not None
    assert estimate.duration_hours.model_dump() == {
        "low": 1.8,
        "expected": 3.0,
        "high": 6.0,
    }
    assert estimate.hourly_rate_usd == 4.49
    assert estimate.cost_usd is not None
    assert estimate.cost_usd.expected == 13.47
    assert estimate.historical_run_count == 0
    assert "Provisional LoraSuite sizing baseline" in estimate.duration_basis
    assert "218 approved training items" in " ".join(estimate.assumptions)


def test_uses_completed_runpod_execution_history_for_matching_gpu(tmp_path: Path):
    runs = [
        RunPodTrainingRun(
            id=f"run-{index}",
            bundle_path=tmp_path / f"bundle-{index}",
            bundle_fingerprint=f"fingerprint-{index}",
            modality="image",
            training_target_profile_id="runcomfy_flux1_dev_character",
            endpoint_id=f"endpoint-{index}",
            status="completed",
            execution_time_ms=duration_ms,
        )
        for index, duration_ms in enumerate((7_200_000, 14_400_000), start=1)
    ]
    reports = [
        RunPodPreflightReport(
            bundle_path=run.bundle_path,
            bundle_fingerprint=run.bundle_fingerprint,
            training_target_profile_id=run.training_target_profile_id,
            endpoint_id=run.endpoint_id,
            ready=True,
            gpu=RunPodPreflightGpu(
                available=True,
                name="NVIDIA H100 80GB HBM3",
                memory_gb=80,
            ),
        )
        for run in runs
    ]
    atomic_write_json(
        tmp_path / "runpod_training_runs.json",
        {"version": 1, "runs": [run.model_dump(mode="json") for run in runs]},
    )
    atomic_write_json(
        tmp_path / "runpod_preflight_reports.json",
        {
            "version": 1,
            "reports": [report.model_dump(mode="json") for report in reports],
        },
    )

    estimate = TrainingEstimateService(tmp_path).estimate(
        TrainingEstimateRequest(
            provider="runpod",
            training_target_profile_id="runcomfy_flux1_dev_character",
            gpu_type="NVIDIA H100 80GB HBM3",
        )
    )

    assert estimate.duration_hours is not None
    assert estimate.duration_hours.low == 2.0
    assert estimate.duration_hours.expected == 3.0
    assert estimate.duration_hours.high == 4.0
    assert estimate.historical_run_count == 2
    assert estimate.confidence == "medium"
    assert estimate.cost_usd is not None
    assert estimate.cost_usd.expected == 13.65
