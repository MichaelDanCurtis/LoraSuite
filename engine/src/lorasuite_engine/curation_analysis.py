from __future__ import annotations

import math
import statistics
import subprocess
import tempfile
from array import array
from pathlib import Path

from lorasuite_engine.dataset_analysis import DatasetImageAnalyzer, DatasetImageEvidence
from lorasuite_engine.identity_engine import SFaceIdentityEngine
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.models import (
    CurationAnalysisEvidence,
    CurationRecommendation,
    MediaItem,
    MediaType,
)
from lorasuite_engine.speech_analysis import AppleSpeechAnalyzer


class CurationAnalyzer:
    def __init__(self, vault_root: Path | None = None) -> None:
        identity_engine = None
        if vault_root is not None:
            try:
                identity_models = IdentityModelService(vault_root)
                if identity_models.status().ready:
                    identity_engine = SFaceIdentityEngine(identity_models.paths)
            except Exception:
                identity_engine = None
        self.image_analyzer = DatasetImageAnalyzer(identity_engine=identity_engine)
        self.speech_analyzer = AppleSpeechAnalyzer()

    def analyze(self, item: MediaItem) -> CurationAnalysisEvidence:
        if item.media_type == MediaType.IMAGE:
            return self._analyze_image(item)
        if item.media_type == MediaType.AUDIO:
            return self._analyze_audio(item)
        return self._analyze_video(item)

    def _analyze_image(self, item: MediaItem) -> CurationAnalysisEvidence:
        try:
            evidence = self.image_analyzer.analyze(item.raw_path)
        except (OSError, ValueError) as error:
            return CurationAnalysisEvidence(
                media_item_id=item.id,
                media_type=item.media_type,
                recommendation=CurationRecommendation.REJECT,
                confidence=0.98,
                reasons=["image could not be analyzed"],
                warnings=[str(error)],
                analyzer="local-image-curator-v1",
            )

        reasons: list[str] = []
        warnings: list[str] = []
        if evidence.quality_score < 0.22:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.92
            reasons.append("very low sharpness, exposure, or usable detail")
        elif evidence.face_count > 1:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.82
            reasons.append("multiple faces require subject confirmation")
        elif evidence.face_count == 0 and evidence.body_coverage < 0.03:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.76
            reasons.append("no clear face or person signal")
        elif evidence.quality_score < 0.42:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.72
            reasons.append("borderline visual quality")
        elif evidence.face_count == 1:
            recommendation = CurationRecommendation.KEEP
            confidence = 0.88
            reasons.append("one usable face with sufficient visual quality")
        else:
            recommendation = CurationRecommendation.KEEP
            confidence = 0.74
            reasons.append("usable person or body evidence")
        if evidence.face_count == 0:
            warnings.append("identity must be confirmed from body context or source continuity")
        return CurationAnalysisEvidence(
            media_item_id=item.id,
            media_type=item.media_type,
            recommendation=recommendation,
            confidence=confidence,
            quality_score=evidence.quality_score,
            face_count=evidence.face_count,
            face_area=evidence.face_area,
            body_coverage=evidence.body_coverage,
            pose_coverage=evidence.pose_coverage,
            aesthetic_score=evidence.aesthetic_score,
            head_yaw=evidence.head_yaw,
            head_pitch=evidence.head_pitch,
            head_roll=evidence.head_roll,
            reasons=reasons,
            warnings=warnings,
            analyzer=evidence.analyzer,
        )

    def _analyze_audio(self, item: MediaItem) -> CurationAnalysisEvidence:
        override = _metadata_string(item, "audio_review_override")
        original = item.metadata_json.get("audio_original")
        kind = _metadata_string(item, "audio_kind")
        active_ratio, clipping_ratio, signal_warning = _audio_signal_metrics(item.raw_path)
        warnings = [signal_warning] if signal_warning else []
        speech = None
        if original is not False and kind not in {"music", "reused_or_music"}:
            speech = self.speech_analyzer.analyze(item.raw_path, item.duration)
            warnings.extend(speech.warnings)

        if override == "keep":
            recommendation = CurationRecommendation.KEEP
            confidence = 0.99
            reasons = ["kept by explicit user audio review"]
        elif original is False or kind in {"music", "reused_or_music"}:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.96
            reasons = ["source metadata identifies reused or musical audio"]
        elif item.duration is not None and item.duration < 1.5:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.9
            reasons = ["too little audio for useful speech evidence"]
        elif clipping_ratio is not None and clipping_ratio > 0.04:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.88
            reasons = ["audio is heavily clipped"]
        elif active_ratio is not None and active_ratio < 0.08:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.9
            reasons = ["audio is predominantly silent"]
        elif speech is not None and (speech.word_count or 0) >= 4:
            recommendation = (
                CurationRecommendation.KEEP
                if original is True and (speech.speaker_count or 0) <= 1
                else CurationRecommendation.REVIEW
            )
            confidence = 0.9 if recommendation == CurationRecommendation.KEEP else 0.84
            reasons = [
                f"WhisperKit detected {speech.word_count} words across "
                f"{round((speech.speech_duration_ratio or 0) * 100)}% of the track"
            ]
            if (speech.speaker_count or 0) > 1:
                reasons.append(f"SpeakerKit detected {speech.speaker_count} speakers")
            elif original is not True:
                reasons.append("speaker ownership still requires verification")
        elif speech is not None and speech.word_count == 0:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.82
            reasons = ["no reliable speech transcript was detected"]
        elif original is True and (active_ratio is None or active_ratio >= 0.25):
            recommendation = CurationRecommendation.KEEP
            confidence = 0.78
            reasons = ["original audio has sufficient active signal"]
        else:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.72
            reasons = ["speaker ownership and speech content require verification"]
        return CurationAnalysisEvidence(
            media_item_id=item.id,
            media_type=item.media_type,
            recommendation=recommendation,
            confidence=confidence,
            active_audio_ratio=active_ratio,
            clipping_ratio=clipping_ratio,
            transcript=speech.transcript if speech else None,
            language=speech.language if speech else None,
            speech_duration_ratio=speech.speech_duration_ratio if speech else None,
            transcript_confidence=speech.transcript_confidence if speech else None,
            word_count=speech.word_count if speech else None,
            speaker_count=speech.speaker_count if speech else None,
            speaker_duration_ratio=speech.speaker_duration_ratio if speech else None,
            reasons=reasons,
            warnings=warnings,
            analyzer=(
                "apple-speech-audio-curator-v2"
                if speech is not None
                else "local-audio-signal-curator-v1"
            ),
        )

    def _analyze_video(self, item: MediaItem) -> CurationAnalysisEvidence:
        if item.duration is not None and item.duration < 1.0:
            return CurationAnalysisEvidence(
                media_item_id=item.id,
                media_type=item.media_type,
                recommendation=CurationRecommendation.REJECT,
                confidence=0.88,
                reasons=["video is too short for useful temporal evidence"],
                analyzer="local-video-curator-v1",
            )
        if item.width is not None and item.height is not None and min(item.width, item.height) < 256:
            return CurationAnalysisEvidence(
                media_item_id=item.id,
                media_type=item.media_type,
                recommendation=CurationRecommendation.REVIEW,
                confidence=0.8,
                reasons=["video resolution is marginal"],
                analyzer="local-video-curator-v1",
            )
        samples, warning = _sample_video_evidence(item, self.image_analyzer)
        if not samples:
            return CurationAnalysisEvidence(
                media_item_id=item.id,
                media_type=item.media_type,
                recommendation=CurationRecommendation.REVIEW,
                confidence=0.55,
                reasons=["representative video frames could not be measured"],
                warnings=[warning] if warning else [],
                sample_count=0,
                analyzer="sampled-video-curator-v2",
            )
        quality_score = statistics.fmean(sample.quality_score for sample in samples)
        face_count = max(sample.face_count for sample in samples)
        face_area = max(sample.face_area for sample in samples)
        body_coverage = max(sample.body_coverage for sample in samples)
        pose_coverage = max(sample.pose_coverage for sample in samples)
        aesthetic_score = statistics.fmean(sample.aesthetic_score for sample in samples)
        person_signal = max(
            min(1.0, face_area / 0.1),
            min(1.0, body_coverage / 0.3),
            pose_coverage,
        )
        warnings = [warning] if warning else []
        if quality_score < 0.2:
            recommendation = CurationRecommendation.REJECT
            confidence = min(0.96, 0.82 + (0.2 - quality_score) * 0.7)
            reasons = ["sampled frames have very low usable visual quality"]
        elif person_signal < 0.08:
            recommendation = CurationRecommendation.REVIEW
            confidence = min(0.9, 0.72 + quality_score * 0.12)
            reasons = ["sampled frames lack a consistent person signal"]
        else:
            recommendation = CurationRecommendation.REVIEW
            confidence = min(0.95, 0.7 + quality_score * 0.12 + person_signal * 0.1)
            reasons = ["sampled frames support intelligent identity breakdown"]
        return CurationAnalysisEvidence(
            media_item_id=item.id,
            media_type=item.media_type,
            recommendation=recommendation,
            confidence=confidence,
            quality_score=quality_score,
            face_count=face_count,
            face_area=face_area,
            body_coverage=body_coverage,
            pose_coverage=pose_coverage,
            aesthetic_score=aesthetic_score,
            sample_count=len(samples),
            reasons=reasons,
            warnings=warnings,
            analyzer="sampled-video-curator-v2",
        )


