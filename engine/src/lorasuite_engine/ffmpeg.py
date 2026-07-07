from math import isfinite
from pathlib import Path
import subprocess


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.6f}".rstrip("0").rstrip(".")


def _stderr_summary(stderr: str | None) -> str:
    if not stderr:
        return "no stderr output"
    return " ".join(stderr.split())[-1000:]


def extract_frames(
    video_path: Path,
    output_dir: Path,
    start_seconds: float,
    end_seconds: float,
    frames_per_second: int = 1,
) -> list[Path]:
    if not isfinite(start_seconds) or not isfinite(end_seconds):
        raise ValueError("segment seconds must be finite")
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds must be greater than start_seconds")
    if frames_per_second <= 0:
        raise ValueError("frames_per_second must be greater than zero")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "frame_%05d.png"
    duration = end_seconds - start_seconds
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        _format_seconds(start_seconds),
        "-i",
        str(video_path),
        "-t",
        _format_seconds(duration),
        "-vf",
        f"fps={frames_per_second}",
        str(output_pattern),
    ]

    try:
        result = subprocess.run(command, capture_output=True, shell=False, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg executable was not found") from exc

    if result.returncode != 0:
        summary = _stderr_summary(result.stderr)
        raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}: {summary}")

    return sorted(output_dir.glob("frame_*.png"))
