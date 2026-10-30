#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise the packaged LoraSuite engine and parent watchdog."
    )
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    engine = (args.engine or default_engine_path()).expanduser().resolve()
    if not engine.is_file():
        raise SystemExit(f"Packaged engine does not exist: {engine}")
    if args.port < 1024 or args.port > 65_535:
        raise SystemExit("Sidecar smoke port must be between 1024 and 65535.")
    if port_is_open(args.port):
        raise SystemExit(f"Sidecar smoke requires port {args.port} to be free.")

    report = qualify_sidecar(engine, port=args.port, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))


def qualify_sidecar(
    engine: Path, *, port: int, timeout_seconds: float
) -> dict[str, object]:
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sidecar: subprocess.Popen[bytes] | None = None
    try:
        sidecar = subprocess.Popen(
            [
                str(engine),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
                "--parent-pid",
                str(parent.pid),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        health = wait_for_health(sidecar, port=port, timeout_seconds=timeout_seconds)
        parent.terminate()
        parent.wait(timeout=10)
        wait_for_sidecar_shutdown(sidecar, port=port, timeout_seconds=15)
        return {
            "engine": str(engine),
            "engine_bytes": engine.stat().st_size,
            "engine_sha256": sha256(engine),
            "health": health,
            "parent_watchdog": "passed",
            "platform": sys.platform,
        }
    except Exception as error:
        output = read_process_output(sidecar)
        if output:
            print(output, file=sys.stderr)
        raise SystemExit(f"Packaged sidecar smoke failed: {error}") from error
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if sidecar is not None and sidecar.poll() is None:
            sidecar.kill()
            sidecar.wait(timeout=5)


def wait_for_health(
    sidecar: subprocess.Popen[bytes], *, port: int, timeout_seconds: float
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if sidecar.poll() is not None:
            raise RuntimeError(
                f"Engine exited before readiness ({sidecar.returncode})."
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as response:
                payload = json.load(response)
            if (
                payload.get("status") == "ok"
                and payload.get("service") == "lorasuite-engine"
            ):
                return payload
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Engine did not become ready before timeout.")


def wait_for_sidecar_shutdown(
    sidecar: subprocess.Popen[bytes], *, port: int, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if sidecar.poll() is not None and not port_is_open(port):
            return
        time.sleep(0.25)
    raise RuntimeError(
        "Engine did not exit after its desktop parent terminated "
        f"(returncode={sidecar.poll()}, listener={port_is_open(port)})."
    )


def default_engine_path() -> Path:
    target = rust_host_target()
    suffix = ".exe" if os.name == "nt" else ""
    return ROOT / "src-tauri" / "binaries" / f"lorasuite-engine-{target}{suffix}"


def rust_host_target() -> str:
    result = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
    )
    target = next(
        (
            line.split(":", 1)[1].strip()
            for line in result.stdout.splitlines()
            if line.startswith("host:")
        ),
        "",
    )
    if not target:
        raise RuntimeError("Unable to determine the Rust host target.")
    return target


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_process_output(process: subprocess.Popen[bytes] | None) -> str:
    if process is None or process.stdout is None:
        return ""
    if process.poll() is None:
        return ""
    return process.stdout.read().decode(errors="replace").strip()


if __name__ == "__main__":
    main()
