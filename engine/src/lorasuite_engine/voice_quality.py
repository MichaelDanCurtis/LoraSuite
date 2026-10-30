from __future__ import annotations

import math
import statistics
import subprocess
from array import array
from pathlib import Path
from typing import Any

from lorasuite_engine.models import CurationRecommendation, VoiceSegmentQualityEvidence


class VoiceQualityAnalyzer:
    def analyze(
        self,
        path: Path,
        *,
        transcript_confidence: float | None,
        speaker_count: int | None,
        source_metadata: dict[str, Any],
    ) -> VoiceSegmentQualityEvidence:
        samples, warning = decode_mono_pcm(path)
        classification, isolation_applied, music_risk = classify_source(source_metadata)
        warnings = [warning] if warning else []
        if not samples:
            return VoiceSegmentQualityEvidence(
                quality_score=0.0,
                recommendation=CurationRecommendation.REJECT,
                speaker_count=speaker_count,
                source_classification=classification,
                voice_isolation_applied=isolation_applied,
                background_music_risk=music_risk,
                reasons=["audio signal could not be measured"],
                warnings=warnings,
            )

        metrics = signal_metrics(samples)
        transcript_score = transcript_confidence if transcript_confidence is not None else 0.55
        snr_score = clamp((metrics["snr_db"] - 8.0) / 22.0)
        activity_score = clamp(metrics["active_audio_ratio"] / 0.45)
        clipping_score = 1.0 - clamp(metrics["clipping_ratio"] / 0.025)
        reverb_score = 1.0 - metrics["reverb_risk"]
        speaker_score = 1.0 if speaker_count == 1 else 0.35 if speaker_count and speaker_count > 1 else 0.65
        music_score = 1.0 - music_risk
        quality_score = clamp(
            0.25 * snr_score
            + 0.18 * activity_score
            + 0.18 * clipping_score
            + 0.12 * reverb_score
            + 0.12 * transcript_score
            + 0.08 * speaker_score
            + 0.07 * music_score
        )

        reasons: list[str] = []
        if metrics["clipping_ratio"] > 0.025:
            recommendation = CurationRecommendation.REJECT
            reasons.append("audio is heavily clipped")
        elif metrics["active_audio_ratio"] < 0.18:
            recommendation = CurationRecommendation.REJECT
            reasons.append("segment contains too little active voice")
        elif speaker_count is not None and speaker_count > 1:
            recommendation = CurationRecommendation.REVIEW
            reasons.append(f"SpeakerKit detected {speaker_count} speakers")
        elif classification in {"music", "reused_or_music"}:
            recommendation = CurationRecommendation.REVIEW
            reasons.append("source metadata suggests music, but detected speech requires human verification")
        elif quality_score >= 0.68 and metrics["snr_db"] >= 14 and metrics["reverb_risk"] < 0.65:
            recommendation = CurationRecommendation.KEEP
            reasons.append("clean active speech with usable signal separation")
        elif quality_score < 0.42:
            recommendation = CurationRecommendation.REJECT
            reasons.append("combined speech cleanliness is too low")
        else:
            recommendation = CurationRecommendation.REVIEW
            reasons.append("speech is usable but needs a quality check")

        if isolation_applied:
            reasons.append("vocal isolation was applied before segmentation")
        if metrics["snr_db"] < 14:
            warnings.append("low voice-to-background separation")
        if metrics["reverb_risk"] >= 0.65:
            warnings.append("quiet-tail persistence suggests possible room echo or reverb")
        if speaker_count is None:
            warnings.append("speaker overlap was not measured")
        return VoiceSegmentQualityEvidence(
            quality_score=quality_score,
            recommendation=recommendation,
            active_audio_ratio=metrics["active_audio_ratio"],
            silence_ratio=metrics["silence_ratio"],
            clipping_ratio=metrics["clipping_ratio"],
            noise_floor_db=metrics["noise_floor_db"],
            snr_db=metrics["snr_db"],
            dynamic_range_db=metrics["dynamic_range_db"],
            reverb_risk=metrics["reverb_risk"],
            background_music_risk=music_risk,
            speaker_count=speaker_count,
            source_classification=classification,
            voice_isolation_applied=isolation_applied,
            reasons=reasons,
            warnings=warnings,
        )


def decode_mono_pcm(path: Path) -> tuple[array, str | None]:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, shell=False, timeout=60)
    except FileNotFoundError:
        return array("h"), "ffmpeg unavailable"
    except subprocess.TimeoutExpired:
        return array("h"), "audio quality analysis timed out"
    if result.returncode != 0 or not result.stdout:
        return array("h"), "audio signal could not be decoded"
    samples = array("h")
    samples.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % 2)])
    return samples, None


def signal_metrics(samples: array) -> dict[str, float]:
    window_size = 320
    rms = [
        math.sqrt(sum(value * value for value in samples[offset : offset + window_size]) / len(samples[offset : offset + window_size]))
        for offset in range(0, len(samples), window_size)
        if samples[offset : offset + window_size]
    ]
    db = [amplitude_db(value) for value in rms]
    noise_floor = percentile(db, 0.15)
    signal_level = percentile(db, 0.85)
    peak_level = percentile(db, 0.98)
    active_threshold = max(-48.0, noise_floor + 8.0)
    active = [value >= active_threshold for value in db]
    active_ratio = sum(active) / max(1, len(active))
    clipping_ratio = sum(abs(value) >= 32700 for value in samples) / len(samples)
    return {
        "active_audio_ratio": clamp(active_ratio),
        "silence_ratio": clamp(1.0 - active_ratio),
        "clipping_ratio": clamp(clipping_ratio),
        "noise_floor_db": noise_floor,
        "snr_db": max(0.0, signal_level - noise_floor),
        "dynamic_range_db": max(0.0, peak_level - noise_floor),
        "reverb_risk": reverb_tail_risk(rms, active),
    }


def reverb_tail_risk(rms: list[float], active: list[bool]) -> float:
    ratios: list[float] = []
    for index in range(4, len(active) - 12):
        if not active[index] or active[index + 1]:
            continue
        if sum(active[index + 1 : index + 12]) > 2:
            continue
        before = statistics.fmean(rms[index - 3 : index + 1])
        tail = statistics.fmean(rms[index + 3 : index + 12])
        if before > 1.0:
            ratios.append(tail / before)
    if not ratios:
        return 0.35
    return clamp((statistics.median(ratios) - 0.08) / 0.42)


def classify_source(metadata: dict[str, Any]) -> tuple[str, bool, float]:
    isolation = metadata.get("voice_isolation_applied") is True
    kind = str(metadata.get("audio_kind") or "").lower()
    original = metadata.get("audio_original")
    if kind in {"music", "reused_or_music"} or original is False:
        return kind or "reused_or_music", isolation, 1.0
    if isolation:
        return "isolated_voice", True, 0.08
    if original is True:
        return "original_voice", False, 0.2
    return "unverified_voice", False, 0.45


def amplitude_db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1.0) / 32768.0)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return -96.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
