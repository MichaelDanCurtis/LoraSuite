from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.model_metadata import LoraModelCard
from lorasuite_engine.models import TrainingTargetSpec, utc_now
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.vault import sha256_file


RECOVERED_DATASET_FORMAT = "lorasuite.recovered-dataset.v1"


class RecoveredDatasetExport(BaseModel):
    id: str
    format: Literal["lorasuite.recovered-dataset.v1"] = RECOVERED_DATASET_FORMAT
    export_path: Path
    manifest_path: Path
    manifest_sha256: str
    export_type: str
    modality: Literal["image", "video", "voice", "audio_visual"]
    project_id: str
    snapshot_id: str
    dataset_version: int = 1
    fingerprint: str
    fingerprint_source: Literal["manifest", "content"]
    training_target: TrainingTargetSpec
    trigger_token: str = ""
    trigger_token_source: Literal["model_card", "caption_consensus", "unknown"] = "unknown"
    model_card: LoraModelCard | None = None
    revision_lineage: RevisionLineage = Field(default_factory=RevisionLineage)
    file_count: int = 0
    verified_file_count: int = 0
    integrity_status: Literal["verified", "structural", "failed"] = "failed"
    ready: bool = False
    source_available: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    imported_at: Any = Field(default_factory=utc_now)
    verified_at: Any = Field(default_factory=utc_now)


