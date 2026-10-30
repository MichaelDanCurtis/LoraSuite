from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.benchmark_generation import (
    BenchmarkGenerationRun,
    BenchmarkGenerationService,
)
from lorasuite_engine.comfyui_handoff import (
    ComfyEvaluationReport,
    ComfyEvaluationReportService,
)
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.evaluation_harness import (
    BenchmarkCaseResult,
    BenchmarkRun,
    EvaluationHarnessService,
)
from lorasuite_engine.image_evaluation import (
    ImageBenchmarkCaseResult,
    ImageBenchmarkRun,
    ImageEvaluationHarnessService,
)
from lorasuite_engine.model_registry import ModelArtifactRecord, ModelRegistryService
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.video_dataset import VideoDatasetService


EVALUATION_COMPARISON_FORMAT = "lorasuite.artifact-comparison.v1"
IMPROVEMENT_REQUEST_FORMAT = "lorasuite.improvement-request.v1"
DATASET_REVISION_FORMAT = "lorasuite.dataset-revision.v1"

BenchmarkKind = Literal["image", "audio_visual"]
Comparability = Literal[
    "exact_baseline",
    "prompt_seed_matched",
    "case_matched",
    "partial",
]
MetricDirection = Literal["higher", "lower", "target"]
DeltaVerdict = Literal["improved", "regressed", "unchanged", "unavailable"]
COMPARABLE_METRICS = {
    "visual_quality",
    "aesthetic_score",
    "subject_coverage",
    "face_area",
    "body_coverage",
    "pose_coverage",
    "identity_similarity",
    "temporal_stability",
    "motion_score",
    "identity_frame_coverage",
    "audio_quality",
    "speaker_similarity",
    "transcript_similarity",
    "av_sync_proxy",
    "syncnet_lse_c",
    "syncnet_lse_d",
    "syncnet_offset_frames",
}


class ArtifactEvidenceRecord(BaseModel):
    artifact_id: str
    checkpoint_name: str
    checkpoint_sha256: str
    dataset_snapshot_id: str
    dataset_fingerprint: str
    training_run_id: str
    model_family: str
    modality: str
    benchmark_run_id: str
    benchmark_generation_run_id: str | None = None
    benchmark_status: str
    case_ids: list[str] = Field(default_factory=list)
    prompt_seed_signature: str | None = None
    baseline_signature: str | None = None
    comfy_report_ids: list[str] = Field(default_factory=list)


class MetricDelta(BaseModel):
    metric: str
    direction: MetricDirection
    reference_value: float | None = None
    candidate_value: float | None = None
    reference_baseline: float | None = None
    candidate_baseline: float | None = None
    reference_lift: float | None = None
    candidate_lift: float | None = None
    delta: float | None = None
    verdict: DeltaVerdict = "unavailable"


class EvaluationCaseComparison(BaseModel):
    case_id: str
    label: str
    prompt: str
    seed: int | None = None
    reference_passed: bool | None = None
    candidate_passed: bool
    reference_blocked: bool | None = None
    candidate_blocked: bool
    metrics: list[MetricDelta] = Field(default_factory=list)
    candidate_reasons: list[str] = Field(default_factory=list)


class ComfyEvidenceSummary(BaseModel):
    report_count: int = 0
    pass_count: int = 0
    review_count: int = 0
    fail_count: int = 0
    average_rating: float | None = None
    average_metrics: dict[str, float] = Field(default_factory=dict)


class ArtifactComparison(BaseModel):
    format: Literal["lorasuite.artifact-comparison.v1"] = EVALUATION_COMPARISON_FORMAT
    contract_version: int = 1
    id: str = Field(default_factory=lambda: new_id("artifact_comparison"))
    project_id: str
    benchmark_kind: BenchmarkKind
    comparison_kind: Literal["baseline_vs_artifact", "artifact_vs_artifact"]
    reference: ArtifactEvidenceRecord | None = None
    candidate: ArtifactEvidenceRecord
    comparability: Comparability
    comparability_notes: list[str] = Field(default_factory=list)
    cases: list[EvaluationCaseComparison] = Field(default_factory=list)
    aggregate_metrics: list[MetricDelta] = Field(default_factory=list)
    improved_count: int = 0
    regressed_count: int = 0
    unchanged_count: int = 0
    reference_comfy: ComfyEvidenceSummary | None = None
    candidate_comfy: ComfyEvidenceSummary = Field(default_factory=ComfyEvidenceSummary)
    created_at: Any = Field(default_factory=utc_now)


