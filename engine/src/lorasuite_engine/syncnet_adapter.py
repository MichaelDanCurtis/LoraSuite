from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory


Runner = Callable[..., subprocess.CompletedProcess[str]]


def evaluate(
    repo: Path,
    model: Path,
    video: Path,
    *,
    python: Path = Path(sys.executable),
    runner: Runner = subprocess.run,
) -> dict[str, float | int]:
    repository = repo.expanduser().resolve(strict=False)
    model_path = model.expanduser().resolve(strict=False)
    video_path = video.expanduser().resolve(strict=False)
    script = repository / "demo_syncnet.py"
    for path, label in ((script, "demo_syncnet.py"), (model_path, "SyncNet model"), (video_path, "video")):
        if not path.is_file():
            raise ValueError(f"{label} was not found: {path}")
    with TemporaryDirectory(prefix="lorasuite-syncnet-") as temporary:
        command = [
            str(python),
            str(script),
            "--initial_model",
            str(model_path),
            "--videofile",
            str(video_path),
            "--tmp_dir",
            temporary,
            "--reference",
            "lorasuite",
        ]
        result = runner(
            command,
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            shell=False,
        )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0:
        detail = output.strip().splitlines()[-1] if output.strip() else f"exit {result.returncode}"
        raise RuntimeError(f"SyncNet evaluation failed: {detail}")
    return parse_metrics(output)


def parse_metrics(output: str) -> dict[str, float | int]:
    offset = _metric(output, r"AV\s+offset\s*:\s*(-?\d+)", "AV offset", int)
    distance = _metric(output, r"Min\s+dist\s*:\s*(-?\d+(?:\.\d+)?)", "minimum distance", float)
    confidence = _metric(output, r"Confidence\s*:\s*(-?\d+(?:\.\d+)?)", "confidence", float)
    return {"lse_c": confidence, "lse_d": distance, "offset_frames": offset}


def _metric(output: str, pattern: str, label: str, cast):
    match = re.search(pattern, output, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"SyncNet output did not contain {label}")
    return cast(match.group(1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LoraSuite adapter for canonical SyncNet LSE scoring")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        print(json.dumps(evaluate(arguments.repo, arguments.model, arguments.video, python=arguments.python), sort_keys=True))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
