from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SyncNetCapability(BaseModel):
    configured: bool = False
    ready: bool = False
    mode: Literal["custom", "canonical", "unconfigured"] = "unconfigured"
    executable: str | None = None
    repository_path: Path | None = None
    model_path: Path | None = None
    problems: list[str] = Field(default_factory=list)
    setup: list[str] = Field(default_factory=list)


def syncnet_capability() -> SyncNetCapability:
    custom = os.environ.get("LORASUITE_SYNCNET_COMMAND", "").strip()
    if custom:
        try:
            arguments = shlex.split(custom)
        except ValueError as error:
            return SyncNetCapability(
                configured=True,
                mode="custom",
                problems=[f"SyncNet command is invalid: {error}"],
            )
        executable = arguments[0] if arguments else ""
        problem = _executable_problem(executable)
        return SyncNetCapability(
            configured=True,
            ready=problem is None,
            mode="custom",
            executable=executable or None,
            problems=[problem] if problem else [],
        )

    repository_value = os.environ.get("LORASUITE_SYNCNET_REPO", "").strip()
    repository = Path(repository_value).expanduser().resolve(strict=False) if repository_value else Path.home() / ".lorasuite" / "models" / "syncnet_python"
    if not repository.exists():
        return SyncNetCapability(
            problems=["Canonical SyncNet repository is not configured."],
            setup=[
                "Set LORASUITE_SYNCNET_REPO to a pinned joonson/syncnet_python checkout.",
                "Set LORASUITE_SYNCNET_MODEL if syncnet_v2.model is outside the repository data folder.",
            ],
        )

    model_value = os.environ.get("LORASUITE_SYNCNET_MODEL", "").strip()
    model = Path(model_value).expanduser().resolve(strict=False) if model_value else repository / "data" / "syncnet_v2.model"
    python_value = os.environ.get("LORASUITE_SYNCNET_PYTHON", "").strip()
    bundled_python = repository / ".venv" / "bin" / "python"
    python = Path(python_value).expanduser().resolve(strict=False) if python_value else bundled_python
    problems = []
    if not (repository / "demo_syncnet.py").is_file():
        problems.append("demo_syncnet.py is missing from the configured repository.")
    if not (repository / "SyncNetInstance.py").is_file():
        problems.append("SyncNetInstance.py is missing from the configured repository.")
    if not model.is_file():
        problems.append("syncnet_v2.model is missing.")
    if not python.is_file():
        problems.append("The isolated SyncNet Python environment is missing.")
    if shutil.which("ffmpeg") is None:
        problems.append("ffmpeg is not available on PATH.")
    return SyncNetCapability(
        configured=True,
        ready=not problems,
        mode="canonical",
        executable=str(python),
        repository_path=repository,
        model_path=model,
        problems=problems,
        setup=["Install the canonical repository dependencies in the LoraSuite engine environment."],
    )


def syncnet_command() -> list[str] | None:
    capability = syncnet_capability()
    if capability.mode == "custom":
        return shlex.split(os.environ["LORASUITE_SYNCNET_COMMAND"])
    if not capability.ready:
        return None
    return [
        sys.executable,
        "-m",
        "lorasuite_engine.syncnet_adapter",
        "--python",
        str(capability.executable),
        "--repo",
        str(capability.repository_path),
        "--model",
        str(capability.model_path),
        "--video",
        "{video}",
    ]


def _executable_problem(executable: str) -> str | None:
    if not executable:
        return "SyncNet command is empty."
    path = Path(executable).expanduser()
    if path.is_absolute() or "/" in executable:
        return None if path.is_file() else f"SyncNet executable was not found: {executable}"
    return None if shutil.which(executable) else f"SyncNet executable is not on PATH: {executable}"
