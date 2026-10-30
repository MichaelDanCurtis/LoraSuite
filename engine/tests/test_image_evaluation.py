from pathlib import Path

import pytest

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.image_evaluation import (
    ImageBenchmarkMetrics,
    ImageEvaluationHarnessService,
    default_image_benchmark_suite,
)
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord, ModelRegistryService
from lorasuite_engine.models import TrainingIntent
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_workflow import TrainingWorkflowService


def _suite(root: Path) -> tuple[Path, Path]:
    baseline = root / "baseline"
    lora = root / "lora"
    baseline.mkdir()
    lora.mkdir()
    for definition in default_image_benchmark_suite():
        (baseline / definition.filename).write_bytes(b"baseline")
        (lora / definition.filename).write_bytes(b"lora")
    return baseline, lora


def _artifact(vault_root: Path, project_id: str) -> ModelArtifactRecord:
    record = ModelArtifactRecord(
        id="image-artifact-1",
        project_id=project_id,
        training_run_id="image-training-1",
        snapshot_id="image-snapshot-1",
        dataset_fingerprint="image-fingerprint",
        checkpoint_name="person.safetensors",
        checkpoint_path=vault_root / "person.safetensors",
        checkpoint_sha256="abc123",
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
    atomic_write_json(vault_root / "model_artifacts.json", {
        "version": 1,
        "artifacts": [record.model_dump(mode="json")],
    })
    return record


def test_scores_matched_images_and_certifies_the_linked_artifact(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="person_token"),
    )
    artifact = _artifact(vault_root, project.id)
    baseline, lora = _suite(tmp_path)

    def analyzer(_path, variant, definition, project_id):
        assert project_id == project.id
        is_lora = variant == "lora"
        return ImageBenchmarkMetrics(
            visual_quality=0.78,
            aesthetic_score=0.72,
            subject_coverage=0.82,
            face_count=1,
            face_area=0.12,
            body_coverage=0.35 if definition.composition == "full_body" else 0.20,
            pose_coverage=0.65,
            identity_similarity=0.76 if is_lora else 0.31,
        )

    service = ImageEvaluationHarnessService(vault_root, analyzer=analyzer)
    run = service.create_run(
        project_id=project.id,
        baseline_dir=baseline,
        lora_dir=lora,
        artifact_id=artifact.id,
    )
    completed = service.process_run(run.id)

    assert completed.status == "complete"
    assert completed.summary.passed_count == 6
    assert completed.summary.release_ready is True
    assert completed.summary.identity_gain == pytest.approx(0.45)
    registered = ModelRegistryService(vault_root).get_artifact(artifact.id)
    assert registered is not None
    assert registered.acceptance.status == "certified"
    assert registered.acceptance.benchmark_run_id == run.id
    assert registered.acceptance.visual_quality == pytest.approx(0.78)
    assert registered.acceptance.subject_coverage == pytest.approx(0.82)
    workflow = TrainingWorkflowService(vault_root).status(project.id)
    evaluation_lane = next(lane for lane in workflow.lanes if lane.id == "evaluate")
    assert evaluation_lane.state == "ready"
    assert evaluation_lane.phase == "select"

    ModelRegistryService(vault_root).select_release(artifact.id)
    workflow = TrainingWorkflowService(vault_root).status(project.id)
    evaluation_lane = next(lane for lane in workflow.lanes if lane.id == "evaluate")
    assert evaluation_lane.state == "complete"
    assert evaluation_lane.phase == "release"


def test_blocks_image_release_when_identity_evidence_is_unavailable(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    baseline, lora = _suite(tmp_path)

    def analyzer(_path, _variant, _definition, _project_id):
        return ImageBenchmarkMetrics(
            visual_quality=0.8,
            aesthetic_score=0.7,
            subject_coverage=0.8,
            face_count=1,
            face_area=0.1,
            body_coverage=0.3,
            pose_coverage=0.6,
            analyzer_notes=["identity unavailable"],
        )

    service = ImageEvaluationHarnessService(vault_root, analyzer=analyzer)
    completed = service.process_run(service.create_run(
        project_id=project.id,
        baseline_dir=baseline,
        lora_dir=lora,
    ).id)

    assert completed.summary.blocked_count == 6
    assert completed.summary.failed_count == 0
    assert completed.summary.release_ready is False


def test_prepares_fixed_image_contract_with_trigger_token(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="person_token"),
    )

    workspace = ImageEvaluationHarnessService(vault_root).prepare_workspace(
        project.id,
        tmp_path / "image-evaluation",
    )

    assert len(workspace.cases) == 6
    assert workspace.contract_path.is_file()
    assert (workspace.baseline_dir / "neutral_closeup.prompt.txt").read_text().startswith("person_token")
    assert "identical seeds" in workspace.contract_path.read_text()


def test_rejects_non_image_or_cross_project_artifacts(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    other = CharacterProjectService(vault_root).create_project()
    artifact = _artifact(vault_root, other.id)
    baseline, lora = _suite(tmp_path)

    with pytest.raises(ValueError, match="different character project"):
        ImageEvaluationHarnessService(vault_root).create_run(
            project_id=project.id,
            baseline_dir=baseline,
            lora_dir=lora,
            artifact_id=artifact.id,
        )
