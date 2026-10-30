import json
import struct
from pathlib import Path

import numpy as np
import pytest

from lorasuite_engine.h3_lora import H3LoRAImport, H3LoRAService, H3LoRASlot, SafeFile, adapter_pairs, bf16, compile_overlay, cached_overlay

NAME = "blocks.0.attn.out_proj"


def write_tensors(path, tensors, dtype="F32"):
    path.parent.mkdir(parents=True, exist_ok=True)
    header, payload = {}, b""
    for name, values in tensors.items():
        values = np.asarray(values, dtype="<f4")
        data = bf16(values) if dtype == "BF16" else values.tobytes()
        header[name] = {"dtype": dtype, "shape": list(values.shape), "data_offsets": [len(payload), len(payload) + len(data)]}
        payload += data
    encoded = json.dumps(header).encode()
    encoded += b" " * (-len(encoded) % 8)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)
    return path


@pytest.fixture
def stack(tmp_path):
    models = tmp_path / "models"
    write_tensors(models / "FL2VA/transformer/base.safetensors", {NAME + ".weight": np.ones((4, 3))}, "BF16")
    service = H3LoRAService(tmp_path / "vault")
    a = np.array([[1, 2, 3], [2, 0, -1]], dtype=np.float32)
    b = np.array([[1, 2], [0, 1], [2, 1], [-1, 0]], dtype=np.float32)
    adapters = []
    for index in range(2):
        path = write_tensors(tmp_path / f"adapter{index}.safetensors", {NAME + ".lora_A.weight": a, NAME + ".lora_B.weight": b * (index + 1)})
        adapters.append(service.import_adapter(H3LoRAImport(path=str(path), label=f"Fixture {index}", base_variant="FL2VA", provenance="Synthetic unit test, not a trained adapter"), models))
    directory = tmp_path / "run"
    directory.mkdir()
    return service, models, adapters, directory, a, b


def test_two_adapter_strengths_sum_before_rounding_and_preserve_base(stack):
    service, models, adapters, directory, a, b = stack
    base = models / "FL2VA/transformer/base.safetensors"
    before = base.read_bytes()
    slots = [H3LoRASlot(adapter_id=adapters[0]["id"], strength=0.5), H3LoRASlot(adapter_id=adapters[1]["id"], strength=-0.125)]
    captured = service.capture(slots, "FL2VA", models, directory)
    output = directory / "overlay.safetensors"
    messages = []
    result = compile_overlay(captured, models, "FL2VA", output, messages.append)
    np.testing.assert_array_equal(SafeFile(output).read(NAME + ".weight"), 1 + 0.25 * (b @ a))
    assert result["tensor_count"] == 1 and messages
    assert base.read_bytes() == before
    assert H3LoRAService(service.root).list() == service.list()
    assert all(Path(item["path"]).parent == directory for item in captured)


def test_disabled_and_zero_do_not_load(stack):
    service, models, adapters, directory, *_ = stack
    assert service.capture([H3LoRASlot(adapter_id=adapters[0]["id"], enabled=False), H3LoRASlot(adapter_id=adapters[1]["id"], strength=0)], "Ref2VA", models, directory) == []


