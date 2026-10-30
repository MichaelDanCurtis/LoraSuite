from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.exports import RunComfyDatasetEntry, create_runcomfy_dataset_export
from lorasuite_engine.models import (
    CaptionSource,
    CharacterProject,
    CropKind,
    CropRecipe,
    CropRecipeStatus,
    DatasetBalance,
    DatasetCaptionRecord,
    DatasetDuplicateCandidate,
    DatasetDuplicateCluster,
    DatasetDuplicateProposal,
    DatasetItemStatus,
    DatasetReviewStatus,
    DatasetSnapshot,
    DatasetSnapshotStatus,
    DatasetStrongestSetProposal,
    DatasetView,
    ExportPackage,
    MediaItem,
    StrongestSetCandidate,
    TrainingIntent,
    VisionCaptionEvidence,
    new_id,
    utc_now,
)
from lorasuite_engine.model_metadata import (
    LoraModelCardOverrides,
    build_snapshot_model_card,
    render_model_card_markdown,
)
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import (
    ModelIntentRecipe,
    RecipeCheck,
    RecipeCompliance,
    TrainingTargetSpec,
    get_training_target_profile,
    recipe_for_training_target,
)
from lorasuite_engine.vault import VaultService


class DatasetCompilerService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def snapshots_path(self) -> Path:
        return self.vault_root / "dataset_snapshots.json"

    def list_snapshots(self, project_id: str | None = None) -> list[DatasetSnapshot]:
        snapshots = self._read_snapshots().values()
        if project_id is not None:
            snapshots = (snapshot for snapshot in snapshots if snapshot.project_id == project_id)
        return sorted(
            snapshots,
            key=lambda snapshot: (snapshot.version, snapshot.updated_at),
            reverse=True,
        )

    def get_snapshot(self, snapshot_id: str) -> DatasetSnapshot | None:
        return self._read_snapshots().get(snapshot_id)

    def create_revision(
        self,
        snapshot_id: str,
        *,
        improvement_request_id: str,
        source_artifact_id: str,
        source_checkpoint_sha256: str,
        revision_plan: list[str],
    ) -> DatasetSnapshot:
        snapshots = self._read_snapshots()
        source = snapshots.get(snapshot_id)
        if source is None:
            raise KeyError(snapshot_id)
        if source.status not in {
            DatasetSnapshotStatus.FROZEN,
            DatasetSnapshotStatus.EXPORTED,
        }:
            raise ValueError("only a frozen or exported dataset can start a revision")
        if not source.fingerprint:
            raise ValueError("the source dataset revision has no immutable fingerprint")
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
        revision.id = new_id("dataset_snapshot")
        revision.version = max(versions, default=source.version) + 1
        revision.status = DatasetSnapshotStatus.DRAFT
        revision.fingerprint = None
        revision.export_package_id = None
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
        revision.model_card = build_snapshot_model_card(revision)
        snapshots[revision.id] = revision
        self._write_snapshots(snapshots)
        return revision

    def compile_project(
        self,
        project_id: str,
        training_target: TrainingTargetSpec | None = None,
    ) -> DatasetSnapshot:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        training_target = training_target or get_training_target_profile(
            "runcomfy_flux1_dev_character"
        ).spec()
        media_by_id = {
            item.id: item for item in VaultService(self.vault_root).list_media_items()
        }
        snapshots = self._read_snapshots()
        draft = next(
            (
                snapshot
                for snapshot in snapshots.values()
                if snapshot.project_id == project_id
                and snapshot.status == DatasetSnapshotStatus.DRAFT
                and snapshot.training_target.profile_id == training_target.profile_id
                and snapshot.training_target.recipe_id == training_target.recipe_id
                and snapshot.training_target.recipe_version == training_target.recipe_version
            ),
            None,
        )
        if draft is None:
            versions = [
                snapshot.version
                for snapshot in snapshots.values()
                if snapshot.project_id == project_id
            ]
            draft = DatasetSnapshot(
                project_id=project.id,
                project_name=project.name,
                version=max(versions, default=0) + 1,
                intent=project.intent.model_copy(deep=True),
                training_target=training_target.model_copy(deep=True),
            )

        shared_vision_records = _shared_vision_records(
            snapshots.values(),
            project_id,
        )
        existing_by_source = {
            item.source_media_item_id: item for item in draft.items.values()
        }
        compiled_items: dict[str, DatasetCaptionRecord] = {}
        for media_item_id in project.candidate_media_item_ids:
            observation = project.observations.get(media_item_id)
            source_item = media_by_id.get(media_item_id)
            if (
                observation is None
                or source_item is None
                or observation.review_status != DatasetReviewStatus.ACCEPTED
            ):
                continue
            training_item, crop_recipe = _training_asset(
                project,
                observation.view,
                media_item_id,
                source_item,
                media_by_id,
            )
            attributes, tags, unresolved = _caption_evidence(
                project.intent,
                observation.view,
                observation.head_yaw,
                crop_recipe,
            )
            existing = existing_by_source.get(media_item_id)
            shared_vision_record = shared_vision_records.get(
                (media_item_id, training_item.id)
            )
            if existing is None:
                record = DatasetCaptionRecord(
                    source_media_item_id=media_item_id,
                    training_media_item_id=training_item.id,
                    crop_recipe_id=crop_recipe.id if crop_recipe else None,
                    caption=_seed_caption(project.intent, tags),
                    tags=tags,
                    attributes=attributes,
                    unresolved_attributes=unresolved,
                    view=observation.view,
                    quality_score=observation.quality_score,
                    diversity_score=observation.diversity_score,
                    identity_score=observation.identity_score,
                    is_anchor=observation.is_anchor,
                    source_id=source_item.source_id,
                )
                shared_evidence = _record_vision_evidence(shared_vision_record)
                if shared_evidence is not None:
                    _apply_vision_to_record(
                        record,
                        intent=project.intent,
                        training_target=training_target,
                        evidence=shared_evidence,
                        provider_label=shared_vision_record.caption_provider,
                        model=shared_vision_record.caption_model,
                        mark_for_review=True,
                    )
            else:
                record = existing.model_copy(deep=True)
                reusable_evidence = (
                    _record_vision_evidence(record)
                    or _record_vision_evidence(shared_vision_record)
                )
                record.training_media_item_id = training_item.id
                record.crop_recipe_id = crop_recipe.id if crop_recipe else None
                record.view = observation.view
                record.quality_score = observation.quality_score
                record.diversity_score = observation.diversity_score
                record.identity_score = observation.identity_score
                record.is_anchor = observation.is_anchor
                record.source_id = source_item.source_id
                if record.caption_source != CaptionSource.USER:
                    record.attributes = attributes
                    if reusable_evidence is not None:
                        _apply_vision_to_record(
                            record,
                            intent=project.intent,
                            training_target=training_target,
                            evidence=reusable_evidence,
                            provider_label=(
                                record.caption_provider
                                or (
                                    shared_vision_record.caption_provider
                                    if shared_vision_record is not None
                                    else None
                                )
                            ),
                            model=(
                                record.caption_model
                                or (
                                    shared_vision_record.caption_model
                                    if shared_vision_record is not None
                                    else None
                                )
                            ),
                            mark_for_review=False,
                        )
                    else:
                        record.caption = _seed_caption(project.intent, tags)
                        record.tags = tags
                        record.unresolved_attributes = unresolved
                elif record.vision_evidence is None and reusable_evidence is not None:
                    record.vision_evidence = reusable_evidence
                record.updated_at = utc_now()
            compiled_items[record.id] = record

        draft.project_name = project.name
        draft.intent = project.intent.model_copy(deep=True)
        draft.training_target = training_target.model_copy(deep=True)
        draft.items = compiled_items
        draft.balance = _calculate_balance(draft)
        draft.updated_at = utc_now()
        draft.model_card = build_snapshot_model_card(draft)
        snapshots[draft.id] = draft
        self._write_snapshots(snapshots)
        return draft

    def update_item(
        self,
        snapshot_id: str,
        item_id: str,
        *,
        caption: str | None = None,
        tags: list[str] | None = None,
        status: DatasetItemStatus | None = None,
    ) -> DatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        item = snapshot.items.get(item_id)
        if item is None:
            raise ValueError(f"dataset item not found: {item_id}")
        if caption is not None:
            cleaned_caption = caption.strip().strip(",")
            if not cleaned_caption:
                raise ValueError("caption must not be empty")
            item.caption = cleaned_caption
            item.caption_source = CaptionSource.USER
        if tags is not None:
            item.tags = _clean_terms(tags)
            item.caption_source = CaptionSource.USER
        if status is not None:
            item.status = status
            item.strongest_set_excluded = False
            if status == DatasetItemStatus.EXCLUDED:
                item.strongest_set_rank = None
                item.strongest_set_score = None
                item.strongest_set_reasons = []
        item.updated_at = utc_now()
        snapshot.balance = _calculate_balance(snapshot)
        snapshot.updated_at = utc_now()
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def update_model_card(
        self,
        snapshot_id: str,
        overrides: LoraModelCardOverrides,
    ) -> DatasetSnapshot:
        snapshots = self._read_snapshots()
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        merged = snapshot.model_card_overrides.model_dump()
        merged.update(overrides.model_dump(exclude_unset=True))
        snapshot.model_card_overrides = LoraModelCardOverrides.model_validate(merged)
        snapshot.updated_at = utc_now()
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        self._sync_export_model_card(snapshot)
        return snapshot

    def bulk_update_status(
        self,
        snapshot_id: str,
        *,
        status: DatasetItemStatus,
        item_ids: list[str] | None = None,
    ) -> DatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        selected_ids = set(item_ids) if item_ids else set(snapshot.items)
        unknown_ids = selected_ids.difference(snapshot.items)
        if unknown_ids:
            raise ValueError(f"dataset item not found: {sorted(unknown_ids)[0]}")
        for item_id in selected_ids:
            item = snapshot.items[item_id]
            item.status = status
            item.strongest_set_excluded = False
            if status == DatasetItemStatus.EXCLUDED:
                item.strongest_set_rank = None
                item.strongest_set_score = None
                item.strongest_set_reasons = []
            item.updated_at = utc_now()
        snapshot.balance = _calculate_balance(snapshot)
        snapshot.updated_at = utc_now()
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def propose_strongest_set(
        self,
        snapshot_id: str,
        *,
        target_count: int | None = None,
        disqualified_item_ids: list[str] | None = None,
        included_item_ids: list[str] | None = None,
    ) -> DatasetStrongestSetProposal:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        return _build_strongest_set_proposal(
            snapshot,
            target_count,
            disqualified_item_ids=disqualified_item_ids,
            included_item_ids=included_item_ids,
        )

    def propose_duplicate_groups(
        self,
        snapshot_id: str,
    ) -> DatasetDuplicateProposal:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        media_by_id = {
            item.id: item for item in VaultService(self.vault_root).list_media_items()
        }
        records = [
            item
            for item in snapshot.items.values()
            if item.status != DatasetItemStatus.EXCLUDED
            and item.training_media_item_id in media_by_id
        ]
        hashes: dict[str, int] = {}
        unreadable_media_ids: set[str] = set()
        for item in records:
            media_id = item.training_media_item_id
            if media_id in hashes or media_id in unreadable_media_ids:
                continue
            media = media_by_id[media_id]
            try:
                with Image.open(media.raw_path) as image:
                    hashes[media_id] = _dataset_difference_hash(image)
            except (FileNotFoundError, OSError, UnidentifiedImageError):
                unreadable_media_ids.add(media_id)

        remaining = set(item.id for item in records)
        records_by_id = {item.id: item for item in records}
        clusters: list[DatasetDuplicateCluster] = []
        while remaining:
            keeper = max(
                (records_by_id[item_id] for item_id in remaining),
                key=lambda item: (_selection_base_score(item), item.id),
            )
            keeper_media = media_by_id[keeper.training_media_item_id]
            keeper_hash = hashes.get(keeper.training_media_item_id)
            matches: list[tuple[DatasetCaptionRecord, int]] = []
            for item_id in remaining:
                candidate = records_by_id[item_id]
                candidate_media = media_by_id[candidate.training_media_item_id]
                exact_match = (
                    candidate.training_media_item_id == keeper.training_media_item_id
                    or (
                        bool(candidate_media.sha256)
                        and candidate_media.sha256 == keeper_media.sha256
                    )
                )
                candidate_hash = hashes.get(candidate.training_media_item_id)
                hash_distance = (
                    (candidate_hash ^ keeper_hash).bit_count()
                    if candidate_hash is not None and keeper_hash is not None
                    else 64
                )
                if exact_match or hash_distance <= 5:
                    matches.append((candidate, 0 if exact_match else hash_distance))
            matched_ids = {candidate.id for candidate, _distance in matches}
            remaining.difference_update(matched_ids or {keeper.id})
            if len(matches) < 2:
                continue
            ordered = sorted(
                matches,
                key=lambda pair: (
                    pair[0].id != keeper.id,
                    pair[1],
                    -_selection_base_score(pair[0]),
                    pair[0].id,
                ),
            )
            cluster_id = f"dataset_duplicate_{hashlib.sha256('|'.join(sorted(matched_ids)).encode('utf-8')).hexdigest()[:16]}"
            clusters.append(
                DatasetDuplicateCluster(
                    id=cluster_id,
                    recommended_keep_item_id=keeper.id,
                    candidates=[
                        DatasetDuplicateCandidate(
                            item_id=item.id,
                            training_media_item_id=item.training_media_item_id,
                            hash_distance=distance,
                            score=round(_selection_base_score(item), 4),
                            group=_selection_view(item),
                            is_recommended_keep=item.id == keeper.id,
                        )
                        for item, distance in ordered
                    ],
                )
            )
        clusters.sort(
            key=lambda cluster: (-len(cluster.candidates), cluster.id)
        )
        return DatasetDuplicateProposal(
            snapshot_id=snapshot.id,
            scanned_count=len(records),
            duplicate_count=sum(len(cluster.candidates) - 1 for cluster in clusters),
            unreadable_count=sum(
                item.training_media_item_id in unreadable_media_ids
                for item in records
            ),
            clusters=clusters,
        )

    def apply_strongest_set(
        self,
        snapshot_id: str,
        *,
        target_count: int | None = None,
        disqualified_item_ids: list[str] | None = None,
        included_item_ids: list[str] | None = None,
    ) -> tuple[DatasetSnapshot, DatasetStrongestSetProposal]:
        snapshot, snapshots = self._require_draft(snapshot_id)
        proposal = _build_strongest_set_proposal(
            snapshot,
            target_count,
            disqualified_item_ids=disqualified_item_ids,
            included_item_ids=included_item_ids,
        )
        selected = {
            candidate.item_id: (rank, candidate)
            for rank, candidate in enumerate(proposal.selected, start=1)
        }
        now = utc_now()
        for item in snapshot.items.values():
            selection = selected.get(item.id)
            if selection is not None:
                rank, candidate = selection
                if item.status == DatasetItemStatus.EXCLUDED and item.strongest_set_excluded:
                    item.status = DatasetItemStatus.NEEDS_REVIEW
                item.strongest_set_excluded = False
                item.strongest_set_rank = rank
                item.strongest_set_score = candidate.score
                item.strongest_set_reasons = list(candidate.reasons)
                item.updated_at = now
                continue
            if item.status != DatasetItemStatus.EXCLUDED:
                item.status = DatasetItemStatus.EXCLUDED
                item.strongest_set_excluded = True
                item.strongest_set_rank = None
                item.strongest_set_score = None
                item.strongest_set_reasons = []
                item.updated_at = now

        snapshot.balance = _calculate_balance(snapshot)
        snapshot.updated_at = now
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot, proposal

    def restore_strongest_set(self, snapshot_id: str) -> DatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        now = utc_now()
        for item in snapshot.items.values():
            if item.strongest_set_excluded:
                item.status = DatasetItemStatus.NEEDS_REVIEW
            if item.strongest_set_excluded or item.strongest_set_rank is not None:
                item.strongest_set_excluded = False
                item.strongest_set_rank = None
                item.strongest_set_score = None
                item.strongest_set_reasons = []
                item.updated_at = now
        snapshot.balance = _calculate_balance(snapshot)
        snapshot.updated_at = now
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def apply_vision_evidence(
        self,
        snapshot_id: str,
        item_id: str,
        *,
        evidence: VisionCaptionEvidence,
        provider_label: str,
        model: str,
    ) -> DatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        item = snapshot.items.get(item_id)
        if item is None:
            raise ValueError(f"dataset item not found: {item_id}")
        _apply_vision_to_record(
            item,
            intent=snapshot.intent,
            training_target=snapshot.training_target,
            evidence=evidence,
            provider_label=provider_label,
            model=model,
            mark_for_review=True,
        )
        snapshot.balance = _calculate_balance(snapshot)
        snapshot.updated_at = utc_now()
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def freeze_snapshot(self, snapshot_id: str) -> DatasetSnapshot:
        snapshot, snapshots = self._require_draft(snapshot_id)
        if snapshot.balance.review_count:
            raise ValueError("resolve or exclude every caption before freezing")
        approved = [
            item
            for item in snapshot.items.values()
            if item.status == DatasetItemStatus.APPROVED
        ]
        if not approved:
            raise ValueError("approve at least one dataset item before freezing")
        trigger_token = snapshot.intent.trigger_token.strip()
        if not trigger_token:
            raise ValueError("training intent requires a trigger token before freezing")
        for item in approved:
            if trigger_token not in item.caption:
                raise ValueError(
                    f"approved caption is missing trigger token: {item.id}"
                )
        failed_blockers = [
            check
            for check in snapshot.balance.recipe_compliance.checks
            if not check.passed and check.severity == "blocker"
        ] if snapshot.balance.recipe_compliance else []
        if failed_blockers:
            raise ValueError(
                f"training recipe preflight failed: {failed_blockers[0].detail}"
            )
        snapshot.fingerprint = _snapshot_fingerprint(snapshot)
        snapshot.status = DatasetSnapshotStatus.FROZEN
        snapshot.frozen_at = utc_now()
        snapshot.updated_at = snapshot.frozen_at
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot

    def export_runcomfy(self, snapshot_id: str, output_dir: Path) -> tuple[DatasetSnapshot, ExportPackage]:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        if snapshot.status not in {
            DatasetSnapshotStatus.FROZEN,
            DatasetSnapshotStatus.EXPORTED,
        }:
            raise ValueError("freeze the dataset snapshot before export")
        media_by_id = {
            item.id: item for item in VaultService(self.vault_root).list_media_items()
        }
        entries: list[RunComfyDatasetEntry] = []
        for item in snapshot.items.values():
            if item.status != DatasetItemStatus.APPROVED:
                continue
            media_item = media_by_id.get(item.training_media_item_id)
            if media_item is None:
                raise ValueError(f"training media not found: {item.training_media_item_id}")
            entries.append(
                RunComfyDatasetEntry(
                    image_path=media_item.raw_path,
                    caption=item.caption,
                    dataset_item_id=item.id,
                    source_media_item_id=item.source_media_item_id,
                    training_media_item_id=item.training_media_item_id,
                    crop_recipe_id=item.crop_recipe_id,
                )
            )
        package = create_runcomfy_dataset_export(
            entries=entries,
            output_dir=Path(output_dir),
            snapshot_id=snapshot.id,
            project_id=snapshot.project_id,
            version=snapshot.version,
            fingerprint=snapshot.fingerprint or _snapshot_fingerprint(snapshot),
            training_target=snapshot.training_target.model_dump(mode="json"),
            model_card=(
                snapshot.model_card.model_dump(mode="json")
                if snapshot.model_card
                else build_snapshot_model_card(snapshot).model_dump(mode="json")
            ),
            revision_lineage=RevisionLineage.from_snapshot(
                snapshot
            ).manifest_payload(),
        )
        snapshots = self._read_snapshots()
        snapshot.status = DatasetSnapshotStatus.EXPORTED
        snapshot.export_package_id = package.id
        snapshot.export_path = package.output_path
        snapshot.updated_at = utc_now()
        snapshot.model_card = build_snapshot_model_card(snapshot)
        snapshots[snapshot.id] = snapshot
        self._write_snapshots(snapshots)
        return snapshot, package

    def _require_draft(
        self, snapshot_id: str
    ) -> tuple[DatasetSnapshot, dict[str, DatasetSnapshot]]:
        snapshots = self._read_snapshots()
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        if snapshot.status != DatasetSnapshotStatus.DRAFT:
            raise ValueError("frozen dataset snapshots are immutable")
        return snapshot, snapshots

    def _read_snapshots(self) -> dict[str, DatasetSnapshot]:
        with json_file_lock(self.snapshots_path):
            if not self.snapshots_path.exists():
                return {}
            payload = json.loads(self.snapshots_path.read_text(encoding="utf-8"))
            return {
                item["id"]: DatasetSnapshot.model_validate(item)
                for item in payload.get("snapshots", [])
            }

    def _write_snapshots(self, snapshots: dict[str, DatasetSnapshot]) -> None:
        with json_file_lock(self.snapshots_path):
            atomic_write_json(
                self.snapshots_path,
                {
                    "version": 1,
                    "snapshots": [
                        snapshot.model_dump(mode="json")
                        for snapshot in snapshots.values()
                    ],
                },
            )

    def _sync_export_model_card(self, snapshot: DatasetSnapshot) -> None:
        if snapshot.export_path is None or snapshot.model_card is None:
            return
        export_path = Path(snapshot.export_path)
        manifest_path = export_path / "manifest.json"
        if not export_path.is_dir() or not manifest_path.is_file():
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_card_path"] = "model_card.json"
        manifest["model_card"] = snapshot.model_card.model_dump(mode="json")
        atomic_write_json(manifest_path, manifest)
        atomic_write_json(
            export_path / "model_card.json",
            snapshot.model_card.model_dump(mode="json"),
        )
        _atomic_write_text(
            export_path / "README.md",
            render_model_card_markdown(snapshot.model_card),
        )


