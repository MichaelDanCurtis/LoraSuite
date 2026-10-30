import json
import os
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
    width: int
    height: int
    fps: float | None


def _run_ffmpeg_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    # Desktop/launchd processes do not inherit the interactive shell's Homebrew
    # PATH. Match the native H3 runner while preserving explicitly configured tools.
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]))
    try:
        result = subprocess.run(command, capture_output=True, shell=False, text=True, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{command[0]} executable was not found. Install FFmpeg (including ffprobe) or add its bin directory to the engine PATH, then restart the engine.") from exc
    if result.returncode != 0:
        summary = _stderr_summary(result.stderr)
        raise RuntimeError(f"{command[0]} failed with exit code {result.returncode}: {summary}")
    return result


def _parse_fraction(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" not in value:
            parsed = float(value)
            return parsed if isfinite(parsed) and parsed > 0 else None
        numerator_raw, denominator_raw = value.split("/", 1)
        numerator = float(numerator_raw)
        denominator = float(denominator_raw)
    except (TypeError, ValueError):
        return None
    if denominator == 0:
        return None
    parsed = numerator / denominator
    return parsed if isfinite(parsed) and parsed > 0 else None


def _positive_int_metadata(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


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
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("metadata root must be an object")
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            raise ValueError("metadata must include at least one video stream")
        stream = streams[0]
        if not isinstance(stream, dict):
            raise ValueError("video stream metadata must be an object")
        format_metadata = payload.get("format")
        if not isinstance(format_metadata, dict):
            raise ValueError("format metadata must be an object")
        if "duration" not in format_metadata:
            raise ValueError("format duration is required")
        raw_duration = format_metadata["duration"]
        if isinstance(raw_duration, bool):
            raise ValueError("format duration must not be boolean")
        duration = float(raw_duration)
        if not isfinite(duration) or duration < 0:
            raise ValueError("duration must be finite and non-negative")
        width = _positive_int_metadata(stream.get("width"), "width")
        height = _positive_int_metadata(stream.get("height"), "height")
        if "avg_frame_rate" not in stream:
            raise ValueError("avg_frame_rate is required")
        raw_fps = stream["avg_frame_rate"]
        if not isinstance(raw_fps, str):
            raise ValueError("avg_frame_rate must be a string")
        fps = _parse_fraction(raw_fps)
        if fps is None:
            raise ValueError("avg_frame_rate must parse to a positive finite value")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"ffprobe returned invalid metadata for {video_path}: {exc}") from exc
    return VideoMetadata(
        duration_seconds=duration,
        width=width,
        height=height,
        fps=fps,
    )


def probe_audio_duration(path: Path) -> float:
    result = _run_ffmpeg_command(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)])
    try:
        payload = json.loads(result.stdout)
        if not payload.get("streams"):
            raise ValueError("No audio stream")
        duration = float(payload["format"]["duration"])
        if not isfinite(duration) or duration <= 0:
            raise ValueError("Invalid audio duration")
        return duration
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot read audio duration: {exc}") from exc


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


def normalize_training_video(
    input_path: Path,
    output_path: Path,
    *,
    fps: int = 16,
    max_dimension: int = 1024,
) -> Path:
    """Create a deterministic, silent H.264 training clip with even dimensions."""
    if fps <= 0 or max_dimension < 256:
        raise ValueError("video normalization settings are invalid")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
    scale = (
        f"scale=if(gte(iw\\,ih)\\,min({max_dimension}\\,iw)\\,-2):"
        f"if(lt(iw\\,ih)\\,min({max_dimension}\\,ih)\\,-2),fps={fps}"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(input_path), "-an", "-vf", scale,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary_path),
    ]
    try:
        _run_ffmpeg_command(command)
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_path


