from types import SimpleNamespace

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.evaluation_harness import BenchmarkRun, BenchmarkSummary
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord, ModelRegistryService
from lorasuite_engine.models import (
    DatasetSnapshotStatus,
    RequestedOutput,
    TrainingIntent,
    VoiceDatasetCompilation,
)
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_targets import RecipeCompliance
from lorasuite_engine.training_workflow import TrainingWorkflowService, _id_lane, _image_lane, _voice_lane, _video_lane


def test_empty_project_reports_real_cross_lane_blockers(tmp_path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="Wizard Character")

    workflow = TrainingWorkflowService(vault_root).status(project.id)

    assert workflow.project_name == "Wizard Character"
    assert workflow.recommended_lane == "image"
    assert workflow.complete_count == 0
    lanes = {lane.id: lane for lane in workflow.lanes}
    assert lanes["image"].phase == "identity"
    assert lanes["video"].phase == "curate"
    assert lanes["video"].target_workspace == "curate"
    assert lanes["voice"].action_label == "Select voice anchors"
    assert lanes["voice"].target_workspace == "identify"
    assert lanes["id_lora"].state == "blocked"
    assert lanes["id_lora"].target_mode == "video"
    assert lanes["evaluate"].state == "blocked"


def test_recommendation_stays_with_the_outputs_requested_by_the_creation_brief(tmp_path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        name="Voice Character",
        intent=TrainingIntent(requested_outputs=[RequestedOutput.VOICE]),
    )

    workflow = TrainingWorkflowService(vault_root).status(project.id)

    assert workflow.recommended_lane == "voice"
    assert workflow.recommendation == "Voice Dataset: Select voice anchors"


def test_image_planner_advances_review_freeze_export_and_handoff(tmp_path) -> None:
    balance = SimpleNamespace(total_count=12, approved_count=10, review_count=2)
    snapshot = SimpleNamespace(status=DatasetSnapshotStatus.DRAFT, balance=balance, export_path=None)
    assert _image_lane(12, snapshot).phase == "review"

    balance.review_count = 0
    assert _image_lane(12, snapshot).phase == "freeze"

    snapshot.status = DatasetSnapshotStatus.FROZEN
    assert _image_lane(12, snapshot).phase == "export"

    snapshot.status = DatasetSnapshotStatus.EXPORTED
    snapshot.export_path = tmp_path / "image-dataset"
    assert _image_lane(12, snapshot).action_label == "Re-export image dataset"
    snapshot.export_path.mkdir()
    (snapshot.export_path / "manifest.json").write_text("{}")
    assert _image_lane(12, snapshot).state == "complete"


def test_h3_reference_workflow_allows_stills_and_never_demands_training(tmp_path) -> None:
    profile = "comfyui_minimax_h3_ref2va"
    assert _video_lane(0, None, profile).action_label == "Choose H3 references"
    project = CharacterProjectService(tmp_path).create_project(name="H3 references", intent=TrainingIntent(requested_outputs=[RequestedOutput.VIDEO], training_target_profile_ids={RequestedOutput.VIDEO: profile}))
    workflow = TrainingWorkflowService(tmp_path).status(project.id)
    evaluation = next(lane for lane in workflow.lanes if lane.id == "evaluate")
    assert evaluation.action_label == "Open H3 package"
    assert evaluation.target_mode == "video"
    assert workflow.recommended_lane == "video"
    assert "does not require a trained checkpoint" in evaluation.summary


def test_h3_missing_export_returns_to_packaging(tmp_path) -> None:
    snapshot = SimpleNamespace(target_profile_id="comfyui_minimax_h3_ref2va", status="exported", export_path=tmp_path / "missing", balance=SimpleNamespace(total_count=1, approved_count=1, review_count=0))
    assert _video_lane(0, snapshot).action_label == "Re-export H3 package"


def test_voice_planner_requires_quality_then_review_then_export() -> None:
    segment = SimpleNamespace(status="needs_review", quality=None)
    compilation = VoiceDatasetCompilation(project_id="project")
    compilation.segments = {"segment": segment}
    assert _voice_lane(1, 1, compilation).phase == "quality"

    segment.quality = object()
    assert _voice_lane(1, 1, compilation).phase == "review"

    segment.status = "approved"
    assert _voice_lane(1, 1, compilation).phase == "review"
    compilation.balance.recipe_compliance = RecipeCompliance(
        recipe_id="fish_speech_s2_voice_character",
        recipe_version=1,
        recipe_label="Fish Speech S2 Voice Character",
        status="ready",
        score=1,
    )
    assert _voice_lane(1, 1, compilation).phase == "export"