class ImprovementAction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("improvement_action"))
    category: Literal[
        "dataset_coverage",
        "curation",
        "caption_policy",
        "identity_evidence",
        "training_recipe",
        "video_data",
        "voice_data",
        "evaluation_setup",
    ]
    priority: Literal["high", "medium", "low"]
    title: str
    recommendation: str
    evidence: list[str] = Field(default_factory=list)
    automatic: bool = False


class ImprovementRequest(BaseModel):
    format: Literal["lorasuite.improvement-request.v1"] = IMPROVEMENT_REQUEST_FORMAT
    contract_version: int = 1
    id: str = Field(default_factory=lambda: new_id("improvement_request"))
    comparison_id: str
    project_id: str
    benchmark_kind: BenchmarkKind
    candidate_artifact_id: str
    candidate_checkpoint_sha256: str
    reference_artifact_id: str | None = None
    reference_checkpoint_sha256: str | None = None
    status: Literal["draft", "approved", "rejected"] = "draft"
    summary: str
    actions: list[ImprovementAction] = Field(default_factory=list)
    decision_note: str = ""
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    decided_at: Any | None = None


class ArtifactComparisonRequest(BaseModel):
    project_id: str
    benchmark_kind: BenchmarkKind
    candidate_artifact_id: str
    reference_artifact_id: str | None = None


class ImprovementDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = ""


class DatasetRevisionRecord(BaseModel):
    format: Literal["lorasuite.dataset-revision.v1"] = DATASET_REVISION_FORMAT
    contract_version: int = 1
    id: str = Field(default_factory=lambda: new_id("dataset_revision"))
    improvement_request_id: str
    comparison_id: str
    project_id: str
    modality: Literal["image", "video"]
    source_artifact_id: str
    source_checkpoint_sha256: str
    parent_snapshot_id: str
    parent_snapshot_fingerprint: str
    revision_snapshot_id: str
    revision_version: int
    action_ids: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"
    created_at: Any = Field(default_factory=utc_now)


