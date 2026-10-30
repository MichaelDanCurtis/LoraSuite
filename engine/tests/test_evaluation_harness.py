import shlex
import sys
from pathlib import Path
from subprocess import CompletedProcess

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.evaluation_harness import (
    BenchmarkMetrics,
    EvaluationHarnessService,
    _syncnet_command_metrics,
    default_benchmark_suite,
    _syncnet_command_metrics,
)
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord, ModelRegistryService
from lorasuite_engine.models import TrainingIntent
from lorasuite_engine.storage import atomic_write_json


def make_suite(root: Path) -> tuple[Path, Path]:
    baseline = root / "baseline"
    lora = root / "lora"
    baseline.mkdir()
    lora.mkdir()
    for definition in default_benchmark_suite():
        (baseline / definition.filename).write_bytes(b"baseline")
        (lora / definition.filename).write_bytes(b"lora")
    return baseline, lora


def register_artifact(vault_root: Path, project_id: str) -> ModelArtifactRecord:
    record = ModelArtifactRecord(
        id="artifact-1",
        project_id=project_id,
        training_run_id="training-1",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name="person.safetensors",
        checkpoint_path=vault_root / "person.safetensors",
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
        "artifacts": [record.model_dump(mode="json")],
    })
    return record


def test_persists_screening_ready_baseline_vs_lora_comparison(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(subject_name="Person", trigger_token="person_token"),
    )
    baseline_dir, lora_dir = make_suite(tmp_path)

    def analyzer(_path, variant, definition, _work_dir, project_id):
        assert project_id == project.id
        is_lora = variant == "lora"
        return BenchmarkMetrics(
            visual_quality=0.72 if is_lora else 0.65,
            temporal_stability=0.68 if is_lora else 0.64,
            motion_score=0.32,
            subject_coverage=0.81,
            identity_similarity=0.72 if is_lora else 0.42,
            identity_frame_coverage=0.92,
            audio_quality=0.79 if definition.audio_required else None,
            speaker_similarity=0.82 if definition.audio_required else None,
            transcript_similarity=0.91 if definition.audio_required else None,
            av_sync_proxy=0.63 if definition.audio_required else None,
            duration_seconds=4.0,
        )

    service = EvaluationHarnessService(vault_root, analyzer=analyzer)
    queued = service.create_run(
        project_id=project.id,
        baseline_dir=baseline_dir,
        lora_dir=lora_dir,
    )
    completed = service.process_run(queued.id)

    assert completed.status == "complete"
    assert completed.summary.screening_ready is True
    assert completed.summary.release_ready is False
    assert completed.summary.validation_level == "screening"
    assert completed.summary.passed_count == 4
    assert completed.summary.identity_gain == 0.3
    assert service.get_run(queued.id).summary.screening_ready is True


def test_prepares_reproducible_baseline_and_lora_workspace(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="person_token"),
    )

    workspace = EvaluationHarnessService(vault_root).prepare_workspace(
        project.id,
        tmp_path / "evaluation",
    )

    assert workspace.baseline_dir.is_dir()
    assert workspace.lora_dir.is_dir()
    assert workspace.contract_path.is_file()
    assert (workspace.baseline_dir / "identity_closeup.prompt.txt").read_text().startswith("person_token")
    assert "matching seeds" in workspace.contract_path.read_text()


def test_reads_certified_syncnet_metrics_from_configured_command(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "syncnet_adapter.py"
    script.write_text(
        "import json, sys\n"
        "assert sys.argv[1].endswith('.mp4')\n"
        "print(json.dumps({'lse_c': 6.4, 'lse_d': 7.2, 'offset_frames': -1}))\n",
        encoding="utf-8",
    )
    video = tmp_path / "speech.mp4"
    video.write_bytes(b"fixture")
    monkeypatch.setenv(
        "LORASUITE_SYNCNET_COMMAND",
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{video}}",
    )

    metrics = _syncnet_command_metrics(video)

    assert metrics is not None
    assert metrics.lse_c == 6.4
    assert metrics.lse_d == 7.2
    assert metrics.offset_frames == -1


