import hashlib
from pathlib import Path

from PIL import Image

from lorasuite_engine.api import create_app


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lorasuite-engine"}


def test_create_app_uses_env_vault_root(monkeypatch, tmp_path):
    vault_root = tmp_path / "env-vault"
    monkeypatch.setenv("LORASUITE_VAULT_ROOT", str(vault_root))

    app = create_app()

    assert app.state.vault_root == vault_root


def test_import_local_image_endpoint_copies_file_and_returns_media_items(client, tmp_path):
    image_path = tmp_path / "api-image.png"
    Image.new("RGB", (17, 29), color=(93, 10, 47)).save(image_path)
    expected_sha256 = file_sha256(image_path)

    response = client.post("/vault/import/local", json={"paths": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["media_items"]) == 1
    media_item = payload["media_items"][0]
    raw_path = Path(media_item["raw_path"])
    assert raw_path.name == f"{expected_sha256}.png"
    assert raw_path.read_bytes() == image_path.read_bytes()
    assert media_item["media_type"] == "image"
    assert media_item["sha256"] == expected_sha256
    assert media_item["width"] == 17
    assert media_item["height"] == 29
    assert media_item["metadata_json"]["original_path"] == str(image_path)