class ImprovementLoopService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def comparisons_path(self) -> Path:
        return self.vault_root / "artifact_comparisons.json"

    @property
    def requests_path(self) -> Path:
        return self.vault_root / "improvement_requests.json"

    @property
    def revisions_path(self) -> Path:
        return self.vault_root / "dataset_revisions.json"

    def list_comparisons(
        self,
        *,
        project_id: str | None = None,
        benchmark_kind: BenchmarkKind | None = None,
    ) -> list[ArtifactComparison]:
        comparisons = self._read_comparisons().values()
        if project_id:
            comparisons = (
                item for item in comparisons if item.project_id == project_id
            )
        if benchmark_kind:
            comparisons = (
                item for item in comparisons
                if item.benchmark_kind == benchmark_kind
            )
        return sorted(comparisons, key=lambda item: item.created_at, reverse=True)

    def get_comparison(self, comparison_id: str) -> ArtifactComparison | None:
        return self._read_comparisons().get(comparison_id)

    def create_comparison(
        self,
        request: ArtifactComparisonRequest,
    ) -> ArtifactComparison:
        registry = ModelRegistryService(self.vault_root)
        candidate = self._require_artifact(
            registry,
            request.candidate_artifact_id,
            request.project_id,
            request.benchmark_kind,
        )
        reference = None
        if request.reference_artifact_id:
            if request.reference_artifact_id == request.candidate_artifact_id:
                raise ValueError("reference and candidate artifacts must be different")
            reference = self._require_artifact(
                registry,
                request.reference_artifact_id,
                request.project_id,
                request.benchmark_kind,
            )
        candidate_run = self._latest_benchmark_run(
            candidate.id,
            request.benchmark_kind,
        )
        if candidate_run is None:
            raise ValueError("candidate artifact has no completed benchmark run")
        reference_run = None
        if reference is not None:
            reference_run = self._latest_benchmark_run(
                reference.id,
                request.benchmark_kind,
            )
            if reference_run is None:
                raise ValueError("reference artifact has no completed benchmark run")
        candidate_generation = self._generation_for(candidate_run.id)
        reference_generation = (
            self._generation_for(reference_run.id)
            if reference_run is not None
            else None
        )
        candidate_reports = ComfyEvaluationReportService(
            self.vault_root
        ).list_reports(artifact_id=candidate.id)
        reference_reports = (
            ComfyEvaluationReportService(self.vault_root).list_reports(
                artifact_id=reference.id
            )
            if reference is not None
            else []
        )
        comparability, notes = _comparability(
            candidate_run,
            reference_run,
            candidate_generation,
            reference_generation,
        )
        cases = _compare_cases(
            candidate_run,
            reference_run,
            candidate_generation,
        )
        aggregate = _aggregate_metrics(cases)
        comparison = ArtifactComparison(
            project_id=request.project_id,
            benchmark_kind=request.benchmark_kind,
            comparison_kind=(
                "artifact_vs_artifact"
                if reference is not None
                else "baseline_vs_artifact"
            ),
            reference=(
                _evidence_record(
                    reference,
                    reference_run,
                    reference_generation,
                    reference_reports,
                )
                if reference is not None and reference_run is not None
                else None
            ),
            candidate=_evidence_record(
                candidate,
                candidate_run,
                candidate_generation,
                candidate_reports,
            ),
            comparability=comparability,
            comparability_notes=notes,
            cases=cases,
            aggregate_metrics=aggregate,
            improved_count=sum(item.verdict == "improved" for item in aggregate),
            regressed_count=sum(item.verdict == "regressed" for item in aggregate),
            unchanged_count=sum(item.verdict == "unchanged" for item in aggregate),
            reference_comfy=(
                _comfy_summary(reference_reports)
                if reference is not None
                else None
            ),
            candidate_comfy=_comfy_summary(candidate_reports),
        )
        comparisons = self._read_comparisons()
        comparisons[comparison.id] = comparison
        self._write_comparisons(comparisons)
        return comparison

    def list_requests(
        self,
        *,
        project_id: str | None = None,
        status: Literal["draft", "approved", "rejected"] | None = None,
    ) -> list[ImprovementRequest]:
        requests = self._read_requests().values()
        if project_id:
            requests = (item for item in requests if item.project_id == project_id)
        if status:
            requests = (item for item in requests if item.status == status)
        return sorted(requests, key=lambda item: item.created_at, reverse=True)

    def get_request(self, request_id: str) -> ImprovementRequest | None:
        return self._read_requests().get(request_id)

    def create_request(self, comparison_id: str) -> ImprovementRequest:
        comparison = self.get_comparison(comparison_id)
        if comparison is None:
            raise KeyError(comparison_id)
        existing = next(
            (
                item for item in self._read_requests().values()
                if item.comparison_id == comparison.id and item.status == "draft"
            ),
            None,
        )
        if existing is not None:
            return existing
        actions = _improvement_actions(comparison)
        request = ImprovementRequest(
            comparison_id=comparison.id,
            project_id=comparison.project_id,
            benchmark_kind=comparison.benchmark_kind,
            candidate_artifact_id=comparison.candidate.artifact_id,
            candidate_checkpoint_sha256=comparison.candidate.checkpoint_sha256,
            reference_artifact_id=(
                comparison.reference.artifact_id
                if comparison.reference is not None
                else None
            ),
            reference_checkpoint_sha256=(
                comparison.reference.checkpoint_sha256
                if comparison.reference is not None
                else None
            ),
            summary=_improvement_summary(comparison, actions),
            actions=actions,
        )
        requests = self._read_requests()
        requests[request.id] = request
        self._write_requests(requests)
        return request

    def decide_request(
        self,
        request_id: str,
        decision: ImprovementDecisionRequest,
    ) -> ImprovementRequest:
        requests = self._read_requests()
        request = requests.get(request_id)
        if request is None:
            raise KeyError(request_id)
        if request.status != "draft":
            raise ValueError("only a draft improvement request can be decided")
        request.status = decision.decision
        request.decision_note = decision.note.strip()
        request.decided_at = utc_now()
        request.updated_at = request.decided_at
        requests[request.id] = request
        self._write_requests(requests)
        return request

    def list_revisions(
        self,
        *,
        project_id: str | None = None,
    ) -> list[DatasetRevisionRecord]:
        revisions = self._read_revisions().values()
        if project_id:
            revisions = (
                item for item in revisions if item.project_id == project_id
            )
        return sorted(revisions, key=lambda item: item.created_at, reverse=True)

    def materialize_revision(
        self,
        request_id: str,
    ) -> DatasetRevisionRecord:
        request = self.get_request(request_id)
        if request is None:
            raise KeyError(request_id)
        if request.status != "approved":
            raise ValueError(
                "approve the improvement request before creating a dataset revision"
            )
        revisions = self._read_revisions()
        existing = next(
            (
                item for item in revisions.values()
                if item.improvement_request_id == request.id
            ),
            None,
        )
        if existing is not None:
            return existing
        artifact = ModelRegistryService(self.vault_root).get_artifact(
            request.candidate_artifact_id
        )
        if artifact is None:
            raise ValueError("the source model artifact is no longer registered")
        if artifact.checkpoint_sha256 != request.candidate_checkpoint_sha256:
            raise ValueError(
                "the source checkpoint SHA-256 no longer matches the approved request"
            )
        if artifact.project_id != request.project_id:
            raise ValueError("the source artifact project no longer matches")
        plan = [
            f"{action.title}: {action.recommendation}"
            for action in request.actions
        ]
        if artifact.modality == "image":
            source = DatasetCompilerService(self.vault_root).get_snapshot(
                artifact.snapshot_id
            )
            if source is None:
                raise ValueError("the source image dataset snapshot is unavailable")
            if source.fingerprint != artifact.dataset_fingerprint:
                raise ValueError(
                    "the source image dataset fingerprint does not match the artifact"
                )
            revision = DatasetCompilerService(self.vault_root).create_revision(
                source.id,
                improvement_request_id=request.id,
                source_artifact_id=artifact.id,
                source_checkpoint_sha256=artifact.checkpoint_sha256,
                revision_plan=plan,
            )
            modality: Literal["image", "video"] = "image"
        elif artifact.modality == "video":
            source = VideoDatasetService(self.vault_root).get_snapshot(
                artifact.snapshot_id
            )
            if source is None:
                raise ValueError("the source video dataset snapshot is unavailable")
            if source.fingerprint != artifact.dataset_fingerprint:
                raise ValueError(
                    "the source video dataset fingerprint does not match the artifact"
                )
            revision = VideoDatasetService(self.vault_root).create_revision(
                source.id,
                improvement_request_id=request.id,
                source_artifact_id=artifact.id,
                source_checkpoint_sha256=artifact.checkpoint_sha256,
                revision_plan=plan,
            )
            modality = "video"
        else:
            raise ValueError(
                f"dataset revision materialization is not implemented for "
                f"{artifact.modality} artifacts"
            )
        record = DatasetRevisionRecord(
            improvement_request_id=request.id,
            comparison_id=request.comparison_id,
            project_id=request.project_id,
            modality=modality,
            source_artifact_id=artifact.id,
            source_checkpoint_sha256=artifact.checkpoint_sha256,
            parent_snapshot_id=source.id,
            parent_snapshot_fingerprint=source.fingerprint or "",
            revision_snapshot_id=revision.id,
            revision_version=revision.version,
            action_ids=[action.id for action in request.actions],
        )
        revisions[record.id] = record
        self._write_revisions(revisions)
        return record

    def _latest_benchmark_run(
        self,
        artifact_id: str,
        benchmark_kind: BenchmarkKind,
    ) -> ImageBenchmarkRun | BenchmarkRun | None:
        service = (
            ImageEvaluationHarnessService(self.vault_root)
            if benchmark_kind == "image"
            else EvaluationHarnessService(self.vault_root)
        )
        return next(
            (
                run for run in service.list_runs()
                if run.artifact_id == artifact_id and run.status == "complete"
            ),
            None,
        )

    def _generation_for(
        self,
        benchmark_run_id: str,
    ) -> BenchmarkGenerationRun | None:
        return next(
            (
                run for run in BenchmarkGenerationService(
                    self.vault_root
                ).list_runs()
                if run.benchmark_run_id == benchmark_run_id
                and run.status == "completed"
            ),
            None,
        )

    @staticmethod
    def _require_artifact(
        registry: ModelRegistryService,
        artifact_id: str,
        project_id: str,
        benchmark_kind: BenchmarkKind,
    ) -> ModelArtifactRecord:
        artifact = registry.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        if artifact.project_id != project_id:
            raise ValueError("artifact belongs to a different character project")
        allowed = (
            {"image"}
            if benchmark_kind == "image"
            else {"video", "audio_visual"}
        )
        if artifact.modality not in allowed:
            raise ValueError(
                f"{benchmark_kind.replace('_', '-')} comparison does not support "
                f"{artifact.modality} artifacts"
            )
        return artifact

    def _read_comparisons(self) -> dict[str, ArtifactComparison]:
        with json_file_lock(self.comparisons_path):
            if not self.comparisons_path.exists():
                return {}
            payload = json.loads(
                self.comparisons_path.read_text(encoding="utf-8")
            )
            return {
                item.id: item
                for raw in payload.get("comparisons", [])
                if (item := ArtifactComparison.model_validate(raw))
            }

    def _write_comparisons(
        self,
        comparisons: dict[str, ArtifactComparison],
    ) -> None:
        with json_file_lock(self.comparisons_path):
            atomic_write_json(
                self.comparisons_path,
                {
                    "version": 1,
                    "format": EVALUATION_COMPARISON_FORMAT,
                    "comparisons": [
                        item.model_dump(mode="json")
                        for item in comparisons.values()
                    ],
                },
            )

    def _read_requests(self) -> dict[str, ImprovementRequest]:
        with json_file_lock(self.requests_path):
            if not self.requests_path.exists():
                return {}
            payload = json.loads(self.requests_path.read_text(encoding="utf-8"))
            return {
                item.id: item
                for raw in payload.get("requests", [])
                if (item := ImprovementRequest.model_validate(raw))
            }

    def _write_requests(
        self,
        requests: dict[str, ImprovementRequest],
    ) -> None:
        with json_file_lock(self.requests_path):
            atomic_write_json(
                self.requests_path,
                {
                    "version": 1,
                    "format": IMPROVEMENT_REQUEST_FORMAT,
                    "requests": [
                        item.model_dump(mode="json")
                        for item in requests.values()
                    ],
                },
            )

    def _read_revisions(self) -> dict[str, DatasetRevisionRecord]:
        with json_file_lock(self.revisions_path):
            if not self.revisions_path.exists():
                return {}
            payload = json.loads(self.revisions_path.read_text(encoding="utf-8"))
            return {
                item.id: item
                for raw in payload.get("revisions", [])
                if (item := DatasetRevisionRecord.model_validate(raw))
            }

    def _write_revisions(
        self,
        revisions: dict[str, DatasetRevisionRecord],
    ) -> None:
        with json_file_lock(self.revisions_path):
            atomic_write_json(
                self.revisions_path,
                {
                    "version": 1,
                    "format": DATASET_REVISION_FORMAT,
                    "revisions": [
                        item.model_dump(mode="json")
                        for item in revisions.values()
                    ],
                },
            )


