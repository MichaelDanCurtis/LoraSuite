import json
import shutil

import pytest
from PIL import Image

from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.models import (
    CurationReviewStatus,
    DatasetReviewStatus,
    DatasetView,
    DerivativeType,
    MediaType,
    RequestedOutput,
    SpeakerConfirmation,
    TrainingIntent,
)
from lorasuite_engine.video_dataset import VideoDatasetService
from lorasuite_engine.vault import VaultService


def test_compiles_splits_and_exports_accepted_video_clips(tmp_path):
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    source_items = []
    for index in (1, 2):
        source_path = tmp_path / f"source-{index}.mp4"
        source_path.write_bytes(f"source-{index}".encode())
        source = vault.import_local_paths([source_path]).media_items[0]
        source = vault.annotate_media_item(source.id, metadata={}, duration=8, width=720, height=1280)
        source_items.append(source)
    curation = CurationService(vault_root)
    handoff = curation.add_to_handoff([item.id for item in source_items])
    for source in source_items:
        handoff = curation.update_review_status(source.id, CurationReviewStatus.ACCEPTED)
        clip_path = tmp_path / f"clip-{source.id}.mp4"
        clip_path.write_bytes(f"clip-{source.id}".encode())
        derivative = vault.build_derivative_media_item(
            source_item=source,
            derivative_path=clip_path,
            media_type=MediaType.VIDEO,
            derivative_type=DerivativeType.VIDEO_CLIP,
            metadata={
                "scores": {
                    "quality": 0.9,
                    "identity_coverage": 0.8,
                    "stability": 0.85,
                    "motion": 0.7,
                }
            },
        )
        derivative.duration = 4
        derivative.width = 720
        derivative.height = 1280
        vault.append_media_items([derivative])
    project = CharacterProjectService(vault_root).create_project(
        name="Video Person",
        intent=TrainingIntent(subject_name="Video Person", trigger_token="video_person"),
    )

    def copy_normalizer(source, destination, **_options):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    service = VideoDatasetService(vault_root, normalizer=copy_normalizer)
    candidates = service.candidate_media()
    assert len(candidates) == 2
    assert all(item.metadata_json["derivative_type"] == "video_clip" for item in candidates)

    draft = service.compile_project(project.id)
    assert draft.balance.total_count == 2
    assert draft.balance.review_count == 2
    assert all("video_person" in item.caption for item in draft.items.values())

    approved = service.bulk_status(draft.id, "approved")
    assert approved.balance.recipe_compliance is not None
    assert approved.balance.recipe_compliance.recipe_id == "wan22_14b_t2v_character"
    assert approved.balance.recipe_compliance.status == "review"
    assert approved.balance.average_stability == 0.85
    assert approved.balance.average_motion == 0.7
    frozen = service.freeze(approved.id)
    assert frozen.status == "frozen"
    assert frozen.balance.train_count == 1
    assert frozen.balance.validation_count == 1
    assert frozen.fingerprint

    exported, package = service.export(frozen.id, tmp_path / "video-export")
    assert exported.status == "exported"
    assert package.export_type.value == "ai_toolkit_video"
    pairs = sorted((tmp_path / "video-export" / "videos").iterdir())
    assert len(pairs) == 4
    manifest = json.loads((tmp_path / "video-export" / "manifest.json").read_text())
    assert {entry["split"] for entry in manifest["files"]} == {"train", "validation"}
    assert manifest["training_target"]["ready"] is True
    assert manifest["training_target"]["recipe_id"] == "wan22_14b_t2v_character"
    assert manifest["training_target"]["recipe_version"] == 1
    assert manifest["training_target"]["num_frames"] == 41
    assert manifest["training_target"]["fps"] == 16
    assert manifest["recipe_compliance"]["status"] == "review"
    assert all(entry["training_frame_window"] == 41 for entry in manifest["files"])
    assert manifest["revision_lineage"] == {}


