import hashlib
import json
from pathlib import Path

from PIL import Image

from lorasuite_engine.models import MediaType
from lorasuite_engine.vault import VaultService


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_image(path: Path, size: tuple[int, int] = (23, 31)) -> Path:
    Image.new("RGB", size, color=(19, 73, 121)).save(path)
    return path


def test_import_local_image_copies_file_and_records_metadata(tmp_path):
    source_path = make_image(tmp_path / "Reference.PNG")
    vault_root = tmp_path / "vault"
    expected_sha256 = file_sha256(source_path)

    result = VaultService(vault_root).import_local_paths([source_path])

    assert result.errors == []
    media_items = result.media_items
    assert len(media_items) == 1
    media_item = media_items[0]
    raw_path = vault_root / "raw" / f"{expected_sha256}.png"
    assert raw_path.read_bytes() == source_path.read_bytes()
    assert media_item.raw_path == raw_path
    assert media_item.media_type == MediaType.IMAGE
    assert media_item.sha256 == expected_sha256
    assert media_item.width == 23
    assert media_item.height == 31
    assert media_item.metadata_json["original_path"] == str(source_path)

    vault_manifest = json.loads((vault_root / "vault.json").read_text())
    assert vault_manifest["sources"][0]["kind"] == "local"
    assert vault_manifest["sources"][0]["download_tool"] == "local-import"
    assert vault_manifest["media_items"][0]["raw_path"] == str(raw_path)
    assert vault_manifest["media_items"][0]["metadata_json"]["original_path"] == str(
        source_path
    )


def test_import_rejects_unsupported_suffix(tmp_path):
    unsupported_path = tmp_path / "notes.txt"
    unsupported_path.write_text("SECRET_TOKEN=do-not-store", encoding="utf-8")
    vault_root = tmp_path / "vault"

    result = VaultService(vault_root).import_local_paths([unsupported_path])

    assert result.media_items == []
    assert result.errors[0].code == "unsupported_suffix"
    assert not (vault_root / "raw").exists()
    manifest_path = vault_root / "vault.json"
    if manifest_path.exists():
        assert "SECRET_TOKEN" not in manifest_path.read_text(encoding="utf-8")


def test_import_missing_supported_file_skips_with_error_without_manifest(tmp_path):
    missing_path = tmp_path / "missing.png"
    vault_root = tmp_path / "vault"

    result = VaultService(vault_root).import_local_paths([missing_path])

    assert result.media_items == []
    assert result.errors[0].path == str(missing_path)
    assert result.errors[0].code == "missing_path"
    assert not (vault_root / "raw").exists()
    assert not (vault_root / "vault.json").exists()


def test_import_corrupt_png_skips_with_error_without_manifest(tmp_path):
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"not a png")
    vault_root = tmp_path / "vault"

    result = VaultService(vault_root).import_local_paths([corrupt_path])

    assert result.media_items == []
    assert result.errors[0].path == str(corrupt_path)
    assert result.errors[0].code == "unreadable_image"
    assert not (vault_root / "raw").exists()
    assert not (vault_root / "vault.json").exists()


def test_import_mixed_valid_and_invalid_records_error_for_invalid_only(tmp_path):
    valid_path = make_image(tmp_path / "valid.png")
    invalid_path = tmp_path / "invalid.png"
    invalid_path.write_bytes(b"not a png")
    vault_root = tmp_path / "vault"
    expected_sha256 = file_sha256(valid_path)

    result = VaultService(vault_root).import_local_paths([valid_path, invalid_path])

    assert len(result.media_items) == 1
    assert result.media_items[0].sha256 == expected_sha256
    assert len(result.errors) == 1
    assert result.errors[0].path == str(invalid_path)
    assert result.errors[0].code == "unreadable_image"

    manifest = json.loads((vault_root / "vault.json").read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 1
    assert len(manifest["media_items"]) == 1
    assert manifest["media_items"][0]["sha256"] == expected_sha256
    assert sorted(path.name for path in (vault_root / "raw").iterdir()) == [
        f"{expected_sha256}.png"
    ]


def test_import_duplicate_sha_returns_existing_media_without_appending(tmp_path):
    source_path = make_image(tmp_path / "duplicate.png")
    vault_root = tmp_path / "vault"
    service = VaultService(vault_root)

    first_result = service.import_local_paths([source_path])
    second_result = service.import_local_paths([source_path])

    assert len(first_result.media_items) == 1
    assert len(second_result.media_items) == 1
    assert second_result.media_items[0].id == first_result.media_items[0].id
    assert second_result.errors == []

    manifest = json.loads((vault_root / "vault.json").read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 1
    assert len(manifest["media_items"]) == 1


def test_import_preserves_unknown_manifest_top_level_keys(tmp_path):
    source_path = make_image(tmp_path / "schema.png")
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "vault.json").write_text(
        json.dumps({"schema_version": 1, "sources": [], "media_items": []}),
        encoding="utf-8",
    )

    result = VaultService(vault_root).import_local_paths([source_path])

    assert len(result.media_items) == 1
    manifest = json.loads((vault_root / "vault.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert len(manifest["media_items"]) == 1