def _training_asset(
    project: CharacterProject,
    view: DatasetView,
    source_media_item_id: str,
    source_item: MediaItem,
    media_by_id: dict[str, MediaItem],
) -> tuple[MediaItem, CropRecipe | None]:
    desired_kind = {
        DatasetView.FACE: CropKind.FACE,
        DatasetView.UPPER_BODY: CropKind.UPPER_BODY,
        DatasetView.FULL_BODY: CropKind.FULL_BODY,
    }.get(view)
    materialized = [
        recipe
        for recipe in project.crop_recipes.values()
        if recipe.media_item_id == source_media_item_id
        and recipe.status == CropRecipeStatus.MATERIALIZED
        and recipe.output_media_item_id in media_by_id
    ]
    selected = next(
        (recipe for recipe in materialized if recipe.kind == desired_kind),
        materialized[0] if materialized else None,
    )
    if selected is None or selected.output_media_item_id is None:
        return source_item, None
    return media_by_id[selected.output_media_item_id], selected


def _caption_evidence(
    intent: TrainingIntent,
    view: DatasetView,
    head_yaw: float | None,
    crop_recipe: CropRecipe | None,
) -> tuple[dict[str, str], list[str], list[str]]:
    framing = {
        DatasetView.FACE: "close-up portrait",
        DatasetView.UPPER_BODY: "upper-body portrait",
        DatasetView.FULL_BODY: "full-body photo",
        DatasetView.ENVIRONMENT: "environmental portrait",
        DatasetView.UNKNOWN: "portrait",
    }[view]
    attributes = {
        "framing": framing,
        "asset": crop_recipe.kind.value if crop_recipe else "original",
    }
    tags = [framing]
    if head_yaw is not None:
        absolute_yaw = abs(head_yaw)
        head_angle = (
            "front view"
            if absolute_yaw < 0.20
            else "three-quarter view"
            if absolute_yaw < 0.55
            else "profile view"
        )
        attributes["head_angle"] = head_angle
        tags.append(head_angle)
    known = {"framing", "head angle", "head_angle", "identity", "face", "body"}
    unresolved = [
        attribute
        for attribute in intent.controllable_attributes
        if attribute.strip().lower() not in known
    ]
    return attributes, _clean_terms(tags), _clean_terms(unresolved)


