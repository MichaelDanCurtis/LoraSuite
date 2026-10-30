from __future__ import annotations

import math
import wave
from array import array
from hashlib import sha256
from pathlib import Path

import pytest

from lorasuite_engine.curation_analysis import CurationAnalyzer
from lorasuite_engine.models import MediaItem, MediaType
from lorasuite_engine.speech_analysis import AudioSpeechEvidence


def test_audio_curator_uses_speech_and_single_speaker_evidence(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.wav"
    samples = array(
        "h",
        (
            int(9000 * math.sin(2 * math.pi * 220 * index / 8000))
            for index in range(8000 * 2)
        ),
    )
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(samples.tobytes())

    item = MediaItem(
        source_id="source_voice",
        raw_path=audio_path,
        media_type=MediaType.AUDIO,
        sha256=sha256(audio_path.read_bytes()).hexdigest(),
        duration=2.0,
        metadata_json={"audio_original": True, "audio_kind": "original"},
    )
    analyzer = CurationAnalyzer()
    analyzer.speech_analyzer = FakeSpeechAnalyzer()

    evidence = analyzer.analyze(item)

    assert evidence.recommendation.value == "keep"
    assert evidence.transcript == "This is a clean voice sample."
    assert evidence.language == "en"
    assert evidence.word_count == 6
    assert evidence.speaker_count == 1
    assert evidence.speech_duration_ratio == pytest.approx(0.72)
    assert evidence.analyzer == "apple-speech-audio-curator-v2"


class FakeSpeechAnalyzer:
    def analyze(self, path: Path, duration: float | None) -> AudioSpeechEvidence:
        assert path.name == "voice.wav"
        assert duration == 2.0
        return AudioSpeechEvidence(
            transcript="This is a clean voice sample.",
            language="en",
            speech_duration_ratio=0.72,
            transcript_confidence=0.94,
            word_count=6,
            speaker_count=1,
            speaker_duration_ratio=0.7,
        )
