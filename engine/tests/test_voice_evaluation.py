from pathlib import Path

import pytest

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.voice_evaluation import (
    VoiceArtifactEvaluationService,
    VoiceEvaluationSample,
)


def test_evaluates_and_selects_earliest_passing_voice_checkpoint(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="Voice Person")
    first = _voice_artifact(vault_root, tmp_path, project.id, "voice_step=250.ckpt", "artifact-250")
    second = _voice_artifact(vault_root, tmp_path, project.id, "voice_step_500.ckpt", "artifact-500", append=True)
    samples = _samples(tmp_path / "samples")

    def evaluator(audio_path, transcript_path, project_id, run_id):
        assert project_id == project.id
        return VoiceEvaluationSample(
            id=audio_path.stem,
            audio_path=audio_path,
            transcript_path=transcript_path,
            expected_transcript=transcript_path.read_text(),
            actual_transcript=transcript_path.read_text(),
            duration_seconds=4.0,
            quality_score=0.84,
            speaker_similarity=0.88,
            transcript_similarity=0.96,
            active_audio_ratio=0.7,
            silence_ratio=0.3,
            clipping_ratio=0.0,
            snr_db=24.0,
            checks={"quality": True, "speaker_similarity": True, "transcript_similarity": True},
            passed=True,
        )

    service = VoiceArtifactEvaluationService(vault_root, evaluator=evaluator)
    later = service.create_run(project_id=project.id, artifact_id=second.id, samples_dir=samples)
    assert later.samples_dir.is_relative_to(vault_root)
    assert (later.samples_dir / "phrase_0.wav").read_bytes() == b"audio-0"
    later = service.process_run(later.id)
    earlier = service.create_run(project_id=project.id, artifact_id=first.id, samples_dir=samples)
    earlier = service.process_run(earlier.id)

    assert earlier.summary.screening_ready is True
    assert earlier.summary.passed_count == 3
    assert earlier.checkpoint_step == 250
    assert service.recommended_run(project.id).id == earlier.id
    selected = service.select_for_release(earlier.id)
    assert selected.selected_for_release is True
    assert not service.get_run(later.id).selected_for_release
    assert "Voice Person" not in service.runs_path.read_text()


def test_blocks_release_selection_when_voice_checks_are_unavailable(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="Voice Person")
    artifact = _voice_artifact(vault_root, tmp_path, project.id, "voice.ckpt", "artifact-1")
    samples = _samples(tmp_path / "samples")

    def evaluator(audio_path, transcript_path, project_id, run_id):
        return VoiceEvaluationSample(
            id=audio_path.stem,
            audio_path=audio_path,
            transcript_path=transcript_path,
            expected_transcript=transcript_path.read_text(),
            duration_seconds=4.0,
            checks={"speaker_similarity": None, "transcript_similarity": None},
            blocked=True,
        )

    service = VoiceArtifactEvaluationService(vault_root, evaluator=evaluator)
    run = service.process_run(service.create_run(project_id=project.id, artifact_id=artifact.id, samples_dir=samples).id)

    assert run.summary.blocked_count == 3
    assert run.summary.screening_ready is False
    with pytest.raises(ValueError, match="pass screening"):
        service.select_for_release(run.id)


def test_requires_sidecar_transcripts_and_voice_artifact(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="Voice Person")
    artifact = _voice_artifact(vault_root, tmp_path, project.id, "voice.ckpt", "artifact-1")
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "sample.wav").write_bytes(b"audio")
    service = VoiceArtifactEvaluationService(vault_root)

    with pytest.raises(ValueError, match="matching"):
        service.create_run(project_id=project.id, artifact_id=artifact.id, samples_dir=samples)


def test_rejects_voice_artifact_from_another_character(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(name="Voice Person")
    other = CharacterProjectService(vault_root).create_project(name="Other Person")
    artifact = _voice_artifact(vault_root, tmp_path, other.id, "voice.ckpt", "artifact-1")
    samples = _samples(tmp_path / "samples")

    with pytest.raises(ValueError, match="different character project"):
        VoiceArtifactEvaluationService(vault_root).create_run(
            project_id=project.id,
            artifact_id=artifact.id,
            samples_dir=samples,
        )


def _voice_artifact(vault_root: Path, root: Path, project_id: str, name: str, artifact_id: str, append: bool = False) -> ModelArtifactRecord:
    checkpoint = root / "checkpoints" / name
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(name.encode())
    record = ModelArtifactRecord(
        id=artifact_id,
        project_id=project_id,
        training_run_id=f"run-{artifact_id}",
        snapshot_id=project_id,
        dataset_fingerprint="voice-fingerprint",
        checkpoint_name=name,
        checkpoint_path=checkpoint,
        checkpoint_sha256="sha",
        checkpoint_size_bytes=checkpoint.stat().st_size,
        trigger_token="voice_person",
        modality="voice",
        model_family="fish_speech_s2",
        evaluation=ArtifactEvaluation(
            status="review",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )
    records = []
    path = vault_root / "model_artifacts.json"
    if append and path.exists():
        import json
        records = json.loads(path.read_text())["artifacts"]
    records.append(record.model_dump(mode="json"))
    atomic_write_json(path, {"version": 1, "artifacts": records})
    return record


def _samples(root: Path) -> Path:
    root.mkdir(parents=True)
    for index in range(3):
        (root / f"phrase_{index}.wav").write_bytes(f"audio-{index}".encode())
        (root / f"phrase_{index}.txt").write_text(f"Evaluation phrase {index}.")
    return root