def _seed_caption(intent: TrainingIntent, tags: list[str]) -> str:
    subject = intent.trigger_token.strip() or intent.subject_name.strip() or "subject"
    target = "person" if intent.target_type.value == "character" else intent.target_type.value
    return ", ".join(_clean_terms([subject, target, *tags]))


def _shared_vision_records(
    snapshots: Iterable[DatasetSnapshot],
    project_id: str,
) -> dict[tuple[str, str], DatasetCaptionRecord]:
    shared: dict[tuple[str, str], DatasetCaptionRecord] = {}
    project_snapshots = sorted(
        (snapshot for snapshot in snapshots if snapshot.project_id == project_id),
        key=lambda snapshot: snapshot.updated_at,
    )
    for snapshot in project_snapshots:
        for record in snapshot.items.values():
            if _record_vision_evidence(record) is None:
                continue
            shared[
                (record.source_media_item_id, record.training_media_item_id)
            ] = record
    return shared


def _record_vision_evidence(
    record: DatasetCaptionRecord | None,
) -> VisionCaptionEvidence | None:
    if record is None:
        return None
    if record.vision_evidence is not None:
        return record.vision_evidence.model_copy(deep=True)
    if record.caption_source != CaptionSource.VISION:
        return None
    values = {
        field: record.attributes.get(field, "")
        for field in (
            "expression",
            "pose",
            "clothing",
            "environment",
            "camera",
            "lighting",
            "visual_style",
            "other_people",
            "watermark",
            "content",
        )
    }
    if not any(
        _known_value(value)
        for key, value in values.items()
        if key not in {"other_people", "watermark", "content"}
    ):
        return None
    return VisionCaptionEvidence(
        expression=values["expression"] or "unknown",
        pose=values["pose"] or "unknown",
        clothing=values["clothing"] or "unknown",
        environment=values["environment"] or "unknown",
        camera=values["camera"] or "unknown",
        lighting=values["lighting"] or "unknown",
        visual_style=values["visual_style"] or "unknown",
        other_people=values["other_people"] or "none",
        watermark=values["watermark"] or "none",
        content=values["content"] or "general",
        confidence=record.caption_confidence or 0.0,
    )


