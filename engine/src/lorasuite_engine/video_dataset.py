from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.ffmpeg import normalize_training_video, probe_video
from lorasuite_engine.models import (
    CurationReviewStatus,
    ExportPackage,
    ExportType,
    MediaItem,
    MediaType,
    RequestedOutput,
    new_id,
    utc_now,
)
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import (
    ModelIntentRecipe,
    RecipeCheck,
    RecipeCompliance,
    get_training_target_profile,
)
from lorasuite_engine.vault import VaultService, sha256_file


VideoDatasetItemStatus = Literal["needs_review", "approved", "excluded"]
VideoDatasetSnapshotStatus = Literal["draft", "frozen", "exported"]
VideoDatasetSplit = Literal["unassigned", "train", "validation"]


class VideoDatasetItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("video_dataset_item"))
    media_item_id: str
    source_media_item_id: str
    caption: str
    status: VideoDatasetItemStatus = "needs_review"
    split: VideoDatasetSplit = "unassigned"
    duration_seconds: float
    width: int
    height: int
    fps: float | None = None
    quality_score: float = 0.0
    identity_score: float = 0.0
    stability_score: float = 0.0
    motion_score: float = 0.0
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)


class VideoDatasetBalance(BaseModel):
    total_count: int = 0
    approved_count: int = 0
    review_count: int = 0
    excluded_count: int = 0
    source_count: int = 0
    total_duration_seconds: float = 0.0
    train_count: int = 0
    validation_count: int = 0
    average_quality: float = 0.0
    average_identity: float = 0.0
    average_stability: float = 0.0
    average_motion: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    recipe_compliance: RecipeCompliance | None = None


class VideoDatasetSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("video_dataset_snapshot"))
    project_id: str
    project_name: str
    version: int = 1
    status: VideoDatasetSnapshotStatus = "draft"
    trigger_token: str
    intent_type: str = "character"
    target_profile_id: str = "runcomfy_wan22_14b_t2v_character"
    target_label: str = "WAN 2.2 14B T2V Character Video"
    reference_image_media_item_ids: list[str] = Field(default_factory=list)
    reference_audio_media_item_ids: list[str] = Field(default_factory=list)
    items: dict[str, VideoDatasetItem] = Field(default_factory=dict)
    balance: VideoDatasetBalance = Field(default_factory=VideoDatasetBalance)
    fingerprint: str | None = None
    export_path: Path | None = None
    parent_snapshot_id: str | None = None
    parent_fingerprint: str | None = None
    improvement_request_id: str | None = None
    source_artifact_id: str | None = None
    source_checkpoint_sha256: str | None = None
    revision_plan: list[str] = Field(default_factory=list)
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    frozen_at: Any | None = None