def render_clean_audio(
    input_path: Path,
    output_path: Path,
    *,
    high_pass_hz: int,
    low_pass_hz: int,
    noise_floor_db: int,
    noise_reduction_db: int,
    gate_threshold_db: int,
    presence_gain_db: float,
    normalize: bool,
) -> Path:
    """Render a non-destructive speech-focused PCM derivative."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp.wav")
    filters = [
        f"highpass=f={high_pass_hz}",
        f"lowpass=f={low_pass_hz}",
    ]
    if noise_reduction_db > 0:
        filters.append(f"afftdn=nr={noise_reduction_db}:nf={noise_floor_db}")
    gate_threshold = 10 ** (gate_threshold_db / 20)
    filters.append(
        f"agate=threshold={gate_threshold:.8f}:ratio=2:attack=20:release=250"
    )
    if presence_gain_db != 0:
        filters.append(
            f"equalizer=f=3000:t=q:w=1:g={presence_gain_db:.2f}"
        )
    if normalize:
        filters.append("loudnorm=I=-18:TP=-2:LRA=7")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-af",
        ",".join(filters),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "48000",
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


def prepare_speaker_audio(input_path: Path, output_path: Path) -> Path:
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
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
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


def extract_audio_segment(
    input_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> Path:
    if not isfinite(start_seconds) or not isfinite(end_seconds):
        raise ValueError("segment seconds must be finite")
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError("segment time range is invalid")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp.wav")
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
        str(input_path),
        "-t",
        _format_seconds(end_seconds - start_seconds),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "24000",
        "-ac",
        "1",
        str(temporary_path),
    ]
    try:
        _run_ffmpeg_command(command)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def extract_video_clip(
    video_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
    *,
    include_audio: bool = True,
) -> Path:
    if not isfinite(start_seconds) or not isfinite(end_seconds):
        raise ValueError("clip seconds must be finite")
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds must be greater than start_seconds")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
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
        _format_seconds(end_seconds - start_seconds),
        "-map",
        "0:v:0",
        *(["-map", "0:a?"] if include_audio else ["-an"]),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(temporary_path),
    ]
    try:
        _run_ffmpeg_command(command)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
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


def extract_analysis_frames(
    video_path: Path,
    output_dir: Path,
    *,
    duration_seconds: float,
    frames_per_second: float,
    max_width: int,
) -> list[Path]:
    if not isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and greater than zero")
    if not isfinite(frames_per_second) or frames_per_second <= 0:
        raise ValueError("frames_per_second must be finite and greater than zero")
    if isinstance(max_width, bool) or not isinstance(max_width, int) or max_width <= 0:
        raise ValueError("max_width must be a positive integer")

    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".lorasuite_analysis_", dir=output_dir) as temp_output:
        temp_output_dir = Path(temp_output)
        output_pattern = temp_output_dir / "analysis_%05d.jpg"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-hwaccel",
            "videotoolbox",
            "-i",
            str(video_path),
            "-t",
            _format_seconds(duration_seconds),
            "-vf",
            f"fps={_format_seconds(frames_per_second)},scale='min({max_width},iw)':-2",
            "-q:v",
            "3",
            str(output_pattern),
        ]
        try:
            _run_ffmpeg_command(command)
        except RuntimeError:
            command[command.index("-hwaccel") : command.index("-hwaccel") + 2] = []
            _run_ffmpeg_command(command)

        produced_frames = sorted(temp_output_dir.glob("analysis_*.jpg"))
        public_frames: list[Path] = []
        for frame in produced_frames:
            public_frame = output_dir / frame.name
            frame.replace(public_frame)
            public_frames.append(public_frame)
        return public_frames


def extract_frame_at_timestamp(
    video_path: Path,
    output_path: Path,
    timestamp_seconds: float,
) -> Path:
    if not isfinite(timestamp_seconds) or timestamp_seconds < 0:
        raise ValueError("timestamp_seconds must be finite and zero or greater")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp.png")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        _format_seconds(timestamp_seconds),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(temporary_path),
    ]
    try:
        _run_ffmpeg_command(command)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path