def _evidence_record(
    artifact: ModelArtifactRecord,
    run: ImageBenchmarkRun | BenchmarkRun,
    generation: BenchmarkGenerationRun | None,
    reports: list[ComfyEvaluationReport],
) -> ArtifactEvidenceRecord:
    return ArtifactEvidenceRecord(
        artifact_id=artifact.id,
        checkpoint_name=artifact.checkpoint_name,
        checkpoint_sha256=artifact.checkpoint_sha256,
        dataset_snapshot_id=artifact.snapshot_id,
        dataset_fingerprint=artifact.dataset_fingerprint,
        training_run_id=artifact.training_run_id,
        model_family=artifact.model_family,
        modality=artifact.modality,
        benchmark_run_id=run.id,
        benchmark_generation_run_id=generation.id if generation else None,
        benchmark_status=run.status,
        case_ids=sorted(run.cases),
        prompt_seed_signature=_prompt_seed_signature(generation),
        baseline_signature=_baseline_signature(run),
        comfy_report_ids=[item.id for item in reports],
    )


def _comparability(
    candidate: ImageBenchmarkRun | BenchmarkRun,
    reference: ImageBenchmarkRun | BenchmarkRun | None,
    candidate_generation: BenchmarkGenerationRun | None,
    reference_generation: BenchmarkGenerationRun | None,
) -> tuple[Comparability, list[str]]:
    if reference is None:
        if candidate_generation is not None:
            return (
                "prompt_seed_matched",
                ["Baseline and LoRA outputs used the same prompt and seed contract."],
            )
        return (
            "case_matched",
            ["The run used the same named cases, but no cloud prompt and seed record is linked."],
        )
    candidate_cases = set(candidate.cases)
    reference_cases = set(reference.cases)
    if candidate_cases != reference_cases:
        return (
            "partial",
            ["Only benchmark cases present in both artifact runs were compared."],
        )
    candidate_prompt_seed = _prompt_seed_signature(candidate_generation)
    reference_prompt_seed = _prompt_seed_signature(reference_generation)
    if (
        candidate_prompt_seed
        and candidate_prompt_seed == reference_prompt_seed
    ):
        candidate_baseline = _baseline_signature(candidate)
        reference_baseline = _baseline_signature(reference)
        if candidate_baseline and candidate_baseline == reference_baseline:
            return (
                "exact_baseline",
                ["Both artifacts share identical baseline files, prompts, and seeds."],
            )
        return (
            "prompt_seed_matched",
            ["Both artifacts used the same prompts and seeds; deltas are normalized against each run's baseline."],
        )
    return (
        "case_matched",
        ["Named benchmark cases match, but prompt and seed lineage is incomplete or different."],
    )


