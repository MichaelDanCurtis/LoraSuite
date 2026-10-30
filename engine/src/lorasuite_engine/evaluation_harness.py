from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.ffmpeg import extract_analysis_frames, extract_audio, probe_video
from lorasuite_engine.identity_engine import SFaceIdentityEngine, anchor_similarity
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.models import MediaItem, MediaType, new_id, utc_now
from lorasuite_engine.speaker_identity import SpeakerEmbeddingEngine, SpeakerIdentityModelService, VoiceIdentityService
from lorasuite_engine.speech_analysis import AppleSpeechAnalyzer
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.syncnet_runtime import syncnet_command
from lorasuite_engine.vault import VaultService, sha256_file
from lorasuite_engine.video_analysis import analyze_video_frames
from lorasuite_engine.voice_quality import VoiceQualityAnalyzer, decode_mono_pcm


class BenchmarkCaseDefinition(BaseModel):
    id: str
    label: str
    filename: str
    prompt: str
    audio_required: bool = False
    expected_transcript: str | None = None


class BenchmarkMetrics(BaseModel):
    visual_quality: float
    temporal_stability: float
    motion_score: float
    subject_coverage: float
    identity_similarity: float | None = None
    identity_frame_coverage: float | None = None
    audio_quality: float | None = None
    speaker_similarity: float | None = None
    transcript_similarity: float | None = None
    av_sync_proxy: float | None = None
    syncnet_lse_c: float | None = None
    syncnet_lse_d: float | None = None
    syncnet_offset_frames: int | None = None
    duration_seconds: float
    analyzer_notes: list[str] = Field(default_factory=list)


class BenchmarkCaseResult(BaseModel):
    definition: BenchmarkCaseDefinition
    baseline_path: Path
    lora_path: Path
    baseline: BenchmarkMetrics
    lora: BenchmarkMetrics
    passed: bool
    blocked: bool
    checks: dict[str, bool | None]
    certified_checks: dict[str, bool | None] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    review_decision: Literal["pending", "accepted", "rejected"] = "pending"
    review_note: str = ""
    reviewed_at: Any | None = None


class BenchmarkSummary(BaseModel):
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    identity_gain: float | None = None
    average_lora_identity: float | None = None
    average_lora_stability: float = 0.0
    average_lora_motion: float = 0.0
    average_speaker_similarity: float | None = None
    average_av_sync_proxy: float | None = None
    average_syncnet_lse_c: float | None = None
    average_syncnet_lse_d: float | None = None
    screening_ready: bool = False
    automated_release_ready: bool = False
    human_review_ready: bool = False
    release_ready: bool = False
    review_pending_count: int = 0
    review_accepted_count: int = 0
    review_rejected_count: int = 0
    validation_level: Literal["screening", "certified"] = "screening"
    warnings: list[str] = Field(default_factory=list)


class BenchmarkRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("benchmark_run"))
    project_id: str
    artifact_id: str | None = None
    baseline_dir: Path
    lora_dir: Path
    status: Literal["queued", "running", "complete", "failed"] = "queued"
    cases: dict[str, BenchmarkCaseResult] = Field(default_factory=dict)
    summary: BenchmarkSummary = Field(default_factory=BenchmarkSummary)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class BenchmarkWorkspace(BaseModel):
    project_id: str
    root: Path
    baseline_dir: Path
    lora_dir: Path
    contract_path: Path
    cases: list[BenchmarkCaseDefinition]


class SyncNetMetrics(BaseModel):
    lse_c: float
    lse_d: float
    offset_frames: int = 0


def default_benchmark_suite() -> list[BenchmarkCaseDefinition]:
    return [
        BenchmarkCaseDefinition(
            id="identity_closeup",
            label="Close-up identity",
            filename="identity_closeup.mp4",
            prompt="{trigger}, close-up portrait, natural expression, subtle head movement, steady camera",
        ),
        BenchmarkCaseDefinition(
            id="full_body_motion",
            label="Full-body motion",
            filename="full_body_motion.mp4",
            prompt="{trigger}, full body, walking naturally across the frame, consistent clothing and anatomy",
        ),
        BenchmarkCaseDefinition(
            id="camera_motion",
            label="Camera motion",
            filename="camera_motion.mp4",
            prompt="{trigger}, medium shot, slow camera orbit, stable face and body identity, cinematic video",
        ),
        BenchmarkCaseDefinition(
            id="speech_closeup",
            label="Speaking close-up",
            filename="speech_closeup.mp4",
            prompt="{trigger}, close-up, speaking clearly to camera, natural mouth movement, steady identity",
            audio_required=True,
            expected_transcript="This is a LoraSuite identity and voice evaluation.",
        ),
    ]


