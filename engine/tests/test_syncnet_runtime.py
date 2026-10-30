from pathlib import Path
from subprocess import CompletedProcess

from lorasuite_engine.syncnet_adapter import evaluate, parse_metrics
from lorasuite_engine.syncnet_runtime import syncnet_capability, syncnet_command


def test_parses_canonical_syncnet_log_metrics() -> None:
    metrics = parse_metrics("AV offset:  -2\nMin dist:  7.125\nConfidence:  4.750\n")
    assert metrics == {"lse_c": 4.75, "lse_d": 7.125, "offset_frames": -2}


def test_adapter_invokes_canonical_demo_and_emits_lorasuite_contract(tmp_path: Path) -> None:
    repository = tmp_path / "syncnet"
    repository.mkdir()
    (repository / "demo_syncnet.py").write_text("# fixture\n")
    model = repository / "syncnet_v2.model"
    model.write_bytes(b"model")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    captured = {}

    def runner(command, **options):
        captured["command"] = command
        captured["options"] = options
        return CompletedProcess(command, 0, stdout="", stderr="AV offset: 1\nMin dist: 6.8\nConfidence: 5.4\n")

    metrics = evaluate(repository, model, video, runner=runner)

    assert metrics == {"lse_c": 5.4, "lse_d": 6.8, "offset_frames": 1}
    assert captured["command"][1] == str(repository / "demo_syncnet.py")
    assert captured["options"]["cwd"] == repository
    assert captured["options"]["shell"] is False


def test_reports_canonical_runtime_readiness_and_builds_adapter_command(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "syncnet"
    (repository / "data").mkdir(parents=True)
    (repository / "demo_syncnet.py").write_text("# fixture\n")
    (repository / "SyncNetInstance.py").write_text("# fixture\n")
    model = repository / "data" / "syncnet_v2.model"
    model.write_bytes(b"model")
    python = repository / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    monkeypatch.delenv("LORASUITE_SYNCNET_COMMAND", raising=False)
    monkeypatch.setenv("LORASUITE_SYNCNET_REPO", str(repository))
    monkeypatch.setattr("lorasuite_engine.syncnet_runtime.shutil.which", lambda name: f"/usr/bin/{name}")

    status = syncnet_capability()
    command = syncnet_command()

    assert status.ready is True
    assert status.mode == "canonical"
    assert command is not None
    assert command[-1] == "{video}"
    assert "lorasuite_engine.syncnet_adapter" in command
    assert "--python" in command
    assert str(python) in command


def test_reports_missing_syncnet_configuration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LORASUITE_SYNCNET_COMMAND", raising=False)
    monkeypatch.delenv("LORASUITE_SYNCNET_REPO", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    status = syncnet_capability()
    assert status.ready is False
    assert status.mode == "unconfigured"
    assert status.problems