def test_overlay_cache_reuses_and_invalidates(stack, monkeypatch):
    service, models, adapters, directory, *_ = stack
    captured = service.capture([H3LoRASlot(adapter_id=adapters[0]["id"])], "FL2VA", models, directory)
    cache = directory / "cache"
    first = cached_overlay(captured, models, "FL2VA", cache)
    second = cached_overlay(captured, models, "FL2VA", cache)
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert first["path"] == second["path"] and first["sha256"] == second["sha256"]
    # Changing strength cannot reuse a different stack's file.
    changed = cached_overlay([{**captured[0], "strength": .5}], models, "FL2VA", cache)
    assert not changed["cache_hit"] and changed["path"] != first["path"]
    # Corruption never becomes a successful cache hit.
    Path(first["path"]).write_bytes(b"bad")
    repaired = cached_overlay(captured, models, "FL2VA", cache)
    assert not repaired["cache_hit"] and repaired["sha256"] == first["sha256"]
    with pytest.raises(ValueError, match="canceled"):
        cached_overlay(captured, models, "FL2VA", cache, canceled=lambda: True)
    Path(captured[0]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        cached_overlay(captured, models, "FL2VA", cache)



def test_wrong_base_and_modified_adapter_rejected(stack):
    service, models, adapters, directory, *_ = stack
    slot = H3LoRASlot(adapter_id=adapters[0]["id"])
    with pytest.raises(ValueError):
        service.capture([slot], "Ref2VA", models, directory)
    Path(adapters[0]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        service.capture([slot], "FL2VA", models, directory)


def test_cancellation_removes_partial_output(stack):
    service, models, adapters, directory, *_ = stack
    captured = service.capture([H3LoRASlot(adapter_id=adapters[0]["id"])], "FL2VA", models, directory)
    with pytest.raises(ValueError, match="canceled"):
        compile_overlay(captured, models, "FL2VA", directory / "overlay.safetensors", canceled=lambda: True)
    assert not (directory / "overlay.safetensors").exists()
    assert not (directory / "overlay.partial").exists()


def test_changed_base_rejected_before_composition(stack):
    service, models, adapters, directory, *_ = stack
    captured = service.capture([H3LoRASlot(adapter_id=adapters[0]["id"])], "FL2VA", models, directory)
    write_tensors(models / "FL2VA/transformer/base.safetensors", {NAME + ".weight": np.zeros((4, 3))}, "BF16")
    with pytest.raises(ValueError, match="base changed"):
        compile_overlay(captured, models, "FL2VA", directory / "overlay.safetensors")


def test_explicit_alpha_uses_alpha_over_rank(tmp_path):
    source = SafeFile(write_tensors(tmp_path / "a.safetensors", {NAME + ".lora_A.default.weight": np.ones((2, 3)), NAME + ".lora_B.default.weight": np.ones((4, 2)), NAME + ".alpha": np.array(4)}))
    assert adapter_pairs(source)[NAME]["scale"] == 2


@pytest.mark.parametrize("suffix", ["", ".default"])
def test_prefixed_adapter_import_and_stack_preserve_alpha_and_original_files(stack, tmp_path, suffix):
    service, models, adapters, directory, a, b = stack
    prefix = "diffusion_model." + NAME
    path = write_tensors(tmp_path / "prefixed.safetensors", {
        prefix + f".lora_A{suffix}.weight": a,
        prefix + f".lora_B{suffix}.weight": b,
        prefix + ".alpha": np.array(4),
    })
    original = path.read_bytes()
    pairs = adapter_pairs(SafeFile(path))
    assert set(pairs) == {NAME}
    assert pairs[NAME]["A"] == prefix + f".lora_A{suffix}.weight"
    assert pairs[NAME]["scale"] == 2
    imported = service.import_adapter(H3LoRAImport(path=str(path), label="Prefixed fixture", base_variant="FL2VA", provenance="Synthetic test"), models)
    captured = service.capture([H3LoRASlot(adapter_id=adapters[0]["id"], strength=.5), H3LoRASlot(adapter_id=imported["id"], strength=.25)], "FL2VA", models, directory)
    output = directory / "prefixed-overlay.safetensors"
    compile_overlay(captured, models, "FL2VA", output)
    np.testing.assert_array_equal(SafeFile(output).read(NAME + ".weight"), 1 + b @ a)
    assert path.read_bytes() == original
    assert Path(imported["path"]).read_bytes() == original


@pytest.mark.parametrize("tensors,pattern", [
    ({"diffusion_model." + NAME + ".lora_A.weight": np.ones((2, 3)), NAME + ".lora_B.weight": np.ones((4, 2))}, "Ambiguous"),
    ({"diffusion_model." + NAME + ".lora_A.weight": np.ones((2, 3)), NAME + ".lora_A.weight": np.ones((2, 3))}, "Ambiguous"),
    ({"diffusion_model.diffusion_model." + NAME + ".lora_A.weight": np.ones((2, 3))}, "Unsupported H3"),
    ({"other." + NAME + ".lora_A.weight": np.ones((2, 3))}, "Unsupported H3"),
    ({"diffusion_model.blocks.50.attn.out_proj.lora_A.weight": np.ones((2, 3))}, "Unsupported H3"),
    ({"diffusion_model." + NAME + ".lora_A.weight": np.ones((2, 3)), "diffusion_model." + NAME + ".lora_B.weight": np.ones((4, 2)), NAME + ".alpha": np.array(4)}, "unused alpha"),
])
def test_prefix_normalization_fails_closed(tmp_path, tensors, pattern):
    with pytest.raises(ValueError, match=pattern):
        adapter_pairs(SafeFile(write_tensors(tmp_path / "bad-prefix.safetensors", tensors)))


@pytest.mark.parametrize("tensors,pattern", [
    ({NAME + ".lora_A.weight": np.ones((2, 3))}, "Incomplete"),
    ({"transformer_blocks.0.attn.to_q.lora_A.weight": np.ones((2, 3))}, "Unsupported H3"),
    ({NAME + ".lora_A.weight": np.ones((2, 3)), NAME + ".lora_B.weight": np.ones((4, 3))}, "rank"),
    ({"blocks.50.attn.out_proj.lora_A.weight": np.ones((2, 3))}, "Unsupported H3"),
    ({NAME + ".lora_magnitude_vector.weight": np.ones((2, 3))}, "Unsupported LoRA"),
])
def test_unsupported_adapters_fail_closed(tmp_path, tensors, pattern):
    with pytest.raises(ValueError, match=pattern):
        adapter_pairs(SafeFile(write_tensors(tmp_path / "a.safetensors", tensors)))


@pytest.mark.parametrize("strength", [float("nan"), float("inf"), -2.1, 2.1])
def test_nonfinite_or_out_of_range_strength_rejected(strength):
    with pytest.raises(ValueError):
        H3LoRASlot(adapter_id="h3_lora_" + "a" * 24, strength=strength)


def test_nonfinite_import_and_shape_mismatch(stack, tmp_path):
    service, models, *_ = stack
    for values, message in [(np.full((4, 2), np.nan), "Non-finite"), (np.ones((5, 2)), "does not match")]:
        path = write_tensors(tmp_path / "bad.safetensors", {NAME + ".lora_A.weight": np.ones((2, 3)), NAME + ".lora_B.weight": values})
        with pytest.raises(ValueError, match=message):
            service.import_adapter(H3LoRAImport(path=str(path), label="Bad", base_variant="FL2VA", provenance="Test"), models)


def test_malformed_safetensors_rejected(tmp_path):
    path = tmp_path / "bad.safetensors"
    for data in (b"bad", struct.pack("<Q", 2**40), struct.pack("<Q", 13) + b'{"a":1,"a":2}'):
        path.write_bytes(data)
        with pytest.raises(ValueError):
            SafeFile(path)