class VideoDatasetService:
    def __init__(
        self,
        vault_root: Path,
        *,
        normalizer: Callable[..., Path] = normalize_training_video,
    ):
        self.vault_root = Path(vault_root)
        self.normalizer = normalizer

    @property
    def snapshots_path(self) -> Path:
        return self.vault_root / "video_dataset_snapshots.json"

    def list_snapshots(self, project_id: str | None = None) -> list[VideoDatasetSnapshot]:
        snapshots = self._read_snapshots().values()
        if project_id:
            snapshots = (snapshot for snapshot in snapshots if snapshot.project_id == project_id)
        return sorted(snapshots, key=lambda snapshot: (snapshot.version, snapshot.updated_at), reverse=True)

    def get_snapshot(self, snapshot_id: str) -> VideoDatasetSnapshot | None:
        return self._read_snapshots().get(snapshot_id)

    def create_revision(
        self,
        snapshot_id: str,
        *,
        improvement_request_id: str,
        source_artifact_id: str,
        source_checkpoint_sha256: str,
        revision_plan: list[str],
    ) -> VideoDatasetSnapshot:
        snapshots = self._read_snapshots()
        source = snapshots.get(snapshot_id)
        if source is None:
            raise KeyError(snapshot_id)
        if source.status not in {"frozen", "exported"}:
            raise ValueError("only a frozen or exported video dataset can start a revision")
        if not source.fingerprint:
            raise ValueError("the source video dataset revision has no immutable fingerprint")
        existing = next(
            (
                snapshot for snapshot in snapshots.values()
                if snapshot.improvement_request_id == improvement_request_id
            ),
            None,
        )
        if existing is not None:
            return existing
        versions = [
            snapshot.version
            for snapshot in snapshots.values()
            if snapshot.project_id == source.project_id
        ]
        now = utc_now()
        revision = source.model_copy(deep=True)
        revision.id = new_id("video_dataset_snapshot")
        revision.version = max(versions, default=source.version) + 1
        revision.status = "draft"
        revision.fingerprint = None
        revision.export_path = None
        revision.parent_snapshot_id = source.id
        revision.parent_fingerprint = source.fingerprint
        revision.improvement_request_id = improvement_request_id
        revision.source_artifact_id = source_artifact_id
        revision.source_checkpoint_sha256 = source_checkpoint_sha256
        revision.revision_plan = list(dict.fromkeys(revision_plan))
        revision.created_at = now
        revision.updated_at = now
        revision.frozen_at = None
        snapshots[revision.id] = revision
        self._write_snapshots(snapshots)
        return revision

    def candidate_media(self, project_id: str | None = None) -> list[MediaItem]:
        vault_items = VaultService(self.vault_root).list_media_items()
        handoff = CurationService(self.vault_root).get_handoff(project_id)
        accepted_roots = {
            item.media_item_id
            for item in handoff.items
            if item.lane.value == "video" and item.review_status == CurationReviewStatus.ACCEPTED
        }
        if not accepted_roots:
            return []
        clips_by_source = {
            str(item.metadata_json.get("source_media_item_id"))
            for item in vault_items
            if item.media_type == MediaType.VIDEO
            and item.metadata_json.get("derivative_type") == "video_clip"
            and str(item.metadata_json.get("source_media_item_id")) in accepted_roots
        }
        candidates = []
        for item in vault_items:
            if item.media_type != MediaType.VIDEO:
                continue
            source_id = str(item.metadata_json.get("source_media_item_id") or item.id)
            is_clip = item.metadata_json.get("derivative_type") == "video_clip"
            if is_clip and source_id in accepted_roots:
                candidates.append(item)
            elif item.id in accepted_roots and item.id not in clips_by_source:
                candidates.append(item)
        return sorted(candidates, key=lambda item: (str(item.metadata_json.get("source_media_item_id")), item.id))

    def compile_project(
        self,
        project_id: str,
        media_item_ids: list[str] | None = None,
        target_profile_id: str | None = None,
        reference_image_media_item_ids: list[str] | None = None,
        reference_audio_media_item_ids: list[str] | None = None,
        *,
        new_draft: bool = False,
        confirmed_scene_image_ids: list[str] | None = None,
        confirmed_scene_video_ids: list[str] | None = None,
    ) -> VideoDatasetSnapshot:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        requested_target_id = (
            target_profile_id
            or project.intent.training_target_profile_ids.get(RequestedOutput.VIDEO)
            or "runcomfy_wan22_14b_t2v_character"
        )
        target = get_training_target_profile(requested_target_id)
        if target.modality != "video":
            raise ValueError(f"video compilation requires a video target, not {target.modality}")
        if target.model_family == "minimax_h3_ref2va":
            selected_image_ids, selected_audio_ids = self._validate_h3_references(
                project_id,
                reference_image_media_item_ids,
                reference_audio_media_item_ids,
                confirmed_scene_image_ids,
            )
        else:
            if reference_image_media_item_ids or reference_audio_media_item_ids:
                raise ValueError("standalone references are available only for the MiniMax H3 target")
            selected_image_ids, selected_audio_ids = [], []
        candidates = self.candidate_media(project_id)
        if confirmed_scene_video_ids:
            if target.model_family != "minimax_h3_ref2va" or not set(confirmed_scene_video_ids).issubset(media_item_ids or []):
                raise ValueError("Scene video confirmation requires selected H3 references")
            vault = VaultService(self.vault_root)
            for key in dict.fromkeys(confirmed_scene_video_ids):
                item = vault.get_media_item(key)
                preparation = item.metadata_json.get("h3_reference_preparation", {}) if item else {}
                if not item or item.media_type != MediaType.VIDEO or (preparation and (preparation.get("project_id") != project_id or preparation.get("purpose") != "motion")):
                    raise ValueError("Choose a motion clip prepared for this scene's project")
                if key not in {candidate.id for candidate in candidates}:
                    candidates.append(item)
        if media_item_ids is not None:
            selected = set(media_item_ids)
            candidates = [item for item in candidates if item.id in selected]
            unknown = selected.difference(item.id for item in candidates)
            if unknown:
                raise ValueError(f"video candidate not found or not accepted: {sorted(unknown)[0]}")
        if not candidates and not (target.model_family == "minimax_h3_ref2va" and (selected_image_ids or selected_audio_ids)):
            raise ValueError("no accepted video clips are available for compilation")
        snapshots = self._read_snapshots()
        draft = next(
            (
                snapshot for snapshot in snapshots.values()
                if not new_draft and snapshot.project_id == project_id and snapshot.status == "draft"
            ),
            None,
        )
        if draft is None:
            versions = [snapshot.version for snapshot in snapshots.values() if snapshot.project_id == project_id]
            draft = VideoDatasetSnapshot(
                project_id=project.id,
                project_name=project.name,
                version=max(versions, default=0) + 1,
                trigger_token=project.intent.trigger_token,
                target_profile_id=target.profile_id,
                target_label=target.label,
            )
        existing_by_media = {item.media_item_id: item for item in draft.items.values()}
        compiled: dict[str, VideoDatasetItem] = {}
        for media in candidates:
            metadata = _video_metadata(media)
            existing = existing_by_media.get(media.id)
            scores = media.metadata_json.get("scores") if isinstance(media.metadata_json.get("scores"), dict) else {}
            record = existing or VideoDatasetItem(
                media_item_id=media.id,
                source_media_item_id=str(media.metadata_json.get("source_media_item_id") or media.id),
                caption=_seed_caption(project.intent.trigger_token, project.intent.subject_name),
                duration_seconds=metadata["duration"],
                width=metadata["width"],
                height=metadata["height"],
                fps=metadata["fps"],
            )
            record.duration_seconds = metadata["duration"]
            record.width = metadata["width"]
            record.height = metadata["height"]
            record.fps = metadata["fps"]
            record.quality_score = _score(scores, "quality")
            record.identity_score = _score(scores, "identity_coverage")
            record.stability_score = _score(scores, "stability")
            record.motion_score = _score(scores, "motion")
            record.updated_at = utc_now()
            compiled[record.id] = record
        draft.project_name = project.name
        draft.trigger_token = project.intent.trigger_token
        draft.intent_type = project.intent.target_type.value
        draft.target_profile_id = target.profile_id
        draft.target_label = target.label
        if reference_image_media_item_ids is not None or target.model_family != "minimax_h3_ref2va":
            draft.reference_image_media_item_ids = selected_image_ids
        if reference_audio_media_item_ids is not None or target.model_family != "minimax_h3_ref2va":
            draft.reference_audio_media_item_ids = selected_audio_ids
        draft.items = compiled
        draft.balance = _balance(draft)
        draft.updated_at = utc_now()
        snapshots[draft.id] = draft
        self._write_snapshots(snapshots)
        return draft

    def _validate_h3_references(
        self,
        project_id: str,
        image_ids: list[str] | None,
        audio_ids: list[str] | None,
        confirmed_scene_image_ids: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        requested_images = list(dict.fromkeys(image_ids or []))
        requested_audio = list(dict.fromkeys(audio_ids or []))
        if len(requested_images) > 9:
            raise ValueError("MiniMax H3 accepts at most 9 reviewed image references")
        if len(requested_audio) > 3:
            raise ValueError("MiniMax H3 accepts at most 3 reviewed audio references")
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        # Explicit scene-only review does not change project identity observations
        # or training eligibility. Audio still requires its existing speaker gate.
        confirmed = set(confirmed_scene_image_ids or [])
        if not confirmed.issubset(requested_images) or any(
            key not in media_by_id or media_by_id[key].media_type != MediaType.IMAGE
            for key in confirmed
        ):
            raise ValueError("Scene confirmation requires selected image media")
        accepted_image_ids = {
            observation.media_item_id
            for observation in project.observations.values()
            if observation.review_status.value == "accepted"
            and media_by_id.get(observation.media_item_id) is not None
            and media_by_id[observation.media_item_id].media_type == MediaType.IMAGE
        }
        handoff = CurationService(self.vault_root).get_handoff(project_id)
        accepted_audio_ids = {
            item.media_item_id
            for item in handoff.items
            if item.lane.value == "audio"
            and item.review_status.value == "accepted"
            and item.speaker_confirmation is not None
            and media_by_id.get(item.media_item_id) is not None
            and media_by_id[item.media_item_id].media_type == MediaType.AUDIO
        }
        accepted_audio_ids.update(
            item.id for item in media_by_id.values()
            if item.media_type == MediaType.AUDIO
            and item.metadata_json.get("h3_audio_reviews", {}).get(project_id, {}).get("scope") == "scene_reference_only"
            and item.metadata_json.get("h3_audio_reviews", {}).get(project_id, {}).get("role") in {"voice", "sound"}
        )
        unknown_image_ids = set(requested_images).difference(accepted_image_ids | confirmed)
        if unknown_image_ids:
            raise ValueError(f"H3 image reference is not identity-approved: {sorted(unknown_image_ids)[0]}")
        unknown_audio_ids = set(requested_audio).difference(accepted_audio_ids)
        if unknown_audio_ids:
            raise ValueError(f"H3 audio reference is not speaker-confirmed: {sorted(unknown_audio_ids)[0]}")
        return requested_images, requested_audio

    def update_item(
        self,
        snapshot_id: str,
        item_id: str,
        *,
        caption: str | None = None,
        status: VideoDatasetItemStatus | None = None,
    ) -> VideoDatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        item = snapshot.items.get(item_id)
        if item is None:
            raise ValueError(f"video dataset item not found: {item_id}")
        if caption is not None:
            caption = caption.strip().strip(",")
            if not caption:
                raise ValueError("video caption must not be empty")
            item.caption = caption
        if status is not None:
            item.status = status
        item.updated_at = utc_now()
        snapshot.balance = _balance(snapshot)
        snapshot.updated_at = utc_now()
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def bulk_status(self, snapshot_id: str, status: VideoDatasetItemStatus) -> VideoDatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        for item in snapshot.items.values():
            if item.status == "needs_review":
                item.status = status
                item.updated_at = utc_now()
        snapshot.balance = _balance(snapshot)
        snapshot.updated_at = utc_now()
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def freeze(self, snapshot_id: str) -> VideoDatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        snapshot.balance = _balance(snapshot)
        target = get_training_target_profile(snapshot.target_profile_id)
        recipe = target.recipe
        trigger_required = recipe is None or recipe.captions.trigger_token_required
        if snapshot.balance.review_count:
            raise ValueError("resolve or exclude every video before freezing")
        approved = [item for item in snapshot.items.values() if item.status == "approved"]
        if not approved and not (target.model_family == "minimax_h3_ref2va" and (snapshot.reference_image_media_item_ids or snapshot.reference_audio_media_item_ids)):
            raise ValueError("approve at least one video before freezing")
        if trigger_required and not snapshot.trigger_token.strip():
            raise ValueError("the Identity project requires a trigger token")
        for item in approved:
            if trigger_required and snapshot.trigger_token not in item.caption:
                raise ValueError(f"approved video caption is missing trigger token: {item.id}")
        failed_blockers = [
            check
            for check in snapshot.balance.recipe_compliance.checks
            if not check.passed and check.severity == "blocker"
        ] if snapshot.balance.recipe_compliance else []
        if failed_blockers:
            raise ValueError(
                f"video training recipe preflight failed: {failed_blockers[0].detail}"
            )
        if recipe is not None and recipe.workflow_kind == "inference":
            for item in approved:
                item.split = "unassigned"
        else:
            validation_sources = _validation_sources(approved)
            for item in approved:
                item.split = "validation" if item.source_media_item_id in validation_sources else "train"
        snapshot.balance = _balance(snapshot)
        snapshot.fingerprint = _fingerprint(snapshot)
        snapshot.status = "frozen"
        snapshot.frozen_at = utc_now()
        snapshot.updated_at = snapshot.frozen_at
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def export(self, snapshot_id: str, output_dir: Path) -> tuple[VideoDatasetSnapshot, ExportPackage]:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        if snapshot.status not in {"frozen", "exported"}:
            raise ValueError("freeze the video dataset before export")
        target = get_training_target_profile(snapshot.target_profile_id)
        recipe = target.recipe
        if recipe is not None and recipe.workflow_kind == "inference":
            return self._export_reference_package(snapshot, target, output_dir)
        policy = recipe.dataset if recipe is not None else None
        target_fps = policy.target_fps if policy and policy.target_fps else 16
        target_num_frames = (
            policy.target_num_frames if policy and policy.target_num_frames else 41
        )
        maximum_dimension = (
            policy.maximum_normalized_dimension
            if policy and policy.maximum_normalized_dimension
            else 1024
        )
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        output_dir = Path(output_dir).expanduser().resolve(strict=False)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(mkdtemp(prefix=f".{output_dir.name}.staging.", dir=output_dir.parent))
        moved = False
        try:
            videos_dir = staged / "videos"
            videos_dir.mkdir(parents=True)
            manifest_items: list[dict[str, Any]] = []
            approved = [item for item in snapshot.items.values() if item.status == "approved"]
            for index, item in enumerate(sorted(approved, key=lambda candidate: candidate.id), start=1):
                media = media_by_id.get(item.media_item_id)
                if media is None or not media.raw_path.is_file():
                    raise ValueError(f"video media is missing: {item.media_item_id}")
                basename = f"{item.split}_{index:06d}"
                video_path = videos_dir / f"{basename}.mp4"
                caption_path = videos_dir / f"{basename}.txt"
                self.normalizer(
                    media.raw_path,
                    video_path,
                    fps=target_fps,
                    max_dimension=maximum_dimension,
                )
                caption_path.write_text(item.caption.rstrip() + "\n", encoding="utf-8")
                manifest_items.append({
                    "video": f"videos/{video_path.name}",
                    "caption": f"videos/{caption_path.name}",
                    "caption_text": item.caption,
                    "split": item.split,
                    "dataset_item_id": item.id,
                    "media_item_id": item.media_item_id,
                    "source_media_item_id": item.source_media_item_id,
                    "sha256": sha256_file(video_path),
                    "duration_seconds": item.duration_seconds,
                    "normalized_fps": target_fps,
                    "training_frame_window": target_num_frames,
                    "max_dimension": maximum_dimension,
                })
            manifest_path = staged / "manifest.json"
            manifest_path.write_text(json.dumps({
                "created_by": "LoraSuite",
                "dataset_snapshot_id": snapshot.id,
                "dataset_fingerprint": snapshot.fingerprint,
                "modality": "video",
                "revision_lineage": RevisionLineage.from_snapshot(
                    snapshot
                ).manifest_payload(),
                "training_target": {
                    "profile_id": snapshot.target_profile_id,
                    "label": target.label,
                    "ready": target.ready,
                    "model_family": target.model_family,
                    "base_model": target.base_model,
                    "recipe_id": target.recipe_id,
                    "recipe_version": target.recipe_version,
                    "recipe_status": recipe.status if recipe else None,
                    "num_frames": target_num_frames,
                    "fps": target_fps,
                    "maximum_normalized_dimension": maximum_dimension,
                },
                "recipe_compliance": (
                    snapshot.balance.recipe_compliance.model_dump(mode="json")
                    if snapshot.balance.recipe_compliance
                    else None
                ),
                "files": manifest_items,
            }, indent=2) + "\n", encoding="utf-8")
            (staged / "export_report.md").write_text(
                "# LoraSuite Video Dataset\n\n"
                f"- Snapshot: {snapshot.id}\n- Clips: {len(manifest_items)}\n"
                f"- Train: {snapshot.balance.train_count}\n- Validation: {snapshot.balance.validation_count}\n"
                f"- Recipe: {target.recipe_id or 'unversioned'} v{target.recipe_version or 0}\n"
                f"- Format: silent H.264 MP4, {target_fps} FPS, paired captions\n"
                f"- Training window: {target_num_frames} frames\n"
                f"- Cloud trainer: {target.provider} / {target.label}\n"
                "- Held-out validation clips remain local and are not uploaded for training\n",
                encoding="utf-8",
            )
            if output_dir.exists():
                shutil.rmtree(output_dir)
            staged.replace(output_dir)
            moved = True
        finally:
            if not moved and staged.exists():
                shutil.rmtree(staged)
        package = ExportPackage(
            export_type=ExportType.AI_TOOLKIT_VIDEO,
            output_path=output_dir,
            manifest_path=output_dir / "manifest.json",
            source_segment_ids=[],
            status="complete",
        )
        snapshots = self._read_snapshots()
        snapshot.status = "exported"
        snapshot.export_path = output_dir
        snapshot.updated_at = utc_now()
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot, package

    def _export_reference_package(
        self,
        snapshot: VideoDatasetSnapshot,
        target: Any,
        output_dir: Path,
    ) -> tuple[VideoDatasetSnapshot, ExportPackage]:
        if target.model_family != "minimax_h3_ref2va":
            raise ValueError(f"unsupported video inference package: {target.model_family}")
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        approved = sorted(
            (item for item in snapshot.items.values() if item.status == "approved"),
            key=lambda item: item.id,
        )
        maximum = target.recipe.dataset.maximum_approved_items if target.recipe else 3
        if len(approved) > maximum:
            raise ValueError(f"MiniMax H3 accepts at most {maximum} reviewed video references")
        output_dir = Path(output_dir).expanduser().resolve(strict=False)
        if self.vault_root.resolve().is_relative_to(output_dir):
            raise ValueError("Choose an export folder outside the vault root and its parents")
        if output_dir.exists() and any(output_dir.iterdir()):
            previous_manifest = output_dir / "manifest.json"
            try:
                previous = json.loads(previous_manifest.read_text())
            except (OSError, ValueError):
                raise ValueError("Refusing to replace a non-empty folder without a matching LoraSuite H3 package")
            if previous.get("created_by") != "LoraSuite" or previous.get("dataset_snapshot_id") != snapshot.id or previous.get("inference_target", {}).get("model_family") != "minimax_h3_ref2va":
                raise ValueError("Choose an empty folder or this snapshot's existing H3 export folder")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(mkdtemp(prefix=f".{output_dir.name}.staging.", dir=output_dir.parent))
        moved = False
        try:
            references_dir = staged / "references"
            references_dir.mkdir(parents=True)
            references: list[dict[str, Any]] = []
            for index, media_item_id in enumerate(snapshot.reference_image_media_item_ids, start=1):
                media = media_by_id.get(media_item_id)
                if media is None or not media.raw_path.is_file():
                    raise ValueError(f"image reference is missing: {media_item_id}")
                suffix = media.raw_path.suffix.lower() or ".png"
                destination = references_dir / f"image_{index}{suffix}"
                shutil.copy2(media.raw_path, destination)
                references.append({
                    "type": "image",
                    "tag": f"<Picture {index}>",
                    "path": f"references/{destination.name}",
                    "role": "identity or style; assign explicitly in the prompt",
                    "media_item_id": media_item_id,
                    "sha256": sha256_file(destination),
                })
            for index, item in enumerate(approved, start=1):
                media = media_by_id.get(item.media_item_id)
                if media is None or not media.raw_path.is_file():
                    raise ValueError(f"video media is missing: {item.media_item_id}")
                suffix = media.raw_path.suffix.lower() or ".mp4"
                destination = references_dir / f"video_{index}{suffix}"
                shutil.copy2(media.raw_path, destination)
                references.append({
                    "type": "video",
                    "tag": f"<Video {index}>",
                    "path": f"references/{destination.name}",
                    "role": "identity, motion, camera, or voice; assign explicitly in the prompt",
                    "caption": item.caption,
                    "dataset_item_id": item.id,
                    "media_item_id": item.media_item_id,
                    "source_media_item_id": item.source_media_item_id,
                    "sha256": sha256_file(destination),
                    "duration_seconds": item.duration_seconds,
                })
            for index, media_item_id in enumerate(snapshot.reference_audio_media_item_ids, start=1):
                media = media_by_id.get(media_item_id)
                if media is None or not media.raw_path.is_file():
                    raise ValueError(f"audio reference is missing: {media_item_id}")
                suffix = media.raw_path.suffix.lower() or ".wav"
                destination = references_dir / f"audio_{index}{suffix}"
                shutil.copy2(media.raw_path, destination)
                references.append({
                    "type": "audio",
                    "tag": f"<Audio {index}>",
                    "path": f"references/{destination.name}",
                    "role": "reviewed audio; assign voice or ambient sound explicitly in the scene",
                    "media_item_id": media_item_id,
                    "sha256": sha256_file(destination),
                    "duration_seconds": media.duration,
                })
            manifest_path = staged / "manifest.json"
            manifest_path.write_text(json.dumps({
                "created_by": "LoraSuite",
                "dataset_snapshot_id": snapshot.id,
                "dataset_fingerprint": snapshot.fingerprint,
                "modality": "video",
                "workflow_kind": "inference",
                "revision_lineage": RevisionLineage.from_snapshot(snapshot).manifest_payload(),
                "inference_target": {
                    "profile_id": target.profile_id,
                    "label": target.label,
                    "model_family": target.model_family,
                    "base_model": target.base_model,
                    "recipe_id": target.recipe_id,
                    "recipe_version": target.recipe_version,
                    "pipeline": target.recipe.inference.pipeline if target.recipe and target.recipe.inference else None,
                },
                "reference_limits": {"images": 9, "videos": 3, "audio": 3},
                "references": references,
                "prompt_guidance": target.recipe.captions.guidance if target.recipe else [],
                "comfyui_workflow": "MiniMax H3 R2V",
                "comfyui_tutorial_url": "https://docs.comfy.org/tutorials/video/minimax/minimax-h3",
                "recipe_compliance": (
                    snapshot.balance.recipe_compliance.model_dump(mode="json")
                    if snapshot.balance.recipe_compliance
                    else None
                ),
            }, indent=2) + "\n", encoding="utf-8")
            (staged / "README.md").write_text(
                "# LoraSuite MiniMax H3 Reference Package\n\n"
                "This is a zero-shot Ref2VA inference package, not a LoRA training dataset.\n\n"
                "1. Open ComfyUI 0.30.0 or later.\n"
                "2. Choose the `MiniMax H3 R2V` template.\n"
                "3. Load the files in `references/` in manifest order.\n"
                "4. Refer to each input by its manifest tag and explicitly assign its role.\n\n"
                "Every standalone image/audio reference was explicitly selected from identity-approved or speaker-confirmed media.\n"
                "Reviewed source videos are copied without stripping their soundtracks.\n",
                encoding="utf-8",
            )
            if output_dir.exists():
                shutil.rmtree(output_dir)
            staged.replace(output_dir)
            moved = True
        finally:
            if not moved and staged.exists():
                shutil.rmtree(staged)
        package = ExportPackage(
            export_type=ExportType.MINIMAX_H3_REFERENCE,
            output_path=output_dir,
            manifest_path=output_dir / "manifest.json",
            source_segment_ids=[],
            status="complete",
        )
        snapshots = self._read_snapshots()
        snapshot.status = "exported"
        snapshot.export_path = output_dir
        snapshot.updated_at = utc_now()
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot, package

    def _require_draft(self, snapshot_id: str) -> tuple[VideoDatasetSnapshot, dict[str, VideoDatasetSnapshot]]:
        snapshots = self._read_snapshots()
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        if snapshot.status != "draft":
            raise ValueError("frozen video dataset snapshots are immutable")
        return snapshot, snapshots

    def _read_snapshots(self) -> dict[str, VideoDatasetSnapshot]:
        with json_file_lock(self.snapshots_path):
            if not self.snapshots_path.exists():
                return {}
            payload = json.loads(self.snapshots_path.read_text(encoding="utf-8"))
            return {item["id"]: VideoDatasetSnapshot.model_validate(item) for item in payload.get("snapshots", [])}

    def _write_snapshots(self, snapshots: dict[str, VideoDatasetSnapshot]) -> None:
        with json_file_lock(self.snapshots_path):
            atomic_write_json(self.snapshots_path, {
                "version": 1,
                "snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots.values()],
            })


def _video_metadata(media: MediaItem) -> dict[str, Any]:
    duration = float(media.duration or 0)
    width = int(media.width or 0)
    height = int(media.height or 0)
    fps: float | None = None
    if duration <= 0 or width <= 0 or height <= 0:
        probed = probe_video(media.raw_path)
        duration, width, height, fps = probed.duration_seconds, probed.width, probed.height, probed.fps
    if duration < 0.5:
        raise ValueError(f"video clip is too short: {media.id}")
    return {"duration": duration, "width": width, "height": height, "fps": fps}


def _seed_caption(trigger_token: str, subject_name: str) -> str:
    terms = [trigger_token.strip(), subject_name.strip(), "person in motion", "natural movement", "continuous video"]
    return ", ".join(term for index, term in enumerate(terms) if term and term not in terms[:index])


def _score(scores: dict[str, Any], key: str) -> float:
    try:
        return max(0.0, min(1.0, float(scores.get(key, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _balance(snapshot: VideoDatasetSnapshot) -> VideoDatasetBalance:
    items = list(snapshot.items.values())
    approved = [item for item in items if item.status == "approved"]
    source_count = len({item.source_media_item_id for item in approved})
    try:
        recipe = get_training_target_profile(snapshot.target_profile_id).recipe
    except ValueError:
        recipe = None
    compliance = (
        _calculate_recipe_compliance(snapshot, recipe)
        if recipe is not None
        else None
    )
    warnings = (
        [check.detail for check in compliance.checks if not check.passed]
        if compliance is not None
        else []
    )
    return VideoDatasetBalance(
        total_count=len(items),
        approved_count=len(approved),
        review_count=sum(item.status == "needs_review" for item in items),
        excluded_count=sum(item.status == "excluded" for item in items),
        source_count=source_count,
        total_duration_seconds=round(sum(item.duration_seconds for item in approved), 3),
        train_count=sum(item.status == "approved" and item.split == "train" for item in items),
        validation_count=sum(item.status == "approved" and item.split == "validation" for item in items),
        average_quality=sum(item.quality_score for item in approved) / len(approved) if approved else 0.0,
        average_identity=sum(item.identity_score for item in approved) / len(approved) if approved else 0.0,
        average_stability=sum(item.stability_score for item in approved) / len(approved) if approved else 0.0,
        average_motion=sum(item.motion_score for item in approved) / len(approved) if approved else 0.0,
        warnings=warnings,
        recipe_compliance=compliance,
    )


def _calculate_recipe_compliance(
    snapshot: VideoDatasetSnapshot,
    recipe: ModelIntentRecipe,
) -> RecipeCompliance:
    policy = recipe.dataset
    items = list(snapshot.items.values())
    approved = [item for item in items if item.status == "approved"]
    source_counts = Counter(item.source_media_item_id for item in approved)
    largest_source_share = (
        max(source_counts.values(), default=0) / len(approved)
        if approved
        else 0.0
    )
    total_duration = sum(item.duration_seconds for item in approved)
    average_quality = _average(approved, "quality_score")
    average_identity = _average(approved, "identity_score")
    average_stability = _average(approved, "stability_score")
    average_motion = _average(approved, "motion_score")
    trigger_token = snapshot.trigger_token.strip()
    missing_trigger_captions = (
        sum(trigger_token not in item.caption for item in approved)
        if recipe.captions.trigger_token_required and trigger_token
        else len(approved)
        if recipe.captions.trigger_token_required
        else 0
    )
    minimum_clip_duration = policy.minimum_clip_duration_seconds or 0.0
    maximum_clip_duration = policy.maximum_clip_duration_seconds
    short_clips = [
        item for item in approved
        if item.duration_seconds + 1e-6 < minimum_clip_duration
    ]
    long_clips = [
        item for item in approved
        if maximum_clip_duration is not None
        and item.duration_seconds > maximum_clip_duration
    ]
    low_fps_clips = [
        item for item in approved
        if policy.target_fps is not None
        and item.fps is not None
        and item.fps + 1e-6 < policy.target_fps
    ]
    checks = [
        RecipeCheck(
            check_id="modality",
            label="Recipe modality",
            passed=recipe.modality == "video",
            severity="blocker",
            detail=f"Recipe must target video; {recipe.label} targets {recipe.modality}.",
            current=recipe.modality,
            target="video",
        ),
        RecipeCheck(
            check_id="intent",
            label="Training intent",
            passed=snapshot.intent_type == recipe.intent,
            severity="blocker",
            detail=(
                f"Recipe expects a {recipe.intent} project; this project is "
                f"{snapshot.intent_type}."
            ),
            current=snapshot.intent_type,
            target=recipe.intent,
        ),
        RecipeCheck(
            check_id="trigger-token",
            label="Trigger token",
            passed=bool(trigger_token) or not recipe.captions.trigger_token_required,
            severity="blocker",
            detail=(
                "The Identity project requires a trigger token before freezing."
                if recipe.captions.trigger_token_required
                else "This inference reference recipe does not require a trigger token."
            ),
            current=trigger_token or "not required",
            target="required" if recipe.captions.trigger_token_required else "not required",
        ),
        RecipeCheck(
            check_id="clip-review",
            label="Clip review",
            passed=not any(item.status == "needs_review" for item in items),
            severity="blocker",
            detail="Resolve or exclude every video before freezing.",
            current=sum(item.status == "needs_review" for item in items),
            target=0,
        ),
        RecipeCheck(
            check_id="caption-trigger-coverage",
            label="Trigger coverage",
            passed=missing_trigger_captions == 0,
            severity="blocker",
            detail=(
                f"{missing_trigger_captions} approved video caption"
                f"{'' if missing_trigger_captions == 1 else 's'} are missing the trigger token."
            ),
            current=missing_trigger_captions,
            target=0,
        ),
        RecipeCheck(
            check_id="frame-window",
            label=(
                f"{policy.target_num_frames}-frame window"
                if policy.target_num_frames
                else "Reference duration"
            ),
            passed=not short_clips,
            severity="blocker",
            detail=(
                f"{len(short_clips)} approved clip"
                f"{'' if len(short_clips) == 1 else 's'} cannot provide "
                f"{policy.target_num_frames or 'the required'} frames at {policy.target_fps or 'the target'} FPS."
            ),
            current=len(short_clips),
            target=0,
        ),
        RecipeCheck(
            check_id="approved-clips",
            label="Approved clips",
            passed=len(approved) >= policy.minimum_approved_items,
            detail=f"Approve at least {policy.minimum_approved_items} clips for the {recipe.label} baseline.",
            current=len(approved),
            target=policy.minimum_approved_items,
        ),
        RecipeCheck(
            check_id="maximum-clips",
            label="Dataset size",
            passed=len(approved) <= policy.maximum_approved_items,
            severity="blocker" if recipe.workflow_kind == "inference" else "warning",
            detail=f"Keep no more than {policy.maximum_approved_items} approved clips without a deliberate recipe revision.",
            current=len(approved),
            target=policy.maximum_approved_items,
        ),
        RecipeCheck(
            check_id="source-count",
            label="Independent sources",
            passed=len(source_counts) >= policy.minimum_sources,
            detail=f"Represent at least {policy.minimum_sources} independent source videos.",
            current=len(source_counts),
            target=policy.minimum_sources,
        ),
        RecipeCheck(
            check_id="source-balance",
            label="Source balance",
            passed=not approved or largest_source_share <= policy.maximum_source_share,
            detail=(
                "One source contributes more than "
                f"{round(policy.maximum_source_share * 100)}% of approved clips."
            ),
            current=round(largest_source_share, 3),
            target=policy.maximum_source_share,
        ),
        RecipeCheck(
            check_id="minimum-duration",
            label="Training duration",
            passed=(
                policy.minimum_total_duration_seconds is None
                or total_duration >= policy.minimum_total_duration_seconds
            ),
            detail=f"Approve at least {policy.minimum_total_duration_seconds or 0:g} seconds of reviewed motion.",
            current=round(total_duration, 3),
            target=policy.minimum_total_duration_seconds,
        ),
        RecipeCheck(
            check_id="maximum-duration",
            label="Duration ceiling",
            passed=(
                policy.maximum_total_duration_seconds is None
                or total_duration <= policy.maximum_total_duration_seconds
            ),
            detail=f"Approved motion exceeds the {policy.maximum_total_duration_seconds or 0:g}-second recipe ceiling.",
            current=round(total_duration, 3),
            target=policy.maximum_total_duration_seconds,
        ),
        RecipeCheck(
            check_id="clip-duration",
            label="Clip duration",
            passed=not long_clips,
            detail=f"{len(long_clips)} approved clips exceed the {maximum_clip_duration or 0:g}-second review range.",
            current=len(long_clips),
            target=0,
        ),
        RecipeCheck(
            check_id="source-fps",
            label="Source frame rate",
            passed=not low_fps_clips,
            detail=f"{len(low_fps_clips)} approved clips are below the {policy.target_fps or 16} FPS training rate.",
            current=len(low_fps_clips),
            target=0,
        ),
        RecipeCheck(
            check_id="quality",
            label="Average quality",
            passed=average_quality >= policy.minimum_average_quality,
            detail=f"Average video quality is below {round(policy.minimum_average_quality * 100)}%.",
            current=round(average_quality, 3),
            target=policy.minimum_average_quality,
        ),
        RecipeCheck(
            check_id="identity",
            label="Temporal identity",
            passed=(
                policy.minimum_average_identity is None
                or average_identity >= policy.minimum_average_identity
            ),
            detail=f"Average temporal identity evidence is below {round((policy.minimum_average_identity or 0) * 100)}%.",
            current=round(average_identity, 3),
            target=policy.minimum_average_identity,
        ),
        RecipeCheck(
            check_id="stability",
            label="Temporal stability",
            passed=(
                policy.minimum_average_stability is None
                or average_stability >= policy.minimum_average_stability
            ),
            detail=f"Average temporal stability is below {round((policy.minimum_average_stability or 0) * 100)}%.",
            current=round(average_stability, 3),
            target=policy.minimum_average_stability,
        ),
        RecipeCheck(
            check_id="motion-floor",
            label="Motion floor",
            passed=(
                policy.minimum_average_motion is None
                or average_motion >= policy.minimum_average_motion
            ),
            detail=f"Average motion is below the {round((policy.minimum_average_motion or 0) * 100)}% recipe floor.",
            current=round(average_motion, 3),
            target=policy.minimum_average_motion,
        ),
        RecipeCheck(
            check_id="motion-ceiling",
            label="Motion ceiling",
            passed=(
                policy.maximum_average_motion is None
                or average_motion <= policy.maximum_average_motion
            ),
            detail=f"Average motion exceeds the {round((policy.maximum_average_motion or 0) * 100)}% stability ceiling.",
            current=round(average_motion, 3),
            target=policy.maximum_average_motion,
        ),
    ]
    failed_blockers = [
        check for check in checks
        if not check.passed and check.severity == "blocker"
    ]
    failed_warnings = [
        check for check in checks
        if not check.passed and check.severity == "warning"
    ]
    return RecipeCompliance(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.version,
        recipe_label=recipe.label,
        status=(
            "blocked"
            if failed_blockers
            else "review"
            if failed_warnings
            else "ready"
        ),
        score=sum(check.passed for check in checks) / len(checks),
        blocker_count=len(failed_blockers),
        warning_count=len(failed_warnings),
        checks=checks,
    )


def _average(items: list[VideoDatasetItem], attribute: str) -> float:
    if not items:
        return 0.0
    return sum(float(getattr(item, attribute)) for item in items) / len(items)


def _validation_sources(items: list[VideoDatasetItem]) -> set[str]:
    sources = sorted({item.source_media_item_id for item in items}, key=lambda value: hashlib.sha256(value.encode()).hexdigest())
    if len(sources) < 2:
        return set()
    count = max(1, round(len(sources) * 0.2))
    return set(sources[-count:])


def _fingerprint(snapshot: VideoDatasetSnapshot) -> str:
    target = get_training_target_profile(snapshot.target_profile_id)
    payload = {
        "training_target": {
            "profile_id": target.profile_id,
            "recipe_id": target.recipe_id,
            "recipe_version": target.recipe_version,
        },
        "reference_image_media_item_ids": snapshot.reference_image_media_item_ids,
        "reference_audio_media_item_ids": snapshot.reference_audio_media_item_ids,
        "items": [{
            "media_item_id": item.media_item_id,
            "source_media_item_id": item.source_media_item_id,
            "caption": item.caption,
            "split": item.split,
        } for item in sorted(snapshot.items.values(), key=lambda item: item.id) if item.status == "approved"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
