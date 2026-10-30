import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from lorasuite_engine.models import (
    AssetRole,
    DerivativeType,
    MediaItem,
    MediaStatus,
    MediaSource,
    MediaType,
    SourceKind,
)
from lorasuite_engine.raw_images import (
    RAW_IMAGE_SUFFIXES,
    is_raw_image,
    materialize_raw_image,
    raw_image_dimensions,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock

SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"}) | RAW_IMAGE_SUFFIXES
SUPPORTED_AUDIO_SUFFIXES = frozenset({".aac", ".m4a", ".mp3", ".wav"})
SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})


class LocalImportError(BaseModel):
    path: str
    code: str
    message: str


class LocalImportResult(BaseModel):
    media_items: list[MediaItem] = Field(default_factory=list)
    errors: list[LocalImportError] = Field(default_factory=list)


class ExactDuplicateCluster(BaseModel):
    id: str
    media_type: MediaType
    sha256: str
    canonical_media_item_id: str
    canonical_raw_path: Path
    duplicate_count: int
    media_item_ids: list[str] = Field(default_factory=list)
    source_bundle_keys: list[str] = Field(default_factory=list)
    original_paths: list[str] = Field(default_factory=list)
    origins: list[dict[str, Any]] = Field(default_factory=list)


class VaultMediaPage(BaseModel):
    items: list[MediaItem] = Field(default_factory=list)
    offset: int
    limit: int
    total: int
    has_more: bool
    next_offset: int | None = None
    snapshot: str


class VaultSnapshotConflict(ValueError):
    pass


@dataclass(frozen=True)
class _ValidatedLocalPath:
    path: Path
    media_type: MediaType
    width: int | None = None
    height: int | None = None


def detect_media_type(path: Path) -> MediaType | None:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return MediaType.IMAGE
    if suffix in SUPPORTED_AUDIO_SUFFIXES:
        return MediaType.AUDIO
    if suffix in SUPPORTED_VIDEO_SUFFIXES:
        return MediaType.VIDEO
    return None


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int, int]:
    if is_raw_image(path):
        return raw_image_dimensions(path)
    with Image.open(path) as image:
        image.verify()

    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        return oriented.width, oriented.height


