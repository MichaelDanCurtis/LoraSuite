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

    media_items = VaultService(vault_root).import_local_paths([source_path])

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

    media_items = VaultService(vault_root).import_local_paths([unsupported_path])

    assert media_items == []
    assert not (vault_root / "raw").exists()
    manifest_path = vault_root / "vault.json"
    if manifest_path.exists():
        assert "SECRET_TOKEN" not in manifest_path.read_text(encoding="utf-8")
