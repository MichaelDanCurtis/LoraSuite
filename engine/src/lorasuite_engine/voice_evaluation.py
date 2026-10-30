from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.models import MediaItem, MediaType, new_id, utc_now
from lorasuite_engine.speaker_identity import SpeakerEmbeddingEngine, SpeakerIdentityModelService, VoiceIdentityService
from lorasuite_engine.speech_analysis import AppleSpeechAnalyzer
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService, sha256_file
from lorasuite_engine.voice_quality import VoiceQualityAnalyzer


class VoiceEvaluationSample(BaseModel):
    id: str
    audio_path: Path
    transcript_path: Path
    expected_transcript: str
    actual_transcript: str | None = None
    duration_seconds: float = 0.0
    quality_score: float | None = None
    speaker_similarity: float | None = None
    transcript_similarity: float | None = None
    active_audio_ratio: float | None = None
    silence_ratio: float | None = None
    clipping_ratio: float | None = None
    snr_db: float | None = None
    checks: dict[str, bool | None] = Field(default_factory=dict)
    passed: bool = False
    blocked: bool = False
    notes: list[str] = Field(default_factory=list)


class VoiceEvaluationSummary(BaseModel):
    sample_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    average_quality: float | None = None
    average_speaker_similarity: float | None = None
    average_transcript_similarity: float | None = None
    screening_ready: bool = False
    rank_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class VoiceArtifactEvaluationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("voice_evaluation"))
    project_id: str
    artifact_id: str
    checkpoint_name: str
    checkpoint_step: int | None = None
    samples_dir: Path
    status: Literal["queued", "running", "complete", "failed"] = "queued"
    samples: dict[str, VoiceEvaluationSample] = Field(default_factory=dict)
    summary: VoiceEvaluationSummary = Field(default_factory=VoiceEvaluationSummary)
    selected_for_release: bool = False
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


SampleEvaluator = Callable[[Path, Path, str, str], VoiceEvaluationSample]


