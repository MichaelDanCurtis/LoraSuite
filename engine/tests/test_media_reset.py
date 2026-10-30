import json
from pathlib import Path

import pytest

from lorasuite_engine.media_reset import MediaResetService


def test_clear_all_media_removes_media_state_but_preserves_models(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "raw" / "image.jpg").write_bytes(b"image")
    (vault / "previews").mkdir()
    (vault / "previews" / "thumb.jpg").write_bytes(b"thumb")
    (vault / "models" / "identity").mkdir(parents=True)
    (vault / "models" / "identity" / "model.bin").write_bytes(b"model")
    (vault / "vault.json").write_text('{"media_items": []}', encoding="utf-8")
    (vault / "character_projects.json").write_text('{"projects": []}', encoding="utf-8")
    (vault / "model_artifacts.json").write_text('{"artifacts": []}', encoding="utf-8")

    result = MediaResetService(vault).clear_all_media()

    assert result["status"] == "cleared"
    assert result["files_removed"] == 4
    assert not (vault / "raw").exists()
    assert not (vault / "previews").exists()
    assert not (vault / "vault.json").exists()
    assert not (vault / "character_projects.json").exists()
    assert (vault / "models" / "identity" / "model.bin").read_bytes() == b"model"
    assert (vault / "model_artifacts.json").exists()


def test_clear_all_media_refuses_active_jobs(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "ingress_jobs.json").write_text(
        json.dumps({"jobs": [{"id": "job", "status": "running"}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="active"):
        MediaResetService(vault).clear_all_media()

    assert (vault / "ingress_jobs.json").exists()
