from __future__ import annotations

import wave
from array import array
from pathlib import Path

import numpy as np

import lorasuite_engine.speaker_identity as speaker_identity_module
from lorasuite_engine.models import IdentityRuntimeStatus
from lorasuite_engine.speaker_identity import VoiceIdentityService
from lorasuite_engine.vault import VaultService


def write_wav(path: Path, level: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(array("h", [0, level, -level, 0] * 8000).tobytes())


def test_voice_identity_persists_anchors_and_scores_candidates(monkeypatch, tmp_path: Path) -> None:
    paths = [tmp_path / "anchor.wav", tmp_path / "match.wav", tmp_path / "other.wav"]
    for index, path in enumerate(paths, start=1):
        write_wav(path, index * 1000)
    vault = VaultService(tmp_path / "vault")
    anchor, match, other = vault.import_local_paths(paths).media_items
    embeddings = {
        anchor.id: np.array([1.0, 0.0], dtype=np.float32),
        match.id: np.array([0.9, 0.1], dtype=np.float32),
        other.id: np.array([0.0, 1.0], dtype=np.float32),
    }

    class FakeEmbeddingEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def embedding(self, item):
            return embeddings[item.id].copy()

    monkeypatch.setattr(speaker_identity_module, "SpeakerEmbeddingEngine", FakeEmbeddingEngine)
    monkeypatch.setattr(
        speaker_identity_module.SpeakerIdentityModelService,
        "status",
        lambda _self: IdentityRuntimeStatus(installed=True, ready=True),
    )
    service = VoiceIdentityService(tmp_path / "vault")

    anchored = service.set_anchors("project_1", [anchor.id])
    analyzed = service.analyze("project_1", [match.id, other.id])

    assert anchored.anchor_media_item_ids == [anchor.id]
    assert analyzed.evidence[anchor.id].is_anchor is True
    assert analyzed.evidence[match.id].recommendation.value == "keep"
    assert analyzed.evidence[match.id].similarity > 0.9
    assert analyzed.evidence[other.id].recommendation.value == "reject"
    assert analyzed.evidence[other.id].similarity == 0.0
    assert service.get_profile("project_1").evidence[match.id].similarity > 0.9


def test_voice_identity_requires_a_trusted_anchor(tmp_path: Path) -> None:
    service = VoiceIdentityService(tmp_path / "vault")

    try:
        service.analyze("project_1", [])
    except ValueError as error:
        assert str(error) == "Select at least one trusted voice anchor"
    else:
        raise AssertionError("expected voice analysis without anchors to fail")