def _apply_vision_to_record(
    item: DatasetCaptionRecord,
    *,
    intent: TrainingIntent,
    training_target: TrainingTargetSpec,
    evidence: VisionCaptionEvidence,
    provider_label: str | None,
    model: str | None,
    mark_for_review: bool,
) -> None:
    evidence_values = {
        "expression": evidence.expression,
        "pose": evidence.pose,
        "clothing": evidence.clothing,
        "environment": evidence.environment,
        "camera": evidence.camera,
        "lighting": evidence.lighting,
        "visual_style": evidence.visual_style,
        "other_people": evidence.other_people,
        "watermark": evidence.watermark,
        "content": evidence.content,
    }
    for key, value in evidence_values.items():
        if _known_value(value):
            item.attributes[key] = value

    base_tags = [
        item.attributes.get("framing", ""),
        item.attributes.get("head_angle", ""),
    ]
    visual_tags = [
        evidence.expression,
        evidence.pose,
        evidence.clothing,
        evidence.environment,
        evidence.camera,
        evidence.lighting,
        evidence.visual_style,
    ]
    if _visible_exception(evidence.other_people):
        visual_tags.append(evidence.other_people)
    if _visible_exception(evidence.watermark):
        visual_tags.append(evidence.watermark)
    if evidence.content != "general":
        visual_tags.append(evidence.content)
    item.tags = _clean_terms(
        [value for value in [*base_tags, *visual_tags] if _known_value(value)]
    )
    item.caption = _render_vision_caption(
        intent,
        training_target,
        item.attributes,
        item.tags,
        evidence,
    )
    item.unresolved_attributes = _unresolved_controllable_attributes(
        intent,
        evidence,
    )
    item.caption_source = CaptionSource.VISION
    item.caption_provider = provider_label or item.caption_provider
    item.caption_model = model or item.caption_model
    item.caption_confidence = evidence.confidence
    item.vision_evidence = evidence.model_copy(deep=True)
    if mark_for_review:
        item.status = DatasetItemStatus.NEEDS_REVIEW
    item.updated_at = utc_now()