class EvaluationHarnessService:
    def __init__(
        self,
        vault_root: Path,
        *,
        analyzer: Callable[[Path, str, BenchmarkCaseDefinition, Path, str], BenchmarkMetrics] | None = None,
        syncnet_evaluator: Callable[[Path], SyncNetMetrics | None] | None = None,
    ):
        self.vault_root = Path(vault_root)
        self.analyzer = analyzer or self._analyze_variant
        self.syncnet_evaluator = syncnet_evaluator or _syncnet_command_metrics

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "benchmark_runs.json"

    def list_runs(self, project_id: str | None = None) -> list[BenchmarkRun]:
        runs = self._read().values()
        if project_id:
            runs = (run for run in runs if run.project_id == project_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        return self._read().get(run_id)

    def prepare_workspace(self, project_id: str, output_dir: Path) -> BenchmarkWorkspace:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        root = Path(output_dir).expanduser().resolve(strict=False)
        baseline_dir = root / "baseline"
        lora_dir = root / "lora"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        lora_dir.mkdir(parents=True, exist_ok=True)
        cases = default_benchmark_suite()
        expanded = []
        for definition in cases:
            prompt = definition.prompt.replace("{trigger}", project.intent.trigger_token or "trigger_token")
            payload = {**definition.model_dump(mode="json"), "prompt": prompt}
            expanded.append(payload)
            for directory in (baseline_dir, lora_dir):
                (directory / f"{Path(definition.filename).stem}.prompt.txt").write_text(
                    prompt.rstrip() + "\n",
                    encoding="utf-8",
                )
        contract_path = root / "evaluation_contract.json"
        contract_path.write_text(json.dumps({
            "created_by": "LoraSuite",
            "format": "av-evaluation-v1",
            "project_id": project.id,
            "trigger_token": project.intent.trigger_token,
            "instructions": "Generate every named MP4 twice with matching seeds and settings: once with the base model and once with the LoRA.",
            "baseline_dir": str(baseline_dir),
            "lora_dir": str(lora_dir),
            "cases": expanded,
        }, indent=2) + "\n", encoding="utf-8")
        return BenchmarkWorkspace(
            project_id=project.id,
            root=root,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
            contract_path=contract_path,
            cases=cases,
        )

    def create_run(
        self,
        *,
        project_id: str,
        baseline_dir: Path,
        lora_dir: Path,
        artifact_id: str | None = None,
    ) -> BenchmarkRun:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        if artifact_id:
            artifact = ModelRegistryService(self.vault_root).get_artifact(artifact_id)
            if artifact is None:
                raise ValueError("model artifact is not registered")
            if artifact.project_id and artifact.project_id != project_id:
                raise ValueError("model artifact belongs to a different character project")
        source_baseline_dir = Path(baseline_dir).expanduser().resolve(strict=False)
        source_lora_dir = Path(lora_dir).expanduser().resolve(strict=False)
        for definition in default_benchmark_suite():
            for directory, label in ((source_baseline_dir, "baseline"), (source_lora_dir, "LoRA")):
                path = directory / definition.filename
                if not path.is_file():
                    raise ValueError(f"{label} benchmark video is missing: {path}")
        input_root = self.vault_root / "benchmark_inputs" / new_id("input_set")
        baseline_dir = input_root / "baseline"
        lora_dir = input_root / "lora"
        try:
            baseline_dir.mkdir(parents=True, exist_ok=True)
            lora_dir.mkdir(parents=True, exist_ok=True)
            for definition in default_benchmark_suite():
                shutil.copy2(source_baseline_dir / definition.filename, baseline_dir / definition.filename)
                shutil.copy2(source_lora_dir / definition.filename, lora_dir / definition.filename)
        except Exception:
            shutil.rmtree(input_root, ignore_errors=True)
            raise
        run = BenchmarkRun(
            project_id=project_id,
            artifact_id=artifact_id,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
        )
        runs = self._read()
        runs[run.id] = run
        self._write(runs)
        return run

    def review_case(
        self,
        run_id: str,
        case_id: str,
        decision: Literal["pending", "accepted", "rejected"],
        note: str = "",
    ) -> BenchmarkRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != "complete":
            raise ValueError("benchmark scoring must complete before human review")
        result = run.cases.get(case_id)
        if result is None:
            raise KeyError(case_id)
        result.review_decision = decision
        result.review_note = note.strip()
        result.reviewed_at = None if decision == "pending" else utc_now()
        run.summary = _summarize(run.cases)
        run.updated_at = utc_now()
        self._save(run)
        self._record_artifact_acceptance(run)
        return run

    def process_run(self, run_id: str) -> BenchmarkRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = "running"
        run.updated_at = utc_now()
        self._save(run)
        registry = ModelRegistryService(self.vault_root)
        if run.artifact_id:
            registry.begin_acceptance(run.artifact_id, run.id)
        try:
            results = {}
            for definition in default_benchmark_suite():
                baseline_path = run.baseline_dir / definition.filename
                lora_path = run.lora_dir / definition.filename
                work_dir = self.vault_root / "benchmark_work" / run.id / definition.id
                baseline = self.analyzer(baseline_path, "baseline", definition, work_dir / "baseline", run.project_id)
                lora = self.analyzer(lora_path, "lora", definition, work_dir / "lora", run.project_id)
                result = _compare_case(definition, baseline_path, lora_path, baseline, lora)
                results[definition.id] = result
            run.cases = results
            run.summary = _summarize(results)
            run.status = "complete"
            run.completed_at = utc_now()
            self._record_artifact_acceptance(run)
        except Exception as error:
            run.status = "failed"
            run.error = str(error)
            run.completed_at = utc_now()
            if run.artifact_id:
                registry.record_acceptance(
                    run.artifact_id,
                    run.id,
                    error=run.error,
                )
        run.updated_at = utc_now()
        self._save(run)
        return run

    def _record_artifact_acceptance(self, run: BenchmarkRun) -> None:
        if not run.artifact_id:
            return
        ModelRegistryService(self.vault_root).record_acceptance(
            run.artifact_id,
            run.id,
            screening_ready=run.summary.screening_ready,
            release_ready=run.summary.release_ready,
            passed_count=run.summary.passed_count,
            failed_count=run.summary.failed_count,
            blocked_count=run.summary.blocked_count,
            identity_similarity=run.summary.average_lora_identity,
            temporal_stability=run.summary.average_lora_stability,
            speaker_similarity=run.summary.average_speaker_similarity,
            av_sync_proxy=run.summary.average_av_sync_proxy,
            warnings=run.summary.warnings,
        )

    def _analyze_variant(
        self,
        video_path: Path,
        variant: str,
        definition: BenchmarkCaseDefinition,
        work_dir: Path,
        project_id: str,
    ) -> BenchmarkMetrics:
        metadata = probe_video(video_path)
        shutil.rmtree(work_dir, ignore_errors=True)
        frame_rate = min(2.0, max(0.5, 24.0 / max(metadata.duration_seconds, 1.0)))
        frames = extract_analysis_frames(
            video_path,
            work_dir / "frames",
            duration_seconds=metadata.duration_seconds,
            frames_per_second=frame_rate,
            max_width=768,
        )
        analysis = analyze_video_frames(
            source_media_item_id=f"benchmark:{variant}:{definition.id}",
            duration_seconds=metadata.duration_seconds,
            frame_paths=frames,
            sample_fps=frame_rate,
            max_keeper_count=len(frames),
        )
        frame_scores = [frame.scores for frame in analysis.frames]
        notes: list[str] = []
        identity_similarity, identity_coverage, face_embeddings = self._identity_metrics(project_id, frames, notes)
        audio_path = work_dir / "audio.wav"
        audio_quality = speaker_similarity = transcript_similarity = av_sync = None
        syncnet = None
        try:
            extract_audio(video_path, audio_path)
        except RuntimeError:
            if definition.audio_required:
                notes.append("required audio stream is missing")
        else:
            quality = VoiceQualityAnalyzer().analyze(
                audio_path,
                transcript_confidence=None,
                speaker_count=None,
                source_metadata={"audio_original": True},
            )
            audio_quality = quality.quality_score
            speaker_similarity = self._speaker_similarity(project_id, audio_path, notes)
            if definition.expected_transcript:
                try:
                    speech = AppleSpeechAnalyzer().analyze(audio_path, metadata.duration_seconds)
                    transcript_similarity = _text_similarity(definition.expected_transcript, speech.transcript)
                except (OSError, RuntimeError, ValueError) as error:
                    notes.append(f"speech transcription unavailable: {error}")
            av_sync = _av_sync_proxy(frames, face_embeddings, audio_path, metadata.duration_seconds)
            if av_sync is None:
                notes.append("AV-sync proxy unavailable without stable face landmarks and active audio")
            if definition.audio_required:
                try:
                    syncnet = self.syncnet_evaluator(video_path)
                except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                    notes.append(f"certified SyncNet evaluation unavailable: {error}")
        return BenchmarkMetrics(
            visual_quality=_mean(score.overall for score in frame_scores),
            temporal_stability=_mean(score.stability for score in frame_scores),
            motion_score=_mean(1.0 - score.stability for score in frame_scores),
            subject_coverage=_mean(max(score.face_quality, min(1.0, score.face_area / 0.10), min(1.0, score.body_coverage / 0.30)) for score in frame_scores),
            identity_similarity=identity_similarity,
            identity_frame_coverage=identity_coverage,
            audio_quality=audio_quality,
            speaker_similarity=speaker_similarity,
            transcript_similarity=transcript_similarity,
            av_sync_proxy=av_sync,
            syncnet_lse_c=syncnet.lse_c if syncnet else None,
            syncnet_lse_d=syncnet.lse_d if syncnet else None,
            syncnet_offset_frames=syncnet.offset_frames if syncnet else None,
            duration_seconds=metadata.duration_seconds,
            analyzer_notes=notes,
        )

    def _identity_metrics(self, project_id: str, frames: list[Path], notes: list[str]):
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        models = IdentityModelService(self.vault_root)
        if project is None or not models.status().ready:
            notes.append("face identity model or project anchors are unavailable")
            return None, None, {}
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        engine = SFaceIdentityEngine(models.paths)
        anchors = []
        for media_id, observation in project.observations.items():
            if not observation.is_anchor:
                continue
            item = media_by_id.get(media_id)
            if item is None:
                continue
            faces = engine.analyze(item.raw_path)
            if faces:
                selected = next((face for face in faces if face.face.index == observation.selected_face_index), faces[0])
                anchors.append(selected.embedding)
        if not anchors:
            notes.append("no usable visual identity anchors are available")
            return None, None, {}
        similarities = []
        analyses = {}
        for frame in frames:
            faces = engine.analyze(frame)
            analyses[frame] = faces
            scores = [anchor_similarity(face.embedding, anchors) for face in faces]
            scores = [score for score in scores if score is not None]
            if scores:
                similarities.append(max(scores))
        return (
            _mean(similarities) if similarities else 0.0,
            len(similarities) / max(1, len(frames)),
            analyses,
        )

    def _speaker_similarity(self, project_id: str, audio_path: Path, notes: list[str]) -> float | None:
        profile = VoiceIdentityService(self.vault_root).get_profile(project_id)
        model = SpeakerIdentityModelService()
        if not profile.anchor_media_item_ids or not model.status().ready:
            notes.append("speaker identity model or voice anchors are unavailable")
            return None
        vault = VaultService(self.vault_root)
        engine = SpeakerEmbeddingEngine(self.vault_root, model.model_path)
        anchors = [engine.embedding(vault.get_media_item(item_id)) for item_id in profile.anchor_media_item_ids if vault.get_media_item(item_id)]
        if not anchors:
            return None
        consensus = np.mean(anchors, axis=0)
        consensus /= max(float(np.linalg.norm(consensus)), 1e-12)
        candidate = MediaItem(
            id=new_id("benchmark_audio"), source_id="benchmark", raw_path=audio_path,
            media_type=MediaType.AUDIO, sha256=sha256_file(audio_path),
        )
        embedding = engine.embedding(candidate)
        embedding /= max(float(np.linalg.norm(embedding)), 1e-12)
        return float(np.dot(consensus, embedding))

    def _read(self) -> dict[str, BenchmarkRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            return {item["id"]: BenchmarkRun.model_validate(item) for item in payload.get("runs", [])}

    def _save(self, run: BenchmarkRun) -> None:
        runs = self._read()
        runs[run.id] = run
        self._write(runs)

    def _write(self, runs: dict[str, BenchmarkRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {"version": 1, "runs": [run.model_dump(mode="json") for run in runs.values()]})


def _compare_case(definition, baseline_path, lora_path, baseline, lora) -> BenchmarkCaseResult:
    checks: dict[str, bool | None] = {
        "visual_quality": lora.visual_quality >= 0.38,
        "temporal_stability": lora.temporal_stability >= 0.32,
        "motion_range": 0.05 <= lora.motion_score <= 0.82,
        "subject_coverage": lora.subject_coverage >= 0.28,
        "identity_similarity": None if lora.identity_similarity is None else lora.identity_similarity >= 0.45,
        "identity_gain": None if lora.identity_similarity is None or baseline.identity_similarity is None else lora.identity_similarity - baseline.identity_similarity >= 0.02,
        "identity_frame_coverage": None if lora.identity_frame_coverage is None else lora.identity_frame_coverage >= 0.60,
    }
    if definition.audio_required:
        checks.update({
            "audio_quality": None if lora.audio_quality is None else lora.audio_quality >= 0.55,
            "speaker_similarity": None if lora.speaker_similarity is None else lora.speaker_similarity >= 0.65,
            "transcript_similarity": None if lora.transcript_similarity is None else lora.transcript_similarity >= 0.60,
            "av_sync_proxy": None if lora.av_sync_proxy is None else lora.av_sync_proxy >= 0.15,
        })
    certified_checks = {}
    if definition.audio_required:
        certified_checks = {
            "syncnet_lse_c": None if lora.syncnet_lse_c is None else lora.syncnet_lse_c >= 3.0,
            "syncnet_lse_d": None if lora.syncnet_lse_d is None else lora.syncnet_lse_d <= 10.0,
            "syncnet_offset": None if lora.syncnet_offset_frames is None else abs(lora.syncnet_offset_frames) <= 3,
        }
    blocked = any(value is None for value in checks.values())
    failed = [name for name, value in checks.items() if value is False]
    certified_failed = [name for name, value in certified_checks.items() if value is False]
    return BenchmarkCaseResult(
        definition=definition,
        baseline_path=baseline_path,
        lora_path=lora_path,
        baseline=baseline,
        lora=lora,
        passed=not blocked and not failed,
        blocked=blocked,
        checks=checks,
        certified_checks=certified_checks,
        reasons=[
            *(f"failed {name.replace('_', ' ')}" for name in failed),
            *(f"failed certified {name.replace('_', ' ')}" for name in certified_failed),
            *lora.analyzer_notes,
        ],
    )


def _summarize(results: dict[str, BenchmarkCaseResult]) -> BenchmarkSummary:
    values = list(results.values())
    lora_identity = [item.lora.identity_similarity for item in values if item.lora.identity_similarity is not None]
    base_identity = [item.baseline.identity_similarity for item in values if item.baseline.identity_similarity is not None]
    speakers = [item.lora.speaker_similarity for item in values if item.lora.speaker_similarity is not None]
    sync = [item.lora.av_sync_proxy for item in values if item.lora.av_sync_proxy is not None]
    syncnet_c = [item.lora.syncnet_lse_c for item in values if item.lora.syncnet_lse_c is not None]
    syncnet_d = [item.lora.syncnet_lse_d for item in values if item.lora.syncnet_lse_d is not None]
    blocked_count = sum(item.blocked for item in values)
    failed_count = sum(not item.blocked and not item.passed for item in values)
    warnings = []
    if blocked_count:
        warnings.append("Install identity and speaker models and select trusted anchors to resolve blocked metrics.")
    screening_ready = bool(values) and all(item.passed for item in values)
    certified_values = [
        value
        for item in values
        for value in item.certified_checks.values()
    ]
    automated_release_ready = screening_ready and bool(certified_values) and all(value is True for value in certified_values)
    accepted_count = sum(item.review_decision == "accepted" for item in values)
    rejected_count = sum(item.review_decision == "rejected" for item in values)
    pending_count = sum(item.review_decision == "pending" for item in values)
    human_review_ready = bool(values) and accepted_count == len(values)
    release_ready = automated_release_ready and human_review_ready
    if screening_ready and not automated_release_ready:
        warnings.append("Local AV activity correlation passed, but certified SyncNet LSE-C/LSE-D validation is still required.")
    elif automated_release_ready and pending_count:
        warnings.append(f"Automated certification passed; human review is pending for {pending_count} case(s).")
    if rejected_count:
        warnings.append(f"Human review rejected {rejected_count} case(s); regenerate or reset those decisions before release.")
    return BenchmarkSummary(
        passed_count=sum(item.passed for item in values),
        failed_count=failed_count,
        blocked_count=blocked_count,
        identity_gain=(_mean(lora_identity) - _mean(base_identity)) if lora_identity and base_identity else None,
        average_lora_identity=_mean(lora_identity) if lora_identity else None,
        average_lora_stability=_mean(item.lora.temporal_stability for item in values),
        average_lora_motion=_mean(item.lora.motion_score for item in values),
        average_speaker_similarity=_mean(speakers) if speakers else None,
        average_av_sync_proxy=_mean(sync) if sync else None,
        average_syncnet_lse_c=_mean(syncnet_c) if syncnet_c else None,
        average_syncnet_lse_d=_mean(syncnet_d) if syncnet_d else None,
        screening_ready=screening_ready,
        automated_release_ready=automated_release_ready,
        human_review_ready=human_review_ready,
        release_ready=release_ready,
        review_pending_count=pending_count,
        review_accepted_count=accepted_count,
        review_rejected_count=rejected_count,
        validation_level="certified" if release_ready else "screening",
        warnings=warnings,
    )


def _av_sync_proxy(frames, face_analyses, audio_path, duration) -> float | None:
    if len(frames) < 4 or not face_analyses:
        return None
    samples, _warning = decode_mono_pcm(audio_path)
    if not samples:
        return None
    mouth_motion = []
    prior = None
    valid_indices = []
    for index, frame_path in enumerate(frames):
        faces = face_analyses.get(frame_path) or []
        if not faces:
            prior = None
            continue
        box = faces[0].face.bounding_box
        with Image.open(frame_path) as image:
            width, height = image.size
            crop = image.convert("L").crop((
                int(box.x * width), int((box.y + box.height * 0.58) * height),
                int((box.x + box.width) * width), int((box.y + box.height) * height),
            )).resize((48, 24))
            pixels = np.asarray(crop, dtype=np.float32) / 255.0
        if prior is not None:
            mouth_motion.append(float(np.mean(np.abs(pixels - prior))))
            valid_indices.append(index)
        prior = pixels
    if len(mouth_motion) < 3 or max(mouth_motion) - min(mouth_motion) < 1e-5:
        return None
    audio = np.asarray(samples, dtype=np.float32) / 32768.0
    energies = []
    for index in valid_indices:
        center = index / max(1, len(frames) - 1) * duration
        start = max(0, int((center - 0.12) * 16000))
        end = min(len(audio), int((center + 0.12) * 16000))
        window = audio[start:end]
        energies.append(float(np.sqrt(np.mean(window * window))) if len(window) else 0.0)
    if max(energies) - min(energies) < 1e-6:
        return None
    correlation = float(np.corrcoef(mouth_motion, energies)[0, 1])
    return max(0.0, min(1.0, correlation)) if math.isfinite(correlation) else None


def _syncnet_command_metrics(video_path: Path) -> SyncNetMetrics | None:
    arguments = syncnet_command()
    if not arguments:
        return None
    if any("{video}" in argument for argument in arguments):
        arguments = [argument.replace("{video}", str(video_path)) for argument in arguments]
    else:
        arguments.append(str(video_path))
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=300, shell=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(detail)
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise ValueError("SyncNet command must emit a JSON object on its final stdout line") from error
    return SyncNetMetrics(
        lse_c=float(payload["lse_c"]),
        lse_d=float(payload["lse_d"]),
        offset_frames=int(payload.get("offset_frames") or 0),
    )


def _text_similarity(expected: str, actual: str) -> float:
    left = [word.strip(".,!?;:\"'").lower() for word in expected.split() if word.strip()]
    right = [word.strip(".,!?;:\"'").lower() for word in actual.split() if word.strip()]
    if not left:
        return 1.0
    distances = list(range(len(right) + 1))
    for index, word in enumerate(left, start=1):
        next_row = [index]
        for column, candidate in enumerate(right, start=1):
            next_row.append(min(next_row[-1] + 1, distances[column] + 1, distances[column - 1] + (word != candidate)))
        distances = next_row
    return max(0.0, 1.0 - distances[-1] / max(len(left), len(right), 1))


def _mean(values) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 0.0
