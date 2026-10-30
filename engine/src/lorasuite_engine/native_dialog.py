from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def pick_native_directory(
    title: str = "Choose LoraSuite package folder",
) -> Path | None:
    if sys.platform != "darwin":
        raise ValueError("native web folder selection is currently available on macOS")

    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                f'POSIX path of (choose folder with prompt "{escaped_title}")',
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"could not open the folder selector: {error}") from error

    if result.returncode != 0:
        message = result.stderr.strip()
        if "User canceled" in message or "(-128)" in message:
            return None
        raise ValueError(message or "the folder selector could not be opened")

    path = Path(result.stdout.strip()).expanduser()
    if not path.is_dir():
        raise ValueError("the selected package destination is not a folder")
    return path.resolve()