def _render_vision_caption(
    intent: TrainingIntent,
    training_target: TrainingTargetSpec,
    attributes: dict[str, str],
    tags: list[str],
    evidence: VisionCaptionEvidence,
) -> str:
    recipe = recipe_for_training_target(training_target)
    render_style = recipe.captions.render_style if recipe is not None else "concise"
    if render_style == "narrative":
        return _narrative_caption(intent, attributes, evidence)
    return _seed_caption(intent, tags)


def _narrative_caption(
    intent: TrainingIntent,
    attributes: dict[str, str],
    evidence: VisionCaptionEvidence,
) -> str:
    subject = intent.trigger_token.strip() or intent.subject_name.strip() or "subject"
    target = "person" if intent.target_type.value == "character" else intent.target_type.value
    framing = attributes.get("framing", "")
    lead = (
        f"A {framing} of {subject}, a {target}"
        if _known_value(framing)
        else f"{subject}, a {target}"
    )
    subject_details: list[str] = []
    if _known_value(evidence.pose):
        subject_details.append(evidence.pose)
    if _known_value(evidence.clothing):
        subject_details.append(f"wearing {evidence.clothing}")
    if _known_value(evidence.expression):
        expression = evidence.expression
        subject_details.append(
            f"with {expression}"
            if "expression" in expression.casefold()
            else f"with a {expression} expression"
        )
    first_sentence = ", ".join([lead, *subject_details]).rstrip(",") + "."

    scene_details: list[str] = []
    if _known_value(evidence.environment):
        scene_details.append(f"The setting is {evidence.environment}")
    if _known_value(evidence.camera):
        scene_details.append(f"the composition is {evidence.camera}")
    if _known_value(evidence.lighting):
        scene_details.append(f"the lighting is {evidence.lighting}")
    if _known_value(evidence.visual_style):
        scene_details.append(f"the visual treatment is {evidence.visual_style}")
    sentences = [first_sentence]
    if scene_details:
        scene_sentence = ", and ".join(scene_details)
        sentences.append(scene_sentence[:1].upper() + scene_sentence[1:] + ".")
    if _visible_exception(evidence.other_people):
        sentences.append(f"Other visible people: {evidence.other_people}.")
    if _visible_exception(evidence.watermark):
        sentences.append(f"Visible text or watermark: {evidence.watermark}.")
    return " ".join(sentences)