def test_refuses_unaccepted_video_sources(tmp_path):
    vault_root = tmp_path / "vault"
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    source = VaultService(vault_root).import_local_paths([source_path]).media_items[0]
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="person"),
    )

    service = VideoDatasetService(vault_root)
    assert service.candidate_media() == []
    try:
        service.compile_project(project.id, [source.id])
    except ValueError as error:
        assert "not found or not accepted" in str(error)
    else:
        raise AssertionError("Expected unaccepted source to be rejected")


def test_freeze_blocks_clips_shorter_than_wan_frame_window(tmp_path):
    vault_root = tmp_path / "vault"
    source_path = tmp_path / "short.mp4"
    source_path.write_bytes(b"short")
    vault = VaultService(vault_root)
    source = vault.import_local_paths([source_path]).media_items[0]
    source = vault.annotate_media_item(
        source.id,
        metadata={
            "scores": {
                "quality": 0.9,
                "identity_coverage": 0.9,
                "stability": 0.9,
                "motion": 0.5,
            }
        },
        duration=2.0,
        width=720,
        height=1280,
    )
    curation = CurationService(vault_root)
    curation.add_to_handoff([source.id])
    curation.update_review_status(source.id, CurationReviewStatus.ACCEPTED)
    project = CharacterProjectService(vault_root).create_project(
        name="Short Video",
        intent=TrainingIntent(subject_name="Short Video", trigger_token="short_person"),
    )

    service = VideoDatasetService(vault_root)
    approved = service.bulk_status(
        service.compile_project(project.id).id,
        "approved",
    )
    compliance = approved.balance.recipe_compliance
    assert compliance is not None
    assert compliance.status == "blocked"
    assert next(
        check for check in compliance.checks if check.check_id == "frame-window"
    ).passed is False

    try:
        service.freeze(approved.id)
    except ValueError as error:
        assert "cannot provide 41 frames at 16 FPS" in str(error)
    else:
        raise AssertionError("Expected the short clip to fail WAN recipe preflight")