def _compare_cases(
    candidate: ImageBenchmarkRun | BenchmarkRun,
    reference: ImageBenchmarkRun | BenchmarkRun | None,
    candidate_generation: BenchmarkGenerationRun | None,
) -> list[EvaluationCaseComparison]:
    comparisons = []
    shared_ids = sorted(
        set(candidate.cases)
        if reference is None
        else set(candidate.cases).intersection(reference.cases)
    )
    seeds = _case_seeds(candidate_generation)
    for case_id in shared_ids:
        candidate_case = candidate.cases[case_id]
        reference_case = reference.cases[case_id] if reference is not None else None
        metrics = _case_metric_deltas(candidate_case, reference_case)
        comparisons.append(
            EvaluationCaseComparison(
                case_id=case_id,
                label=candidate_case.definition.label,
                prompt=candidate_case.definition.prompt,
                seed=seeds.get(case_id),
                reference_passed=(
                    reference_case.passed
                    if reference_case is not None
                    else None
                ),
                candidate_passed=candidate_case.passed,
                reference_blocked=(
                    reference_case.blocked
                    if reference_case is not None
                    else None
                ),
                candidate_blocked=candidate_case.blocked,
                metrics=metrics,
                candidate_reasons=list(candidate_case.reasons),
            )
        )
    return comparisons


