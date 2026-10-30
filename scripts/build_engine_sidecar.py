#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = ROOT / "engine"
BUILD_ROOT = ROOT / ".lorasuite" / "build" / "engine-sidecar"
BINARY_ROOT = ROOT / "src-tauri" / "binaries"


def main() -> None:
    python = engine_python()
    ensure_pyinstaller(python)
    target = target_triple()
    executable_name = "lorasuite-engine.exe" if os.name == "nt" else "lorasuite-engine"
    target_name = f"lorasuite-engine-{target}{'.exe' if os.name == 'nt' else ''}"
    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    (BUILD_ROOT / "dist").mkdir(parents=True, exist_ok=True)
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "lorasuite-engine",
        "--paths",
        str(ENGINE_ROOT / "src"),
        "--distpath",
        str(BUILD_ROOT / "dist"),
        "--workpath",
        str(BUILD_ROOT / "work"),
        "--specpath",
        str(BUILD_ROOT / "spec"),
        "--collect-data",
        "lorasuite_engine",
        "--collect-submodules",
        "uvicorn",
        str(ENGINE_ROOT / "src" / "lorasuite_engine" / "sidecar.py"),
    ]
    if sys.platform == "darwin":
        signing_identity = os.environ.get("APPLE_SIGNING_IDENTITY", "").strip()
        if signing_identity and signing_identity != "-":
            command[3:3] = ["--codesign-identity", signing_identity]
    subprocess.run(command, cwd=ROOT, check=True)
    source = BUILD_ROOT / "dist" / executable_name
    if not source.is_file():
        raise SystemExit(f"PyInstaller did not create {source}")
    BINARY_ROOT.mkdir(parents=True, exist_ok=True)
    destination = BINARY_ROOT / target_name
    shutil.copy2(source, destination)
    destination.chmod(0o755)
    print(f"Built {destination} ({destination.stat().st_size:,} bytes)")


def engine_python() -> Path:
    configured = os.environ.get("LORASUITE_ENGINE_PYTHON")
    if configured:
        candidate = Path(configured).expanduser()
    elif os.name == "nt":
        candidate = ENGINE_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ENGINE_ROOT / ".venv" / "bin" / "python"
    if not candidate.is_file():
        raise SystemExit(
            f"LoraSuite engine Python was not found at {candidate}. "
            "Create engine/.venv and install engine[dev]."
        )
    return candidate.absolute()


def ensure_pyinstaller(python: Path) -> None:
    result = subprocess.run(
        [str(python), "-c", "import PyInstaller"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit(
            "PyInstaller is not installed in the engine environment. "
            "Run: engine/.venv/bin/pip install -e 'engine[dev]'"
        )


def target_triple() -> str:
    configured = os.environ.get("TAURI_ENV_TARGET_TRIPLE")
    if configured:
        return configured
    rustc = subprocess.run(
        ["rustc", "-vV"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    host = next(
        (line.split(":", 1)[1].strip() for line in rustc.splitlines() if line.startswith("host:")),
        "",
    )
    if not host:
        raise SystemExit(
            f"Could not determine the Rust target triple on {platform.platform()}"
        )
    return host


if __name__ == "__main__":
    main()