def test_exports_minimax_h3_zero_shot_reference_package(tmp_path):
    vault_root = tmp_path / "vault"
    source_path = tmp_path / "h3-reference.mp4"
    source_path.write_bytes(b"video-with-audio-reference")
    vault = VaultService(vault_root)
    source = vault.import_local_paths([source_path]).media_items[0]
    source = vault.annotate_media_item(
        source.id,
        metadata={
            "scores": {
                "quality": 0.9,
                "identity_coverage": 0.9,
                "stability": 0.8,
                "motion": 0.6,
            }
        },
        duration=6.0,
        width=720,
        height=1280,
    )
    curation = CurationService(vault_root)
    curation.add_to_handoff([source.id])
    curation.update_review_status(source.id, CurationReviewStatus.ACCEPTED)
    project = CharacterProjectService(vault_root).create_project(
        name="H3 Person",
        intent=TrainingIntent(
            subject_name="H3 Person",
            trigger_token="",
            training_target_profile_ids={
                "video": "comfyui_minimax_h3_ref2va",
            },
        ),
    )
    image_path = tmp_path / "h3-still.png"
    Image.new("RGB", (8, 8), color=(120, 30, 20)).save(image_path)
    image = vault.import_local_paths([image_path]).media_items[0]
    projects = CharacterProjectService(vault_root)
    projects.add_candidates(project.id, [image.id])
    projects.update_observation(
        project.id,
        image.id,
        review_status=DatasetReviewStatus.ACCEPTED,
        view=DatasetView.FACE,
    )
    audio_path = tmp_path / "h3-voice.wav"
    audio_path.write_bytes(b"speaker-reference")
    audio = vault.import_local_paths([audio_path]).media_items[0]
    curation.add_to_handoff(
        [audio.id],
        project_id=project.id,
        requested_output=RequestedOutput.VIDEO,
    )
    curation.update_review_status(
        audio.id,
        CurationReviewStatus.ACCEPTED,
        project_id=project.id,
        requested_output=RequestedOutput.VIDEO,
        speaker_confirmation=SpeakerConfirmation.HUMAN_OVERRIDE,
    )

    service = VideoDatasetService(vault_root)
    draft = service.compile_project(
        project.id,
        reference_image_media_item_ids=[image.id],
        reference_audio_media_item_ids=[audio.id],
    )
    assert draft.target_profile_id == "comfyui_minimax_h3_ref2va"
    assert draft.reference_image_media_item_ids == [image.id]
    assert draft.reference_audio_media_item_ids == [audio.id]
    approved = service.bulk_status(draft.id, "approved")
    assert approved.balance.recipe_compliance is not None
    assert approved.balance.recipe_compliance.recipe_id == "minimax_h3_ref2va_character"
    assert next(
        check for check in approved.balance.recipe_compliance.checks
        if check.check_id == "trigger-token"
    ).passed is True

    frozen = service.freeze(approved.id)
    assert {item.split for item in frozen.items.values()} == {"unassigned"}
    unrelated = tmp_path / "personal-files"
    unrelated.mkdir()
    protected = unrelated / "keep.txt"
    protected.write_text("Keep this file")
    with pytest.raises(ValueError, match="non-empty folder"):
        service.export(frozen.id, unrelated)
    assert protected.read_text() == "Keep this file"
    with pytest.raises(ValueError, match="vault root"):
        service.export(frozen.id, vault_root)
    exported, package = service.export(frozen.id, tmp_path / "h3-export")

    assert exported.status == "exported"
    assert package.export_type.value == "minimax_h3_reference"
    manifest = json.loads((tmp_path / "h3-export" / "manifest.json").read_text())
    assert manifest["workflow_kind"] == "inference"
    assert manifest["inference_target"]["profile_id"] == "comfyui_minimax_h3_ref2va"
    assert [reference["tag"] for reference in manifest["references"]] == [
        "<Picture 1>",
        "<Video 1>",
        "<Audio 1>",
    ]
    assert manifest["reference_limits"] == {"images": 9, "videos": 3, "audio": 3}
    assert manifest["references"][2]["role"] == "reviewed audio; assign voice or ambient sound explicitly in the scene"
    assert (tmp_path / "h3-export" / "references" / "video_1.mp4").read_bytes() == b"video-with-audio-reference"
    assert (tmp_path / "h3-export" / "references" / "image_1.png").read_bytes() == image_path.read_bytes()
    assert (tmp_path / "h3-export" / "references" / "audio_1.wav").read_bytes() == b"speaker-reference"
    readme = (tmp_path / "h3-export" / "README.md").read_text()
    assert "zero-shot Ref2VA inference package, not a LoRA training dataset" in readme


def test_minimax_h3_rejects_audio_without_subject_confirmation(tmp_path):
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    video_path = tmp_path / "reference.mp4"
    video_path.write_bytes(b"video")
    video = vault.import_local_paths([video_path]).media_items[0]
    video = vault.annotate_media_item(video.id, metadata={}, duration=6, width=720, height=1280)
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(
            training_target_profile_ids={"video": "comfyui_minimax_h3_ref2va"},
        ),
    )
    curation = CurationService(vault_root)
    curation.add_to_handoff([video.id], project_id=project.id, requested_output=RequestedOutput.VIDEO)
    curation.update_review_status(video.id, CurationReviewStatus.ACCEPTED, project_id=project.id, requested_output=RequestedOutput.VIDEO)
    audio_path = tmp_path / "unconfirmed.wav"
    audio_path.write_bytes(b"unconfirmed")
    audio = vault.import_local_paths([audio_path]).media_items[0]
    curation.add_to_handoff([audio.id], project_id=project.id, requested_output=RequestedOutput.VIDEO)
    curation.update_review_status(audio.id, CurationReviewStatus.ACCEPTED, project_id=project.id, requested_output=RequestedOutput.VIDEO)

    try:
        VideoDatasetService(vault_root).compile_project(
            project.id,
            reference_audio_media_item_ids=[audio.id],
        )
    except ValueError as error:
        assert "not speaker-confirmed" in str(error)
    else:
        raise AssertionError("Expected unconfirmed H3 audio to be rejected")
