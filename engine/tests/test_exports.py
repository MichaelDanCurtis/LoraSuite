import json
from pathlib import Path

import pytest
from PIL import Image

import lorasuite_engine.exports as exports_module
from lorasuite_engine.exports import create_voice_dataset_export
from lorasuite_engine.models import (
    CurationRecommendation,
    ExportType,
    VoiceDatasetCompilation,
    VoiceDatasetSegment,
    VoiceExportTarget,
    VoiceSegmentQualityEvidence,
    VoiceSegmentStatus,
)
from lorasuite_engine.vault import sha256_file


def create_frame(path: Path, color: tuple[int, int, int] = (200, 100, 50)) -> Path:
    Image.new("RGB", (32, 32), color=color).save(path)
    return path


def test_voice_dataset_export_writes_approved_audio_and_transcripts(tmp_path):
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"RIFF-test-audio")
    compilation = VoiceDatasetCompilation(
        project_id="project_1",
        source_media_item_ids=["source_1"],
        segments={
            "segment_1": VoiceDatasetSegment(
                id="segment_1",
                project_id="project_1",
                source_media_item_id="source_1",
                media_item_id="media_1",
                audio_path=audio,
                start_seconds=1.25,
                end_seconds=4.5,
                transcript="A reviewed voice line.",
                language="en",
                speaker_similarity=0.93,
                status=VoiceSegmentStatus.APPROVED,
            )
        },
    )

    package = create_voice_dataset_export(compilation=compilation, output_dir=tmp_path / "voice")

    assert package.export_type == ExportType.VOICE_HANDOFF
    assert (tmp_path / "voice/voice_cloning/audio/000001.wav").read_bytes() == audio.read_bytes()
    assert (tmp_path / "voice/voice_cloning/audio/000001.txt").read_text() == "A reviewed voice line.\n"
    assert json.loads((tmp_path / "voice/voice_cloning/metadata.jsonl").read_text())["text"] == "A reviewed voice line."
    assert (tmp_path / f"voice/voice_cloning/fish_speech/{compilation.project_id}/000001.wav").is_file()
    assert (tmp_path / f"voice/voice_cloning/fish_speech/{compilation.project_id}/000001.lab").read_text() == "A reviewed voice line.\n"
    manifest = json.loads((tmp_path / "voice/manifest.json").read_text())
    assert manifest["character_project_id"] == "project_1"
    assert manifest["target"] == "voice_cloning"
    assert manifest["training_target"]["profile_id"] == "runpod_fish_speech_s2_voice_lora"
    assert manifest["training_target"]["recipe_id"] == "fish_speech_s2_voice_character"
    assert manifest["training_target"]["recipe_version"] == 1
    assert manifest["training_target"]["ready"] is False
    assert manifest["dataset_fingerprint"]
    assert manifest["recipe_compliance"]["status"] == "review"
    assert manifest["files"][0]["speaker_similarity"] == 0.93
    assert manifest["files"][0]["transcript_text"] == "A reviewed voice line."


def test_voice_dataset_export_can_build_both_training_targets(tmp_path):
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"RIFF-test-audio")
    segment = VoiceDatasetSegment(
        id="segment_1",
        project_id="project_1",
        source_media_item_id="source_1",
        media_item_id="media_1",
        audio_path=audio,
        start_seconds=2.0,
        end_seconds=5.0,
        transcript="Aligned reference speech.",
        status=VoiceSegmentStatus.APPROVED,
    )

    create_voice_dataset_export(
        compilation=VoiceDatasetCompilation(
            project_id="project_1",
            source_media_item_ids=["source_1"],
            segments={segment.id: segment},
        ),
        output_dir=tmp_path / "both",
        target=VoiceExportTarget.BOTH,
    )

    assert (tmp_path / "both/voice_cloning/audio/000001.wav").is_file()
    assert (tmp_path / "both/av_lora/audio_reference/000001.wav").is_file()
    av_entry = json.loads((tmp_path / "both/av_lora/audio_manifest.jsonl").read_text())
    assert av_entry["start_seconds"] == 2.0
    assert av_entry["end_seconds"] == 5.0


def test_voice_dataset_export_marks_recipe_compliant_fish_speech_package_ready(tmp_path):
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"RIFF-test-audio")
    quality = VoiceSegmentQualityEvidence(
        quality_score=0.9,
        recommendation=CurationRecommendation.KEEP,
        active_audio_ratio=0.8,
        silence_ratio=0.1,
        clipping_ratio=0.0,
        background_music_risk=0.1,
        speaker_count=1,
        source_classification="isolated_voice",
    )
    segments = {
        f"segment_{index}": VoiceDatasetSegment(
            id=f"segment_{index}",
            project_id="project_1",
            source_media_item_id=f"source_{1 if index <= 2 else 2}",
            media_item_id=f"media_{index}",
            audio_path=audio,
            start_seconds=0,
            end_seconds=4,
            transcript=f"Verified spoken phrase {index}.",
            transcript_confidence=0.94,
            speaker_similarity=0.91,
            quality=quality,
            status=VoiceSegmentStatus.APPROVED,
        )
        for index in range(1, 5)
    }

    create_voice_dataset_export(
        compilation=VoiceDatasetCompilation(
            project_id="project_1",
            source_media_item_ids=["source_1", "source_2"],
            segments=segments,
        ),
        output_dir=tmp_path / "ready-voice",
    )

    manifest = json.loads((tmp_path / "ready-voice/manifest.json").read_text())
    assert manifest["training_target"]["ready"] is True
    assert manifest["recipe_compliance"]["status"] == "ready"
    assert manifest["training_target"]["warnings"] == []
