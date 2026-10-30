from __future__ import annotations

import os

import pytest

from lorasuite_engine.sidecar import _parse_args, _process_is_alive, _watch_parent, _watch_packaged_launcher


@pytest.mark.parametrize("arguments", [
    ["--library-supervisor", "python", "server", "settings", "8189"],
    ["--h3-supervisor", "/saved/run", "3"],
])
def test_retired_supervisor_commands_are_rejected(arguments):
    with pytest.raises(SystemExit):
        _parse_args(arguments)


def test_process_is_alive_detects_the_current_process() -> None:
    assert _process_is_alive(os.getpid()) is True


def test_process_is_alive_rejects_invalid_process_ids() -> None:
    assert _process_is_alive(0) is False
    assert _process_is_alive(-1) is False


def test_process_is_alive_detects_a_missing_process() -> None:
    process_id = max(os.getpid() + 100_000, 9_000_000)
    while _process_is_alive(process_id):
        process_id += 100_000
    assert _process_is_alive(process_id) is False


def test_watch_parent_exits_after_the_parent_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter([True, True, False])
    exit_codes: list[int] = []
    monkeypatch.setattr("lorasuite_engine.sidecar.time.sleep", lambda _: None)

    _watch_parent(
        42,
        process_is_alive=lambda _: next(observations),
        exit_process=exit_codes.append,
    )

    assert exit_codes == [0]


def test_sidecar_arguments_accept_a_desktop_parent_pid() -> None:
    arguments = _parse_args(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--parent-pid",
            "42",
        ]
    )

    assert arguments.parent_pid == 42


def test_sidecar_arguments_reject_a_nonpositive_parent_pid() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--parent-pid", "0"])


def test_packaged_worker_exits_when_launcher_is_killed(monkeypatch):
    observations = iter([42, 42, 1])
    exits = []
    monkeypatch.setattr('lorasuite_engine.sidecar.time.sleep', lambda _: None)
    _watch_packaged_launcher(42, parent_pid=lambda: next(observations), exit_process=exits.append)
    assert exits == [0]


def test_already_orphaned_packaged_worker_exits_immediately():
    exits = []
    _watch_packaged_launcher(1, exit_process=exits.append)
    assert exits == [0]
