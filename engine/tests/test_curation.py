from hashlib import sha256
from pathlib import Path

from PIL import Image

from lorasuite_engine.curation import CurationService
from lorasuite_engine.ingress import IngressService
from lorasuite_engine.models import (
    CurationReviewStatus,
    DerivativeType,
    IngressCandidate,
    MediaItem,
    MediaStatus,
    MediaType,
    RequestedOutput,
    SpeakerConfirmation,
    SourceKind,
)
from lorasuite_engine.vault import VaultService


def test_curation_groups_linked_source_and_derivatives(tmp_path: Path):
    vault = VaultService(tmp_path / "vault")
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    source = MediaItem(
        source_id="source_1",
        raw_path=source_path,
        media_type=MediaType.VIDEO,
        sha256=sha256(source_path.read_bytes()).hexdigest(),
        metadata_json={
            "source_bundle_key": "instagram:post_1",
            "source_kind": "instagram",
            "display_name": "Example reel",
            "source_locator": "https://instagram.example/reel/1",
        },
    )
    vault.append_media_items([source])

    frame_path = tmp_path / "frame.png"
    Image.new("RGB", (32, 32), color=(20, 40, 60)).save(frame_path)
    frame = vault.build_derivative_media_item(
        source_item=source,
        derivative_path=frame_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.VIDEO_FRAME,
    )
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    audio = vault.build_derivative_media_item(
        source_item=source,
        derivative_path=audio_path,
        media_type=MediaType.AUDIO,
        derivative_type=DerivativeType.AUDIO_CLIP,
    )
    vault.append_media_items([frame, audio])

    bundles = CurationService(tmp_path / "vault").list_source_bundles()

    assert len(bundles) == 1
    assert bundles[0].id == "instagram:post_1"
    assert bundles[0].title == "Example reel"
    assert [lane.value for lane in bundles[0].intent_lanes] == ["image", "video", "audio"]
    assert {item.media_item_id for item in bundles[0].items} == {
        source.id,
        frame.id,
        audio.id,
    }


def test_curation_handoff_persists_cross_media_review_status(tmp_path: Path):
    vault = VaultService(tmp_path / "vault")
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    video = MediaItem(
        source_id="source_1",
        raw_path=video_path,
        media_type=MediaType.VIDEO,
        sha256=sha256(video_path.read_bytes()).hexdigest(),
    )
    vault.append_media_items([video])
    service = CurationService(tmp_path / "vault")

    handoff = service.add_to_handoff([video.id])
    updated = service.update_review_status(video.id, CurationReviewStatus.ACCEPTED)
    restored = CurationService(tmp_path / "vault").get_handoff()

    assert handoff.items[0].lane.value == "video"
    assert updated.items[0].review_status == CurationReviewStatus.ACCEPTED
    assert restored == updated


def test_curation_handoff_is_scoped_by_project_and_requested_output(tmp_path: Path):
    vault = VaultService(tmp_path / "vault")
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"voice")
    audio = MediaItem(
        source_id="source_1",
        raw_path=audio_path,
        media_type=MediaType.AUDIO,
        sha256=sha256(audio_path.read_bytes()).hexdigest(),
    )
    vault.append_media_items([audio])
    service = CurationService(tmp_path / "vault")

    service.add_to_handoff(
        [audio.id],
        project_id="project_a",
        requested_output=RequestedOutput.VOICE,
    )
    service.add_to_handoff(
        [audio.id],
        project_id="project_b",
        requested_output=RequestedOutput.ID_LORA,
    )
    updated = service.update_review_status(
        audio.id,
        CurationReviewStatus.ACCEPTED,
        project_id="project_a",
        requested_output=RequestedOutput.VOICE,
        speaker_confirmation=SpeakerConfirmation.HUMAN_OVERRIDE,
    )

    assert len(updated.items) == 1
    assert updated.items[0].project_id == "project_a"
    assert updated.items[0].speaker_confirmation == SpeakerConfirmation.HUMAN_OVERRIDE
    project_b = service.get_handoff("project_b", RequestedOutput.ID_LORA)
    assert len(project_b.items) == 1
    assert project_b.items[0].review_status == CurationReviewStatus.PENDING


def test_curation_rejection_ignores_media_and_rejects_existing_handoff(tmp_path: Path):
    vault = VaultService(tmp_path / "vault")
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"voice")
    audio = MediaItem(
        source_id="source_1",
        raw_path=audio_path,
        media_type=MediaType.AUDIO,
        sha256=sha256(audio_path.read_bytes()).hexdigest(),
    )
    vault.append_media_items([audio])
    service = CurationService(tmp_path / "vault")
    service.add_to_handoff([audio.id])

    rejected = service.reject_media_items([audio.id])
    handoff = service.get_handoff()

    assert rejected[0].status == MediaStatus.IGNORED
    assert VaultService(tmp_path / "vault").get_media_item(audio.id).status == MediaStatus.IGNORED
    assert handoff.items[0].review_status == CurationReviewStatus.REJECTED
    assert service.list_source_bundles() == []

    restored = service.restore_audio_items([audio.id])

    assert restored[0].status == MediaStatus.REVIEWED
    assert restored[0].metadata_json["audio_review_override"] == "keep"
    assert service.get_handoff().items[0].review_status == CurationReviewStatus.PENDING
    assert len(service.list_source_bundles()) == 1


def test_curation_backfills_original_audio_metadata_from_ingress_store(tmp_path: Path):
    vault_root = tmp_path / "vault"
    candidate = IngressCandidate(
        id="candidate_audio_1",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.example/reel/1#audio",
        display_name="Example reel voice",
        media_type=MediaType.AUDIO,
        metadata_json={
            "platform_media_id": "post_1",
            "audio_original": False,
            "audio_kind": "reused_or_music",
        },
    )
    IngressService(vault_root).store_candidates([candidate])
    audio_path = tmp_path / f"{candidate.id}.m4a"
    audio_path.write_bytes(b"audio")
    imported = VaultService(vault_root).import_local_paths([audio_path]).media_items[0]

    bundles = CurationService(vault_root).list_source_bundles()
    restored = VaultService(vault_root).get_media_item(imported.id)

    assert bundles[0].id == "instagram:post:1"
    assert bundles[0].title == "Example reel voice"
    assert restored is not None
    assert restored.metadata_json["audio_original"] is False
    assert restored.metadata_json["audio_kind"] == "reused_or_music"
