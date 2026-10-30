import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from PIL import UnidentifiedImageError

from lorasuite_engine.model_metadata import LoraModelCard, render_model_card_markdown
from lorasuite_engine.models import (
    ExportPackage,
    ExportType,
    VoiceDatasetCompilation,
    VoiceExportTarget,
    VoiceSegmentStatus,
)
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.vault import image_dimensions, sha256_file
from lorasuite_engine.voice_dataset import refresh_voice_dataset_contract


ALLOWED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
CREATED_BY = "LoraSuite"


@dataclass(frozen=True)
class RunComfyDatasetEntry:
    image_path: Path
    caption: str
    dataset_item_id: str
    source_media_item_id: str
    training_media_item_id: str
    crop_recipe_id: str | None = None




def create_runcomfy_dataset_export(
    *,
    entries: list[RunComfyDatasetEntry],
    output_dir: Path,
    snapshot_id: str,
    project_id: str,
    version: int,
    fingerprint: str,
    training_target: dict[str, object] | None = None,
    model_card: dict[str, object] | None = None,
    revision_lineage: dict[str, str] | None = None,
) -> ExportPackage:
    if not entries:
        raise ValueError("At least one approved dataset item is required for export")
    frame_paths = [entry.image_path for entry in entries]
    _validate_frame_paths(frame_paths)
    output_path = _normalize_output_dir(output_dir)
    _validate_output_dir(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = Path(
        mkdtemp(prefix=f".{output_path.name or 'export'}.staging.", dir=output_path.parent)
    )
    moved_to_output = False
    try:
        images_dir = staged_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        exported_files: list[dict[str, str | None]] = []
        for index, entry in enumerate(entries, start=1):
            suffix = entry.image_path.suffix.lower()
            basename = f"{index:06d}"
            staged_image = images_dir / f"{basename}{suffix}"
            staged_caption = images_dir / f"{basename}.txt"
            final_image = output_path / "images" / staged_image.name
            final_caption = output_path / "images" / staged_caption.name
            shutil.copy2(entry.image_path, staged_image)
            staged_caption.write_text(entry.caption.rstrip() + "\n", encoding="utf-8")
            exported_files.append(
                {
                    "image": str(final_image),
                    "caption": str(final_caption),
                    "caption_text": entry.caption,
                    "sha256": sha256_file(staged_image),
                    "dataset_item_id": entry.dataset_item_id,
                    "source_media_item_id": entry.source_media_item_id,
                    "training_media_item_id": entry.training_media_item_id,
                    "crop_recipe_id": entry.crop_recipe_id,
                }
            )
        package = ExportPackage(
            export_type=ExportType.RUNCOMFY_IMAGE,
            output_path=output_path,
            manifest_path=output_path / "manifest.json",
            source_segment_ids=[],
            status="complete",
        )
        resolved_model_card = (
            LoraModelCard.model_validate(model_card)
            if model_card is not None
            else None
        )
        manifest = {
            "created_by": CREATED_BY,
            "export_id": package.id,
            "export_type": package.export_type.value,
            "status": package.status,
            "dataset_snapshot_id": snapshot_id,
            "dataset_version": version,
            "dataset_fingerprint": fingerprint,
            "character_project_id": project_id,
            "training_target": training_target or {},
            "revision_lineage": revision_lineage or {},
            "model_card_path": "model_card.json" if resolved_model_card else None,
            "model_card": (
                resolved_model_card.model_dump(mode="json")
                if resolved_model_card
                else None
            ),
            "files": exported_files,
        }
        (staged_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if resolved_model_card is not None:
            (staged_path / "model_card.json").write_text(
                resolved_model_card.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            (staged_path / "README.md").write_text(
                render_model_card_markdown(resolved_model_card),
                encoding="utf-8",
            )
        (staged_path / "export_report.md").write_text(
            "# RunComfy Character Dataset Export\n\n"
            f"- Snapshot: {snapshot_id}\n"
            f"- Version: {version}\n"
            f"- Fingerprint: `{fingerprint}`\n"
            f"- Training target: {(training_target or {}).get('label', 'Unspecified')}\n"
            f"- Images: {len(exported_files)}\n"
            "- Captions: one reviewed .txt file per image\n",
            encoding="utf-8",
        )
        _replace_directory(staged_path, output_path)
        moved_to_output = True
        return package
    finally:
        if not moved_to_output and staged_path.exists():
            shutil.rmtree(staged_path)


def create_voice_dataset_export(
    *,
    compilation: VoiceDatasetCompilation,
    output_dir: Path,
    target: VoiceExportTarget = VoiceExportTarget.VOICE_CLONING,
) -> ExportPackage:
    compilation = refresh_voice_dataset_contract(compilation)
    approved = [
        segment
        for segment in compilation.segments.values()
        if segment.status == VoiceSegmentStatus.APPROVED
    ]
    if not approved:
        raise ValueError("At least one approved voice segment is required for export")
    output_path = _normalize_output_dir(output_dir)
    _validate_voice_output_dir(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = Path(
        mkdtemp(prefix=f".{output_path.name or 'voice-export'}.staging.", dir=output_path.parent)
    )
    moved_to_output = False
    try:
        lanes: list[tuple[str, Path]] = []
        if target in {VoiceExportTarget.VOICE_CLONING, VoiceExportTarget.BOTH}:
            lanes.append(("voice_cloning", Path("voice_cloning") / "audio"))
        if target in {VoiceExportTarget.AV_LORA, VoiceExportTarget.BOTH}:
            lanes.append(("av_lora_audio_reference", Path("av_lora") / "audio_reference"))
        for _lane, relative_dir in lanes:
            (staged_path / relative_dir).mkdir(parents=True, exist_ok=True)
        exported_files: list[dict[str, object]] = []
        voice_metadata: list[dict[str, object]] = []
        av_metadata: list[dict[str, object]] = []
        fish_speech_root = staged_path / "voice_cloning" / "fish_speech" / compilation.project_id
        if target in {VoiceExportTarget.VOICE_CLONING, VoiceExportTarget.BOTH}:
            fish_speech_root.mkdir(parents=True, exist_ok=True)
        for index, segment in enumerate(approved, start=1):
            basename = f"{index:06d}"
            artifacts: list[dict[str, str]] = []
            for lane, relative_dir in lanes:
                staged_audio = staged_path / relative_dir / f"{basename}.wav"
                staged_transcript = staged_path / relative_dir / f"{basename}.txt"
                final_audio = output_path / relative_dir / staged_audio.name
                final_transcript = output_path / relative_dir / staged_transcript.name
                shutil.copy2(segment.audio_path, staged_audio)
                staged_transcript.write_text(segment.transcript.rstrip() + "\n", encoding="utf-8")
                artifacts.append({
                    "lane": lane,
                    "audio": str(final_audio),
                    "transcript": str(final_transcript),
                })
                if lane == "voice_cloning":
                    fish_audio = fish_speech_root / f"{basename}.wav"
                    fish_transcript = fish_speech_root / f"{basename}.lab"
                    shutil.copy2(segment.audio_path, fish_audio)
                    fish_transcript.write_text(segment.transcript.rstrip() + "\n", encoding="utf-8")
                    voice_metadata.append({
                        "audio": f"audio/{basename}.wav",
                        "text": segment.transcript,
                        "language": segment.language,
                        "speaker": compilation.project_id,
                    })
                else:
                    av_metadata.append({
                        "audio_reference": f"audio_reference/{basename}.wav",
                        "text": segment.transcript,
                        "source_media_item_id": segment.source_media_item_id,
                        "start_seconds": segment.start_seconds,
                        "end_seconds": segment.end_seconds,
                    })
            exported_files.append(
                {
                    "artifacts": artifacts,
                    "transcript_text": segment.transcript,
                    "sha256": sha256_file(segment.audio_path),
                    "voice_segment_id": segment.id,
                    "source_media_item_id": segment.source_media_item_id,
                    "media_item_id": segment.media_item_id,
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "language": segment.language,
                    "speaker_similarity": segment.speaker_similarity,
                    "quality_score": segment.quality.quality_score if segment.quality else None,
                }
            )
        if voice_metadata:
            (staged_path / "voice_cloning" / "metadata.jsonl").write_text(
                "".join(json.dumps(entry) + "\n" for entry in voice_metadata),
                encoding="utf-8",
            )
        if av_metadata:
            (staged_path / "av_lora" / "audio_manifest.jsonl").write_text(
                "".join(json.dumps(entry) + "\n" for entry in av_metadata),
                encoding="utf-8",
            )
        package = ExportPackage(
            export_type=ExportType.VOICE_HANDOFF,
            output_path=output_path,
            manifest_path=output_path / "manifest.json",
            source_segment_ids=[segment.id for segment in approved],
            status="complete",
        )
        voice_duration = sum(segment.end_seconds - segment.start_seconds for segment in approved)
        voice_sources = {segment.source_media_item_id for segment in approved}
        profile = get_training_target_profile(compilation.target_profile_id)
        compliance = compilation.balance.recipe_compliance
        voice_training_warnings = (
            [check.detail for check in compliance.checks if not check.passed]
            if compliance is not None
            else ["The voice dataset has no versioned training recipe."]
        )
        fish_speech_enabled = target in {VoiceExportTarget.VOICE_CLONING, VoiceExportTarget.BOTH}
        manifest = {
            "created_by": CREATED_BY,
            "export_id": package.id,
            "export_type": package.export_type.value,
            "status": package.status,
            "target": target.value,
            "character_project_id": compilation.project_id,
            "dataset_fingerprint": compilation.dataset_fingerprint,
            "source_media_item_ids": compilation.source_media_item_ids,
            "files": exported_files,
            "training_target": {
                "profile_id": profile.profile_id,
                "label": profile.label,
                "model_family": profile.model_family,
                "base_model": profile.base_model,
                "recipe_id": profile.recipe_id,
                "recipe_version": profile.recipe_version,
                "recipe_status": profile.recipe.status if profile.recipe else None,
                "ready": (
                    fish_speech_enabled
                    and compliance is not None
                    and compliance.status == "ready"
                ),
                "dataset_root": "voice_cloning/fish_speech",
                "approved_segments": len(approved),
                "duration_seconds": voice_duration,
                "source_count": len(voice_sources),
                "warnings": voice_training_warnings if fish_speech_enabled else ["The export does not include the voice-cloning lane."],
            },
            "recipe_compliance": (
                compliance.model_dump(mode="json")
                if compliance is not None
                else None
            ),
        }
        (staged_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        (staged_path / "export_report.md").write_text(
            "# LoraSuite Voice Dataset Export\n\n"
            f"- Project: {compilation.project_id}\n"
            f"- Approved voice segments: {len(approved)}\n"
            f"- Target: {target.value}\n"
            f"- Recipe: {profile.recipe_id or 'unversioned'} v{profile.recipe_version or 0}\n"
            f"- Dataset fingerprint: {compilation.dataset_fingerprint or 'unavailable'}\n"
            "- Format: mono PCM WAV with matching transcript files\n"
            "- AV-LoRA output is an audio-reference lane for later video pairing\n",
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


def _validate_voice_output_dir(output_path: Path) -> None:
    if output_path.exists() and not output_path.is_dir():
        raise ValueError(f"output_dir exists and is not a directory: {output_path}")
    if not output_path.exists() or _directory_is_empty(output_path):
        return
    manifest_path = output_path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if (
        manifest.get("created_by") == CREATED_BY
        and manifest.get("export_type") == ExportType.VOICE_HANDOFF.value
    ):
        return
    raise ValueError(
        f"output_dir is non-empty and is not a LoraSuite voice export: {output_path}"
    )


def _normalize_output_dir(output_dir: Path) -> Path:
    value = str(output_dir).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("output_dir must not be empty")
    return Path(value).expanduser()


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
