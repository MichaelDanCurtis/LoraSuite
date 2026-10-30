#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src-tauri" / "target" / "release" / "bundle" / "macos" / "LoraSuite.app"
ENGINE_ADDRESS = ("127.0.0.1", 8765)
HEALTH_URL = "http://127.0.0.1:8765/health"


def main() -> None:
    global ENGINE_ADDRESS, HEALTH_URL
    parser = argparse.ArgumentParser(
        description="Qualify the packaged LoraSuite desktop application."
    )
    parser.add_argument("--app", type=Path, default=APP)
    parser.add_argument("--dmg", type=Path)
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="Launch the app and verify its owned engine exits with the desktop parent.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--engine-port", type=int, default=8765, help="The loopback engine port compiled into this desktop build.")
    args = parser.parse_args()
    if not 1024 <= args.engine_port <= 65535:
        parser.error("--engine-port must be between 1024 and 65535")
    ENGINE_ADDRESS = ("127.0.0.1", args.engine_port)
    HEALTH_URL = f"http://127.0.0.1:{args.engine_port}/health"

    if sys.platform != "darwin":
        raise SystemExit("The current desktop bundle smoke supports macOS only.")

    app = args.app.expanduser()
    dmg = args.dmg.expanduser() if args.dmg is not None else default_dmg_path()
    report = qualify_bundle(app, dmg)
    if args.lifecycle:
        report["lifecycle"] = qualify_lifecycle(
            app, timeout_seconds=args.timeout
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def qualify_bundle(app: Path, dmg: Path) -> dict[str, object]:
    require_path(app, "application bundle")
    require_path(dmg, "disk image")
    info_path = app / "Contents" / "Info.plist"
    require_path(info_path, "application Info.plist")
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)

    executable_name = str(info.get("CFBundleExecutable") or "")
    executable = app / "Contents" / "MacOS" / executable_name
    engine = app / "Contents" / "MacOS" / "lorasuite-engine"
    require_path(executable, "desktop executable")
    require_path(engine, "embedded engine")

    if info.get("CFBundleIdentifier") != "com.lorasuite.desktop":
        raise SystemExit(
            "Unexpected bundle identifier: "
            f"{info.get('CFBundleIdentifier', '<missing>')}"
        )

    run_checked(["codesign", "--verify", "--deep", "--strict", str(app)])
    run_checked(["hdiutil", "verify", str(dmg)])
    return {
        "app": str(app),
        "bundle_id": info["CFBundleIdentifier"],
        "desktop_executable": str(executable),
        "dmg": str(dmg),
        "dmg_bytes": dmg.stat().st_size,
        "embedded_engine": str(engine),
        "embedded_engine_bytes": engine.stat().st_size,
        "static_checks": "passed",
        "version": str(info.get("CFBundleShortVersionString") or ""),
    }


def default_dmg_path() -> Path:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())
    product_name = str(config["productName"])
    version = str(config["version"])
    architecture = "aarch64" if os.uname().machine == "arm64" else "x64"
    return (
        ROOT
        / "src-tauri"
        / "target"
        / "release"
        / "bundle"
        / "dmg"
        / f"{product_name}_{version}_{architecture}.dmg"
    )


def qualify_lifecycle(app: Path, *, timeout_seconds: float) -> dict[str, object]:
    if port_is_open():
        raise SystemExit(
            f"Lifecycle smoke requires port {ENGINE_ADDRESS[1]} to be free. Stop the development "
            "engine before running with --lifecycle."
        )

    normal_shutdown = qualify_owned_engine_lifecycle(
        app,
        timeout_seconds=timeout_seconds,
        termination="graceful",
    )
    crash_recovery = qualify_owned_engine_lifecycle(
        app,
        timeout_seconds=timeout_seconds,
        termination="forced",
    )
    return {
        **normal_shutdown,
        "restart": "passed",
        "crash_recovery": crash_recovery,
    }


def qualify_owned_engine_lifecycle(
    app: Path,
    *,
    timeout_seconds: float,
    termination: str,
) -> dict[str, object]:
    executable_name = bundle_executable_name(app)
    executable = app / "Contents" / "MacOS" / executable_name
    if port_is_open():
        raise RuntimeError(f"Port {ENGINE_ADDRESS[1]} remained occupied before the {termination} launch.")

    baseline_engine_pids = process_ids_named("lorasuite-engine")
    log_file = tempfile.NamedTemporaryFile(
        mode="w+b",
        prefix=f"lorasuite-desktop-{termination}-",
        suffix=".log",
        delete=False,
    )
    process: subprocess.Popen[bytes] | None = None
    owned_engine_pids: set[int] = set()
    try:
        process = subprocess.Popen(
            [str(executable)],
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        health = wait_for_health(process, timeout_seconds=timeout_seconds)
        owned_engine_pids = process_ids_named("lorasuite-engine") - baseline_engine_pids
        if not owned_engine_pids:
            raise RuntimeError("The desktop app did not start an owned engine process.")

        if termination == "forced":
            process.kill()
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            active_owned_pids = {
                process_id
                for process_id in owned_engine_pids
                if process_is_running(process_id)
            }
            if not port_is_open() and not active_owned_pids:
                break
            time.sleep(0.25)
        else:
            active_owned_pids = {
                process_id
                for process_id in owned_engine_pids
                if process_is_running(process_id)
            }
            raise RuntimeError(
                "The packaged engine survived desktop termination: "
                f"listener={port_is_open()}, pids={sorted(active_owned_pids)}"
            )

        return {
            "desktop_pid": process.pid,
            "engine_pids": sorted(owned_engine_pids),
            "health": health,
            "log": log_file.name,
            "shutdown": "passed",
            "termination": termination,
        }
    except Exception:
        log_file.flush()
        print(Path(log_file.name).read_text(errors="replace"), file=sys.stderr)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for process_id in owned_engine_pids:
            if process_is_running(process_id):
                try:
                    os.kill(process_id, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        log_file.close()


def bundle_executable_name(app: Path) -> str:
    with (app / "Contents" / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    executable_name = str(info.get("CFBundleExecutable") or "")
    if not executable_name:
        raise SystemExit("The application bundle does not declare an executable.")
    return executable_name


def wait_for_health(
    process: subprocess.Popen[bytes], *, timeout_seconds: float
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"The desktop app exited before engine readiness ({process.returncode})."
            )
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
                payload = json.load(response)
            if (
                payload.get("status") == "ok"
                and payload.get("service") == "lorasuite-engine"
            ):
                return payload
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise RuntimeError("The packaged engine did not become ready before timeout.")


def port_is_open() -> bool:
    try:
        with socket.create_connection(ENGINE_ADDRESS, timeout=0.25):
            return True
    except OSError:
        return False


def process_ids_named(name: str) -> set[int]:
    result = subprocess.run(
        ["pgrep", "-x", name],
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or f"Unable to inspect {name} processes.")
    return {int(line) for line in result.stdout.splitlines() if line.strip()}


def process_is_running(process_id: int) -> bool:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(process_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"{' '.join(command)} failed: {detail}")


if __name__ == "__main__":
    main()
