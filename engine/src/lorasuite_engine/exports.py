import json
import shutil
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from PIL import UnidentifiedImageError

from lorasuite_engine.models import ExportPackage, ExportType
from lorasuite_engine.vault import image_dimensions, sha256_file


ALLOWED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
CREATED_BY = "LoraSuite"


def create_runcomfy_image_export(
    frames: list[Path],
    output_dir: Path,
    caption_template: str,
    source_segment_ids: list[str],
) -> ExportPackage:
    frame_paths = [Path(frame) for frame in frames]
    _validate_frame_paths(frame_paths)

    output_path = Path(output_dir)
    _validate_output_dir(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = Path(
        mkdtemp(
            prefix=f".{output_path.name or 'export'}.staging.",
            dir=output_path.parent,
        )
    )
    moved_to_output = False

    try:
        images_dir = staged_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        exported_files: list[dict[str, str]] = []
        for index, frame in enumerate(frame_paths, start=1):
            suffix = frame.suffix.lower()
            basename = f"{index:06d}"
            staged_image = images_dir / f"{basename}{suffix}"
            staged_caption = images_dir / f"{basename}.txt"
            final_image = output_path / "images" / staged_image.name
            final_caption = output_path / "images" / staged_caption.name

            shutil.copy2(frame, staged_image)
            staged_caption.write_text(
                caption_template.rstrip() + "\n",
                encoding="utf-8",
            )
            exported_files.append(
                {
                    "image": str(final_image),
                    "caption": str(final_caption),
                    "sha256": sha256_file(staged_image),
                }
            )

        package = ExportPackage(
            export_type=ExportType.RUNCOMFY_IMAGE,
            output_path=output_path,
            manifest_path=output_path / "manifest.json",
            source_segment_ids=list(source_segment_ids),
            status="complete",
        )
        manifest = {
            "created_by": CREATED_BY,
            "export_id": package.id,
            "export_type": package.export_type.value,
            "status": package.status,
            "source_segment_ids": package.source_segment_ids,
            "files": exported_files,
        }
        (staged_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        (staged_path / "export_report.md").write_text(
            "# RunComfy AI Toolkit Image Export\n\n"
            f"- Status: {package.status}\n"
            f"- Images: {len(exported_files)}\n"
            "- Captions: one .txt file per image with matching basename\n",
            encoding="utf-8",
        )

        _replace_directory(staged_path, output_path)
        moved_to_output = True
        return package
    finally:
        if not moved_to_output and staged_path.exists():
            shutil.rmtree(staged_path)


def _validate_frame_paths(frames: list[Path]) -> None:
    if not frames:
        raise ValueError("At least one frame is required for RunComfy image export")

    seen_frames: set[Path] = set()
    for frame in frames:
        suffix = frame.suffix.lower()
        if suffix == ".webp":
            raise ValueError("WebP is not supported for RunComfy AI Toolkit image export")
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image suffix for RunComfy export: {suffix}")
        if not frame.exists():
            raise ValueError(f"Frame does not exist: {frame}")
        if not frame.is_file():
            raise ValueError(f"Frame is not a file: {frame}")

        frame_identity = frame.resolve()
        if frame_identity in seen_frames:
            raise ValueError(f"Duplicate frame path: {frame}")
        seen_frames.add(frame_identity)

        try:
            image_dimensions(frame)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise ValueError(f"Frame image could not be read: {frame}") from exc


def _validate_output_dir(output_path: Path) -> None:
    if output_path.exists() and not output_path.is_dir():
        raise ValueError(f"output_dir exists and is not a directory: {output_path}")
    if not output_path.exists() or _directory_is_empty(output_path):
        return
    if _is_lorasuite_runcomfy_export(output_path):
        return
    raise ValueError(
        f"output_dir is non-empty and is not a LoraSuite RunComfy export: {output_path}"
    )


def _directory_is_empty(path: Path) -> bool:
    return next(path.iterdir(), None) is None


def _is_lorasuite_runcomfy_export(path: Path) -> bool:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    return (
        manifest.get("created_by") == CREATED_BY
        and manifest.get("export_type") == ExportType.RUNCOMFY_IMAGE.value
    )


def _replace_directory(staged_path: Path, output_path: Path) -> None:
    if not output_path.exists():
        staged_path.replace(output_path)
        return

    backup_path = output_path.with_name(f".{output_path.name}.backup.{uuid4().hex}")
    output_path.replace(backup_path)
    try:
        staged_path.replace(output_path)
    except Exception:
        if not output_path.exists() and backup_path.exists():
            backup_path.replace(output_path)
        raise
    finally:
        if backup_path.exists():
            shutil.rmtree(backup_path)
