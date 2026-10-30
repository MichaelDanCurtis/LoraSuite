import json
import shutil
from pathlib import Path

from PIL import Image

from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.vault import sha256_file


def test_registers_image_export_without_reconstructing_editable_state(tmp_path):
    export = _image_export(tmp_path / "export")
    service = RecoveredDatasetService(tmp_path / "vault")

    record = service.register(export)
    repeated = service.register(export)

    assert repeated.id == record.id
    assert record.ready is True
    assert record.integrity_status == "verified"
    assert record.project_id == "project-1"
    assert record.snapshot_id == "snapshot-1"
    assert record.fingerprint == "fingerprint-1"
    assert record.fingerprint_source == "manifest"
    assert record.training_target.profile_id == "runcomfy_flux1_dev_character"
    assert record.trigger_token == "person_token"
    assert record.trigger_token_source == "caption_consensus"
    assert record.file_count == 2
    assert record.verified_file_count == 2
    assert service.find_by_snapshot_id("snapshot-1").id == record.id
    assert len(service.list_exports()) == 1


def test_recovers_relocated_export_with_stale_absolute_manifest_paths(tmp_path):
    original = _image_export(tmp_path / "original")
    relocated = tmp_path / "relocated"
    shutil.copytree(original, relocated)
    shutil.rmtree(original)

    record = RecoveredDatasetService(tmp_path / "vault").register(relocated)

    assert record.ready is True
    assert record.verified_file_count == 2


def test_marks_recovered_export_failed_when_content_no_longer_matches_manifest(tmp_path):
    export = _image_export(tmp_path / "export")
    (export / "images" / "000001.png").write_bytes(b"changed")

    record = RecoveredDatasetService(tmp_path / "vault").register(export)

    assert record.ready is False
    assert record.integrity_status == "failed"
    assert record.verified_file_count == 1
    assert record.errors == ["Checksum mismatch for 000001.png."]


def _image_export(root: Path) -> Path:
    images = root / "images"
    images.mkdir(parents=True)
    entries = []
    for index, caption in enumerate(
        [
            "person_token, person, close-up portrait, front view",
            "person_token, person, full-body photo, profile view",
        ],
        start=1,
    ):
        image = images / f"{index:06d}.png"
        text = images / f"{index:06d}.txt"
        Image.new("RGB", (32, 32), (index * 50, 20, 10)).save(image)
        text.write_text(caption + "\n", encoding="utf-8")
        entries.append({
            "image": str(image),
            "caption": str(text),
            "caption_text": caption,
            "sha256": sha256_file(image),
            "dataset_item_id": f"item-{index}",
        })
    (root / "manifest.json").write_text(json.dumps({
        "created_by": "LoraSuite",
        "export_type": "runcomfy_image",
        "character_project_id": "project-1",
        "dataset_snapshot_id": "snapshot-1",
        "dataset_version": 2,
        "dataset_fingerprint": "fingerprint-1",
        "training_target": {
            "profile_id": "runcomfy_flux1_dev_character",
        },
        "files": entries,
    }, indent=2), encoding="utf-8")
    return root
