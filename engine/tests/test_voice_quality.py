from array import array

import lorasuite_engine.voice_quality as voice_quality_module
from lorasuite_engine.models import CurationRecommendation
from lorasuite_engine.voice_quality import VoiceQualityAnalyzer, classify_source


def test_voice_quality_keeps_clean_isolated_single_speaker(monkeypatch) -> None:
    samples = array("h")
    for index in range(96):
        level = 11000 if index % 24 < 12 else 120
        samples.extend([level, -level] * 160)
    monkeypatch.setattr(voice_quality_module, "decode_mono_pcm", lambda _path: (samples, None))

    evidence = VoiceQualityAnalyzer().analyze(
        voice_quality_module.Path("voice.wav"),
        transcript_confidence=0.92,
        speaker_count=1,
        source_metadata={"voice_isolation_applied": True},
    )

    assert evidence.recommendation == CurationRecommendation.KEEP
    assert evidence.quality_score >= 0.68
    assert evidence.source_classification == "isolated_voice"
    assert evidence.snr_db is not None and evidence.snr_db > 20
    assert evidence.clipping_ratio == 0.0


def test_voice_quality_rejects_clipped_audio(monkeypatch) -> None:
    samples = array("h", [32767, -32768] * 16000)
    monkeypatch.setattr(voice_quality_module, "decode_mono_pcm", lambda _path: (samples, None))

    evidence = VoiceQualityAnalyzer().analyze(
        voice_quality_module.Path("clipped.wav"),
        transcript_confidence=0.9,
        speaker_count=1,
        source_metadata={"audio_original": True},
    )

    assert evidence.recommendation == CurationRecommendation.REJECT
    assert "clipped" in evidence.reasons[0]


def test_voice_quality_uses_source_provenance_for_music_and_isolation() -> None:
    assert classify_source({"audio_kind": "reused_or_music"}) == (
        "reused_or_music",
        False,
        1.0,
    )
    assert classify_source({"voice_isolation_applied": True}) == (
        "isolated_voice",
        True,
        0.08,
    )
