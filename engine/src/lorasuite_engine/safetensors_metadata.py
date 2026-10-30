from __future__ import annotations

import json
import os
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from lorasuite_engine.model_metadata import LoraModelCard


MAX_HEADER_BYTES = 100_000_000


@dataclass(frozen=True)
class SafetensorsMetadataResult:
    path: Path
    changed: bool
    metadata: dict[str, str]


def read_safetensors_metadata(path: Path) -> dict[str, str]:
    header, _header_size = _read_header(Path(path))
    metadata = header.get("__metadata__", {})
    if not isinstance(metadata, dict):
        raise ValueError("safetensors __metadata__ must be an object")
    return {
        str(key): str(value)
        for key, value in metadata.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def embed_safetensors_metadata(
    path: Path,
    metadata: dict[str, str],
) -> SafetensorsMetadataResult:
    target = Path(path)
    if target.suffix.casefold() != ".safetensors":
        raise ValueError("metadata can only be embedded into .safetensors files")
    cleaned = _clean_metadata(metadata)
    header, old_header_size = _read_header(target)
    existing = read_safetensors_metadata(target)
    merged = {**existing, **cleaned}
    if merged == existing:
        return SafetensorsMetadataResult(
            path=target,
            changed=False,
            metadata=merged,
        )
    header["__metadata__"] = merged
    encoded_header = json.dumps(
        header,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    padding = (-len(encoded_header)) % 8
    if padding:
        encoded_header += b" " * padding
    if len(encoded_header) > MAX_HEADER_BYTES:
        raise ValueError("rewritten safetensors header is too large")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("rb") as source:
        source.seek(8 + old_header_size)
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            try:
                temporary.write(struct.pack("<Q", len(encoded_header)))
                temporary.write(encoded_header)
                shutil.copyfileobj(source, temporary, length=1024 * 1024)
                temporary.flush()
                os.fsync(temporary.fileno())
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
    try:
        shutil.copymode(target, temporary_path)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return SafetensorsMetadataResult(
        path=target,
        changed=True,
        metadata=merged,
    )


def model_card_safetensors_metadata(
    card: LoraModelCard,
    *,
    artifact_id: str,
    training_run_id: str,
    source_checkpoint_sha256: str,
) -> dict[str, str]:
    embedded = card.model_copy(deep=True)
    embedded.artifact = {
        "artifact_id": artifact_id,
        "training_run_id": training_run_id,
        "source_checkpoint_sha256": source_checkpoint_sha256,
    }
    embedded.provenance = {
        **embedded.provenance,
        "artifact_id": artifact_id,
        "training_run_id": training_run_id,
        "source_checkpoint_sha256": source_checkpoint_sha256,
    }
    training_parameters = embedded.training.get("parameters")
    rank = (
        training_parameters.get("network_rank")
        if isinstance(training_parameters, dict)
        else None
    )
    alpha = (
        training_parameters.get("network_alpha")
        if isinstance(training_parameters, dict)
        else None
    )
    values = {
        "lorasuite.schema_version": embedded.schema_version,
        "lorasuite.model_card": embedded.model_dump_json(exclude_none=True),
        "lorasuite.artifact_id": artifact_id,
        "lorasuite.training_run_id": training_run_id,
        "lorasuite.source_checkpoint_sha256": source_checkpoint_sha256,
        "lorasuite.dataset_fingerprint": str(
            embedded.dataset.get("fingerprint") or ""
        ),
        "lorasuite.trigger_token": embedded.trigger_token,
        "lorasuite.base_model": embedded.base_model,
        "lorasuite.model_family": embedded.model_family,
        "lorasuite.target_type": embedded.target_type,
        "lorasuite.recipe_id": embedded.recipe_id or "",
        "lorasuite.recipe_version": (
            str(embedded.recipe_version)
            if embedded.recipe_version is not None
            else ""
        ),
        "modelspec.title": embedded.display_name,
        "modelspec.description": embedded.description,
        "modelspec.license": embedded.license,
        "modelspec.tags": ", ".join(embedded.tags),
        "modelspec.trigger_phrase": embedded.trigger_token,
        "ss_output_name": embedded.name,
        "ss_network_dim": str(rank) if rank is not None else "",
        "ss_network_alpha": str(alpha) if alpha is not None else "",
    }
    return {key: value for key, value in values.items() if value}


def _read_header(path: Path) -> tuple[dict[str, object], int]:
    if path.suffix.casefold() != ".safetensors":
        raise ValueError("checkpoint is not a .safetensors file")
    with path.open("rb") as handle:
        raw_size = handle.read(8)
        if len(raw_size) != 8:
            raise ValueError("safetensors header is truncated")
        header_size = struct.unpack("<Q", raw_size)[0]
        if header_size <= 2 or header_size > MAX_HEADER_BYTES:
            raise ValueError("safetensors header size is invalid")
        raw_header = handle.read(header_size)
        if len(raw_header) != header_size:
            raise ValueError("safetensors header is truncated")
    try:
        header = json.loads(raw_header)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("safetensors header is not valid JSON") from error
    if not isinstance(header, dict):
        raise ValueError("safetensors header must be an object")
    return header, header_size


def _clean_metadata(metadata: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in metadata.items():
        cleaned_key = str(key).strip()
        if not cleaned_key:
            raise ValueError("safetensors metadata keys must not be empty")
        if not isinstance(value, str):
            raise ValueError("safetensors metadata values must be strings")
        result[cleaned_key] = value
    return result