def _metadata_string(item: MediaItem, key: str) -> str | None:
    value = item.metadata_json.get(key)
    return value.lower() if isinstance(value, str) and value else None


def _sample_video_evidence(
    item: MediaItem,
    analyzer: DatasetImageAnalyzer,
) -> tuple[list[DatasetImageEvidence], str | None]:
    if not item.raw_path.exists():
        return [], "video file is missing"
    duration = item.duration if item.duration is not None and item.duration > 0 else 6.0
    timestamps = sorted({max(0.05, duration * fraction) for fraction in (0.1, 0.45, 0.75)})
    samples = []
    with tempfile.TemporaryDirectory(prefix="lorasuite-video-curation-") as directory:
        output_dir = Path(directory)
        for index, timestamp in enumerate(timestamps):
            output_path = output_dir / f"sample-{index:02d}.jpg"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(item.raw_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(output_path),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    shell=False,
                    timeout=30,
                )
            except FileNotFoundError:
                return samples, "ffmpeg unavailable; video frames were not sampled"
            except subprocess.TimeoutExpired:
                return samples, "video frame sampling timed out"
            if result.returncode != 0 or not output_path.exists():
                continue
            try:
                samples.append(analyzer.analyze(output_path))
            except (OSError, ValueError):
                continue
    warning = None if len(samples) == len(timestamps) else "some representative frames could not be analyzed"
    return samples, warning


def _audio_signal_metrics(path: Path) -> tuple[float | None, float | None, str | None]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-t",
        "60",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, shell=False)
    except FileNotFoundError:
        return None, None, "ffmpeg unavailable; source metadata only"
    if result.returncode != 0 or not result.stdout:
        return None, None, "audio signal could not be decoded"
    samples = array("h")
    samples.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % 2)])
    if not samples:
        return 0.0, 0.0, None
    window_size = 160
    window_rms = []
    for offset in range(0, len(samples), window_size):
        window = samples[offset : offset + window_size]
        if not window:
            continue
        window_rms.append(math.sqrt(sum(value * value for value in window) / len(window)))
    noise_floor = max(180.0, statistics.median(window_rms) * 0.18) if window_rms else 180.0
    active_ratio = sum(value > noise_floor for value in window_rms) / max(1, len(window_rms))
    clipping_ratio = sum(abs(value) >= 32700 for value in samples) / len(samples)
    return min(1.0, active_ratio), min(1.0, clipping_ratio), None
