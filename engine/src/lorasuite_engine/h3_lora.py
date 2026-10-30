"""Strict DiffSynth H3 LoRA import and non-destructive, streamed BF16 overlays.

This is not a format-guessing converter. Only fused DiffSynth linear A/B pairs
are accepted; split Q/K/V, DoRA, quantized adapters and other model families fail
closed. Structural validation is not a claim of trained-adapter render quality.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import struct
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import sha256_file

FORMAT = "diffsynth-h3-fused-v1"
TARGET = re.compile(r"(?:blocks\.([0-9]+)|token_refiner\.blocks\.([0-9]+))\.(?:attn\.(?:qkv_proj|out_proj)|mlp\.fc[12])$")
PAIR = re.compile(r"(.+)\.lora_([AB])(?:\.default)?\.weight$")
DTYPES = {"BF16": "<u2", "F16": "<f2", "F32": "<f4", "I64": "<i8", "I32": "<i4", "F64": "<f8"}


class H3LoRASlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str = Field(pattern=r"^h3_lora_[a-f0-9]{24}$")
    strength: float = Field(default=1, ge=-2, le=2, allow_inf_nan=False)
    enabled: bool = True


class H3LoRAImport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    path: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=160)
    base_variant: Literal["FL2VA", "Ref2VA"]
    format: Literal["diffsynth-h3-fused-v1"] = FORMAT
    provenance: str = Field(min_length=1, max_length=2000)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate safetensors header key: {key}")
        result[key] = value
    return result


class SafeFile:
    """Bounded header reader; never pickle/unpickle or execute model code."""
    def __init__(self, path: Path):
        self.path = Path(path)
        size = self.path.stat().st_size
        with self.path.open("rb") as reader:
            prefix = reader.read(8)
            if len(prefix) != 8:
                raise ValueError("Truncated safetensors file")
            length, = struct.unpack("<Q", prefix)
            if not 2 <= length <= min(16 * 1024 * 1024, size - 8):
                raise ValueError("Invalid or oversized safetensors header")
            header = json.loads(reader.read(length), object_pairs_hook=_unique)
        if not isinstance(header, dict) or len(header) > 20001:
            raise ValueError("Invalid safetensors tensor inventory")
        self.offset = length + 8
        self.metadata = header.pop("__metadata__", {})
        self.tensors = header
        spans = []
        for name, tensor in header.items():
            if not isinstance(tensor, dict) or tensor.get("dtype") not in DTYPES:
                raise ValueError(f"Unsupported tensor dtype: {name}")
            shape, offsets = tensor.get("shape"), tensor.get("data_offsets")
            if not isinstance(shape, list) or len(shape) > 8 or any(type(d) is not int or d <= 0 for d in shape):
                raise ValueError(f"Invalid tensor shape: {name}")
            elements = math.prod(shape)
            if elements > 2**31 or not isinstance(offsets, list) or len(offsets) != 2 or any(type(n) is not int for n in offsets):
                raise ValueError(f"Invalid tensor offsets: {name}")
            begin, end = offsets
            if begin < 0 or end - begin != elements * np.dtype(DTYPES[tensor["dtype"]]).itemsize or end > size - self.offset:
                raise ValueError(f"Truncated or malformed tensor: {name}")
            spans.append((begin, end))
        cursor = 0
        for begin, end in sorted(spans):
            if begin != cursor:
                raise ValueError("Overlapping tensors or holes in safetensors payload")
            cursor = end
        if cursor != size - self.offset:
            raise ValueError("Unaccounted safetensors payload")

    def read(self, name: str, rows: slice | None = None) -> np.ndarray:
        t = self.tensors[name]
        data = np.memmap(self.path, mode="r", dtype=DTYPES[t["dtype"]], offset=self.offset + t["data_offsets"][0], shape=tuple(t["shape"]))
        part = data if rows is None else data[rows]
        result = (part.astype(np.uint32) << 16).view(np.float32) if t["dtype"] == "BF16" else part.astype(np.float32)
        if not np.isfinite(result).all():
            raise ValueError(f"Non-finite tensor values: {name}")
        return result


def bf16(values: np.ndarray) -> bytes:
    values = np.asarray(values, dtype="<f4")
    if not np.isfinite(values).all():
        raise ValueError("LoRA composition overflowed; reduce strengths")
    bits = values.view(np.uint32)
    rounded = ((bits + 0x7fff + ((bits >> 16) & 1)) >> 16).astype("<u2")
    if np.any((rounded & 0x7f80) == 0x7f80):
        raise ValueError("LoRA composition exceeds BF16 range")
    return rounded.tobytes()


def adapter_pairs(source: SafeFile) -> dict:
    pairs = {}
    source_names = {}
    for key, tensor in source.tensors.items():
        if key.endswith(".alpha"):
            continue
        match = PAIR.fullmatch(key)
        if not match:
            raise ValueError(f"Unsupported LoRA tensor (expected fused DiffSynth A/B): {key}")
        source_name, side = match.groups()
        # Some H3 exports wrap the same fused transformer under diffusion_model.
        # Normalize only this exact namespace; keep original keys for tensor reads.
        name = source_name.removeprefix("diffusion_model.")
        target = TARGET.fullmatch(name)
        if not target or (int(target[1]) >= 50 if target[1] is not None else int(target[2]) >= 2):
            raise ValueError(f"Unsupported H3 target: {name}")
        if tensor["dtype"] not in {"BF16", "F16", "F32"} or len(tensor["shape"]) != 2:
            raise ValueError(f"LoRA pairs must be floating-point matrices: {key}")
        if name in source_names and source_names[name] != source_name:
            raise ValueError(f"Ambiguous LoRA target namespaces: {name}")
        source_names[name] = source_name
        pair = pairs.setdefault(name, {})
        if side in pair:
            raise ValueError(f"Ambiguous LoRA pair: {name}")
        pair[side] = key
    consumed = set()
    for name, pair in pairs.items():
        if set(pair) != {"A", "B"}:
            raise ValueError(f"Incomplete LoRA pair: {name}")
        a, b = (source.tensors[pair[side]]["shape"] for side in ("A", "B"))
        if not 1 <= a[0] <= 256 or b[1] != a[0]:
            raise ValueError(f"LoRA rank mismatch or unsupported rank: {name}")
        pair["shape"] = [b[0], a[1]]
        pair["rank"] = a[0]
        pair["scale"] = 1.0  # DiffSynth exports use B @ A; no implicit 1/rank.
        consumed.update((pair["A"], pair["B"]))
        alpha_key = source_names[name] + ".alpha"
        if alpha_key in source.tensors:
            alpha = source.read(alpha_key)
            if alpha.size != 1:
                raise ValueError(f"Alpha must be scalar: {name}")
            pair["scale"] = float(alpha.item()) / a[0]
            consumed.add(alpha_key)
    if not pairs or consumed != set(source.tensors):
        raise ValueError("Empty adapter or unused alpha tensors")
    return pairs


def base_inventory(model_dir: Path, variant: str) -> tuple[dict, str]:
    folder = model_dir / variant / "transformer"
    files = sorted(folder.glob("*.safetensors"))
    if not files:
        raise ValueError(f"Missing {variant} transformer weights")
    inventory, identity = {}, []
    for path in files:
        source = SafeFile(path)
        stat = path.stat()
        identity.append((path.name, stat.st_size, stat.st_mtime_ns, sha256_file_header(source)))
        for name, tensor in source.tensors.items():
            if name in inventory:
                raise ValueError(f"Duplicate base tensor: {name}")
            inventory[name] = (source, tensor)
    return inventory, hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def sha256_file_header(source: SafeFile) -> str:
    with source.path.open("rb") as reader:
        return hashlib.sha256(reader.read(source.offset)).hexdigest()


class H3LoRAService:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "h3_loras.json"

    def list(self) -> list[dict]:
        return list(json.loads(self.path.read_text()).get("adapters", {}).values()) if self.path.is_file() else []

    def get(self, adapter_id: str) -> dict:
        for adapter in self.list():
            if adapter["id"] == adapter_id:
                return adapter
        raise ValueError(f"H3 adapter not found: {adapter_id}")

    def import_adapter(self, request: H3LoRAImport, model_dir: Path) -> dict:
        path = Path(request.path).expanduser().resolve(strict=True)
        if path.suffix != ".safetensors" or not path.is_file() or not 0 < path.stat().st_size <= 8 * 1024**3:
            raise ValueError("Choose a local .safetensors adapter (at most 8 GiB)")
        source = SafeFile(path)
        pairs = adapter_pairs(source)
        inventory, base_id = base_inventory(model_dir, request.base_variant)
        self._check_shapes(pairs, inventory)
        # Check every adapter value before allowing it into the library.
        for key in source.tensors:
            source.read(key)
        digest = sha256_file(path)
        adapter_id = "h3_lora_" + hashlib.sha256((digest + request.base_variant + base_id).encode()).hexdigest()[:24]
        destination = self.root / "h3_loras" / adapter_id / "adapter.safetensors"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_suffix(".partial")
            with json_file_lock(destination):
                try:
                    shutil.copyfile(path, temporary)
                    if sha256_file(temporary) != digest:
                        raise ValueError("Adapter changed during import")
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        if sha256_file(destination) != digest:
            raise ValueError("Stored adapter is damaged; restore it before use")
        adapter = {"id": adapter_id, "label": request.label, "base_variant": request.base_variant,
                   "format": FORMAT, "provenance": request.provenance, "sha256": digest,
                   "path": str(destination), "base_inventory_id": base_id,
                   "target_count": len(pairs), "ranks": sorted({p["rank"] for p in pairs.values()}),
                   "overlay_bytes": sum(math.prod(p["shape"]) * 2 for p in pairs.values()),
                   "qualification": "structure_checked_render_unverified"}
        with json_file_lock(self.path):
            adapters = {a["id"]: a for a in self.list()}
            adapters[adapter_id] = adapter
            atomic_write_json(self.path, {"version": 1, "adapters": adapters})
        return adapter

    @staticmethod
    def _check_shapes(pairs, inventory):
        for name, pair in pairs.items():
            target = inventory.get(name + ".weight")
            if target is None or target[1]["dtype"] != "BF16" or target[1]["shape"] != pair["shape"]:
                raise ValueError(f"Adapter does not match this native H3 BF16 base: {name}")

    def capture(self, slots: list[H3LoRASlot], variant: str, model_dir: Path, directory: Path) -> list[dict]:
        active = [slot for slot in slots if slot.enabled and slot.strength != 0]
        if len({s.adapter_id for s in slots}) != len(slots):
            raise ValueError("Each adapter may appear only once in the stack")
        if not active:
            return []
        inventory, base_id = base_inventory(model_dir, variant)
        captured = []
        for slot in active:
            adapter = self.get(slot.adapter_id)
            if adapter["base_variant"] != variant or adapter["base_inventory_id"] != base_id:
                raise ValueError(f"{adapter['label']} belongs to a different H3 base; re-import against the selected base")
            path = Path(adapter["path"])
            if sha256_file(path) != adapter["sha256"]:
                raise ValueError(f"Stored adapter changed: {adapter['label']}")
            self._check_shapes(adapter_pairs(SafeFile(path)), inventory)
            destination = directory / f"{slot.adapter_id}.safetensors"
            shutil.copyfile(path, destination)
            if sha256_file(destination) != adapter["sha256"]:
                raise ValueError("Adapter changed while capturing run inputs")
            captured.append({**adapter, "path": str(destination), "strength": slot.strength})
        return captured


def compile_overlay(adapters: list[dict], model_dir: Path, variant: str, output: Path,
                    progress: Callable[[str], None] = lambda _: None,
                    canceled: Callable[[], bool] = lambda: False) -> dict:
    """Accumulate FP32 deltas a row chunk at a time; round to BF16 only once."""
    inventory, base_id = base_inventory(model_dir, variant)
    targets = {}
    for adapter in adapters:
        if adapter["base_variant"] != variant or adapter["base_inventory_id"] != base_id:
            raise ValueError("H3 base changed since adapter capture")
        path = Path(adapter["path"])
        if sha256_file(path) != adapter["sha256"]:
            raise ValueError("Captured LoRA changed before composition")
        source = SafeFile(path)
        pairs = adapter_pairs(source)
        H3LoRAService._check_shapes(pairs, inventory)
        for name, pair in pairs.items():
            targets.setdefault(name + ".weight", []).append((source, pair, adapter["strength"]))
    if not targets:
        raise ValueError("Cannot compile an empty stack")
    header, offset = {}, 0
    for name in sorted(targets):
        shape = inventory[name][1]["shape"]
        length = math.prod(shape) * 2
        header[name] = {"dtype": "BF16", "shape": shape, "data_offsets": [offset, offset + length]}
        offset += length
    if shutil.disk_usage(output.parent).free < offset + 256 * 1024**2:
        raise ValueError(f"LoRA overlay needs {offset / 1024**3:.2f} GiB of free disk space")
    header["__metadata__"] = {"format": "lorasuite-h3-overlay-v1", "base_variant": variant, "base_inventory_id": base_id}
    encoded = json.dumps(header, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    temporary = output.with_suffix(".partial")
    base_digests = {}
    try:
        with temporary.open("wb") as writer:
            writer.write(struct.pack("<Q", len(encoded)))
            writer.write(encoded)
            for index, (name, deltas) in enumerate(sorted(targets.items())):
                progress(f"Composing LoRA stack: tensor {index + 1}/{len(targets)} · {name}")
                source, tensor = inventory[name]
                prepared = [(s, p, strength, s.read(p["A"])) for s, p, strength in deltas]
                digest = hashlib.sha256()
                for row in range(0, tensor["shape"][0], 128):
                    if canceled():
                        raise ValueError("LoRA composition canceled")
                    rows = slice(row, row + 128)
                    value = source.read(name, rows)
                    digest.update(value.tobytes())
                    for adapter_source, pair, strength, a in prepared:
                        value += (strength * pair["scale"]) * (adapter_source.read(pair["B"], rows) @ a)
                    writer.write(bf16(value))
                base_digests[name] = digest.hexdigest()
            writer.flush()
            os.fsync(writer.fileno())
        if canceled():
            raise ValueError("LoRA composition canceled")
        if base_inventory(model_dir, variant)[1] != base_id:
            raise ValueError("H3 base changed during LoRA composition")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(output), "sha256": sha256_file(output), "tensor_count": len(targets),
            "bytes": output.stat().st_size, "base_inventory_id": base_id,
            "base_tensor_f32_sha256": base_digests, "method": "sum_fp32_then_bf16_v1"}


def overlay_cache_key(adapters: list[dict], model_dir: Path, variant: str, base_id: str) -> str:
    base_files = sorted((model_dir / variant / "transformer").glob("*.safetensors"))
    identity = [(str(p.resolve()), p.stat().st_ino, p.stat().st_ctime_ns) for p in base_files]
    return hashlib.sha256(json.dumps({"version": 1, "method": "sum_fp32_then_bf16_v1",
        "base": base_id, "base_files": identity, "variant": variant,
        "stack": [(a["sha256"], a["strength"]) for a in adapters]}, sort_keys=True).encode()).hexdigest()


def cached_overlay(adapters: list[dict], model_dir: Path, variant: str, cache_root: Path,
                   progress: Callable[[str], None] = lambda _: None,
                   canceled: Callable[[], bool] = lambda: False) -> dict:
    """One verified derived file per ordered stack/base, shared across render runs.

    Runs retain their small captured adapters. Cache entries are not automatically
    evicted while runs may still use them. A restart revalidates the payload hash.
    """
    if not adapters:
        raise ValueError("Cannot cache an empty stack")
    _, base_id = base_inventory(model_dir, variant)
    for adapter in adapters:
        if adapter["base_inventory_id"] != base_id or adapter["base_variant"] != variant:
            raise ValueError("H3 base changed since adapter capture")
        if sha256_file(Path(adapter["path"])) != adapter["sha256"]:
            raise ValueError("Captured LoRA changed before cache lookup")
    key = overlay_cache_key(adapters, model_dir, variant, base_id)
    folder = cache_root.resolve() / key
    folder.mkdir(parents=True, exist_ok=True)
    output, record = folder / "overlay.safetensors", folder / "result.json"
    progress("Waiting for shared LoRA weight cache")
    with json_file_lock(record):
        if canceled():
            raise ValueError("LoRA composition canceled")
        if record.is_file() and output.is_file():
            progress("Verifying cached LoRA weights (no recomposition)")
            try:
                result = json.loads(record.read_text())
                valid = (result["cache_key"] == key and result["base_inventory_id"] == base_id
                         and result["bytes"] == output.stat().st_size
                         and result["sha256"] == sha256_file(output))
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
            if valid:
                if canceled():
                    raise ValueError("LoRA composition canceled")
                if overlay_cache_key(adapters, model_dir, variant, base_id) != key:
                    raise ValueError("H3 base changed during cache verification")
                return {**result, "path": str(output), "cache_hit": True}
            progress("Cached weights failed verification; rebuilding derived file")
        result = compile_overlay(adapters, model_dir, variant, output, progress, canceled)
        if overlay_cache_key(adapters, model_dir, variant, base_id) != key:
            raise ValueError("H3 base changed during cache composition")
        result = {**result, "cache_key": key, "cache_hit": False}
        atomic_write_json(record, result)
        return result