def _case_metric_deltas(
    candidate: ImageBenchmarkCaseResult | BenchmarkCaseResult,
    reference: ImageBenchmarkCaseResult | BenchmarkCaseResult | None,
) -> list[MetricDelta]:
    candidate_metrics = candidate.lora.model_dump()
    candidate_baseline = candidate.baseline.model_dump()
    reference_metrics = (
        reference.lora.model_dump()
        if reference is not None
        else candidate_baseline
    )
    reference_baseline = (
        reference.baseline.model_dump()
        if reference is not None
        else candidate_baseline
    )
    names = sorted(
        name
        for name in set(candidate_metrics).intersection(reference_metrics)
        if name in COMPARABLE_METRICS
        and _number_or_none(candidate_metrics.get(name)) is not None
        and _number_or_none(reference_metrics.get(name)) is not None
    )
    deltas = []
    for name in names:
        candidate_value = _number_or_none(candidate_metrics.get(name))
        reference_value = _number_or_none(reference_metrics.get(name))
        candidate_base = _number_or_none(candidate_baseline.get(name))
        reference_base = _number_or_none(reference_baseline.get(name))
        candidate_lift = _subtract(candidate_value, candidate_base)
        reference_lift = _subtract(reference_value, reference_base)
        delta = (
            _subtract(candidate_value, reference_value)
            if reference is None
            else _subtract(candidate_lift, reference_lift)
        )
        direction = _metric_direction(name)
        deltas.append(
            MetricDelta(
                metric=name,
                direction=direction,
                reference_value=reference_value,
                candidate_value=candidate_value,
                reference_baseline=reference_base,
                candidate_baseline=candidate_base,
                reference_lift=reference_lift,
                candidate_lift=candidate_lift,
                delta=delta,
                verdict=_delta_verdict(
                    name,
                    reference_value,
                    candidate_value,
                    delta,
                    reference is not None,
                ),
            )
        )
    return deltas


def _aggregate_metrics(
    cases: list[EvaluationCaseComparison],
) -> list[MetricDelta]:
    names = sorted({item.metric for case in cases for item in case.metrics})
    aggregates = []
    for name in names:
        values = [
            item
            for case in cases
            for item in case.metrics
            if item.metric == name
        ]
        aggregates.append(
            MetricDelta(
                metric=name,
                direction=_metric_direction(name),
                reference_value=_mean_optional(
                    [item.reference_value for item in values]
                ),
                candidate_value=_mean_optional(
                    [item.candidate_value for item in values]
                ),
                reference_baseline=_mean_optional(
                    [item.reference_baseline for item in values]
                ),
                candidate_baseline=_mean_optional(
                    [item.candidate_baseline for item in values]
                ),
                reference_lift=_mean_optional(
                    [item.reference_lift for item in values]
                ),
                candidate_lift=_mean_optional(
                    [item.candidate_lift for item in values]
                ),
                delta=_mean_optional([item.delta for item in values]),
                verdict=_aggregate_verdict(values),
            )
        )
    return aggregates


