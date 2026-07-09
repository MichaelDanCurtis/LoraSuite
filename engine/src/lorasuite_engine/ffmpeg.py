import json
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.6f}".rstrip("0").rstrip(".")


def _stderr_summary(stderr: str | None) -> str:
    if not stderr:
        return "no stderr output"
    return " ".join(stderr.split())[-1000:]


def _validate_frames_per_second(frames_per_second: int) -> int:
    if isinstance(frames_per_second, bool):
        raise ValueError("frames_per_second must be an integer")
    if isinstance(frames_per_second, Real) and not isfinite(frames_per_second):
        raise ValueError("frames_per_second must be finite")
    if not isinstance(frames_per_second, int):
        raise ValueError("frames_per_second must be an integer")
    if frames_per_second <= 0:
        raise ValueError("frames_per_second must be greater than zero")
    return frames_per_second


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    width: int | None
    height: int | None
    fps: float | None


def _run_ffmpeg_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, shell=False, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{command[0]} executable was not found") from exc
    if result.returncode != 0:
        summary = _stderr_summary(result.stderr)
        raise RuntimeError(f"{command[0]} failed with exit code {result.returncode}: {summary}")
    return result


def _parse_fraction(value: str | None) -> float | None:
    if not value:
        return None
    if "/" not in value:
        parsed = float(value)
        return parsed if isfinite(parsed) and parsed > 0 else None
    numerator_raw, denominator_raw = value.split("/", 1)
    numerator = float(numerator_raw)
    denominator = float(denominator_raw)
    if denominator == 0:
        return None
    parsed = numerator / denominator
    return parsed if isfinite(parsed) and parsed > 0 else None


def probe_video(video_path: Path) -> VideoMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    result = _run_ffmpeg_command(command)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    duration = float(payload.get("format", {}).get("duration") or 0)
    return VideoMetadata(
        duration_seconds=duration,
        width=stream.get("width"),
        height=stream.get("height"),
        fps=_parse_fraction(stream.get("avg_frame_rate")),
    )


def extract_audio(video_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp.wav")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(temporary_path),
    ]
    try:
        _run_ffmpeg_command(command)
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_path


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
    frames_per_second = _validate_frames_per_second(frames_per_second)

    output_dir.mkdir(parents=True, exist_ok=True)
    duration = end_seconds - start_seconds

    with TemporaryDirectory(prefix=".lorasuite_ffmpeg_", dir=output_dir) as temp_output:
        temp_output_dir = Path(temp_output)
        output_pattern = temp_output_dir / "frame_%05d.png"
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

        _run_ffmpeg_command(command)
        produced_frames = sorted(temp_output_dir.glob("frame_*.png"))
        public_frames: list[Path] = []
        for frame in produced_frames:
            public_frame = output_dir / frame.name
            frame.replace(public_frame)
            public_frames.append(public_frame)

        return public_frames