def test_certifies_release_only_when_syncnet_checks_and_human_review_pass(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    artifact = register_artifact(vault_root, project.id)
    baseline_dir, lora_dir = make_suite(tmp_path)

    def analyzer(_path, variant, definition, _work_dir, _project_id):
        is_lora = variant == "lora"
        return BenchmarkMetrics(
            visual_quality=0.7,
            temporal_stability=0.7,
            motion_score=0.3,
            subject_coverage=0.8,
            identity_similarity=0.72 if is_lora else 0.42,
            identity_frame_coverage=0.9,
            audio_quality=0.8 if definition.audio_required else None,
            speaker_similarity=0.8 if definition.audio_required else None,
            transcript_similarity=0.9 if definition.audio_required else None,
            av_sync_proxy=0.6 if definition.audio_required else None,
            syncnet_lse_c=5.2 if definition.audio_required else None,
            syncnet_lse_d=7.1 if definition.audio_required else None,
            syncnet_offset_frames=1 if definition.audio_required else None,
            duration_seconds=4.0,
        )

    service = EvaluationHarnessService(vault_root, analyzer=analyzer)
    run = service.create_run(
        project_id=project.id,
        baseline_dir=baseline_dir,
        lora_dir=lora_dir,
        artifact_id=artifact.id,
    )
    completed = service.process_run(run.id)

    assert completed.summary.screening_ready is True
    assert completed.summary.automated_release_ready is True
    assert completed.summary.release_ready is False
    assert completed.summary.review_pending_count == 4
    assert completed.summary.average_syncnet_lse_c == 5.2
    assert completed.cases["speech_closeup"].certified_checks == {
        "syncnet_lse_c": True,
        "syncnet_lse_d": True,
        "syncnet_offset": True,
    }
    for case_id in completed.cases:
        completed = service.review_case(completed.id, case_id, "accepted", "Visual comparison passed")

    assert completed.summary.release_ready is True
    assert completed.summary.human_review_ready is True
    assert completed.summary.validation_level == "certified"
    assert completed.summary.review_accepted_count == 4
    accepted = ModelRegistryService(vault_root).get_artifact(artifact.id)
    assert accepted is not None
    assert accepted.acceptance.status == "certified"
    assert accepted.acceptance.benchmark_run_id == run.id
    assert accepted.acceptance.release_ready is True
    assert accepted.acceptance.identity_similarity == 0.72
    assert accepted.acceptance.speaker_similarity == 0.8


def test_snapshots_inputs_and_persists_rejected_human_review(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    baseline_dir, lora_dir = make_suite(tmp_path)

    def analyzer(_path, variant, definition, _work_dir, _project_id):
        is_lora = variant == "lora"
        return BenchmarkMetrics(
            visual_quality=0.7,
            temporal_stability=0.7,
            motion_score=0.3,
            subject_coverage=0.8,
            identity_similarity=0.72 if is_lora else 0.42,
            identity_frame_coverage=0.9,
            audio_quality=0.8 if definition.audio_required else None,
            speaker_similarity=0.8 if definition.audio_required else None,
            transcript_similarity=0.9 if definition.audio_required else None,
            av_sync_proxy=0.6 if definition.audio_required else None,
            syncnet_lse_c=5.2 if definition.audio_required else None,
            syncnet_lse_d=7.1 if definition.audio_required else None,
            syncnet_offset_frames=1 if definition.audio_required else None,
            duration_seconds=4.0,
        )

    service = EvaluationHarnessService(vault_root, analyzer=analyzer)
    run = service.create_run(project_id=project.id, baseline_dir=baseline_dir, lora_dir=lora_dir)
    assert run.baseline_dir.is_relative_to(vault_root)
    assert run.lora_dir.is_relative_to(vault_root)
    baseline_dir.rename(tmp_path / "original-baseline-moved")
    lora_dir.rename(tmp_path / "original-lora-moved")

    completed = service.process_run(run.id)
    reviewed = service.review_case(completed.id, "identity_closeup", "rejected", "Face drifts at the end")

    assert reviewed.cases["identity_closeup"].review_note == "Face drifts at the end"
    assert reviewed.summary.review_rejected_count == 1
    assert reviewed.summary.release_ready is False
    restored = EvaluationHarnessService(vault_root, analyzer=analyzer).get_run(run.id)
    assert restored is not None
    assert restored.cases["identity_closeup"].review_decision == "rejected"


def test_rejects_artifact_from_a_different_character_project(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    other = CharacterProjectService(vault_root).create_project()
    artifact = register_artifact(vault_root, other.id)
    baseline_dir, lora_dir = make_suite(tmp_path)

    try:
        EvaluationHarnessService(vault_root).create_run(
            project_id=project.id,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
            artifact_id=artifact.id,
        )
    except ValueError as error:
        assert "different character project" in str(error)
    else:
        raise AssertionError("Expected cross-project artifact evaluation to fail")


def test_syncnet_command_contract_reads_final_json_line(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "speaking clip.mp4"
    video_path.write_bytes(b"video")
    captured = {}

    def fake_run(arguments, **options):
        captured["arguments"] = arguments
        captured["options"] = options
        return CompletedProcess(arguments, 0, stdout='loading\n{"lse_c": 5.4, "lse_d": 6.8, "offset_frames": -1}\n', stderr="")

    monkeypatch.setenv("LORASUITE_SYNCNET_COMMAND", "syncnet-evaluate --video {video}")
    monkeypatch.setattr("lorasuite_engine.evaluation_harness.subprocess.run", fake_run)

    metrics = _syncnet_command_metrics(video_path)

    assert captured["arguments"] == ["syncnet-evaluate", "--video", str(video_path)]
    assert captured["options"]["shell"] is False
    assert metrics.lse_c == 5.4
    assert metrics.lse_d == 6.8
    assert metrics.offset_frames == -1


def test_marks_unavailable_identity_and_voice_metrics_blocked_not_failed(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    baseline_dir, lora_dir = make_suite(tmp_path)

    def analyzer(_path, _variant, definition, _work_dir, _project_id):
        return BenchmarkMetrics(
            visual_quality=0.7,
            temporal_stability=0.7,
            motion_score=0.3,
            subject_coverage=0.8,
            audio_quality=0.75 if definition.audio_required else None,
            duration_seconds=4.0,
            analyzer_notes=["identity model unavailable"],
        )

    service = EvaluationHarnessService(vault_root, analyzer=analyzer)
    run = service.create_run(project_id=project.id, baseline_dir=baseline_dir, lora_dir=lora_dir)
    completed = service.process_run(run.id)

    assert completed.summary.release_ready is False
    assert completed.summary.blocked_count == 4
    assert completed.summary.failed_count == 0
    assert "Install identity" in completed.summary.warnings[0]


def test_requires_every_named_baseline_and_lora_video(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    baseline_dir, lora_dir = make_suite(tmp_path)
    (lora_dir / "camera_motion.mp4").unlink()

    try:
        EvaluationHarnessService(vault_root).create_run(
            project_id=project.id,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
        )
    except ValueError as error:
        assert "camera_motion.mp4" in str(error)
    else:
        raise AssertionError("Expected missing benchmark video to fail")