def _improvement_actions(
    comparison: ArtifactComparison,
) -> list[ImprovementAction]:
    evidence: dict[str, set[str]] = {}
    priorities: dict[str, Literal["high", "medium", "low"]] = {}

    def add(
        key: str,
        priority: Literal["high", "medium", "low"],
        value: str,
    ) -> None:
        evidence.setdefault(key, set()).add(value)
        order = {"low": 0, "medium": 1, "high": 2}
        if order[priority] > order.get(priorities.get(key, "low"), 0):
            priorities[key] = priority

    for case in comparison.cases:
        for metric in case.metrics:
            if metric.verdict == "regressed":
                add(metric.metric, "high", f"{case.case_id}:{metric.metric}")
        for reason in case.candidate_reasons:
            normalized = reason.lower().replace("failed ", "").strip()
            add(normalized.replace(" ", "_"), "high", f"{case.case_id}:{reason}")
        if case.candidate_blocked:
            add("evaluation_setup", "high", f"{case.case_id}:blocked")
        elif not case.candidate_passed:
            add("candidate_failure", "medium", f"{case.case_id}:failed")

    templates: list[
        tuple[
            set[str],
            str,
            str,
            str,
        ]
    ] = [
        (
            {"identity_similarity", "identity_gain", "identity_frame_coverage"},
            "identity_evidence",
            "Strengthen identity coverage",
            "Review trusted anchors and add underrepresented face angles or stable identity frames before compiling a new dataset revision.",
        ),
        (
            {"visual_quality", "aesthetic_quality", "aesthetic_score"},
            "curation",
            "Raise visual quality",
            "Review low-quality, blurred, compressed, or artifact-heavy training items and stage exclusions or replacements for the next revision.",
        ),
        (
            {
                "composition",
                "subject_coverage",
                "face_area",
                "body_coverage",
                "pose_coverage",
            },
            "dataset_coverage",
            "Repair framing and pose coverage",
            "Add or recrop examples for the failed face, upper-body, full-body, or pose ranges identified by the benchmark cases.",
        ),
        (
            {"temporal_stability", "motion_range", "motion_score"},
            "video_data",
            "Improve temporal training evidence",
            "Review unstable clips, repeated motion, and weak subject continuity; stage cleaner motion ranges before building the next video dataset.",
        ),
        (
            {"audio_quality", "speaker_similarity", "transcript_similarity"},
            "voice_data",
            "Improve voice evidence",
            "Review speaker anchors, transcripts, music contamination, clipping, and noise; stage only verified speech for the next voice or audio-visual revision.",
        ),
        (
            {
                "av_sync_proxy",
                "syncnet_lse_c",
                "syncnet_lse_d",
                "syncnet_offset",
                "syncnet_offset_frames",
            },
            "evaluation_setup",
            "Resolve audio-visual synchronization",
            "Inspect synchronized source clips and certified SyncNet evidence before changing training data or promoting the artifact.",
        ),
        (
            {"evaluation_setup"},
            "evaluation_setup",
            "Complete blocked evaluation evidence",
            "Install the required identity, speaker, or synchronization runtime and rerun the same cases before drawing a training conclusion.",
        ),
        (
            {"candidate_failure"},
            "evaluation_setup",
            "Review failed benchmark cases",
            "Inspect the failed matched outputs and their case-level checks before changing the frozen dataset or training recipe.",
        ),
    ]
    actions = []
    consumed: set[str] = set()
    for keys, category, title, recommendation in templates:
        matched = keys.intersection(evidence)
        if not matched:
            continue
        consumed.update(matched)
        action_evidence = sorted(
            value for key in matched for value in evidence[key]
        )
        actions.append(
            ImprovementAction(
                category=category,
                priority=max(
                    (priorities.get(key, "medium") for key in matched),
                    key={"low": 0, "medium": 1, "high": 2}.get,
                ),
                title=title,
                recommendation=recommendation,
                evidence=action_evidence,
            )
        )
    if (
        comparison.regressed_count
        and any(
            metric.metric in {"identity_similarity", "visual_quality"}
            and metric.verdict == "regressed"
            for metric in comparison.aggregate_metrics
        )
    ):
        actions.append(
            ImprovementAction(
                category="training_recipe",
                priority="medium",
                title="Review training intensity",
                recommendation="Compare rank, learning rate, repeats, epochs, and checkpoint timing with the reference revision before retraining; the measured regression may indicate overtraining or an incompatible recipe change.",
                evidence=[
                    f"aggregate:{metric.metric}"
                    for metric in comparison.aggregate_metrics
                    if metric.verdict == "regressed"
                ],
            )
        )
    if not actions:
        actions.append(
            ImprovementAction(
                category="evaluation_setup",
                priority="low",
                title="Preserve the current revision",
                recommendation="No measured regression or failed gate produced a concrete data change. Keep the frozen dataset unchanged and collect additional matched human or ComfyUI evidence before proposing a revision.",
                evidence=[f"comparison:{comparison.id}"],
            )
        )
    return actions


