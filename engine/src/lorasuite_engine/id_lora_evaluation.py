from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.evaluation_harness import BenchmarkCaseDefinition, BenchmarkMetrics, EvaluationHarnessService
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.runpod_runs import RunPodTrainingRunService
from lorasuite_engine.storage import atomic_write_json, json_file_lock


class IdLoraEvaluationCase(BaseModel):
    id: str
    output_name: str
    prompt: str
    expected_transcript: str | None = None
    video_path: Path
    metrics: BenchmarkMetrics
    checks: dict[str, bool | None] = Field(default_factory=dict)
    certified_checks: dict[str, bool | None] = Field(default_factory=dict)
    passed: bool = False
    blocked: bool = False
    certified: bool = False
    reasons: list[str] = Field(default_factory=list)


class IdLoraEvaluationSummary(BaseModel):
    case_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    average_identity: float | None = None
    average_speaker_similarity: float | None = None
    average_transcript_similarity: float | None = None
    average_stability: float = 0.0
    screening_ready: bool = False
    release_ready: bool = False
    warnings: list[str] = Field(default_factory=list)


class IdLoraEvaluationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("id_lora_evaluation"))
    project_id: str
    runpod_run_id: str
    contract_path: Path
    video_paths: dict[str, Path] = Field(default_factory=dict)
    status: Literal["queued", "running", "complete", "failed"] = "queued"
    cases: dict[str, IdLoraEvaluationCase] = Field(default_factory=dict)
    summary: IdLoraEvaluationSummary = Field(default_factory=IdLoraEvaluationSummary)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


Analyzer = Callable[[Path, str, BenchmarkCaseDefinition, Path, str], BenchmarkMetrics]


