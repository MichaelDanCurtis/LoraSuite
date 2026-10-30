from __future__ import annotations

import shutil
import wave
from array import array
from pathlib import Path

import pytest

import lorasuite_engine.voice_dataset as voice_dataset_module
from lorasuite_engine.models import (
    CurationRecommendation,
    VoiceIdentityEvidence,
    VoiceIdentityProfile,
    VoiceSegmentQualityEvidence,
    VoiceSegmentStatus,
)
from lorasuite_engine.speech_analysis import AudioSpeechEvidence, SpeechWord
from lorasuite_engine.vault import VaultService
from lorasuite_engine.voice_dataset import VoiceDatasetService, join_words, segment_speech_words


def write_wav(path: Path, seconds: int = 5) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(array("h", [0, 900, -900, 0] * (4000 * seconds)).tobytes())


def test_segment_speech_words_uses_pauses_and_sentence_boundaries() -> None:
    words = [
        SpeechWord("Hello", 0.2, 0.6, 0.9),
        SpeechWord("there.", 0.7, 3.3, 0.9),
        SpeechWord("Second", 3.45, 3.9, 0.8),
        SpeechWord("thought", 4.0, 4.7, 0.8),
        SpeechWord("after", 5.6, 6.0, 0.9),
        SpeechWord("a pause.", 6.1, 7.0, 0.9),
    ]

    segments = segment_speech_words(words, duration=8.0)

    assert len(segments) == 3
    assert join_words(segments[0][2]) == "Hello there."
    assert join_words(segments[1][2]) == "Second thought"
    assert join_words(segments[2][2]) == "after a pause."
    assert segments[0][0] == pytest.approx(0.08)
    assert segments[-1][1] == pytest.approx(7.18)


def test_join_words_excludes_whisper_non_speech_annotations() -> None:
    words = [
        SpeechWord("*music*", 0.0, 0.5),
        SpeechWord("Spoken", 0.6, 0.9),
        SpeechWord("line.", 1.0, 1.4),
        SpeechWord("[applause]", 1.5, 2.0),
    ]

    assert join_words(words) == "Spoken line."


def test_voice_dataset_compiles_scores_and_persists_review(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "source.wav"
    write_wav(audio_path)
    vault_root = tmp_path / "vault"
    source = VaultService(vault_root).import_local_paths([audio_path]).media_items[0]

    class FakeSpeechAnalyzer:
        def analyze(self, _path: Path, _duration: float | None) -> AudioSpeechEvidence:
            return AudioSpeechEvidence(
                transcript="One clean sentence. Another useful sentence.",
                language="en",
                transcript_confidence=0.94,
                words=[
                    SpeechWord("One", 0.2, 0.5, 0.9),
                    SpeechWord("clean", 0.6, 0.9, 0.9),
                    SpeechWord("sentence.", 1.0, 3.3, 0.9),
                    SpeechWord("Another", 3.5, 3.9, 0.9),
                    SpeechWord("useful", 4.0, 4.3, 0.9),
                    SpeechWord("sentence.", 4.4, 4.8, 0.9),
                ],
            )

    class FakeVoiceIdentityService:
        def __init__(self, _vault_root: Path):
            pass

        def get_profile(self, project_id: str) -> VoiceIdentityProfile:
            return VoiceIdentityProfile(project_id=project_id, anchor_media_item_ids=["anchor"])

        def analyze(self, project_id: str, media_item_ids: list[str]) -> VoiceIdentityProfile:
            return VoiceIdentityProfile(
                project_id=project_id,
                anchor_media_item_ids=["anchor"],
                evidence={
                    media_id: VoiceIdentityEvidence(
                        media_item_id=media_id,
                        similarity=0.91,
                        recommendation=CurationRecommendation.KEEP,
                        reasons=["Speaker closely matches trusted anchors"],
                    )
                    for media_id in media_item_ids
                },
            )

    class FakeQualityAnalyzer:
        def analyze(self, *_args, **_kwargs) -> VoiceSegmentQualityEvidence:
            return VoiceSegmentQualityEvidence(
                quality_score=0.88,
                recommendation=CurationRecommendation.KEEP,
                active_audio_ratio=0.72,
                clipping_ratio=0.0,
                snr_db=24.0,
                source_classification="isolated_voice",
                voice_isolation_applied=True,
                reasons=["clean active speech with usable signal separation"],
            )

    def fake_extract(source_path: Path, output_path: Path, _start: float, _end: float) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)

    monkeypatch.setattr(voice_dataset_module, "AppleSpeechAnalyzer", FakeSpeechAnalyzer)
    monkeypatch.setattr(voice_dataset_module, "VoiceIdentityService", FakeVoiceIdentityService)
    monkeypatch.setattr(voice_dataset_module, "VoiceQualityAnalyzer", FakeQualityAnalyzer)
    monkeypatch.setattr(voice_dataset_module, "extract_audio_segment", fake_extract)

    service = VoiceDatasetService(vault_root)
    compilation = service.compile("project_1", [source.id])

    assert compilation.source_media_item_ids == [source.id]
    assert len(compilation.segments) == 2
    first = next(iter(compilation.segments.values()))
    assert first.speaker_similarity == 0.91
    assert first.recommendation == CurationRecommendation.KEEP
    assert first.audio_path.is_file()

    updated = service.update_segment(
        "project_1",
        first.id,
        status=VoiceSegmentStatus.APPROVED,
        transcript="Reviewed transcript.",
    )
    persisted = VoiceDatasetService(vault_root).get("project_1")

    assert updated.segments[first.id].status == VoiceSegmentStatus.APPROVED
    assert updated.balance.recipe_compliance is not None
    assert updated.balance.recipe_compliance.recipe_id == "fish_speech_s2_voice_character"
    assert updated.balance.recipe_compliance.status == "review"
    assert updated.dataset_fingerprint
    assert persisted.segments[first.id].transcript == "Reviewed transcript."
    assert len(VaultService(vault_root).list_media_items()) == 3

    segment_ids = list(compilation.segments)
    bulk = service.bulk_update_segments(
        "project_1",
        {
            segment_ids[0]: VoiceSegmentStatus.APPROVED,
            segment_ids[1]: VoiceSegmentStatus.REJECTED,
        },
    )
    rescored = service.rescore("project_1")

    assert bulk.segments[segment_ids[1]].status == VoiceSegmentStatus.REJECTED
    assert rescored.segments[segment_ids[0]].status == VoiceSegmentStatus.APPROVED
    assert rescored.segments[segment_ids[1]].speaker_similarity == 0.91


def test_bulk_voice_decisions_validate_every_segment_before_writing(tmp_path: Path) -> None:
    service = VoiceDatasetService(tmp_path / "vault")

    with pytest.raises(KeyError):
        service.bulk_update_segments(
            "project_1",
            {"missing": VoiceSegmentStatus.APPROVED},
        )

    assert service.get("project_1").segments == {}
