import json
import subprocess
import sys

from fastapi.testclient import TestClient

from lorasuite_engine.api import create_app
from lorasuite_engine.library_bridge import LibraryBridge


def test_old_registrations_and_saved_scenes_are_inert(tmp_path, monkeypatch):
    saved = {
        "library_runtime.json": {"runtime": "/old/lm", "pin": "old", "autostart": True},
        "h3_scenes.json": {"scenes": {"saved": {"subject": "Preserved"}}},
        "h3_native_runs.json": {"runs": {"saved": {"status": "interrupted"}}},
        "h3_native_config.json": {"model_dir": "/saved/models"},
    }
    for name, data in saved.items():
        (tmp_path / name).write_text(json.dumps(data))
    original = {name: (tmp_path / name).read_bytes() for name in saved}

    def cannot_spawn(*args, **kwargs):
        raise AssertionError("Startup/shutdown must not launch a retired service")

    monkeypatch.setattr(subprocess, "Popen", cannot_spawn)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 200
        routes = client.get("/openapi.json").json()["paths"]
        assert not any(path.startswith(("/h3-", "/library/runtime")) for path in routes)
        for path in ("/h3-native/runs", "/h3-scenes", "/library/runtime/start",
                     "/library/runtime/stop", "/library/runtime/config"):
            assert client.post(path, json={"autostart": True}).status_code == 404
        assert client.post("/library/config", json={"port": 8190}).json() == {"port": 8190}
    assert {name: (tmp_path / name).read_bytes() for name in saved} == original
    assert "lorasuite_engine.library_runtime" not in sys.modules
    assert "lorasuite_engine.h3_native" not in sys.modules


def test_external_library_browsing_does_not_require_our_export_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(LibraryBridge, "manager", lambda self, **kwargs:
                        {"roots": [str(tmp_path / "independent-models")]} if kwargs.get("roots") else {"items": []})
    with TestClient(create_app(tmp_path)) as client:
        status = client.get("/library/status").json()
        assert status["ready"] is True
        assert status["port"] == 8188
        assert status["export_ready"] is False
        assert status["export_issue"]
        assert "runtime" not in status and "upstream_pin" not in status
    assert not (tmp_path / "library_runtime.json").exists()


def test_export_folder_can_be_under_an_external_library_root(tmp_path, monkeypatch):
    monkeypatch.setattr(LibraryBridge, "manager", lambda self, **kwargs:
                        {"roots": [str(tmp_path)]} if kwargs.get("roots") else {"items": []})
    with TestClient(create_app(tmp_path)) as client:
        status = client.get("/library/status").json()
        assert status["ready"] and status["export_ready"]
        assert status["export_issue"] == ""


def test_disconnected_manager_has_no_hosting_fallback(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("Offline")

    monkeypatch.setattr(LibraryBridge, "manager", unavailable)
    with TestClient(create_app(tmp_path)) as client:
        status = client.get("/library/status").json()
        assert not status["ready"] and not status["export_ready"]
        assert "Open it separately" in status["issue"]
