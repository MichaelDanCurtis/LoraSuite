import json
import shutil
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

from PIL import Image

from lorasuite_engine.models import MediaItem, MediaSource, MediaType, SourceKind

SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})


def detect_media_type(path: Path) -> MediaType | None:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return MediaType.IMAGE
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

    def import_local_paths(self, paths: Iterable[Path]) -> list[MediaItem]:
        imports = [
            (Path(path), media_type)
            for path in paths
            if (media_type := detect_media_type(Path(path))) is not None
        ]
        if not imports:
            return []

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        source = MediaSource(kind=SourceKind.LOCAL, download_tool="local-import")
        media_items = [
            self._import_local_path(path, media_type, source_id=source.id)
            for path, media_type in imports
        ]
        self._write_manifest(source, media_items)
        return media_items

    def _import_local_path(
        self, path: Path, media_type: MediaType, *, source_id: str
    ) -> MediaItem:
        digest = sha256_file(path)
        raw_path = self.raw_dir / f"{digest}{path.suffix.lower()}"
        if path.resolve() != raw_path.resolve():
            shutil.copy2(path, raw_path)

        width: int | None = None
        height: int | None = None
        if media_type == MediaType.IMAGE:
            width, height = image_dimensions(path)

        return MediaItem(
            source_id=source_id,
            raw_path=raw_path,
            media_type=media_type,
            sha256=digest,
            width=width,
            height=height,
            metadata_json={"original_path": str(path)},
        )

    def _write_manifest(
        self, source: MediaSource, media_items: list[MediaItem]
    ) -> None:
        manifest = self._read_manifest()
        manifest["sources"].append(source.model_dump(mode="json"))
        manifest["media_items"].extend(
            media_item.model_dump(mode="json") for media_item in media_items
        )
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _read_manifest(self) -> dict[str, list[dict]]:
        if not self.manifest_path.exists():
            return {"sources": [], "media_items": []}

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {
            "sources": list(manifest.get("sources", [])),
            "media_items": list(manifest.get("media_items", [])),
        }
