from __future__ import annotations

import json
from pathlib import Path

from lorasuite_engine.ingress import IngressService, curation_metadata_for_candidate
from lorasuite_engine.models import (
    CurationBundleItem,
    CurationHandoff,
    CurationHandoffItem,
    CurationLane,
    CurationReviewStatus,
    CurationSourceBundle,
    MediaItem,
    MediaStatus,
    RequestedOutput,
    SpeakerConfirmation,
    SourceKind,
    utc_now,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService


class CurationService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def handoff_path(self) -> Path:
        return self.vault_root / "curation_handoff.json"

    def list_source_bundles(self) -> list[CurationSourceBundle]:
        self._backfill_ingress_metadata()
        media_items = [
            item
            for item in VaultService(self.vault_root).list_media_items()
            if item.status != MediaStatus.IGNORED
        ]
        media_by_id = {item.id: item for item in media_items}
        grouped: dict[str, list[MediaItem]] = {}

        for item in media_items:
            root = _root_item(item, media_by_id)
            bundle_key = _bundle_key(item, root)
            grouped.setdefault(bundle_key, []).append(item)

        bundles = [
            _build_bundle(bundle_key, items, media_by_id)
            for bundle_key, items in grouped.items()
        ]
        return sorted(bundles, key=lambda bundle: bundle.title.casefold())

    def _backfill_ingress_metadata(self) -> int:
        ingress = IngressService(self.vault_root)
        candidates = ingress.list_candidates()
        if not candidates:
            return 0
        candidates_by_id = {candidate.id: candidate for candidate in candidates}
        candidates_by_path = {
            str(Path(local_path)): candidate
            for candidate in candidates
            for local_path in [candidate.metadata_json.get("local_import_path")]
            if isinstance(local_path, str) and local_path
        }
        vault = VaultService(self.vault_root)
        updated_count = 0
        for media_item in vault.list_media_items():
            if media_item.metadata_json.get("ingress_candidate_id"):
                continue
            original_path = media_item.metadata_json.get("original_path")
            if not isinstance(original_path, str) or not original_path:
                continue
            original = Path(original_path)
            candidate = candidates_by_path.get(str(original))
            if candidate is None:
                candidate_id = original.name.split(".", 1)[0]
                candidate = candidates_by_id.get(candidate_id)
            if candidate is None:
                continue
            vault.annotate_media_item(
                media_item.id,
                metadata=curation_metadata_for_candidate(candidate),
                duration=candidate.duration,
                width=candidate.width,
                height=candidate.height,
            )
            updated_count += 1
        return updated_count

    def get_handoff(
        self,
        project_id: str | None = None,
        requested_output: RequestedOutput | None = None,
    ) -> CurationHandoff:
        with json_file_lock(self.handoff_path):
            handoff = self._read_handoff_unlocked()
            return _scoped_handoff(handoff, project_id, requested_output)

    def add_to_handoff(
        self,
        media_item_ids: list[str],
        *,
        project_id: str | None = None,
        requested_output: RequestedOutput | None = None,
    ) -> CurationHandoff:
        media_by_id = {
            item.id: item for item in VaultService(self.vault_root).list_media_items()
        }
        unknown_ids = set(media_item_ids).difference(media_by_id)
        if unknown_ids:
            raise ValueError(f"media item not found: {sorted(unknown_ids)[0]}")

        with json_file_lock(self.handoff_path):
            handoff = self._read_handoff_unlocked()
            items_by_scope = {
                _handoff_item_key(
                    item.media_item_id,
                    item.project_id,
                    item.requested_output,
                ): item
                for item in handoff.items
            }
            for media_item_id in media_item_ids:
                media_item = media_by_id[media_item_id]
                item_key = _handoff_item_key(
                    media_item_id,
                    project_id,
                    requested_output,
                )
                items_by_scope.setdefault(
                    item_key,
                    CurationHandoffItem(
                        media_item_id=media_item_id,
                        lane=CurationLane(media_item.media_type.value),
                        project_id=project_id,
                        requested_output=requested_output,
                    ),
                )
            handoff.items = list(items_by_scope.values())
            handoff.updated_at = utc_now()
            self._write_handoff_unlocked(handoff)
        return _scoped_handoff(handoff, project_id, requested_output)

    def update_review_status(
        self,
        media_item_id: str,
        review_status: CurationReviewStatus,
        *,
        project_id: str | None = None,
        requested_output: RequestedOutput | None = None,
        speaker_confirmation: SpeakerConfirmation | None = None,
    ) -> CurationHandoff:
        with json_file_lock(self.handoff_path):
            handoff = self._read_handoff_unlocked()
            item = next(
                (
                    candidate
                    for candidate in handoff.items
                    if candidate.media_item_id == media_item_id
                    and _scope_matches(candidate, project_id, requested_output)
                ),
                None,
            )
            if item is None:
                raise KeyError(media_item_id)
            item.review_status = review_status
            item.speaker_confirmation = (
                speaker_confirmation
                if review_status == CurationReviewStatus.ACCEPTED
                else None
            )
            item.updated_at = utc_now()
            handoff.updated_at = utc_now()
            self._write_handoff_unlocked(handoff)
        return _scoped_handoff(handoff, project_id, requested_output)

    def reject_media_items(self, media_item_ids: list[str]) -> list[MediaItem]:
        updated_items = VaultService(self.vault_root).update_media_status(
            media_item_ids,
            MediaStatus.IGNORED,
        )
        rejected_ids = {item.id for item in updated_items}
        with json_file_lock(self.handoff_path):
            handoff = self._read_handoff_unlocked()
            handoff_changed = False
            for item in handoff.items:
                if item.media_item_id in rejected_ids:
                    item.review_status = CurationReviewStatus.REJECTED
                    item.updated_at = utc_now()
                    handoff_changed = True
            if handoff_changed:
                handoff.updated_at = utc_now()
                self._write_handoff_unlocked(handoff)
        return updated_items

    def restore_audio_items(self, media_item_ids: list[str]) -> list[MediaItem]:
        vault = VaultService(self.vault_root)
        media_by_id = {item.id: item for item in vault.list_media_items()}
        missing_ids = set(media_item_ids).difference(media_by_id)
        if missing_ids:
            raise KeyError(sorted(missing_ids)[0])
        non_audio = [
            media_item_id
            for media_item_id in media_item_ids
            if media_by_id[media_item_id].media_type.value != "audio"
        ]
        if non_audio:
            raise ValueError("only audio items can override source audio rejection")

        restored = [
            vault.annotate_media_item(
                media_item_id,
                metadata={"audio_review_override": "keep"},
            )
            for media_item_id in media_item_ids
        ]
        ignored_ids = [item.id for item in restored if item.status == MediaStatus.IGNORED]
        if ignored_ids:
            restored_by_id = {item.id: item for item in restored}
            restored_by_id.update(
                {
                    item.id: item
                    for item in vault.update_media_status(ignored_ids, MediaStatus.REVIEWED)
                }
            )
            restored = [restored_by_id[media_item_id] for media_item_id in media_item_ids]
        restored_ids = {item.id for item in restored}
        with json_file_lock(self.handoff_path):
            handoff = self._read_handoff_unlocked()
            handoff_changed = False
            for item in handoff.items:
                if (
                    item.media_item_id in restored_ids
                    and item.review_status == CurationReviewStatus.REJECTED
                ):
                    item.review_status = CurationReviewStatus.PENDING
                    item.updated_at = utc_now()
                    handoff_changed = True
            if handoff_changed:
                handoff.updated_at = utc_now()
                self._write_handoff_unlocked(handoff)
        return restored

    def _read_handoff_unlocked(self) -> CurationHandoff:
        if not self.handoff_path.exists():
            return CurationHandoff()
        handoff = CurationHandoff.model_validate(
            json.loads(self.handoff_path.read_text(encoding="utf-8"))
        )
        if self._adopt_unscoped_handoff_items(handoff):
            handoff.updated_at = utc_now()
            self._write_handoff_unlocked(handoff)
        return handoff

    def _write_handoff_unlocked(self, handoff: CurationHandoff) -> None:
        atomic_write_json(self.handoff_path, handoff.model_dump(mode="json"))

    def _adopt_unscoped_handoff_items(self, handoff: CurationHandoff) -> bool:
        legacy_items = [item for item in handoff.items if item.project_id is None]
        if not legacy_items:
            return False
        # A legacy global handoff can be claimed safely only when there is one
        # project. With multiple projects, leaving it unscoped prevents it from
        # silently appearing in the wrong project.
        from lorasuite_engine.dataset_projects import CharacterProjectService

        projects = CharacterProjectService(self.vault_root).list_projects()
        if len(projects) != 1:
            return False
        project = projects[0]
        for item in legacy_items:
            item.project_id = project.id
            item.requested_output = _legacy_requested_output(item.lane, project.intent.requested_outputs)
            item.updated_at = utc_now()
        return True


def _root_item(item: MediaItem, media_by_id: dict[str, MediaItem]) -> MediaItem:
    current = item
    visited: set[str] = set()
    while current.id not in visited:
        visited.add(current.id)
        parent_id = current.metadata_json.get("source_media_item_id")
        if not isinstance(parent_id, str) or parent_id not in media_by_id:
            return current
        current = media_by_id[parent_id]
    return current


def _bundle_key(item: MediaItem, root: MediaItem) -> str:
    for candidate in (item, root):
        bundle_key = candidate.metadata_json.get("source_bundle_key")
        if isinstance(bundle_key, str) and bundle_key:
            return bundle_key
    return f"media:{root.id}"


def _build_bundle(
    bundle_key: str,
    media_items: list[MediaItem],
    media_by_id: dict[str, MediaItem],
) -> CurationSourceBundle:
    roots = {_root_item(item, media_by_id).id for item in media_items}
    ordered_items = sorted(media_items, key=lambda item: (item.media_type.value, item.id))
    representative = next(
        (item for item in ordered_items if item.id in roots),
        ordered_items[0],
    )
    metadata = representative.metadata_json
    source_kind = _source_kind(metadata.get("source_kind"))
    title = _string_metadata(metadata.get("display_name")) or representative.raw_path.name
    source_locator = _string_metadata(metadata.get("source_locator"))
    lanes = sorted(
        {CurationLane(item.media_type.value) for item in ordered_items},
        key=lambda lane: ("image", "video", "audio").index(lane.value),
    )
    return CurationSourceBundle(
        id=bundle_key,
        title=title,
        source_kind=source_kind,
        source_locator=source_locator,
        root_media_item_ids=sorted(roots),
        intent_lanes=lanes,
        items=[
            CurationBundleItem(
                media_item_id=item.id,
                lane=CurationLane(item.media_type.value),
                role=_string_metadata(item.metadata_json.get("asset_role")) or "source",
                source_media_item_id=_string_metadata(
                    item.metadata_json.get("source_media_item_id")
                ),
                derivative_type=_string_metadata(
                    item.metadata_json.get("derivative_type")
                ),
            )
            for item in ordered_items
        ],
    )


def _source_kind(value: object) -> SourceKind | None:
    try:
        return SourceKind(str(value)) if value is not None else None
    except ValueError:
        return None


def _string_metadata(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _handoff_item_key(
    media_item_id: str,
    project_id: str | None,
    requested_output: RequestedOutput | None,
) -> tuple[str | None, str | None, str]:
    return (
        project_id,
        requested_output.value if requested_output is not None else None,
        media_item_id,
    )


def _scope_matches(
    item: CurationHandoffItem,
    project_id: str | None,
    requested_output: RequestedOutput | None,
) -> bool:
    if project_id is not None and item.project_id != project_id:
        return False
    if requested_output is not None and item.requested_output != requested_output:
        return False
    return True


def _scoped_handoff(
    handoff: CurationHandoff,
    project_id: str | None,
    requested_output: RequestedOutput | None,
) -> CurationHandoff:
    if project_id is None and requested_output is None:
        return handoff
    return CurationHandoff(
        items=[
            item
            for item in handoff.items
            if _scope_matches(item, project_id, requested_output)
        ],
        updated_at=handoff.updated_at,
    )


def _legacy_requested_output(
    lane: CurationLane,
    requested_outputs: list[RequestedOutput],
) -> RequestedOutput:
    if len(requested_outputs) == 1:
        return requested_outputs[0]
    if lane == CurationLane.AUDIO:
        return (
            RequestedOutput.VOICE
            if RequestedOutput.VOICE in requested_outputs
            else RequestedOutput.ID_LORA
        )
    if lane == CurationLane.VIDEO:
        return (
            RequestedOutput.VIDEO
            if RequestedOutput.VIDEO in requested_outputs
            else RequestedOutput.ID_LORA
        )
    return (
        RequestedOutput.IMAGE
        if RequestedOutput.IMAGE in requested_outputs
        else requested_outputs[0] if requested_outputs else RequestedOutput.IMAGE
    )