class VoiceArtifactEvaluationService:
    def __init__(self, vault_root: Path, *, evaluator: SampleEvaluator | None = None):
        self.vault_root = Path(vault_root)
        self.evaluator = evaluator or self._evaluate_sample

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "voice_artifact_evaluations.json"

    def list_runs(self, project_id: str | None = None) -> list[VoiceArtifactEvaluationRun]:
        runs = self._read().values()
        if project_id:
            runs = (run for run in runs if run.project_id == project_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> VoiceArtifactEvaluationRun | None:
        return self._read().get(run_id)

    def create_run(self, *, project_id: str, artifact_id: str, samples_dir: Path) -> VoiceArtifactEvaluationRun:
        if CharacterProjectService(self.vault_root).get_project(project_id) is None:
            raise KeyError(project_id)
        artifact = ModelRegistryService(self.vault_root).get_artifact(artifact_id)
        if artifact is None:
            raise ValueError("voice model artifact is not registered")
        if artifact.modality != "voice":
            raise ValueError("voice evaluation requires a registered voice artifact")
        if artifact.project_id and artifact.project_id != project_id:
            raise ValueError("voice model artifact belongs to a different character project")
        if not artifact.checkpoint_path.is_file():
            raise ValueError("registered voice checkpoint is missing")
        root = Path(samples_dir).expanduser().resolve(strict=False)
        pairs = _sample_pairs(root)
        if not pairs:
            raise ValueError("evaluation folder must contain audio with matching .txt or .lab transcripts")
        run = VoiceArtifactEvaluationRun(
            project_id=project_id,
            artifact_id=artifact.id,
            checkpoint_name=artifact.checkpoint_name,
            checkpoint_step=_checkpoint_step(artifact.checkpoint_name),
            samples_dir=self.vault_root / "voice_evaluation_inputs" / new_id("sample_set"),
        )
        try:
            for audio_path, transcript_path in pairs:
                relative_audio = audio_path.relative_to(root)
                target_audio = run.samples_dir / relative_audio
                target_transcript = target_audio.with_suffix(transcript_path.suffix.lower())
                target_audio.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(audio_path, target_audio)
                shutil.copy2(transcript_path, target_transcript)
        except Exception:
            shutil.rmtree(run.samples_dir, ignore_errors=True)
            raise
        runs = self._read()
        runs[run.id] = run
        self._write(runs)
        return run

    def process_run(self, run_id: str) -> VoiceArtifactEvaluationRun:
        run = self._require(run_id)
        run.status = "running"
        run.error = None
        run.updated_at = utc_now()
        self._save(run)
        try:
            samples: dict[str, VoiceEvaluationSample] = {}
            for audio_path, transcript_path in _sample_pairs(run.samples_dir):
                sample = self.evaluator(audio_path, transcript_path, run.project_id, run.id)
                samples[sample.id] = sample
            run.samples = samples
            run.summary = _summarize(samples.values())
            run.status = "complete"
            run.completed_at = utc_now()
        except Exception as error:
            run.status = "failed"
            run.error = str(error)
            run.completed_at = utc_now()
        run.updated_at = utc_now()
        self._save(run)
        return run

    def select_for_release(self, run_id: str) -> VoiceArtifactEvaluationRun:
        selected = self._require(run_id)
        if selected.status != "complete" or not selected.summary.screening_ready:
            raise ValueError("voice checkpoint must pass screening before release selection")
        runs = self._read()
        for run in runs.values():
            if run.project_id == selected.project_id:
                run.selected_for_release = run.id == selected.id
                run.updated_at = utc_now()
        self._write(runs)
        return runs[selected.id]

    def recommended_run(self, project_id: str) -> VoiceArtifactEvaluationRun | None:
        passing = [
            run for run in self.list_runs(project_id)
            if run.status == "complete" and run.summary.screening_ready
        ]
        if not passing:
            return None
        return min(
            passing,
            key=lambda run: (
                run.checkpoint_step is None,
                run.checkpoint_step if run.checkpoint_step is not None else 10**12,
                -run.summary.rank_score,
            ),
        )

    def _evaluate_sample(self, audio_path: Path, transcript_path: Path, project_id: str, run_id: str) -> VoiceEvaluationSample:
        expected = transcript_path.read_text(encoding="utf-8").strip()
        if not expected:
            raise ValueError(f"evaluation transcript is empty: {transcript_path}")
        duration = float(sf.info(audio_path).duration)
        speech = AppleSpeechAnalyzer().analyze(audio_path, duration)
        quality = VoiceQualityAnalyzer().analyze(
            audio_path,
            transcript_confidence=speech.transcript_confidence,
            speaker_count=speech.speaker_count,
            source_metadata={"audio_original": True},
        )
        notes = list(dict.fromkeys([*speech.warnings, *quality.warnings, *quality.reasons]))
        speaker_similarity = self._speaker_similarity(project_id, audio_path, run_id, notes)
        transcript_similarity = _text_similarity(expected, speech.transcript)
        checks: dict[str, bool | None] = {
            "duration": 1.0 <= duration <= 30.0,
            "quality": quality.quality_score >= 0.60,
            "speaker_similarity": None if speaker_similarity is None else speaker_similarity >= 0.70,
            "transcript_similarity": None if transcript_similarity is None else transcript_similarity >= 0.80,
            "active_speech": None if quality.active_audio_ratio is None else quality.active_audio_ratio >= 0.18,
            "clipping": None if quality.clipping_ratio is None else quality.clipping_ratio <= 0.025,
            "single_speaker": None if speech.speaker_count is None else speech.speaker_count == 1,
        }
        blocked = any(value is None for value in checks.values())
        passed = not blocked and all(checks.values())
        return VoiceEvaluationSample(
            id=sha256_file(audio_path)[:16],
            audio_path=audio_path,
            transcript_path=transcript_path,
            expected_transcript=expected,
            actual_transcript=speech.transcript,
            duration_seconds=duration,
            quality_score=quality.quality_score,
            speaker_similarity=speaker_similarity,
            transcript_similarity=transcript_similarity,
            active_audio_ratio=quality.active_audio_ratio,
            silence_ratio=quality.silence_ratio,
            clipping_ratio=quality.clipping_ratio,
            snr_db=quality.snr_db,
            checks=checks,
            passed=passed,
            blocked=blocked,
            notes=notes,
        )

    def _speaker_similarity(self, project_id: str, audio_path: Path, run_id: str, notes: list[str]) -> float | None:
        profile = VoiceIdentityService(self.vault_root).get_profile(project_id)
        model = SpeakerIdentityModelService()
        if not profile.anchor_media_item_ids or not model.status().ready:
            notes.append("speaker identity model or trusted voice anchors are unavailable")
            return None
        vault = VaultService(self.vault_root)
        engine = SpeakerEmbeddingEngine(self.vault_root, model.model_path)
        anchors = [
            engine.embedding(item)
            for item_id in profile.anchor_media_item_ids
            if (item := vault.get_media_item(item_id)) is not None
        ]
        if not anchors:
            notes.append("trusted voice anchors could not be loaded")
            return None
        consensus = np.mean(anchors, axis=0)
        consensus /= max(float(np.linalg.norm(consensus)), 1e-12)
        candidate = MediaItem(
            id=f"{run_id}:{audio_path.name}",
            source_id="voice_evaluation",
            raw_path=audio_path,
            media_type=MediaType.AUDIO,
            sha256=sha256_file(audio_path),
        )
        embedding = engine.embedding(candidate)
        embedding /= max(float(np.linalg.norm(embedding)), 1e-12)
        return float(np.dot(consensus, embedding))

    def _require(self, run_id: str) -> VoiceArtifactEvaluationRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _save(self, run: VoiceArtifactEvaluationRun) -> None:
        runs = self._read()
        runs[run.id] = run
        self._write(runs)

    def _read(self) -> dict[str, VoiceArtifactEvaluationRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            try:
                payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {
                item["id"]: VoiceArtifactEvaluationRun.model_validate(item)
                for item in payload.get("runs", [])
            }

    def _write(self, runs: dict[str, VoiceArtifactEvaluationRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {
                "version": 1,
                "runs": [run.model_dump(mode="json") for run in runs.values()],
            })


def _sample_pairs(root: Path) -> list[tuple[Path, Path]]:
    if not root.is_dir():
        return []
    pairs = []
    for audio in sorted(path for path in root.rglob("*") if path.suffix.lower() in {".wav", ".flac", ".mp3", ".m4a"}):
        transcript = next((candidate for suffix in (".txt", ".lab") if (candidate := audio.with_suffix(suffix)).is_file()), None)
        if transcript:
            pairs.append((audio, transcript))
    return pairs


def _checkpoint_step(name: str) -> int | None:
    matches = re.findall(r"(?:step|checkpoint|ckpt)[_=-]?(\d+)", name, flags=re.IGNORECASE)
    return int(matches[-1]) if matches else None


def _text_similarity(expected: str, actual: str | None) -> float | None:
    if not actual:
        return None
    left = [word.strip(".,!?;:\"'").lower() for word in expected.split() if word.strip()]
    right = [word.strip(".,!?;:\"'").lower() for word in actual.split() if word.strip()]
    distances = list(range(len(right) + 1))
    for index, word in enumerate(left, start=1):
        next_row = [index]
        for column, candidate in enumerate(right, start=1):
            next_row.append(min(next_row[-1] + 1, distances[column] + 1, distances[column - 1] + (word != candidate)))
        distances = next_row
    return max(0.0, 1.0 - distances[-1] / max(len(left), len(right), 1))


def _summarize(samples) -> VoiceEvaluationSummary:
    values = list(samples)
    qualities = [sample.quality_score for sample in values if sample.quality_score is not None]
    speakers = [sample.speaker_similarity for sample in values if sample.speaker_similarity is not None]
    transcripts = [sample.transcript_similarity for sample in values if sample.transcript_similarity is not None]
    passed = sum(sample.passed for sample in values)
    blocked = sum(sample.blocked for sample in values)
    failed = len(values) - passed - blocked
    average_quality = _mean(qualities)
    average_speaker = _mean(speakers)
    average_transcript = _mean(transcripts)
    warnings = []
    if len(values) < 3:
        warnings.append("Render at least 3 varied phrases before selecting a checkpoint.")
    if blocked:
        warnings.append("Install transcription and speaker identity models to resolve blocked checks.")
    screening_ready = len(values) >= 3 and passed == len(values)
    rank_score = 0.45 * (average_speaker or 0.0) + 0.35 * (average_transcript or 0.0) + 0.20 * (average_quality or 0.0)
    return VoiceEvaluationSummary(
        sample_count=len(values),
        passed_count=passed,
        failed_count=failed,
        blocked_count=blocked,
        average_quality=average_quality,
        average_speaker_similarity=average_speaker,
        average_transcript_similarity=average_transcript,
        screening_ready=screening_ready,
        rank_score=rank_score,
        warnings=warnings,
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