class IdLoraEvaluationService:
    def __init__(self, vault_root: Path, *, analyzer: Analyzer | None = None):
        self.vault_root = Path(vault_root)
        self.analyzer = analyzer or EvaluationHarnessService(self.vault_root)._analyze_variant

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "id_lora_evaluation_runs.json"

    def list_runs(self, project_id: str | None = None) -> list[IdLoraEvaluationRun]:
        runs = self._read().values()
        if project_id:
            runs = (run for run in runs if run.project_id == project_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> IdLoraEvaluationRun | None:
        return self._read().get(run_id)

    def create_run(self, runpod_run_id: str) -> IdLoraEvaluationRun:
        source = RunPodTrainingRunService(self.vault_root).get_run(runpod_run_id)
        if source is None:
            raise KeyError(runpod_run_id)
        if source.action != "run_id_lora" or source.status != "completed":
            raise ValueError("ID-LoRA inference must complete before evaluation")
        if not source.project_id:
            raise ValueError("ID-LoRA inference run has no character project provenance")
        contract = next((
            Path(artifact.local_path) for artifact in source.artifacts
            if artifact.kind == "contract" and artifact.local_path and Path(artifact.local_path).is_file()
        ), None)
        if contract is None:
            raise ValueError("download the ID-LoRA inference contract before evaluation")
        entries = _contract_entries(contract)
        videos = [artifact for artifact in source.artifacts if artifact.kind == "sample" and artifact.local_path and Path(artifact.local_path).suffix.lower() == ".mp4"]
        missing = [entry["output_name"] for entry in entries if _output_video(entry["output_name"], videos) is None]
        if missing:
            raise ValueError(f"downloaded ID-LoRA output is missing: {missing[0]}")
        existing = next((run for run in self.list_runs(source.project_id) if run.runpod_run_id == source.id), None)
        if existing:
            return existing
        run = IdLoraEvaluationRun(
            project_id=source.project_id,
            runpod_run_id=source.id,
            contract_path=self.vault_root / "id_lora_evaluation_inputs" / new_id("input_set") / "inference_contract.json",
        )
        try:
            run.contract_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contract, run.contract_path)
            for entry in entries:
                artifact = _output_video(entry["output_name"], videos)
                if artifact is None or not artifact.local_path:
                    raise ValueError(f"downloaded ID-LoRA output is missing: {entry['output_name']}")
                destination = run.contract_path.parent / f"{entry['output_name']}.mp4"
                shutil.copy2(Path(artifact.local_path), destination)
                run.video_paths[entry["output_name"]] = destination
        except Exception:
            shutil.rmtree(run.contract_path.parent, ignore_errors=True)
            raise
        runs = self._read()
        runs[run.id] = run
        self._write(runs)
        return run

    def process_run(self, run_id: str) -> IdLoraEvaluationRun:
        run = self._require(run_id)
        run.status = "running"
        run.error = None
        run.updated_at = utc_now()
        self._save(run)
        try:
            cases = {}
            for index, entry in enumerate(_contract_entries(run.contract_path), start=1):
                video_path = run.video_paths.get(entry["output_name"])
                if video_path is None or not video_path.is_file():
                    raise ValueError(f"ID-LoRA output is missing: {entry['output_name']}")
                transcript = _speech(entry["prompt"])
                definition = BenchmarkCaseDefinition(
                    id=f"id_lora_{index:02d}",
                    label=entry["output_name"],
                    filename=video_path.name,
                    prompt=entry["prompt"],
                    audio_required=True,
                    expected_transcript=transcript,
                )
                metrics = self.analyzer(
                    video_path,
                    "id_lora",
                    definition,
                    self.vault_root / "id_lora_evaluation_work" / run.id / definition.id,
                    run.project_id,
                )
                result = _evaluate_case(definition, video_path, metrics)
                cases[result.id] = result
            run.cases = cases
            run.summary = _summarize(cases.values())
            run.status = "complete"
            run.completed_at = utc_now()
        except Exception as error:
            run.status = "failed"
            run.error = str(error)
            run.completed_at = utc_now()
        run.updated_at = utc_now()
        self._save(run)
        return run

    def _require(self, run_id: str) -> IdLoraEvaluationRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _save(self, run: IdLoraEvaluationRun) -> None:
        runs = self._read()
        runs[run.id] = run
        self._write(runs)

    def _read(self) -> dict[str, IdLoraEvaluationRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            try:
                payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {item["id"]: IdLoraEvaluationRun.model_validate(item) for item in payload.get("runs", [])}

    def _write(self, runs: dict[str, IdLoraEvaluationRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {"version": 1, "runs": [run.model_dump(mode="json") for run in runs.values()]})


def _contract_entries(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("ID-LoRA inference contract is unreadable") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError("ID-LoRA inference contract is empty")
    entries = []
    output_names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("prompt", "output_name")):
            raise ValueError("ID-LoRA inference contract contains an invalid entry")
        output_name = item["output_name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", output_name):
            raise ValueError("ID-LoRA inference contract contains an unsafe output name")
        if output_name in output_names:
            raise ValueError("ID-LoRA inference contract contains duplicate output names")
        output_names.add(output_name)
        entries.append({"prompt": item["prompt"], "output_name": output_name})
    return entries


def _output_video(output_name: str, artifacts):
    return next((artifact for artifact in artifacts if Path(artifact.name).stem == output_name), None)


def _speech(prompt: str) -> str | None:
    match = re.search(r"\[SPEECH\]\s*:?\s*(.*?)(?=\s*\[SOUNDS\]|$)", prompt, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _evaluate_case(definition: BenchmarkCaseDefinition, path: Path, metrics: BenchmarkMetrics) -> IdLoraEvaluationCase:
    checks: dict[str, bool | None] = {
        "visual_quality": metrics.visual_quality >= 0.38,
        "temporal_stability": metrics.temporal_stability >= 0.32,
        "subject_coverage": metrics.subject_coverage >= 0.35,
        "identity_similarity": None if metrics.identity_similarity is None else metrics.identity_similarity >= 0.55,
        "identity_coverage": None if metrics.identity_frame_coverage is None else metrics.identity_frame_coverage >= 0.50,
        "audio_quality": None if metrics.audio_quality is None else metrics.audio_quality >= 0.55,
        "speaker_similarity": None if metrics.speaker_similarity is None else metrics.speaker_similarity >= 0.65,
        "transcript_similarity": None if metrics.transcript_similarity is None else metrics.transcript_similarity >= 0.60,
        "av_sync_proxy": None if metrics.av_sync_proxy is None else metrics.av_sync_proxy >= 0.30,
    }
    certified = {
        "syncnet_lse_c": None if metrics.syncnet_lse_c is None else metrics.syncnet_lse_c >= 3.0,
        "syncnet_lse_d": None if metrics.syncnet_lse_d is None else metrics.syncnet_lse_d <= 10.0,
        "syncnet_offset": None if metrics.syncnet_offset_frames is None else abs(metrics.syncnet_offset_frames) <= 3,
    }
    blocked = any(value is None for value in checks.values())
    passed = not blocked and all(checks.values())
    certified_pass = passed and all(value is True for value in certified.values())
    reasons = [name.replace("_", " ") for name, value in checks.items() if value is False]
    reasons.extend(f"{name.replace('_', ' ')} unavailable" for name, value in checks.items() if value is None)
    return IdLoraEvaluationCase(
        id=definition.id,
        output_name=definition.label,
        prompt=definition.prompt,
        expected_transcript=definition.expected_transcript,
        video_path=path,
        metrics=metrics,
        checks=checks,
        certified_checks=certified,
        passed=passed,
        blocked=blocked,
        certified=certified_pass,
        reasons=reasons,
    )


def _summarize(cases) -> IdLoraEvaluationSummary:
    values = list(cases)
    passed = sum(case.passed for case in values)
    blocked = sum(case.blocked for case in values)
    failed = len(values) - passed - blocked
    identity = [case.metrics.identity_similarity for case in values if case.metrics.identity_similarity is not None]
    speakers = [case.metrics.speaker_similarity for case in values if case.metrics.speaker_similarity is not None]
    transcripts = [case.metrics.transcript_similarity for case in values if case.metrics.transcript_similarity is not None]
    screening = bool(values) and passed == len(values)
    release = screening and all(case.certified for case in values)
    warnings = []
    if blocked:
        warnings.append("Install all identity, speech, and synchronization analyzers to resolve blocked checks.")
    if screening and not release:
        warnings.append("Local screening passed, but certified SyncNet evidence is incomplete or below threshold.")
    return IdLoraEvaluationSummary(
        case_count=len(values),
        passed_count=passed,
        failed_count=failed,
        blocked_count=blocked,
        average_identity=_mean(identity),
        average_speaker_similarity=_mean(speakers),
        average_transcript_similarity=_mean(transcripts),
        average_stability=sum(case.metrics.temporal_stability for case in values) / len(values) if values else 0.0,
        screening_ready=screening,
        release_ready=release,
        warnings=warnings,
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
