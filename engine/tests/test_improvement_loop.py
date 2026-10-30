from pathlib import Path

import pytest

from lorasuite_engine.benchmark_generation import (
    BenchmarkGenerationItem,
    BenchmarkGenerationRun,
)
from lorasuite_engine.comfyui_handoff import (
    ComfyEvaluationReportRequest,
    ComfyEvaluationReportService,
)
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.image_evaluation import (
    ImageBenchmarkCaseResult,
    ImageBenchmarkMetrics,
    ImageBenchmarkRun,
    default_image_benchmark_suite,
)
from lorasuite_engine.improvement_loop import (
    ArtifactComparisonRequest,
    ImprovementDecisionRequest,
    ImprovementRequest,
    ImprovementLoopService,
)
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord
from lorasuite_engine.models import (
    DatasetCaptionRecord,
    DatasetItemStatus,
    DatasetSnapshot,
    DatasetSnapshotStatus,
    TrainingIntent,
)
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.video_dataset import (
    VideoDatasetItem,
    VideoDatasetService,
    VideoDatasetSnapshot,
)


def _artifact(
    vault_root: Path,
    *,
    artifact_id: str,
    checkpoint_sha: str,
    training_run_id: str,
) -> ModelArtifactRecord:
    return ModelArtifactRecord(
        id=artifact_id,
        project_id="project-1",
        training_run_id=training_run_id,
        snapshot_id=f"snapshot-{artifact_id}",
        dataset_fingerprint=f"fingerprint-{artifact_id}",
        checkpoint_name=f"{artifact_id}.safetensors",
        checkpoint_path=vault_root / f"{artifact_id}.safetensors",
        checkpoint_sha256=checkpoint_sha,
        checkpoint_size_bytes=1024,
        modality="image",
        model_family="flux1",
        evaluation=ArtifactEvaluation(
            status="ready",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )


def _metrics(
    *,
    identity: float,
    quality: float,
    aesthetic: float = 0.7,
) -> ImageBenchmarkMetrics:
    return ImageBenchmarkMetrics(
        visual_quality=quality,
        aesthetic_score=aesthetic,
        subject_coverage=0.8,
        face_count=1,
        face_area=0.1,
        body_coverage=0.3,
        pose_coverage=0.6,
        identity_similarity=identity,
    )


def _run(
    root: Path,
    *,
    run_id: str,
    artifact_id: str,
    baseline_path: Path,
    lora_path: Path,
    lora_identity: float,
    lora_quality: float,
) -> ImageBenchmarkRun:
    definition = default_image_benchmark_suite()[0]
    case = ImageBenchmarkCaseResult(
        definition=definition,
        baseline_path=baseline_path,
        lora_path=lora_path,
        baseline=_metrics(identity=0.30, quality=0.65),
        lora=_metrics(identity=lora_identity, quality=lora_quality),
        passed=True,
        blocked=False,
        checks={"identity_similarity": True, "visual_quality": True},
    )
    return ImageBenchmarkRun(
        id=run_id,
        project_id="project-1",
        artifact_id=artifact_id,
        baseline_dir=root,
        lora_dir=root,
        status="complete",
        cases={definition.id: case},
    )


def _generation(
    root: Path,
    *,
    run_id: str,
    benchmark_run_id: str,
    artifact_id: str,
    output_path: Path,
) -> BenchmarkGenerationRun:
    definition = default_image_benchmark_suite()[0]
    prompt = definition.prompt.replace("{trigger}", "person_token")
    return BenchmarkGenerationRun(
        id=run_id,
        benchmark_kind="image",
        project_id="project-1",
        model_id="flux-model",
        lora_path=f"{artifact_id}.safetensors",
        artifact_id=artifact_id,
        workspace_root=root,
        baseline_dir=root,
        lora_dir=root,
        status="completed",
        benchmark_run_id=benchmark_run_id,
        progress_current=2,
        progress_total=2,
        items=[
            BenchmarkGenerationItem(
                id=f"{definition.id}:baseline",
                case_id=definition.id,
                variant="baseline",
                media_type="image",
                filename=definition.filename,
                prompt=prompt,
                seed=424242,
                status="completed",
                output_path=output_path,
            ),
            BenchmarkGenerationItem(
                id=f"{definition.id}:lora",
                case_id=definition.id,
                variant="lora",
                media_type="image",
                filename=definition.filename,
                prompt=prompt,
                seed=424242,
                status="completed",
                output_path=output_path,
            ),
        ],
    )


def _fixture(vault_root: Path, tmp_path: Path) -> tuple[ModelArtifactRecord, ModelArtifactRecord]:
    reference = _artifact(
        vault_root,
        artifact_id="artifact-reference",
        checkpoint_sha="reference-sha",
        training_run_id="training-reference",
    )
    candidate = _artifact(
        vault_root,
        artifact_id="artifact-candidate",
        checkpoint_sha="candidate-sha",
        training_run_id="training-candidate",
    )
    atomic_write_json(
        vault_root / "model_artifacts.json",
        {
            "version": 1,
            "artifacts": [
                reference.model_dump(mode="json"),
                candidate.model_dump(mode="json"),
            ],
        },
    )
    baseline = tmp_path / "baseline.png"
    reference_lora = tmp_path / "reference.png"
    candidate_lora = tmp_path / "candidate.png"
    baseline.write_bytes(b"same baseline")
    reference_lora.write_bytes(b"reference")
    candidate_lora.write_bytes(b"candidate")
    reference_run = _run(
        tmp_path,
        run_id="benchmark-reference",
        artifact_id=reference.id,
        baseline_path=baseline,
        lora_path=reference_lora,
        lora_identity=0.65,
        lora_quality=0.80,
    )
    candidate_run = _run(
        tmp_path,
        run_id="benchmark-candidate",
        artifact_id=candidate.id,
        baseline_path=baseline,
        lora_path=candidate_lora,
        lora_identity=0.75,
        lora_quality=0.70,
    )
    atomic_write_json(
        vault_root / "image_benchmark_runs.json",
        {
            "version": 1,
            "runs": [
                reference_run.model_dump(mode="json"),
                candidate_run.model_dump(mode="json"),
            ],
        },
    )
    generations = [
        _generation(
            tmp_path,
            run_id="generation-reference",
            benchmark_run_id=reference_run.id,
            artifact_id=reference.id,
            output_path=baseline,
        ),
        _generation(
            tmp_path,
            run_id="generation-candidate",
            benchmark_run_id=candidate_run.id,
            artifact_id=candidate.id,
            output_path=baseline,
        ),
    ]
    atomic_write_json(
        vault_root / "benchmark_generation_runs.json",
        {
            "version": 1,
            "runs": [item.model_dump(mode="json") for item in generations],
        },
    )
    return reference, candidate


def test_compares_artifact_revisions_with_exact_provenance(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    reference, candidate = _fixture(vault_root, tmp_path)
    report_service = ComfyEvaluationReportService(vault_root)
    report_service.record(
        ComfyEvaluationReportRequest(
            artifact_id=candidate.id,
            checkpoint_sha256=candidate.checkpoint_sha256,
            workflow_id="flux-evaluation",
            verdict="pass",
            rating=5,
            prompt="person_token, portrait",
            seed=424242,
            metrics={"identity_similarity": 0.9},
        ),
        project_id="project-1",
        expected_checkpoint_sha256=candidate.checkpoint_sha256,
    )

    comparison = ImprovementLoopService(vault_root).create_comparison(
        ArtifactComparisonRequest(
            project_id="project-1",
            benchmark_kind="image",
            reference_artifact_id=reference.id,
            candidate_artifact_id=candidate.id,
        )
    )

    assert comparison.format == "lorasuite.artifact-comparison.v1"
    assert comparison.comparability == "exact_baseline"
    assert comparison.reference is not None
    assert comparison.reference.checkpoint_sha256 == "reference-sha"
    assert comparison.candidate.checkpoint_sha256 == "candidate-sha"
    assert comparison.candidate_comfy.report_count == 1
    assert comparison.candidate_comfy.average_rating == 5
    metrics = {item.metric: item for item in comparison.aggregate_metrics}
    assert metrics["identity_similarity"].delta == pytest.approx(0.10)
    assert metrics["identity_similarity"].verdict == "improved"
    assert metrics["visual_quality"].delta == pytest.approx(-0.10)
    assert metrics["visual_quality"].verdict == "regressed"
    assert comparison.improved_count >= 1
    assert comparison.regressed_count >= 1


def test_stages_and_approves_non_executing_improvement_request(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    reference, candidate = _fixture(vault_root, tmp_path)
    service = ImprovementLoopService(vault_root)
    comparison = service.create_comparison(
        ArtifactComparisonRequest(
            project_id="project-1",
            benchmark_kind="image",
            reference_artifact_id=reference.id,
            candidate_artifact_id=candidate.id,
        )
    )
    registry_before = (vault_root / "model_artifacts.json").read_bytes()
    benchmarks_before = (vault_root / "image_benchmark_runs.json").read_bytes()

    request = service.create_request(comparison.id)

    assert request.status == "draft"
    assert request.candidate_checkpoint_sha256 == candidate.checkpoint_sha256
    assert any(action.category == "curation" for action in request.actions)
    assert all(action.automatic is False for action in request.actions)

    approved = service.decide_request(
        request.id,
        ImprovementDecisionRequest(
            decision="approved",
            note="Create a new revision after reviewing the flagged images.",
        ),
    )

    assert approved.status == "approved"
    assert approved.decision_note.startswith("Create a new revision")
    assert (vault_root / "model_artifacts.json").read_bytes() == registry_before
    assert (vault_root / "image_benchmark_runs.json").read_bytes() == benchmarks_before
    with pytest.raises(ValueError, match="only a draft"):
        service.decide_request(
            request.id,
            ImprovementDecisionRequest(decision="rejected"),
        )


def test_compares_candidate_against_its_matched_baseline(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _reference, candidate = _fixture(vault_root, tmp_path)

    comparison = ImprovementLoopService(vault_root).create_comparison(
        ArtifactComparisonRequest(
            project_id="project-1",
            benchmark_kind="image",
            candidate_artifact_id=candidate.id,
        )
    )

    assert comparison.comparison_kind == "baseline_vs_artifact"
    assert comparison.reference is None
    identity = next(
        item for item in comparison.aggregate_metrics
        if item.metric == "identity_similarity"
    )
    assert identity.reference_value == pytest.approx(0.30)
    assert identity.candidate_value == pytest.approx(0.75)
    assert identity.delta == pytest.approx(0.45)
    assert identity.verdict == "improved"


def test_rejects_cross_modality_and_missing_evidence(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    reference, candidate = _fixture(vault_root, tmp_path)
    service = ImprovementLoopService(vault_root)

    with pytest.raises(ValueError, match="audio-visual"):
        service.create_comparison(
            ArtifactComparisonRequest(
                project_id="project-1",
                benchmark_kind="audio_visual",
                candidate_artifact_id=candidate.id,
            )
        )


def test_materializes_approved_plan_as_new_immutable_lineage_draft(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    reference, candidate = _fixture(vault_root, tmp_path)
    source = DatasetSnapshot(
        id=candidate.snapshot_id,
        project_id="project-1",
        project_name="Person",
        version=2,
        status=DatasetSnapshotStatus.EXPORTED,
        intent=TrainingIntent(trigger_token="person_token"),
        training_target=get_training_target_profile(
            "runcomfy_flux1_dev_character"
        ).spec(),
        items={
            "item-1": DatasetCaptionRecord(
                id="item-1",
                source_media_item_id="media-1",
                training_media_item_id="media-1",
                caption="person_token, portrait",
                status=DatasetItemStatus.APPROVED,
            )
        },
        fingerprint=candidate.dataset_fingerprint,
        export_path=tmp_path / "exported-dataset",
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [source.model_dump(mode="json")]},
    )
    service = ImprovementLoopService(vault_root)
    comparison = service.create_comparison(
        ArtifactComparisonRequest(
            project_id="project-1",
            benchmark_kind="image",
            reference_artifact_id=reference.id,
            candidate_artifact_id=candidate.id,
        )
    )
    request = service.create_request(comparison.id)
    with pytest.raises(ValueError, match="approve"):
        service.materialize_revision(request.id)
    approved = service.decide_request(
        request.id,
        ImprovementDecisionRequest(decision="approved"),
    )
    source_before = (vault_root / "dataset_snapshots.json").read_text()

    record = service.materialize_revision(approved.id)

    assert record.format == "lorasuite.dataset-revision.v1"
    assert record.parent_snapshot_id == source.id
    assert record.parent_snapshot_fingerprint == source.fingerprint
    assert record.revision_version == 3
    snapshots = {
        item.id: item
        for item in __import__(
            "lorasuite_engine.dataset_compiler",
            fromlist=["DatasetCompilerService"],
        ).DatasetCompilerService(vault_root).list_snapshots()
    }
    original = snapshots[source.id]
    revision = snapshots[record.revision_snapshot_id]
    assert original.status == DatasetSnapshotStatus.EXPORTED
    assert original.fingerprint == source.fingerprint
    assert original.export_path == source.export_path
    assert revision.status == DatasetSnapshotStatus.DRAFT
    assert revision.fingerprint is None
    assert revision.export_path is None
    assert revision.parent_snapshot_id == source.id
    assert revision.improvement_request_id == approved.id
    assert revision.source_artifact_id == candidate.id
    assert revision.items["item-1"].caption == source.items["item-1"].caption
    assert revision.items["item-1"].status == source.items["item-1"].status
    assert revision.revision_plan
    assert revision.model_card is not None
    assert revision.model_card.provenance["parent_dataset_snapshot_id"] == source.id
    assert service.materialize_revision(approved.id).id == record.id
    persisted_original = DatasetCompilerService(vault_root).get_snapshot(source.id)
    assert persisted_original is not None
    assert persisted_original.model_dump(mode="json") == source.model_dump(mode="json")
    assert (vault_root / "dataset_snapshots.json").read_text() != source_before

    atomic_write_json(
        vault_root / "image_benchmark_runs.json",
        {"version": 1, "runs": []},
    )
    with pytest.raises(ValueError, match="no completed benchmark"):
        service.create_comparison(
            ArtifactComparisonRequest(
                project_id="project-1",
                benchmark_kind="image",
                reference_artifact_id=reference.id,
                candidate_artifact_id=candidate.id,
            )
        )


def test_materializes_video_revision_without_mutating_exported_source(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    artifact = ModelArtifactRecord(
        id="artifact-video",
        project_id="project-video",
        training_run_id="training-video",
        snapshot_id="video-snapshot-1",
        dataset_fingerprint="video-fingerprint-1",
        checkpoint_name="person-wan.safetensors",
        checkpoint_path=tmp_path / "person-wan.safetensors",
        checkpoint_sha256="video-checkpoint-sha",
        checkpoint_size_bytes=2048,
        modality="video",
        model_family="wan22_14b_t2v",
        evaluation=ArtifactEvaluation(
            status="ready",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )
    atomic_write_json(
        vault_root / "model_artifacts.json",
        {"version": 1, "artifacts": [artifact.model_dump(mode="json")]},
    )
    source = VideoDatasetSnapshot(
        id=artifact.snapshot_id,
        project_id=artifact.project_id,
        project_name="Person",
        version=4,
        status="exported",
        trigger_token="person_token",
        items={
            "clip-1": VideoDatasetItem(
                id="clip-1",
                media_item_id="video-1",
                source_media_item_id="source-video-1",
                caption="person_token, walking toward camera",
                status="approved",
                split="train",
                duration_seconds=3.0,
                width=720,
                height=1280,
            )
        },
        fingerprint=artifact.dataset_fingerprint,
        export_path=tmp_path / "video-export",
    )
    atomic_write_json(
        vault_root / "video_dataset_snapshots.json",
        {"version": 1, "snapshots": [source.model_dump(mode="json")]},
    )
    request = ImprovementRequest(
        id="improvement-video",
        comparison_id="comparison-video",
        project_id=artifact.project_id,
        benchmark_kind="audio_visual",
        candidate_artifact_id=artifact.id,
        candidate_checkpoint_sha256=artifact.checkpoint_sha256,
        status="approved",
        summary="Create a new video dataset revision.",
    )
    atomic_write_json(
        vault_root / "improvement_requests.json",
        {
            "version": 1,
            "format": "lorasuite.improvement-request.v1",
            "requests": [request.model_dump(mode="json")],
        },
    )

    record = ImprovementLoopService(vault_root).materialize_revision(request.id)

    assert record.modality == "video"
    assert record.revision_version == 5
    snapshots = {
        item.id: item
        for item in VideoDatasetService(vault_root).list_snapshots()
    }
    original = snapshots[source.id]
    revision = snapshots[record.revision_snapshot_id]
    assert original.model_dump(mode="json") == source.model_dump(mode="json")
    assert revision.status == "draft"
    assert revision.fingerprint is None
    assert revision.export_path is None
    assert revision.parent_snapshot_id == source.id
    assert revision.parent_fingerprint == source.fingerprint
    assert revision.items["clip-1"].model_dump(mode="json") == source.items[
        "clip-1"
    ].model_dump(mode="json")
