from pathlib import Path
import json
import shutil

from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.id_lora_dataset import IdLoraDatasetService
from lorasuite_engine.models import (
    CurationReviewStatus,
    DerivativeType,
    MediaType,
    TrainingIntent,
    VoiceDatasetCompilation,
    VoiceDatasetSegment,
    VoiceSegmentQualityEvidence,
    VoiceSegmentStatus,
    CurationRecommendation,
)
from lorasuite_engine.vault import VaultService
from lorasuite_engine.video_dataset import VideoDatasetService
from lorasuite_engine.voice_dataset import VoiceDatasetService


def test_compiles_source_aligned_id_lora_pairs_without_split_leakage(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    curation = CurationService(vault_root)
    project = CharacterProjectService(vault_root).create_project(
        name="AV Person",
        intent=TrainingIntent(subject_name="AV Person", trigger_token="av_person"),
    )
    voice_segments = {}
    for index in (1, 2):
        source_path = tmp_path / f"source-{index}.mp4"
        source_path.write_bytes(f"video-{index}".encode())
        source = vault.import_local_paths([source_path]).media_items[0]
        source = vault.annotate_media_item(source.id, metadata={}, duration=10, width=720, height=1280)
        curation.add_to_handoff([source.id])
        curation.update_review_status(source.id, CurationReviewStatus.ACCEPTED)

        clip_path = tmp_path / f"clip-{index}.mp4"
        clip_path.write_bytes(f"clip-{index}".encode())
        clip = vault.build_derivative_media_item(
            source_item=source,
            derivative_path=clip_path,
            media_type=MediaType.VIDEO,
            derivative_type=DerivativeType.VIDEO_CLIP,
            metadata={
                "time_range": {"start_seconds": 2.0, "end_seconds": 6.0},
                "scores": {"identity_coverage": 0.9, "quality": 0.85},
            },
        )
        clip.duration = 4
        clip.width = 720
        clip.height = 1280

        audio_path = tmp_path / f"audio-{index}.wav"
        audio_path.write_bytes(f"audio-{index}".encode())
        audio = vault.build_derivative_media_item(
            source_item=source,
            derivative_path=audio_path,
            media_type=MediaType.AUDIO,
            derivative_type=DerivativeType.AUDIO_CLIP,
        )
        segment_path = tmp_path / f"segment-{index}.wav"
        segment_path.write_bytes(f"segment-{index}".encode())
        segment_media = vault.build_derivative_media_item(
            source_item=audio,
            derivative_path=segment_path,
            media_type=MediaType.AUDIO,
            derivative_type=DerivativeType.VOICE_SEGMENT,
        )
        vault.append_media_items([clip, audio, segment_media])
        segment = VoiceDatasetSegment(
            id=f"voice-{index}",
            project_id=project.id,
            source_media_item_id=audio.id,
            media_item_id=segment_media.id,
            audio_path=segment_path,
            start_seconds=3.0,
            end_seconds=5.0,
            transcript=f"Spoken line {index}.",
            speaker_similarity=0.93,
            quality=VoiceSegmentQualityEvidence(
                quality_score=0.88,
                recommendation=CurationRecommendation.KEEP,
            ),
            status=VoiceSegmentStatus.APPROVED,
        )
        voice_segments[segment.id] = segment
        reference_path = tmp_path / f"reference-segment-{index}.wav"
        reference_path.write_bytes(f"reference-{index}".encode())
        reference_media = vault.build_derivative_media_item(
            source_item=audio,
            derivative_path=reference_path,
            media_type=MediaType.AUDIO,
            derivative_type=DerivativeType.VOICE_SEGMENT,
        )
        vault.append_media_items([reference_media])
        reference_segment = VoiceDatasetSegment(
            id=f"voice-reference-{index}",
            project_id=project.id,
            source_media_item_id=audio.id,
            media_item_id=reference_media.id,
            audio_path=reference_path,
            start_seconds=7.0,
            end_seconds=9.0,
            transcript=f"Reference line {index}.",
            speaker_similarity=0.94,
            quality=VoiceSegmentQualityEvidence(
                quality_score=0.9,
                recommendation=CurationRecommendation.KEEP,
            ),
            status=VoiceSegmentStatus.APPROVED,
        )
        voice_segments[reference_segment.id] = reference_segment

    def copy_normalizer(source: Path, destination: Path, **_options) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    video_service = VideoDatasetService(vault_root, normalizer=copy_normalizer)
    draft = video_service.compile_project(project.id)
    approved = video_service.bulk_status(draft.id, "approved")
    frozen = video_service.freeze(approved.id)
    exported_video, _package = video_service.export(frozen.id, tmp_path / "video-export")
    VoiceDatasetService(vault_root)._save(VoiceDatasetCompilation(
        project_id=project.id,
        source_media_item_ids=[segment.source_media_item_id for segment in voice_segments.values()],
        segments=voice_segments,
    ))

    service = IdLoraDatasetService(vault_root)
    manifest = service.compile_project(project.id, exported_video.id)

    assert manifest.status == "ready"
    assert manifest.balance.synchronized_pair_count == 2
    assert manifest.balance.voice_reference_count == 4
    assert manifest.balance.train_count == 1
    assert manifest.balance.validation_count == 1
    assert manifest.workflow_kind == "inference"
    assert manifest.target_profile_id == "runpod_id_lora_ltx23_inference"
    assert manifest.balance.recipe_compliance is not None
    assert manifest.balance.recipe_compliance.recipe_id == "id_lora_ltx23_zero_shot_character"
    assert manifest.balance.recipe_compliance.status == "ready"
    assert all(item.pairing_kind == "synchronized_av" for item in manifest.examples.values())
    assert all("[VISUAL]" in item.multimodal_caption and "[SPEECH]" in item.multimodal_caption for item in manifest.examples.values())
    for example in manifest.examples.values():
        reference = manifest.voice_references[example.voice_segment_id]
        assert reference.split == example.split
        assert example.reference_voice_segment_id
        assert example.reference_voice_segment_id != example.voice_segment_id

    exported, package = service.export(manifest.id, tmp_path / "id-lora-export")
    payload = json.loads((tmp_path / "id-lora-export" / "manifest.json").read_text())
    assert exported.export_path == tmp_path / "id-lora-export"
    assert package.export_type.value == "id_lora_av"
    assert len(payload["examples"]) == 2
    assert len(payload["voice_references"]) == 4
    assert payload["training_target"]["ready"] is False
    assert payload["inference_target"]["ready"] is True
    assert payload["inference_target"]["workflow_kind"] == "inference"
    assert payload["inference_target"]["recipe_id"] == "id_lora_ltx23_zero_shot_character"
    assert payload["inference_target"]["recipe_version"] == 1
    assert payload["recipe_compliance"]["status"] == "ready"
    trainer_dataset = json.loads((tmp_path / "id-lora-export" / "trainer_dataset.json").read_text())
    assert len(trainer_dataset) == 2
    assert all(item["reference_audio"] != item["audio"] for item in trainer_dataset)
    assert (tmp_path / "id-lora-export" / "train" / "video").is_dir()
    assert (tmp_path / "id-lora-export" / "validation" / "audio").is_dir()


def test_keeps_unrelated_voice_as_reference_without_claiming_av_sync(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="person"),
    )
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    video = vault.import_local_paths([video_path]).media_items[0]
    video = vault.annotate_media_item(video.id, metadata={}, duration=4, width=720, height=1280)
    curation = CurationService(vault_root)
    curation.add_to_handoff([video.id])
    curation.update_review_status(video.id, CurationReviewStatus.ACCEPTED)
    video_service = VideoDatasetService(vault_root)
    frozen = video_service.freeze(video_service.bulk_status(video_service.compile_project(project.id).id, "approved").id)

    audio_path = tmp_path / "unrelated.wav"
    audio_path.write_bytes(b"audio")
    audio = vault.import_local_paths([audio_path]).media_items[0]
    segment = VoiceDatasetSegment(
        id="unrelated-voice",
        project_id=project.id,
        source_media_item_id=audio.id,
        media_item_id=audio.id,
        audio_path=audio.raw_path,
        start_seconds=0.2,
        end_seconds=1.5,
        transcript="Unrelated source.",
        status=VoiceSegmentStatus.APPROVED,
    )
    VoiceDatasetService(vault_root)._save(VoiceDatasetCompilation(
        project_id=project.id,
        source_media_item_ids=[audio.id],
        segments={segment.id: segment},
    ))

    manifest = IdLoraDatasetService(vault_root).compile_project(project.id, frozen.id)

    example = next(iter(manifest.examples.values()))
    assert example.pairing_kind == "visual_only"
    assert example.voice_segment_id is None
    assert manifest.balance.voice_reference_count == 1
    assert manifest.status == "blocked"