def test_id_lora_planner_requires_inference_download_and_certification() -> None:
    video = SimpleNamespace(
        status="frozen",
        fingerprint="video-fingerprint",
        balance=SimpleNamespace(approved_count=8),
    )
    manifest = SimpleNamespace(
        status="ready",
        export_path="/tmp/id-lora-package",
        balance=SimpleNamespace(
            visual_example_count=8,
            synchronized_pair_count=4,
            voice_reference_count=4,
            warnings=[],
        ),
    )

    assert _id_lane(video, manifest).phase == "inference"

    inference = SimpleNamespace(id="inference-1", status="running", artifacts=[], error=None)
    assert _id_lane(video, manifest, inference).phase == "inference"

    inference.status = "completed"
    inference.artifacts = [SimpleNamespace(kind="sample", local_path=None)]
    assert _id_lane(video, manifest, inference).phase == "download"

    inference.artifacts = [SimpleNamespace(kind="sample", local_path="/tmp/id-lora.mp4")]
    assert _id_lane(video, manifest, inference).phase == "evaluate"

    evaluation = SimpleNamespace(
        status="complete",
        error=None,
        summary=SimpleNamespace(
            passed_count=1,
            failed_count=0,
            blocked_count=0,
            screening_ready=True,
            release_ready=False,
            warnings=["Certified SyncNet evidence is required."],
        ),
    )
    screening = _id_lane(video, manifest, inference, evaluation)
    assert screening.state == "working"
    assert screening.phase == "certification"

    evaluation.summary.release_ready = True
    certified = _id_lane(video, manifest, inference, evaluation)
    assert certified.state == "complete"
    assert certified.phase == "certified"


def test_evaluation_lane_requires_a_linked_artifact_benchmark(tmp_path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="AV Character")
    artifact = ModelArtifactRecord(
        id="artifact-1",
        project_id=project.id,
        training_run_id="run-1",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name="character.safetensors",
        checkpoint_path=tmp_path / "character.safetensors",
        checkpoint_sha256="abc123",
        checkpoint_size_bytes=1024,
        modality="audio_visual",
        model_family="ltx23_id_lora",
        evaluation=ArtifactEvaluation(
            status="ready",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )
    atomic_write_json(vault_root / "model_artifacts.json", {
        "version": 1,
        "artifacts": [artifact.model_dump(mode="json")],
    })

    ready = TrainingWorkflowService(vault_root).status(project.id)
    evaluation = next(lane for lane in ready.lanes if lane.id == "evaluate")
    assert evaluation.phase == "prepare"
    assert evaluation.counts["validated_artifacts"] == 1

    benchmark = BenchmarkRun(
        id="benchmark-1",
        project_id=project.id,
        artifact_id=artifact.id,
        baseline_dir=tmp_path / "baseline",
        lora_dir=tmp_path / "lora",
        status="complete",
        summary=BenchmarkSummary(
            passed_count=4,
            screening_ready=True,
            release_ready=True,
            validation_level="certified",
        ),
    )
    atomic_write_json(vault_root / "benchmark_runs.json", {
        "version": 1,
        "runs": [benchmark.model_dump(mode="json")],
    })

    registry = ModelRegistryService(vault_root)
    registry.record_acceptance(artifact.id, benchmark.id, screening_ready=True, release_ready=True, passed_count=4)
    awaiting_selection = TrainingWorkflowService(vault_root).status(project.id)
    evaluation = next(lane for lane in awaiting_selection.lanes if lane.id == "evaluate")
    assert evaluation.state == "ready"
    assert evaluation.phase == "select"

    registry.select_release(artifact.id)
    complete = TrainingWorkflowService(vault_root).status(project.id)
    evaluation = next(lane for lane in complete.lanes if lane.id == "evaluate")
    assert evaluation.state == "complete"
    assert evaluation.phase == "release"
    assert evaluation.counts["selected_releases"] == 1
