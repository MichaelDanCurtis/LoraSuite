import json
import struct
from pathlib import Path

from lorasuite_engine.model_metadata import build_snapshot_model_card
from lorasuite_engine.models import DatasetBalance, DatasetSnapshot
from lorasuite_engine.safetensors_metadata import (
    embed_safetensors_metadata,
    model_card_safetensors_metadata,
    read_safetensors_metadata,
)
from lorasuite_engine.training_targets import get_training_target_profile


def test_rewrites_safetensors_atomically_and_preserves_tensor_bytes(tmp_path: Path):
    checkpoint = tmp_path / "person.safetensors"
    tensor_bytes = bytes(range(24))
    header = json.dumps({
        "__metadata__": {"existing": "preserved"},
        "tensor": {
            "dtype": "F32",
            "shape": [2, 3],
            "data_offsets": [0, 24],
        },
    }).encode("utf-8")
    checkpoint.write_bytes(struct.pack("<Q", len(header)) + header + tensor_bytes)

    first = embed_safetensors_metadata(
        checkpoint,
        {"lorasuite.trigger_token": "person_token"},
    )
    rewritten = checkpoint.read_bytes()
    rewritten_header_size = struct.unpack("<Q", rewritten[:8])[0]
    second = embed_safetensors_metadata(
        checkpoint,
        {"lorasuite.trigger_token": "person_token"},
    )

    assert first.changed is True
    assert second.changed is False
    assert rewritten[8 + rewritten_header_size:] == tensor_bytes
    assert read_safetensors_metadata(checkpoint) == {
        "existing": "preserved",
        "lorasuite.trigger_token": "person_token",
    }


def test_builds_flat_and_canonical_model_card_metadata():
    target = get_training_target_profile("runcomfy_flux1_dev_character")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Person",
        training_target=target.spec(),
        balance=DatasetBalance(approved_count=35, source_count=3),
        fingerprint="dataset-fingerprint",
    )
    snapshot.intent.subject_name = "Person"
    snapshot.intent.trigger_token = "person_token"
    card = build_snapshot_model_card(snapshot)

    metadata = model_card_safetensors_metadata(
        card,
        artifact_id="artifact-1",
        training_run_id="run-1",
        source_checkpoint_sha256="source-sha",
    )
    embedded_card = json.loads(metadata["lorasuite.model_card"])

    assert metadata["lorasuite.trigger_token"] == "person_token"
    assert metadata["lorasuite.base_model"] == "black-forest-labs/FLUX.1-dev"
    assert metadata["lorasuite.dataset_fingerprint"] == "dataset-fingerprint"
    assert metadata["ss_network_dim"] == "16"
    assert embedded_card["artifact"]["source_checkpoint_sha256"] == "source-sha"