def _improvement_summary(
    comparison: ArtifactComparison,
    actions: list[ImprovementAction],
) -> str:
    if comparison.regressed_count:
        return (
            f"{comparison.regressed_count} aggregate metric(s) regressed and "
            f"{comparison.improved_count} improved. {len(actions)} evidence-backed "
            "action(s) are staged for human approval."
        )
    if any(not case.candidate_passed for case in comparison.cases):
        failed = sum(not case.candidate_passed for case in comparison.cases)
        return (
            f"{failed} benchmark case(s) did not pass. {len(actions)} "
            "evidence-backed action(s) are staged for human approval."
        )
    return (
        f"No measured regression requires an automatic data change. "
        f"{len(actions)} conservative follow-up action(s) are staged for review."
    )


def _comfy_summary(
    reports: list[ComfyEvaluationReport],
) -> ComfyEvidenceSummary:
    ratings = [report.rating for report in reports if report.rating > 0]
    metric_names = sorted(
        {name for report in reports for name in report.metrics}
    )
    return ComfyEvidenceSummary(
        report_count=len(reports),
        pass_count=sum(report.verdict == "pass" for report in reports),
        review_count=sum(report.verdict == "review" for report in reports),
        fail_count=sum(report.verdict == "fail" for report in reports),
        average_rating=(
            sum(ratings) / len(ratings)
            if ratings
            else None
        ),
        average_metrics={
            name: sum(values) / len(values)
            for name in metric_names
            if (
                values := [
                    report.metrics[name]
                    for report in reports
                    if name in report.metrics
                ]
            )
        },
    )


def _prompt_seed_signature(
    generation: BenchmarkGenerationRun | None,
) -> str | None:
    if generation is None:
        return None
    values = sorted(
        (
            item.case_id,
            item.variant,
            item.prompt,
            item.seed,
        )
        for item in generation.items
    )
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _case_seeds(
    generation: BenchmarkGenerationRun | None,
) -> dict[str, int]:
    if generation is None:
        return {}
    return {
        item.case_id: item.seed
        for item in generation.items
        if item.variant == "lora"
    }


def _baseline_signature(
    run: ImageBenchmarkRun | BenchmarkRun,
) -> str | None:
    values = []
    for case_id, case in sorted(run.cases.items()):
        path = Path(case.baseline_path)
        digest = _sha256_file(path)
        if digest is None:
            return None
        values.append((case_id, digest))
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metric_direction(name: str) -> MetricDirection:
    if name in {"syncnet_lse_d"}:
        return "lower"
    if name in {"motion_score", "syncnet_offset_frames"}:
        return "target"
    return "higher"


def _delta_verdict(
    name: str,
    reference_value: float | None,
    candidate_value: float | None,
    delta: float | None,
    normalized: bool,
) -> DeltaVerdict:
    if reference_value is None or candidate_value is None or delta is None:
        return "unavailable"
    threshold = 0.02
    direction = _metric_direction(name)
    if direction == "target":
        target = 0.35 if name == "motion_score" else 0.0
        reference_distance = abs(reference_value - target)
        candidate_distance = abs(candidate_value - target)
        change = reference_distance - candidate_distance
    else:
        change = delta if direction == "higher" else -delta
        if normalized and name == "syncnet_lse_d":
            change = -delta
    if change > threshold:
        return "improved"
    if change < -threshold:
        return "regressed"
    return "unchanged"


def _aggregate_verdict(values: list[MetricDelta]) -> DeltaVerdict:
    available = [item for item in values if item.verdict != "unavailable"]
    if not available:
        return "unavailable"
    improved = sum(item.verdict == "improved" for item in available)
    regressed = sum(item.verdict == "regressed" for item in available)
    if improved > regressed:
        return "improved"
    if regressed > improved:
        return "regressed"
    return "unchanged"


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _mean_optional(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None