class VaultService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def raw_dir(self) -> Path:
        return self.vault_root / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.vault_root / "vault.json"

    def import_local_paths(self, paths: Iterable[Path]) -> LocalImportResult:
        result = LocalImportResult()
        manifest = self._read_manifest()
        media_items_by_sha = self._media_items_by_sha(manifest)
        new_media_items: list[MediaItem] = []
        updated_media_items: dict[str, MediaItem] = {}
        source: MediaSource | None = None

        for path_like in paths:
            validated = self._validate_local_path(Path(path_like))
            if isinstance(validated, LocalImportError):
                result.errors.append(validated)
                continue

            try:
                digest = sha256_file(validated.path)
            except OSError as exc:
                result.errors.append(
                    self._error(
                        validated.path,
                        "read_failed",
                        f"could not read file: {exc.strerror or exc}",
                    )
                )
                continue

            existing_media_item = media_items_by_sha.get(digest)
            if existing_media_item is not None:
                updated = _merge_local_duplicate_path(existing_media_item, validated.path)
                result.media_items.append(updated)
                media_items_by_sha[digest] = updated
                if updated != existing_media_item:
                    updated_media_items[updated.id] = updated
                continue

            if source is None:
                source = MediaSource(kind=SourceKind.LOCAL, download_tool="local-import")

            try:
                media_item = self._import_validated_path(
                    validated, sha256=digest, source_id=source.id
                )
            except OSError as exc:
                result.errors.append(
                    self._error(
                        validated.path,
                        "copy_failed",
                        f"could not copy file: {exc.strerror or exc}",
                    )
                )
                continue

            new_media_items.append(media_item)
            result.media_items.append(media_item)
            media_items_by_sha[digest] = media_item

        if new_media_items or updated_media_items:
            self._write_manifest(
                manifest,
                source,
                new_media_items,
                list(updated_media_items.values()),
            )

        return result

    def list_media_items(self) -> list[MediaItem]:
        manifest = self._read_manifest()
        return [
            MediaItem.model_validate(media_item_json)
            for media_item_json in manifest.get("media_items", [])
        ]

    def query_media_items(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        media_type: MediaType | None = None,
        status: MediaStatus | None = None,
        search: str | None = None,
        include_ignored: bool = False,
        snapshot: str | None = None,
    ) -> VaultMediaPage:
        with json_file_lock(self.manifest_path):
            manifest = self._read_manifest_unlocked()
            payloads = [
                payload
                for payload in manifest.get("media_items", [])
                if isinstance(payload, dict)
            ]
            current_snapshot = _media_snapshot(payloads)
            if snapshot is not None and snapshot != current_snapshot:
                raise VaultSnapshotConflict(
                    "Vault media changed while this page set was loading; restart from the first page."
                )

            normalized_search = (search or "").strip().casefold()
            filtered: list[MediaItem] = []
            for payload in payloads:
                item = MediaItem.model_validate(payload)
                if not include_ignored and item.status == MediaStatus.IGNORED:
                    continue
                if media_type is not None and item.media_type != media_type:
                    continue
                if status is not None and item.status != status:
                    continue
                if normalized_search and normalized_search not in _searchable_media_text(item):
                    continue
                filtered.append(item)

            total = len(filtered)
            items = filtered[offset : offset + limit]
            next_offset = offset + len(items)
            has_more = next_offset < total
            return VaultMediaPage(
                items=items,
                offset=offset,
                limit=limit,
                total=total,
                has_more=has_more,
                next_offset=next_offset if has_more else None,
                snapshot=current_snapshot,
            )

    def get_media_item(self, media_item_id: str) -> MediaItem | None:
        for media_item in self.list_media_items():
            if media_item.id == media_item_id:
                return media_item
        return None

    def append_media_items(self, media_items: list[MediaItem]) -> list[MediaItem]:
        if not media_items:
            return []
        with json_file_lock(self.manifest_path):
            manifest = self._read_manifest_unlocked()
            media_items_json = manifest.setdefault("media_items", [])
            existing_by_id: dict[str, tuple[int, MediaItem]] = {}
            existing_by_content: dict[tuple[MediaType, str], tuple[int, MediaItem]] = {}
            for index, payload in enumerate(media_items_json):
                if not isinstance(payload, dict):
                    continue
                existing = MediaItem.model_validate(payload)
                existing_by_id[existing.id] = (index, existing)
                content_key = _source_content_key(existing)
                if content_key is not None:
                    existing_by_content.setdefault(content_key, (index, existing))

            resolved: list[MediaItem] = []
            changed = False
            for media_item in media_items:
                by_id = existing_by_id.get(media_item.id)
                if by_id is not None:
                    resolved.append(by_id[1])
                    continue
                content_key = _source_content_key(media_item)
                by_content = existing_by_content.get(content_key) if content_key else None
                if by_content is not None:
                    index, canonical = by_content
                    merged = _merge_exact_duplicate_media_item(canonical, media_item)
                    media_items_json[index] = merged.model_dump(mode="json")
                    existing_by_id[merged.id] = (index, merged)
                    existing_by_content[content_key] = (index, merged)
                    resolved.append(merged)
                    changed = changed or merged != canonical
                    continue

                index = len(media_items_json)
                media_items_json.append(media_item.model_dump(mode="json"))
                existing_by_id[media_item.id] = (index, media_item)
                if content_key is not None:
                    existing_by_content[content_key] = (index, media_item)
                resolved.append(media_item)
                changed = True
            if changed:
                atomic_write_json(self.manifest_path, manifest)
            return resolved

    def list_exact_duplicate_clusters(self) -> list[ExactDuplicateCluster]:
        media_items = self.list_media_items()
        groups: dict[tuple[MediaType, str], list[MediaItem]] = {}
        for item in media_items:
            content_key = _source_content_key(item)
            if content_key is not None:
                groups.setdefault(content_key, []).append(item)

        clusters: list[ExactDuplicateCluster] = []
        for (media_type, digest), items in groups.items():
            ordered = sorted(items, key=lambda item: (item.created_at, item.id))
            canonical = ordered[0]
            origins = _duplicate_origins_for_items(ordered)
            original_paths = _original_paths_for_items(ordered)
            duplicate_count = max(len(ordered) - 1, len(origins), len(original_paths) - 1)
            if duplicate_count <= 0:
                continue
            bundle_keys = sorted(
                {
                    key
                    for item in ordered
                    for key in _source_bundle_keys(item.metadata_json)
                }
            )
            clusters.append(
                ExactDuplicateCluster(
                    id=f"duplicate_{digest[:24]}",
                    media_type=media_type,
                    sha256=digest,
                    canonical_media_item_id=canonical.id,
                    canonical_raw_path=canonical.raw_path,
                    duplicate_count=duplicate_count,
                    media_item_ids=[item.id for item in ordered],
                    source_bundle_keys=bundle_keys,
                    original_paths=original_paths,
                    origins=origins,
                )
            )
        return sorted(clusters, key=lambda cluster: (-cluster.duplicate_count, cluster.id))

    def annotate_media_item(
        self,
        media_item_id: str,
        *,
        metadata: dict[str, Any],
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> MediaItem:
        with json_file_lock(self.manifest_path):
            manifest = self._read_manifest_unlocked()
            for index, payload in enumerate(manifest.get("media_items", [])):
                if not isinstance(payload, dict) or payload.get("id") != media_item_id:
                    continue
                item = MediaItem.model_validate(payload)
                item.metadata_json = _merge_provenance_metadata(
                    item.metadata_json,
                    metadata,
                )
                if duration is not None:
                    item.duration = duration
                if width is not None:
                    item.width = width
                if height is not None:
                    item.height = height
                manifest["media_items"][index] = item.model_dump(mode="json")
                atomic_write_json(self.manifest_path, manifest)
                return item
        raise KeyError(media_item_id)

    def rotate_image(self, media_item_id: str, degrees: int = 90) -> MediaItem:
        if degrees not in {90, 180, 270}:
            raise ValueError("image rotation must be 90, 180, or 270 degrees")
        with json_file_lock(self.manifest_path):
            manifest = self._read_manifest_unlocked()
            for index, payload in enumerate(manifest.get("media_items", [])):
                if not isinstance(payload, dict) or payload.get("id") != media_item_id:
                    continue
                item = MediaItem.model_validate(payload)
                if item.media_type != MediaType.IMAGE:
                    raise ValueError("only image media can be rotated")
                try:
                    with Image.open(item.raw_path) as source:
                        oriented = ImageOps.exif_transpose(source)
                        rotated = oriented.rotate(-degrees, expand=True)
                        if rotated.mode not in {"RGB", "RGBA", "L", "LA"}:
                            rotated = rotated.convert("RGBA")
                        self.raw_dir.mkdir(parents=True, exist_ok=True)
                        temporary_path = self.raw_dir / f".{media_item_id}.{uuid4().hex}.png"
                        rotated.save(temporary_path, format="PNG", optimize=True)
                except (OSError, UnidentifiedImageError) as error:
                    raise ValueError(f"image could not be rotated: {error}") from error

                try:
                    digest = sha256_file(temporary_path)
                    rotated_path = self.raw_dir / f"{digest}.png"
                    if rotated_path.exists():
                        temporary_path.unlink(missing_ok=True)
                    else:
                        temporary_path.replace(rotated_path)
                    item.raw_path = rotated_path
                    item.sha256 = digest
                    item.width, item.height = image_dimensions(rotated_path)
                    previous_rotation = item.metadata_json.get("rotation_degrees", 0)
                    try:
                        accumulated_rotation = (int(previous_rotation) + degrees) % 360
                    except (TypeError, ValueError):
                        accumulated_rotation = degrees
                    item.metadata_json = {
                        **item.metadata_json,
                        "rotation_degrees": accumulated_rotation,
                        "orientation_corrected": True,
                    }
                    manifest["media_items"][index] = item.model_dump(mode="json")
                    atomic_write_json(self.manifest_path, manifest)
                    return item
                finally:
                    temporary_path.unlink(missing_ok=True)
        raise KeyError(media_item_id)

    def update_media_status(
        self,
        media_item_ids: list[str],
        status: MediaStatus,
    ) -> list[MediaItem]:
        requested_ids = set(media_item_ids)
        if not requested_ids:
            return []
        with json_file_lock(self.manifest_path):
            manifest = self._read_manifest_unlocked()
            updated_items: list[MediaItem] = []
            for index, payload in enumerate(manifest.get("media_items", [])):
                if not isinstance(payload, dict) or payload.get("id") not in requested_ids:
                    continue
                item = MediaItem.model_validate(payload)
                item.status = status
                manifest["media_items"][index] = item.model_dump(mode="json")
                updated_items.append(item)
            updated_ids = {item.id for item in updated_items}
            missing_ids = requested_ids.difference(updated_ids)
            if missing_ids:
                raise KeyError(sorted(missing_ids)[0])
            atomic_write_json(self.manifest_path, manifest)
            return updated_items

    def build_derivative_media_item(
        self,
        *,
        source_item: MediaItem,
        derivative_path: Path,
        media_type: MediaType,
        derivative_type: DerivativeType,
        metadata: dict[str, Any] | None = None,
    ) -> MediaItem:
        digest = sha256_file(derivative_path)
        width: int | None = None
        height: int | None = None
        if media_type == MediaType.IMAGE:
            width, height = image_dimensions(derivative_path)
        return MediaItem(
            source_id=source_item.source_id,
            raw_path=derivative_path,
            media_type=media_type,
            sha256=digest,
            width=width,
            height=height,
            metadata_json={
                **(metadata or {}),
                "asset_role": AssetRole.DERIVATIVE,
                "derivative_type": derivative_type,
                "source_media_item_id": source_item.id,
            },
        )

    def _validate_local_path(self, path: Path) -> _ValidatedLocalPath | LocalImportError:
        if not path.exists():
            return self._error(path, "missing_path", "path does not exist")
        if not path.is_file():
            return self._error(path, "not_file", "path is not a file")

        media_type = detect_media_type(path)
        if media_type is None:
            return self._error(path, "unsupported_suffix", "suffix is not supported")

        width: int | None = None
        height: int | None = None
        if media_type == MediaType.IMAGE:
            try:
                width, height = image_dimensions(path)
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                return self._error(
                    path,
                    "unreadable_image",
                    f"image could not be decoded: {exc}",
                )

        return _ValidatedLocalPath(
            path=path,
            media_type=media_type,
            width=width,
            height=height,
        )

    def _import_validated_path(
        self, validated: _ValidatedLocalPath, *, sha256: str, source_id: str
    ) -> MediaItem:
        normalized_from_raw = is_raw_image(validated.path)
        raw_path = (
            self._normalize_raw_to_vault(validated.path)
            if normalized_from_raw
            else self._copy_to_raw(validated.path, sha256)
        )
        stored_sha256 = sha256_file(raw_path) if normalized_from_raw else sha256
        width, height = (
            image_dimensions(raw_path)
            if normalized_from_raw
            else (validated.width, validated.height)
        )

        return MediaItem(
            source_id=source_id,
            raw_path=raw_path,
            media_type=validated.media_type,
            sha256=stored_sha256,
            width=width,
            height=height,
            metadata_json={
                "original_path": str(validated.path),
                **(
                    {
                        "original_format": validated.path.suffix.lower(),
                        "source_sha256": sha256,
                        "normalized_from_raw": True,
                    }
                    if normalized_from_raw
                    else {}
                ),
            },
        )

    def _normalize_raw_to_vault(self, path: Path) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.raw_dir / f".raw-{uuid4().hex}.jpg"
        try:
            materialize_raw_image(path, temporary_path)
            digest = sha256_file(temporary_path)
            raw_path = self.raw_dir / f"{digest}.jpg"
            if raw_path.exists():
                return raw_path
            temporary_path.replace(raw_path)
            return raw_path
        finally:
            temporary_path.unlink(missing_ok=True)

    def _copy_to_raw(self, path: Path, digest: str) -> Path:
        raw_path = self.raw_dir / f"{digest}{path.suffix.lower()}"
        if path.resolve() == raw_path.resolve() or raw_path.exists():
            return raw_path

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = raw_path.with_name(f".{raw_path.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(path, temporary_path)
            temporary_path.replace(raw_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return raw_path

    def _write_manifest(
        self,
        manifest: dict[str, Any],
        source: MediaSource | None,
        media_items: list[MediaItem],
        updated_media_items: list[MediaItem] | None = None,
    ) -> None:
        with json_file_lock(self.manifest_path):
            current_manifest = self._read_manifest_unlocked()
            sources = current_manifest.setdefault("sources", [])
            media_items_json = current_manifest.setdefault("media_items", [])
            existing_ids = {
                item.get("id")
                for item in media_items_json
                if isinstance(item, dict)
            }
            if source is not None and media_items:
                sources.append(source.model_dump(mode="json"))
            existing_indexes = {
                item.get("id"): index
                for index, item in enumerate(media_items_json)
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for media_item in updated_media_items or []:
                index = existing_indexes.get(media_item.id)
                if index is not None:
                    media_items_json[index] = media_item.model_dump(mode="json")
            for media_item in media_items:
                if media_item.id not in existing_ids:
                    media_items_json.append(media_item.model_dump(mode="json"))
                    existing_ids.add(media_item.id)
            atomic_write_json(self.manifest_path, current_manifest)

    def _read_manifest(self) -> dict[str, Any]:
        with json_file_lock(self.manifest_path):
            return self._read_manifest_unlocked()

    def _read_manifest_unlocked(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"version": 1, "sources": [], "media_items": []}

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("version", 1)
        manifest.setdefault("sources", [])
        manifest.setdefault("media_items", [])
        return manifest

    def _media_items_by_sha(self, manifest: dict[str, Any]) -> dict[str, MediaItem]:
        media_items_by_sha: dict[str, MediaItem] = {}
        for media_item_json in manifest.get("media_items", []):
            media_item = MediaItem.model_validate(media_item_json)
            media_items_by_sha.setdefault(media_item.sha256, media_item)
            source_sha256 = media_item.metadata_json.get("source_sha256")
            if isinstance(source_sha256, str) and source_sha256:
                media_items_by_sha.setdefault(source_sha256, media_item)
        return media_items_by_sha

    def _error(self, path: Path, code: str, message: str) -> LocalImportError:
        return LocalImportError(path=str(path), code=code, message=message)


def _media_snapshot(payloads: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        payloads,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _searchable_media_text(item: MediaItem) -> str:
    return " ".join(
        (
            item.id,
            item.source_id,
            str(item.raw_path),
            item.media_type.value,
            item.status.value,
            json.dumps(item.metadata_json, sort_keys=True, ensure_ascii=True),
        )
    ).casefold()


def _merge_provenance_metadata(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = {**existing, **incoming}
    existing_keys = existing.get("source_bundle_keys", [])
    bundle_keys = {
        key
        for key in existing_keys
        if isinstance(existing_keys, list) and isinstance(key, str) and key
    }
    for metadata in (existing, incoming):
        bundle_key = metadata.get("source_bundle_key")
        if isinstance(bundle_key, str) and bundle_key:
            bundle_keys.add(bundle_key)
    if bundle_keys:
        merged["source_bundle_keys"] = sorted(bundle_keys)
        merged.setdefault("source_bundle_key", sorted(bundle_keys)[0])

    existing_records = existing.get("ingress_records", [])
    records = list(existing_records) if isinstance(existing_records, list) else []
    record = incoming.get("ingress_record")
    if isinstance(record, dict) and record not in records:
        records.append(record)
    if records:
        merged["ingress_records"] = records
    merged.pop("ingress_record", None)
    return merged


def _source_content_key(item: MediaItem) -> tuple[MediaType, str] | None:
    asset_role = item.metadata_json.get("asset_role")
    derivative_type = item.metadata_json.get("derivative_type")
    if asset_role == AssetRole.DERIVATIVE or str(asset_role) == AssetRole.DERIVATIVE.value:
        return None
    if derivative_type is not None:
        return None
    return item.media_type, item.sha256


def _merge_local_duplicate_path(existing: MediaItem, incoming_path: Path) -> MediaItem:
    existing_paths = _original_paths_for_items([existing])
    incoming = str(incoming_path)
    if incoming in existing_paths:
        return existing
    metadata = dict(existing.metadata_json)
    paths = sorted({*existing_paths, incoming})
    metadata["original_paths"] = paths
    metadata.setdefault("original_path", paths[0])
    origins = _metadata_origins(metadata)
    origin = {"raw_path": incoming, "source_kind": SourceKind.LOCAL.value}
    if origin not in origins:
        origins.append(origin)
    metadata["duplicate_origins"] = origins
    metadata["exact_duplicate_count"] = max(len(origins), len(paths) - 1)
    return existing.model_copy(update={"metadata_json": metadata})


def _merge_exact_duplicate_media_item(
    existing: MediaItem,
    incoming: MediaItem,
) -> MediaItem:
    metadata = dict(existing.metadata_json)
    bundle_keys = sorted(
        {
            *_source_bundle_keys(existing.metadata_json),
            *_source_bundle_keys(incoming.metadata_json),
        }
    )
    if bundle_keys:
        metadata["source_bundle_keys"] = bundle_keys
        metadata.setdefault("source_bundle_key", bundle_keys[0])

    records = _metadata_records(existing.metadata_json)
    for record in _metadata_records(incoming.metadata_json):
        if record not in records:
            records.append(record)
    if records:
        metadata["ingress_records"] = records

    paths = sorted(
        {
            *_original_paths_for_items([existing]),
            *_original_paths_for_items([incoming]),
        }
    )
    if paths:
        metadata["original_paths"] = paths
        metadata.setdefault("original_path", paths[0])

    origins = _metadata_origins(metadata)
    incoming_origin = {
        "media_item_id": incoming.id,
        "raw_path": str(incoming.raw_path),
        "source_id": incoming.source_id,
        "source_bundle_key": incoming.metadata_json.get("source_bundle_key"),
        "source_kind": incoming.metadata_json.get("source_kind"),
        "source_locator": incoming.metadata_json.get("source_locator"),
        "ingress_candidate_id": incoming.metadata_json.get("ingress_candidate_id"),
        "derivative_type": incoming.metadata_json.get("derivative_type"),
        "source_media_item_id": incoming.metadata_json.get("source_media_item_id"),
    }
    incoming_origin = {
        key: value for key, value in incoming_origin.items() if value not in {None, ""}
    }
    if incoming_origin not in origins:
        origins.append(incoming_origin)
    metadata["duplicate_origins"] = origins
    metadata["exact_duplicate_count"] = len(origins)
    return existing.model_copy(update={"metadata_json": metadata})


def _source_bundle_keys(metadata: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    primary = metadata.get("source_bundle_key")
    if isinstance(primary, str) and primary:
        keys.add(primary)
    values = metadata.get("source_bundle_keys")
    if isinstance(values, list):
        keys.update(value for value in values if isinstance(value, str) and value)
    return keys


def _metadata_records(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    records = metadata.get("ingress_records")
    result = [dict(record) for record in records if isinstance(record, dict)] if isinstance(records, list) else []
    record = metadata.get("ingress_record")
    if isinstance(record, dict) and record not in result:
        result.append(dict(record))
    return result


def _metadata_origins(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = metadata.get("duplicate_origins")
    return [dict(value) for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _original_paths_for_items(items: list[MediaItem]) -> list[str]:
    paths: set[str] = set()
    for item in items:
        original = item.metadata_json.get("original_path")
        if isinstance(original, str) and original:
            paths.add(original)
        originals = item.metadata_json.get("original_paths")
        if isinstance(originals, list):
            paths.update(value for value in originals if isinstance(value, str) and value)
    return sorted(paths)


def _duplicate_origins_for_items(items: list[MediaItem]) -> list[dict[str, Any]]:
    origins: list[dict[str, Any]] = []
    canonical_id = items[0].id
    for item in items:
        for origin in _metadata_origins(item.metadata_json):
            if origin not in origins:
                origins.append(origin)
        if item.id == canonical_id:
            continue
        origin = {
            "media_item_id": item.id,
            "raw_path": str(item.raw_path),
            "source_id": item.source_id,
        }
        if origin not in origins:
            origins.append(origin)
    return origins
