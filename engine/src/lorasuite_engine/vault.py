import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from lorasuite_engine.models import (
    AssetRole,
    DerivativeType,
    MediaItem,
    MediaSource,
    MediaType,
    SourceKind,
)

SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
SUPPORTED_AUDIO_SUFFIXES = frozenset({".aac", ".m4a", ".mp3", ".wav"})
SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})


class LocalImportError(BaseModel):
    path: str
    code: str
    message: str


class LocalImportResult(BaseModel):
    media_items: list[MediaItem] = Field(default_factory=list)
    errors: list[LocalImportError] = Field(default_factory=list)


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
    with Image.open(path) as image:
        image.verify()

    with Image.open(path) as image:
        return image.width, image.height


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
                result.media_items.append(existing_media_item)
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

        if source is not None and new_media_items:
            self._write_manifest(manifest, source, new_media_items)

        return result

    def list_media_items(self) -> list[MediaItem]:
        manifest = self._read_manifest()
        return [
            MediaItem.model_validate(media_item_json)
            for media_item_json in manifest.get("media_items", [])
        ]

    def get_media_item(self, media_item_id: str) -> MediaItem | None:
        for media_item in self.list_media_items():
            if media_item.id == media_item_id:
                return media_item
        return None

    def append_media_items(self, media_items: list[MediaItem]) -> None:
        if not media_items:
            return
        manifest = self._read_manifest()
        media_items_json = manifest.setdefault("media_items", [])
        existing_ids = {
            item.get("id")
            for item in media_items_json
            if isinstance(item, dict)
        }
        for media_item in media_items:
            if media_item.id not in existing_ids:
                media_items_json.append(media_item.model_dump(mode="json"))
                existing_ids.add(media_item.id)
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

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
                "asset_role": AssetRole.DERIVATIVE,
                "derivative_type": derivative_type,
                "source_media_item_id": source_item.id,
                **(metadata or {}),
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
                    f"image could not be read by Pillow: {exc}",
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
        raw_path = self._copy_to_raw(validated.path, sha256)

        return MediaItem(
            source_id=source_id,
            raw_path=raw_path,
            media_type=validated.media_type,
            sha256=sha256,
            width=validated.width,
            height=validated.height,
            metadata_json={"original_path": str(validated.path)},
        )

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
        self, manifest: dict[str, Any], source: MediaSource, media_items: list[MediaItem]
    ) -> None:
        sources = manifest.setdefault("sources", [])
        media_items_json = manifest.setdefault("media_items", [])
        sources.append(source.model_dump(mode="json"))
        media_items_json.extend(
            media_item.model_dump(mode="json") for media_item in media_items
        )
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _read_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"sources": [], "media_items": []}

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("sources", [])
        manifest.setdefault("media_items", [])
        return manifest

    def _media_items_by_sha(self, manifest: dict[str, Any]) -> dict[str, MediaItem]:
        media_items_by_sha: dict[str, MediaItem] = {}
        for media_item_json in manifest.get("media_items", []):
            media_item = MediaItem.model_validate(media_item_json)
            media_items_by_sha.setdefault(media_item.sha256, media_item)
        return media_items_by_sha

    def _error(self, path: Path, code: str, message: str) -> LocalImportError:
        return LocalImportError(path=str(path), code=code, message=message)