def _clean_terms(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = value.strip().strip(",")
        key = term.casefold()
        if term and key not in seen:
            cleaned.append(term)
            seen.add(key)
    return cleaned


def _known_value(value: str) -> bool:
    return value.strip().casefold() not in {"", "unknown", "unclear", "not visible"}


def _visible_exception(value: str) -> bool:
    return _known_value(value) and value.strip().casefold() not in {
        "none",
        "no",
        "not present",
        "no watermark",
        "no other people",
    }


def _unresolved_controllable_attributes(
    intent: TrainingIntent,
    evidence: VisionCaptionEvidence,
) -> list[str]:
    values = {
        "expression": evidence.expression,
        "pose": evidence.pose,
        "clothing": evidence.clothing,
        "environment": evidence.environment,
        "background": evidence.environment,
        "camera": evidence.camera,
        "camera angle": evidence.camera,
        "lighting": evidence.lighting,
        "visual style": evidence.visual_style,
        "style": evidence.visual_style,
    }
    unresolved: list[str] = []
    for attribute in intent.controllable_attributes:
        key = attribute.strip().casefold().replace("_", " ")
        value = values.get(key)
        if value is None or not _known_value(value):
            unresolved.append(attribute)
    return _clean_terms(unresolved)


def _build_strongest_set_proposal(
    snapshot: DatasetSnapshot,
    requested_count: int | None,
    *,
    disqualified_item_ids: list[str] | None = None,
    included_item_ids: list[str] | None = None,
) -> DatasetStrongestSetProposal:
    recipe = recipe_for_training_target(snapshot.training_target)
    policy = recipe.dataset if recipe is not None else None
    minimum = policy.minimum_approved_items if policy is not None else 20
    recommended = policy.recommended_approved_items if policy is not None else 35
    maximum = policy.maximum_approved_items if policy is not None else 80
    minimum_sources = policy.minimum_sources if policy is not None else 2
    maximum_source_share = policy.maximum_source_share if policy is not None else 0.65
    view_minimums = {
        DatasetView.FACE: policy.minimum_face_views if policy is not None else 4,
        DatasetView.UPPER_BODY: (
            policy.minimum_upper_body_views if policy is not None else 4
        ),
        DatasetView.FULL_BODY: (
            policy.minimum_full_body_views if policy is not None else 4
        ),
    }

    manually_excluded = [
        item
        for item in snapshot.items.values()
        if item.status == DatasetItemStatus.EXCLUDED
        and not item.strongest_set_excluded
    ]
    manually_excluded_ids = {item.id for item in manually_excluded}
    requested_disqualified_ids = set(disqualified_item_ids or [])
    requested_included_ids = set(included_item_ids or [])
    unknown_ids = requested_disqualified_ids.union(
        requested_included_ids
    ).difference(snapshot.items)
    if unknown_ids:
        raise ValueError(f"dataset item not found: {sorted(unknown_ids)[0]}")
    conflict_ids = requested_disqualified_ids.intersection(requested_included_ids)
    if conflict_ids:
        raise ValueError(
            f"dataset item cannot be both included and disqualified: {sorted(conflict_ids)[0]}"
        )
    requested_disqualified_ids.difference_update(manually_excluded_ids)
    requested_included_ids.difference_update(manually_excluded_ids)
    candidates = [
        item
        for item in snapshot.items.values()
        if item.id not in manually_excluded_ids
        and item.id not in requested_disqualified_ids
    ]
    desired = requested_count if requested_count is not None else recommended
    desired = max(minimum, min(maximum, desired))
    target_count = min(len(candidates), desired)
    anchors = [item for item in candidates if item.is_anchor]
    pinned = [item for item in candidates if item.id in requested_included_ids]
    mandatory_ids = {item.id for item in anchors}.union(item.id for item in pinned)
    if len(mandatory_ids) > target_count:
        target_count = len(mandatory_ids)

    selected: list[DatasetCaptionRecord] = []
    selected_ids: set[str] = set()
    view_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    facet_counts: Counter[str] = Counter()

    def add(item: DatasetCaptionRecord) -> None:
        if item.id in selected_ids or len(selected) >= target_count:
            return
        selected.append(item)
        selected_ids.add(item.id)
        view_counts[_selection_view(item).value] += 1
        if item.source_id:
            source_counts[item.source_id] += 1
        facet_counts.update(_selection_facets(item))

    for item in sorted(pinned, key=_selection_sort_key):
        add(item)

    for item in sorted(anchors, key=_selection_sort_key):
        add(item)

    source_groups: dict[str, list[DatasetCaptionRecord]] = {}
    for item in candidates:
        if item.id in selected_ids or not item.source_id:
            continue
        source_groups.setdefault(item.source_id, []).append(item)
    for source_id in sorted(
        source_groups,
        key=lambda value: (
            -max(_selection_base_score(item) for item in source_groups[value]),
            value,
        ),
    ):
        if len(source_counts) >= minimum_sources or len(selected) >= target_count:
            break
        add(
            max(
                source_groups[source_id],
                key=lambda item: (
                    _selection_dynamic_score(
                        item,
                        view_counts,
                        source_counts,
                        facet_counts,
                    ),
                    item.id,
                ),
            )
        )

    for view, quota in view_minimums.items():
        while view_counts[view.value] < quota and len(selected) < target_count:
            pool = [
                item
                for item in candidates
                if item.id not in selected_ids and _selection_view(item) == view
            ]
            if not pool:
                break
            add(
                max(
                    pool,
                    key=lambda item: (
                        _selection_dynamic_score(
                            item,
                            view_counts,
                            source_counts,
                            facet_counts,
                        ),
                        item.id,
                    ),
                )
            )

    while len(selected) < target_count:
        remaining = [item for item in candidates if item.id not in selected_ids]
        if not remaining:
            break
        balanced = [
            item
            for item in remaining
            if not item.source_id
            or len(source_counts) < minimum_sources
            or (
                (source_counts[item.source_id] + 1)
                / max(1, len(selected) + 1)
                <= maximum_source_share
            )
        ]
        pool = balanced or remaining
        add(
            max(
                pool,
                key=lambda item: (
                    _selection_dynamic_score(
                        item,
                        view_counts,
                        source_counts,
                        facet_counts,
                    ),
                    item.id,
                ),
            )
        )

    selected_candidates = [
        StrongestSetCandidate(
            item_id=item.id,
            score=round(_selection_base_score(item), 4),
            reasons=_selection_reasons(item),
            group=_selection_view(item),
        )
        for item in selected
    ]
    selected_id_set = {item.id for item in selected}
    excluded_item_ids = sorted(
        {
            item.id
            for item in candidates
            if item.id not in selected_id_set
        }.union(requested_disqualified_ids)
    )
    identity_scores = [
        item.identity_score
        for item in selected
        if item.identity_score is not None
    ]
    warnings: list[str] = []
    if requested_count is not None and desired != requested_count:
        warnings.append(
            f"Target adjusted to the recipe range of {minimum}–{maximum} images."
        )
    if len(candidates) < minimum:
        warnings.append(
            f"Only {len(candidates)} recoverable candidates are available; the recipe minimum is {minimum}."
        )
    for view, quota in view_minimums.items():
        if view_counts[view.value] < quota:
            warnings.append(
                f"Only {view_counts[view.value]} {view.value.replace('_', ' ')} views were found; the recipe asks for {quota}."
            )
    if len(source_counts) < minimum_sources:
        warnings.append(
            f"Only {len(source_counts)} independent sources are represented; the recipe asks for {minimum_sources}."
        )

    return DatasetStrongestSetProposal(
        snapshot_id=snapshot.id,
        target_count=target_count,
        selected_count=len(selected),
        excluded_count=len(excluded_item_ids),
        already_excluded_count=len(manually_excluded),
        recipe_minimum=minimum,
        recipe_recommended=recommended,
        recipe_maximum=maximum,
        selected=selected_candidates,
        excluded_item_ids=excluded_item_ids,
        view_counts=dict(sorted(view_counts.items())),
        source_counts=dict(sorted(source_counts.items())),
        average_quality=(
            round(sum(item.quality_score for item in selected) / len(selected), 4)
            if selected
            else 0.0
        ),
        average_diversity=(
            round(sum(item.diversity_score for item in selected) / len(selected), 4)
            if selected
            else 0.0
        ),
        average_identity=(
            round(sum(identity_scores) / len(identity_scores), 4)
            if identity_scores
            else None
        ),
        warnings=warnings,
    )


def _selection_sort_key(item: DatasetCaptionRecord) -> tuple[float, str]:
    return (-_selection_base_score(item), item.id)


def _dataset_difference_hash(image: Image.Image) -> int:
    pixels = list(image.convert("L").resize((9, 8)).get_flattened_data())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(
                pixels[offset + column] > pixels[offset + column + 1]
            )
    return value


def _selection_base_score(item: DatasetCaptionRecord) -> float:
    identity = item.identity_score if item.identity_score is not None else 0.5
    return (
        max(0.0, min(1.0, item.quality_score)) * 0.48
        + max(0.0, min(1.0, identity)) * 0.30
        + max(0.0, min(1.0, item.diversity_score)) * 0.17
        + (0.05 if item.crop_recipe_id else 0.0)
        + (0.35 if item.is_anchor else 0.0)
    )


def _selection_dynamic_score(
    item: DatasetCaptionRecord,
    view_counts: Counter[str],
    source_counts: Counter[str],
    facet_counts: Counter[str],
) -> float:
    view = _selection_view(item).value
    source_bonus = (
        0.10
        if item.source_id and source_counts[item.source_id] == 0
        else 0.04 / (1 + source_counts[item.source_id])
        if item.source_id
        else 0.0
    )
    view_bonus = 0.08 / (1 + view_counts[view])
    facets = _selection_facets(item)
    novelty_bonus = (
        min(
            0.15,
            sum(1 / (1 + facet_counts[facet]) for facet in facets)
            / len(facets)
            * 0.15,
        )
        if facets
        else 0.0
    )
    return _selection_base_score(item) + source_bonus + view_bonus + novelty_bonus


def _selection_view(item: DatasetCaptionRecord) -> DatasetView:
    if item.view not in {DatasetView.UNKNOWN, DatasetView.ENVIRONMENT}:
        return item.view
    evidence = " ".join(
        [
            item.attributes.get("framing", ""),
            item.attributes.get("camera", ""),
            item.caption,
        ]
    ).casefold().replace("_", " ")
    if any(
        term in evidence
        for term in ("full-body", "full body", "head to toe", "wide shot")
    ):
        return DatasetView.FULL_BODY
    if any(
        term in evidence
        for term in (
            "upper-body",
            "upper body",
            "waist up",
            "waist-up",
            "medium shot",
            "medium close",
        )
    ):
        return DatasetView.UPPER_BODY
    if any(
        term in evidence
        for term in ("close-up", "close up", "headshot", "face close")
    ):
        return DatasetView.FACE
    return item.view


def _selection_facets(item: DatasetCaptionRecord) -> set[str]:
    facets = {_selection_view(item).value}
    for key in (
        "expression",
        "pose",
        "clothing",
        "environment",
        "camera",
        "lighting",
        "visual_style",
    ):
        value = item.attributes.get(key, "").strip().casefold()
        if _known_value(value):
            facets.add(f"{key}:{value}")
    return facets


def _selection_reasons(item: DatasetCaptionRecord) -> list[str]:
    reasons: list[str] = []
    if item.is_anchor:
        reasons.append("trusted identity anchor")
    if item.identity_score is not None and item.identity_score >= 0.5:
        reasons.append("strong identity match")
    if item.quality_score >= 0.8:
        reasons.append("high visual quality")
    if item.diversity_score >= 0.35:
        reasons.append("adds visual variety")
    view = _selection_view(item)
    if view in {DatasetView.FACE, DatasetView.UPPER_BODY, DatasetView.FULL_BODY}:
        reasons.append(f"balances {view.value.replace('_', ' ')} coverage")
    if item.source_id:
        reasons.append("balances source coverage")
    return reasons or ["best available quality and identity evidence"]


def _calculate_balance(snapshot: DatasetSnapshot) -> DatasetBalance:
    items = list(snapshot.items.values())
    status_counts = Counter(item.status for item in items)
    active = [item for item in items if item.status != DatasetItemStatus.EXCLUDED]
    approved = [item for item in items if item.status == DatasetItemStatus.APPROVED]
    assessed = approved or active
    view_counts = Counter(item.view.value for item in active)
    crop_counts = Counter(
        item.attributes.get("asset", "original") for item in active
    )
    source_counts = Counter(item.source_id for item in active if item.source_id)
    recipe = recipe_for_training_target(snapshot.training_target)
    compliance = (
        _calculate_recipe_compliance(snapshot, recipe, assessed)
        if recipe is not None
        else None
    )
    if compliance is not None:
        warnings = [
            check.detail
            for check in compliance.checks
            if not check.passed
        ]
    else:
        warnings = _generic_balance_warnings(
            snapshot,
            status_counts,
            active,
            view_counts,
            source_counts,
        )
    return DatasetBalance(
        total_count=len(items),
        approved_count=status_counts[DatasetItemStatus.APPROVED],
        review_count=status_counts[DatasetItemStatus.NEEDS_REVIEW],
        excluded_count=status_counts[DatasetItemStatus.EXCLUDED],
        source_count=len(source_counts),
        cropped_count=sum(item.crop_recipe_id is not None for item in active),
        average_quality=(sum(item.quality_score for item in active) / len(active) if active else 0.0),
        average_diversity=(sum(item.diversity_score for item in active) / len(active) if active else 0.0),
        view_counts=dict(view_counts),
        crop_counts=dict(crop_counts),
        warnings=warnings,
        recipe_compliance=compliance,
    )


def _generic_balance_warnings(
    snapshot: DatasetSnapshot,
    status_counts: Counter,
    active: list[DatasetCaptionRecord],
    view_counts: Counter,
    source_counts: Counter,
) -> list[str]:
    warnings: list[str] = []
    if not snapshot.intent.trigger_token.strip():
        warnings.append("Training intent requires a trigger token before freezing.")
    if status_counts[DatasetItemStatus.NEEDS_REVIEW]:
        warnings.append("Caption review is incomplete.")
    if status_counts[DatasetItemStatus.APPROVED] < 20:
        warnings.append("Fewer than 20 items are approved for training.")
    if view_counts[DatasetView.FACE.value] == 0:
        warnings.append("No close face views are represented.")
    if view_counts[DatasetView.FULL_BODY.value] == 0:
        warnings.append("No full-body views are represented.")
    if active and max(source_counts.values(), default=0) / len(active) > 0.65:
        warnings.append("One source contributes more than 65% of the dataset.")
    if active and not any(item.crop_recipe_id for item in active):
        warnings.append("No materialized crops are represented.")
    return warnings


def _calculate_recipe_compliance(
    snapshot: DatasetSnapshot,
    recipe: ModelIntentRecipe,
    assessed: list[DatasetCaptionRecord],
) -> RecipeCompliance:
    policy = recipe.dataset
    approved = [
        item for item in snapshot.items.values()
        if item.status == DatasetItemStatus.APPROVED
    ]
    source_counts = Counter(item.source_id for item in assessed if item.source_id)
    largest_source_share = (
        max(source_counts.values(), default=0) / len(assessed)
        if assessed
        else 0.0
    )
    view_counts = Counter(item.view.value for item in assessed)
    crop_count = sum(item.crop_recipe_id is not None for item in assessed)
    average_quality = (
        sum(item.quality_score for item in assessed) / len(assessed)
        if assessed
        else 0.0
    )
    average_diversity = (
        sum(item.diversity_score for item in assessed) / len(assessed)
        if assessed
        else 0.0
    )
    trigger_token = snapshot.intent.trigger_token.strip()
    missing_trigger_captions = (
        sum(trigger_token not in item.caption for item in approved)
        if trigger_token
        else len(approved)
    )
    review_count = sum(
        item.status == DatasetItemStatus.NEEDS_REVIEW
        for item in snapshot.items.values()
    )
    checks = [
        RecipeCheck(
            check_id="intent",
            label="Training intent",
            passed=snapshot.intent.target_type.value == recipe.intent,
            severity="blocker",
            detail=(
                f"Recipe expects a {recipe.intent} project; this project is "
                f"{snapshot.intent.target_type.value}."
            ),
            current=snapshot.intent.target_type.value,
            target=recipe.intent,
        ),
        RecipeCheck(
            check_id="trigger-token",
            label="Trigger token",
            passed=bool(trigger_token),
            severity="blocker",
            detail="Training intent requires a trigger token before freezing.",
            current=trigger_token or "missing",
            target="required",
        ),
        RecipeCheck(
            check_id="caption-review",
            label="Caption review",
            passed=review_count == 0,
            severity="blocker",
            detail="Caption review is incomplete.",
            current=review_count,
            target=0,
        ),
        RecipeCheck(
            check_id="caption-trigger-coverage",
            label="Trigger coverage",
            passed=missing_trigger_captions == 0,
            severity="blocker",
            detail=(
                f"{missing_trigger_captions} approved caption"
                f"{'' if missing_trigger_captions == 1 else 's'} are missing the trigger token."
            ),
            current=missing_trigger_captions,
            target=0,
        ),
        RecipeCheck(
            check_id="approved-items",
            label="Approved images",
            passed=len(approved) >= policy.minimum_approved_items,
            detail=(
                f"Approve at least {policy.minimum_approved_items} images for the "
                f"{recipe.label} baseline."
            ),
            current=len(approved),
            target=policy.minimum_approved_items,
        ),
        RecipeCheck(
            check_id="maximum-approved-items",
            label="Dataset size",
            passed=len(approved) <= policy.maximum_approved_items,
            detail=(
                f"Keep no more than {policy.maximum_approved_items} approved images "
                f"for the {recipe.label} baseline."
            ),
            current=len(approved),
            target=policy.maximum_approved_items,
        ),
        RecipeCheck(
            check_id="source-count",
            label="Independent sources",
            passed=len(source_counts) >= policy.minimum_sources,
            detail=(
                f"Represent at least {policy.minimum_sources} independent sources "
                "to reduce source-specific memorization."
            ),
            current=len(source_counts),
            target=policy.minimum_sources,
        ),
        RecipeCheck(
            check_id="source-balance",
            label="Source balance",
            passed=not assessed or largest_source_share <= policy.maximum_source_share,
            detail=(
                "One source contributes more than "
                f"{round(policy.maximum_source_share * 100)}% of the assessed dataset."
            ),
            current=round(largest_source_share, 3),
            target=policy.maximum_source_share,
        ),
        RecipeCheck(
            check_id="face-views",
            label="Close face coverage",
            passed=view_counts[DatasetView.FACE.value] >= policy.minimum_face_views,
            detail=f"Include at least {policy.minimum_face_views} close face views.",
            current=view_counts[DatasetView.FACE.value],
            target=policy.minimum_face_views,
        ),
        RecipeCheck(
            check_id="upper-body-views",
            label="Upper-body coverage",
            passed=(
                view_counts[DatasetView.UPPER_BODY.value]
                >= policy.minimum_upper_body_views
            ),
            detail=f"Include at least {policy.minimum_upper_body_views} upper-body views.",
            current=view_counts[DatasetView.UPPER_BODY.value],
            target=policy.minimum_upper_body_views,
        ),
        RecipeCheck(
            check_id="full-body-views",
            label="Full-body coverage",
            passed=(
                view_counts[DatasetView.FULL_BODY.value]
                >= policy.minimum_full_body_views
            ),
            detail=f"Include at least {policy.minimum_full_body_views} full-body views.",
            current=view_counts[DatasetView.FULL_BODY.value],
            target=policy.minimum_full_body_views,
        ),
        RecipeCheck(
            check_id="materialized-crops",
            label="Materialized crops",
            passed=crop_count >= policy.minimum_materialized_crops,
            detail=f"Represent at least {policy.minimum_materialized_crops} reviewed crops.",
            current=crop_count,
            target=policy.minimum_materialized_crops,
        ),
        RecipeCheck(
            check_id="quality",
            label="Average quality",
            passed=average_quality >= policy.minimum_average_quality,
            detail=(
                "Average image quality is below the recipe baseline of "
                f"{round(policy.minimum_average_quality * 100)}%."
            ),
            current=round(average_quality, 3),
            target=policy.minimum_average_quality,
        ),
        RecipeCheck(
            check_id="diversity",
            label="Average diversity",
            passed=average_diversity >= policy.minimum_average_diversity,
            detail=(
                "Average visual diversity is below the recipe baseline of "
                f"{round(policy.minimum_average_diversity * 100)}%."
            ),
            current=round(average_diversity, 3),
            target=policy.minimum_average_diversity,
        ),
    ]
    failed_blockers = [
        check for check in checks if not check.passed and check.severity == "blocker"
    ]
    failed_warnings = [
        check for check in checks if not check.passed and check.severity == "warning"
    ]
    score = sum(check.passed for check in checks) / len(checks)
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
        score=score,
        blocker_count=len(failed_blockers),
        warning_count=len(failed_warnings),
        checks=checks,
    )


def _snapshot_fingerprint(snapshot: DatasetSnapshot) -> str:
    approved = [
        {
            "id": item.id,
            "source_media_item_id": item.source_media_item_id,
            "training_media_item_id": item.training_media_item_id,
            "crop_recipe_id": item.crop_recipe_id,
            "caption": item.caption,
            "tags": item.tags,
        }
        for item in sorted(snapshot.items.values(), key=lambda item: item.id)
        if item.status == DatasetItemStatus.APPROVED
    ]
    canonical = json.dumps(
        {
            "project_id": snapshot.project_id,
            "version": snapshot.version,
            "intent": snapshot.intent.model_dump(mode="json"),
            "training_target": snapshot.training_target.model_dump(mode="json"),
            "items": approved,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_write_text(path: Path, value: str) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(value, encoding="utf-8")
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
