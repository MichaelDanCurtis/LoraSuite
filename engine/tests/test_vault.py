import hashlib
import json
from pathlib import Path

from PIL import Image

from lorasuite_engine.models import DerivativeType, MediaItem, MediaStatus, MediaType
from lorasuite_engine.vault import VaultService, VaultSnapshotConflict


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


def test_import_local_image_applies_exif_orientation_to_dimensions(tmp_path):
    source_path = tmp_path / "sideways.jpg"
    image = Image.new("RGB", (23, 31), color=(19, 73, 121))
    exif = Image.Exif()
    exif[274] = 6
    image.save(source_path, exif=exif)

    result = VaultService(tmp_path / "vault").import_local_paths([source_path])

    assert result.errors == []
    assert result.media_items[0].width == 31
    assert result.media_items[0].height == 23


def test_import_dng_normalizes_to_training_ready_jpeg_and_preserves_provenance(
    tmp_path, monkeypatch
):
    source_path = tmp_path / "portrait.dng"
    source_path.write_bytes(b"deterministic camera raw")
    source_sha256 = file_sha256(source_path)

    monkeypatch.setattr(
        "lorasuite_engine.vault.raw_image_dimensions",
        lambda path: (4032, 3024),
    )

    def fake_materialize(source, output):
        assert source == source_path
        Image.new("RGB", (4032, 3024), color=(90, 42, 18)).save(output, "JPEG")
        return output

    monkeypatch.setattr("lorasuite_engine.vault.materialize_raw_image", fake_materialize)
    service = VaultService(tmp_path / "vault")

    first = service.import_local_paths([source_path])
    second = service.import_local_paths([source_path])

    assert first.errors == []
    assert second.errors == []
    assert len(first.media_items) == 1
    imported = first.media_items[0]
    assert second.media_items[0].id == imported.id
    assert imported.raw_path.suffix == ".jpg"
    assert imported.raw_path.is_file()
    assert imported.sha256 == file_sha256(imported.raw_path)
    assert imported.width == 4032
    assert imported.height == 3024
    assert imported.metadata_json["original_path"] == str(source_path)
    assert imported.metadata_json["original_format"] == ".dng"
    assert imported.metadata_json["source_sha256"] == source_sha256
    assert imported.metadata_json["normalized_from_raw"] is True

    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["media_items"]) == 1


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


def test_import_duplicate_content_from_different_paths_retains_provenance_cluster(tmp_path):
    first_path = make_image(tmp_path / "first.png")
    second_path = tmp_path / "second.png"
    second_path.write_bytes(first_path.read_bytes())
    service = VaultService(tmp_path / "vault")

    first = service.import_local_paths([first_path]).media_items[0]
    second = service.import_local_paths([second_path]).media_items[0]

    assert second.id == first.id
    assert second.metadata_json["original_paths"] == sorted(
        [str(first_path), str(second_path)]
    )
    clusters = service.list_exact_duplicate_clusters()
    assert len(clusters) == 1
    assert clusters[0].canonical_media_item_id == first.id
    assert clusters[0].duplicate_count == 1
    assert clusters[0].original_paths == sorted([str(first_path), str(second_path)])


def test_append_consolidates_source_duplicates_but_not_derivative_lineage(tmp_path):
    source_path = make_image(tmp_path / "source.png")
    duplicate_path = tmp_path / "duplicate.png"
    duplicate_path.write_bytes(source_path.read_bytes())
    service = VaultService(tmp_path / "vault")
    source = service.import_local_paths([source_path]).media_items[0]
    duplicate = MediaItem(
        source_id="source_social",
        raw_path=duplicate_path,
        media_type=MediaType.IMAGE,
        sha256=source.sha256,
        metadata_json={"source_bundle_key": "instagram:post:one"},
    )
    derivative = service.build_derivative_media_item(
        source_item=source,
        derivative_path=duplicate_path,
        media_type=MediaType.IMAGE,
        derivative_type=DerivativeType.FACE_CROP,
    )

    resolved_source, resolved_derivative = service.append_media_items(
        [duplicate, derivative]
    )

    assert resolved_source.id == source.id
    assert resolved_derivative.id == derivative.id
    assert len(service.list_media_items()) == 2
    assert service.get_media_item(source.id).metadata_json["source_bundle_keys"] == [
        "instagram:post:one"
    ]


def test_query_media_items_pages_filters_and_searches_a_stable_snapshot(tmp_path):
    service = VaultService(tmp_path / "vault")
    items = [
        MediaItem(
            id=f"media_{index:04d}",
            source_id="source_bulk",
            raw_path=tmp_path / f"item-{index:04d}.png",
            media_type=MediaType.VIDEO if index % 5 == 0 else MediaType.IMAGE,
            sha256=f"{index:064x}",
            status=MediaStatus.IGNORED if index == 19 else MediaStatus.NEW,
            metadata_json={"caption": f"candidate {index:04d}"},
        )
        for index in range(5000)
    ]
    service.append_media_items(items)

    first = service.query_media_items(offset=0, limit=500)
    second = service.query_media_items(
        offset=first.next_offset or 0,
        limit=500,
        snapshot=first.snapshot,
    )
    videos = service.query_media_items(media_type=MediaType.VIDEO, limit=500)
    searched = service.query_media_items(search="candidate 0999", limit=10)

    assert first.total == 4999
    assert len(first.items) == 500
    assert first.has_more is True
    assert first.next_offset == 500
    assert second.snapshot == first.snapshot
    assert second.items[0].id == "media_0501"
    assert videos.total == 1000
    assert all(item.media_type == MediaType.VIDEO for item in videos.items)
    assert [item.id for item in searched.items] == ["media_0999"]


def test_query_media_items_rejects_a_stale_snapshot(tmp_path):
    service = VaultService(tmp_path / "vault")
    first = MediaItem(
        id="media_first",
        source_id="source_bulk",
        raw_path=tmp_path / "first.png",
        media_type=MediaType.IMAGE,
        sha256="a" * 64,
    )
    service.append_media_items([first])
    page = service.query_media_items(limit=1)
    service.append_media_items(
        [
            MediaItem(
                id="media_second",
                source_id="source_bulk",
                raw_path=tmp_path / "second.png",
                media_type=MediaType.IMAGE,
                sha256="b" * 64,
            )
        ]
    )

    try:
        service.query_media_items(offset=1, limit=1, snapshot=page.snapshot)
    except VaultSnapshotConflict as error:
        assert "changed" in str(error)
    else:
        raise AssertionError("stale snapshots must not mix vault versions")


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


def test_rotate_image_updates_the_existing_manifest_item(tmp_path):
    source_path = make_image(tmp_path / "sideways.png", size=(40, 20))
    service = VaultService(tmp_path / "vault")
    imported = service.import_local_paths([source_path]).media_items[0]

    rotated = service.rotate_image(imported.id, 90)

    assert rotated.id == imported.id
    assert (rotated.width, rotated.height) == (20, 40)
    assert rotated.raw_path != imported.raw_path
    assert rotated.raw_path.exists()
    assert rotated.metadata_json["orientation_corrected"] is True
    assert rotated.metadata_json["rotation_degrees"] == 90
    restored = service.get_media_item(imported.id)
    assert restored is not None
    assert restored.raw_path == rotated.raw_path
    assert len(service.list_media_items()) == 1