class RecoveredDatasetService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def registry_path(self) -> Path:
        return self.vault_root / "recovered_dataset_exports.json"

    def list_exports(self) -> list[RecoveredDatasetExport]:
        records = list(self._read().values())
        for record in records:
            record.source_available = (
                record.export_path.is_dir()
                and record.manifest_path.is_file()
            )
        return sorted(records, key=lambda record: record.imported_at, reverse=True)

    def get_export(self, record_id: str) -> RecoveredDatasetExport | None:
        record = self._read().get(record_id)
        if record is not None:
            record.source_available = (
                record.export_path.is_dir()
                and record.manifest_path.is_file()
            )
        return record

    def find_by_snapshot_id(self, snapshot_id: str) -> RecoveredDatasetExport | None:
        return next(
            (
                record
                for record in self.list_exports()
                if record.snapshot_id == snapshot_id
            ),
            None,
        )

    def register(self, export_path: Path) -> RecoveredDatasetExport:
        inspected = self._inspect(Path(export_path))
        records = self._read()
        existing = records.get(inspected.id)
        if existing is not None:
            inspected.imported_at = existing.imported_at
        records[inspected.id] = inspected
        self._write(records)
        return inspected

    def verify(self, record_id: str) -> RecoveredDatasetExport:
        records = self._read()
        existing = records.get(record_id)
        if existing is None:
            raise KeyError(record_id)
        inspected = self._inspect(existing.export_path)
        inspected.id = existing.id
        inspected.imported_at = existing.imported_at
        records[record_id] = inspected
        self._write(records)
        return inspected

    def _inspect(self, export_path: Path) -> RecoveredDatasetExport:
        root = export_path.expanduser().resolve(strict=False)
        if not root.is_dir():
            raise ValueError("recovered dataset export folder does not exist")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("recovered dataset export must contain manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"dataset manifest is invalid: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError("dataset manifest must contain a JSON object")

        export_type = _export_type(manifest)
        modality = _modality(export_type, manifest)
        project_id = _first_string(
            manifest,
            "character_project_id",
            "project_id",
        )
        snapshot_id = _first_string(
            manifest,
            "dataset_snapshot_id",
            "snapshot_id",
            "manifest_id",
            "export_id",
        )
        manifest_sha256 = sha256_file(manifest_path)
        declared_fingerprint = _first_string(
            manifest,
            "dataset_fingerprint",
            "fingerprint",
        )
        training_target = _training_target(manifest, modality)
        model_card = _model_card(root, manifest)
        lineage = RevisionLineage.from_source_manifest(manifest)
        verification = _verify_files(root, manifest, modality)
        content_fingerprint = _content_fingerprint(
            export_type=export_type,
            snapshot_id=snapshot_id,
            file_proofs=verification.file_proofs,
        )
        fingerprint = declared_fingerprint or content_fingerprint
        trigger_token, trigger_source = _trigger_token(
            model_card,
            verification.captions,
        )
        errors = list(verification.errors)
        warnings = list(verification.warnings)
        if manifest.get("created_by") != "LoraSuite":
            errors.append("Manifest does not declare LoraSuite provenance.")
        if not project_id:
            warnings.append("Original project ID is unavailable.")
            project_id = f"recovered_project_{fingerprint[:16]}"
        if not snapshot_id:
            warnings.append("Original snapshot ID is unavailable.")
            snapshot_id = f"recovered_snapshot_{fingerprint[:16]}"
        if not declared_fingerprint:
            warnings.append("Manifest has no declared dataset fingerprint; a content fingerprint was recorded.")
        if not trigger_token:
            warnings.append("Trigger token is unknown because no model card or caption consensus was available.")
        if verification.structural_only:
            warnings.append("This export format has structural file checks but no complete checksum contract.")

        integrity_status: Literal["verified", "structural", "failed"]
        if errors:
            integrity_status = "failed"
        elif verification.structural_only:
            integrity_status = "structural"
        else:
            integrity_status = "verified"
        record_id = _record_id(export_type, snapshot_id, fingerprint)
        return RecoveredDatasetExport(
            id=record_id,
            export_path=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            export_type=export_type,
            modality=modality,
            project_id=project_id,
            snapshot_id=snapshot_id,
            dataset_version=_positive_int(manifest.get("dataset_version"), 1),
            fingerprint=fingerprint,
            fingerprint_source="manifest" if declared_fingerprint else "content",
            training_target=training_target,
            trigger_token=trigger_token,
            trigger_token_source=trigger_source,
            model_card=model_card,
            revision_lineage=lineage,
            file_count=verification.file_count,
            verified_file_count=verification.verified_file_count,
            integrity_status=integrity_status,
            ready=not errors and verification.file_count > 0,
            warnings=list(dict.fromkeys(warnings)),
            errors=list(dict.fromkeys(errors)),
        )

    def _read(self) -> dict[str, RecoveredDatasetExport]:
        with json_file_lock(self.registry_path):
            if not self.registry_path.is_file():
                return {}
            try:
                payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            items = payload.get("exports", []) if isinstance(payload, dict) else []
            return {
                item["id"]: RecoveredDatasetExport.model_validate(item)
                for item in items
                if isinstance(item, dict) and item.get("id")
            }

    def _write(self, records: dict[str, RecoveredDatasetExport]) -> None:
        with json_file_lock(self.registry_path):
            atomic_write_json(
                self.registry_path,
                {
                    "version": 1,
                    "exports": [
                        record.model_dump(mode="json")
                        for record in records.values()
                    ],
                },
            )


class _FileVerification(BaseModel):
    file_count: int = 0
    verified_file_count: int = 0
    structural_only: bool = False
    captions: list[str] = Field(default_factory=list)
    file_proofs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _verify_files(
    root: Path,
    manifest: dict[str, Any],
    modality: str,
) -> _FileVerification:
    if modality in {"image", "video"}:
        return _verify_paired_media(root, manifest, modality)
    if modality == "voice":
        return _verify_voice(root, manifest)
    return _verify_audio_visual(root, manifest)


def _verify_paired_media(
    root: Path,
    manifest: dict[str, Any],
    modality: str,
) -> _FileVerification:
    result = _FileVerification()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        result.errors.append("Manifest contains no training file entries.")
        return result
    media_key = "image" if modality == "image" else "video"
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            result.errors.append(f"File entry {index} is invalid.")
            continue
        result.file_count += 1
        media = _resolve_export_file(root, entry.get(media_key))
        caption = _resolve_export_file(root, entry.get("caption"))
        if media is None or not media.is_file():
            result.errors.append(f"File entry {index} is missing its {media_key}.")
            continue
        if caption is None or not caption.is_file():
            result.errors.append(f"File entry {index} is missing its caption.")
            continue
        caption_text = caption.read_text(encoding="utf-8").strip()
        if not caption_text:
            result.errors.append(f"Caption {caption.name} is empty.")
            continue
        expected_sha = str(entry.get("sha256") or "").strip().lower()
        actual_sha = sha256_file(media)
        if expected_sha and expected_sha != actual_sha:
            result.errors.append(f"Checksum mismatch for {media.name}.")
            continue
        if not expected_sha:
            result.structural_only = True
            result.warnings.append(f"{media.name} has no declared checksum.")
        if media.stem != caption.stem:
            result.errors.append(f"Pair basenames do not match: {media.name} and {caption.name}.")
            continue
        declared_caption = str(entry.get("caption_text") or "").strip()
        if declared_caption and declared_caption != caption_text:
            result.errors.append(f"Manifest caption differs from {caption.name}.")
            continue
        result.verified_file_count += 1
        result.captions.append(caption_text)
        result.file_proofs.append(f"{_relative(root, media)}:{actual_sha}")
    return result


def _verify_voice(root: Path, manifest: dict[str, Any]) -> _FileVerification:
    result = _FileVerification()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        result.errors.append("Manifest contains no voice segment entries.")
        return result
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            result.errors.append(f"Voice entry {index} is invalid.")
            continue
        artifacts = entry.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            result.errors.append(f"Voice entry {index} has no exported artifacts.")
            continue
        result.file_count += 1
        expected_sha = str(entry.get("sha256") or "").strip().lower()
        entry_valid = True
        first_sha = ""
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                entry_valid = False
                continue
            audio = _resolve_export_file(root, artifact.get("audio"))
            transcript = _resolve_export_file(root, artifact.get("transcript"))
            if audio is None or not audio.is_file() or transcript is None or not transcript.is_file():
                entry_valid = False
                continue
            actual_sha = sha256_file(audio)
            first_sha = first_sha or actual_sha
            if expected_sha and expected_sha != actual_sha:
                entry_valid = False
            transcript_text = transcript.read_text(encoding="utf-8").strip()
            if not transcript_text:
                entry_valid = False
            elif transcript_text not in result.captions:
                result.captions.append(transcript_text)
        if not expected_sha:
            result.structural_only = True
        if entry_valid:
            result.verified_file_count += 1
            result.file_proofs.append(f"voice:{index}:{first_sha}")
        else:
            result.errors.append(f"Voice entry {index} is missing a file or failed checksum verification.")
    return result


def _verify_audio_visual(root: Path, manifest: dict[str, Any]) -> _FileVerification:
    result = _FileVerification(structural_only=True)
    examples = manifest.get("examples")
    references = manifest.get("voice_references")
    if not isinstance(examples, list) or not examples:
        result.errors.append("Manifest contains no audio-visual examples.")
        return result
    for index, entry in enumerate(examples, start=1):
        if not isinstance(entry, dict):
            result.errors.append(f"Audio-visual example {index} is invalid.")
            continue
        result.file_count += 1
        required = [
            _resolve_export_file(root, entry.get("video")),
            _resolve_export_file(root, entry.get("caption")),
        ]
        audio_value = entry.get("audio")
        if audio_value:
            required.append(_resolve_export_file(root, audio_value))
        if any(path is None or not path.is_file() for path in required):
            result.errors.append(f"Audio-visual example {index} is missing a required file.")
            continue
        result.verified_file_count += 1
        result.file_proofs.extend(
            f"{_relative(root, path)}:{sha256_file(path)}"
            for path in required
            if path is not None
        )
    if isinstance(references, list):
        for index, entry in enumerate(references, start=1):
            if not isinstance(entry, dict):
                result.errors.append(f"Voice reference {index} is invalid.")
                continue
            audio = _resolve_export_file(root, entry.get("audio"))
            transcript = _resolve_export_file(root, entry.get("transcript_file"))
            if audio is None or not audio.is_file() or transcript is None or not transcript.is_file():
                result.errors.append(f"Voice reference {index} is missing a required file.")
                continue
            result.file_proofs.append(f"{_relative(root, audio)}:{sha256_file(audio)}")
    return result


def _resolve_export_file(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    original = Path(value)
    candidates: list[Path] = []
    if original.is_absolute():
        candidates.append(original)
        parts = original.parts
        for marker in (
            "images",
            "videos",
            "voice_cloning",
            "av_lora",
            "voice_references",
            "train",
            "validation",
        ):
            if marker in parts:
                candidates.append(root.joinpath(*parts[parts.index(marker):]))
        candidates.append(root / original.name)
    else:
        candidates.append(root / original)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved == root or root in resolved.parents:
            return resolved
    return None


def _training_target(
    manifest: dict[str, Any],
    modality: str,
) -> TrainingTargetSpec:
    target = manifest.get("training_target")
    target = target if isinstance(target, dict) else {}
    profile_id = str(target.get("profile_id") or "").strip()
    if profile_id:
        try:
            return get_training_target_profile(profile_id).spec()
        except KeyError:
            pass
    return TrainingTargetSpec(
        profile_id=profile_id or f"recovered_{modality}_target",
        label=str(target.get("label") or f"Recovered {modality.title()} Dataset"),
        provider=str(target.get("provider") or "unknown"),
        trainer=str(target.get("trainer") or "unknown"),
        modality=modality,
        model_family=str(target.get("model_family") or "unknown"),
        base_model=str(target.get("base_model") or "unknown"),
        compiler_version=str(target.get("compiler_version") or "recovered-export-v1"),
        resolution_buckets=[
            int(value)
            for value in target.get("resolution_buckets", [])
            if isinstance(value, int)
        ],
        caption_format=str(target.get("caption_format") or "paired_txt"),
        output_format=str(target.get("output_format") or "unknown"),
    )


def _model_card(root: Path, manifest: dict[str, Any]) -> LoraModelCard | None:
    payload = manifest.get("model_card")
    if isinstance(payload, dict):
        try:
            return LoraModelCard.model_validate(payload)
        except ValueError:
            return None
    relative = manifest.get("model_card_path")
    path = _resolve_export_file(root, relative)
    if path is None or not path.is_file():
        return None
    try:
        return LoraModelCard.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _trigger_token(
    model_card: LoraModelCard | None,
    captions: list[str],
) -> tuple[str, Literal["model_card", "caption_consensus", "unknown"]]:
    if model_card is not None and model_card.trigger_token.strip():
        return model_card.trigger_token.strip(), "model_card"
    tokens = {
        caption.split(",", 1)[0].strip()
        for caption in captions
        if "," in caption and caption.split(",", 1)[0].strip()
    }
    if len(tokens) == 1:
        return next(iter(tokens)), "caption_consensus"
    return "", "unknown"


def _export_type(manifest: dict[str, Any]) -> str:
    explicit = str(manifest.get("export_type") or "").strip()
    if explicit:
        return explicit
    if manifest.get("format") == "id-lora-av-v1":
        return "id_lora_av"
    modality = str(manifest.get("modality") or "").strip()
    if modality == "video":
        return "ai_toolkit_video"
    return "unknown"


def _modality(
    export_type: str,
    manifest: dict[str, Any],
) -> Literal["image", "video", "voice", "audio_visual"]:
    mapping: dict[str, Literal["image", "video", "voice", "audio_visual"]] = {
        "runcomfy_image": "image",
        "ai_toolkit_video": "video",
        "voice_handoff": "voice",
        "id_lora_av": "audio_visual",
    }
    if export_type in mapping:
        return mapping[export_type]
    explicit = str(manifest.get("modality") or "").strip()
    if explicit in {"image", "video", "voice", "audio_visual"}:
        return explicit  # type: ignore[return-value]
    raise ValueError(f"unsupported recovered dataset export type: {export_type or 'unknown'}")


def _content_fingerprint(
    *,
    export_type: str,
    snapshot_id: str,
    file_proofs: list[str],
) -> str:
    payload = "\n".join([export_type, snapshot_id, *sorted(file_proofs)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_id(export_type: str, snapshot_id: str, fingerprint: str) -> str:
    payload = f"{export_type}\0{snapshot_id}\0{fingerprint}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"recovered_dataset_{digest}"


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
