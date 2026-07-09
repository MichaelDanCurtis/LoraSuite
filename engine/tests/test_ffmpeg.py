from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import lorasuite_engine.ffmpeg as ffmpeg_module
from lorasuite_engine.ffmpeg import extract_audio, extract_frames, probe_video


ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


@ffmpeg
def test_extract_frames_writes_pngs_from_video_segment(tmp_path: Path):
    video_path = tmp_path / "source.mp4"
    output_dir = tmp_path / "frames"

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=32x32:rate=4:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    frames = extract_frames(
        video_path=video_path,
        output_dir=output_dir,
        start_seconds=0.25,
        end_seconds=1.25,
        frames_per_second=2,
    )

    assert frames
    assert frames == sorted(output_dir.glob("frame_*.png"))
    assert all(frame.suffix == ".png" for frame in frames)
    assert all(frame.exists() and frame.stat().st_size > 0 for frame in frames)


@ffmpeg
def test_extract_frames_returns_only_frames_from_current_invocation(tmp_path: Path):
    video_path = tmp_path / "source.mp4"
    output_dir = tmp_path / "frames"
    output_dir.mkdir()
    stale_frame = output_dir / "frame_99999.png"
    stale_frame.write_bytes(b"stale")

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=32x32:rate=4:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    frames = extract_frames(
        video_path=video_path,
        output_dir=output_dir,
        start_seconds=0.0,
        end_seconds=1.0,
        frames_per_second=1,
    )

    assert frames
    assert stale_frame.exists()
    assert stale_frame not in frames
    assert all(frame.parent == output_dir for frame in frames)
    assert frames == sorted(frames)


@pytest.mark.parametrize(
    ("start_seconds", "end_seconds", "frames_per_second", "match"),
    [
        (-0.1, 1.0, 1, "start_seconds must be zero or greater"),
        (1.0, 1.0, 1, "end_seconds must be greater than start_seconds"),
        (0.0, 1.0, 0, "frames_per_second must be greater than zero"),
    ],
)
def test_extract_frames_validates_inputs_before_running_ffmpeg(
    tmp_path: Path,
    start_seconds: float,
    end_seconds: float,
    frames_per_second: int,
    match: str,
):
    with pytest.raises(ValueError, match=match):
        extract_frames(
            video_path=tmp_path / "missing.mp4",
            output_dir=tmp_path / "frames",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            frames_per_second=frames_per_second,
        )


@pytest.mark.parametrize(
    ("frames_per_second", "match"),
    [
        (1.5, "frames_per_second must be an integer"),
        (float("nan"), "frames_per_second must be finite"),
        (float("inf"), "frames_per_second must be finite"),
        ("1", "frames_per_second must be an integer"),
        (True, "frames_per_second must be an integer"),
    ],
)
def test_extract_frames_rejects_invalid_fps_types_and_values(
    tmp_path: Path,
    frames_per_second,
    match: str,
):
    with pytest.raises(ValueError, match=match):
        extract_frames(
            video_path=tmp_path / "missing.mp4",
            output_dir=tmp_path / "frames",
            start_seconds=0.0,
            end_seconds=1.0,
            frames_per_second=frames_per_second,
        )


def test_extract_frames_raises_runtime_error_with_ffmpeg_stderr(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"not real video")

    def fake_run(command, **kwargs):
        assert command[0] == "ffmpeg"
        assert kwargs["shell"] is False
        return SimpleNamespace(returncode=1, stderr="line one\nline two\n")

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="line one line two"):
        extract_frames(
            video_path=video_path,
            output_dir=tmp_path / "frames",
            start_seconds=0.0,
            end_seconds=1.0,
        )


def test_failed_ffmpeg_run_does_not_leave_public_output_frames(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "source.mp4"
    output_dir = tmp_path / "frames"
    video_path.write_bytes(b"not real video")

    def fake_run(command, **kwargs):
        temp_pattern = Path(command[-1])
        temp_pattern.parent.mkdir(parents=True, exist_ok=True)
        temp_pattern.parent.joinpath("frame_00001.png").write_bytes(b"partial")
        return SimpleNamespace(returncode=1, stderr="failed after partial output")

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="failed after partial output"):
        extract_frames(
            video_path=video_path,
            output_dir=output_dir,
            start_seconds=0.0,
            end_seconds=1.0,
        )

    assert list(output_dir.glob("frame_*.png")) == []


@ffmpeg
def test_probe_video_returns_duration_dimensions_and_fps(tmp_path: Path):
    video_path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=40x24:rate=5:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    metadata = probe_video(video_path)

    assert metadata.width == 40
    assert metadata.height == 24
    assert metadata.duration_seconds > 1.5
    assert metadata.fps == 5


@ffmpeg
def test_extract_audio_writes_wav_from_video(tmp_path: Path):
    video_path = tmp_path / "source_with_audio.mp4"
    output_path = tmp_path / "audio" / "source.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=32x32:rate=4:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    audio_path = extract_audio(video_path=video_path, output_path=output_path)

    assert audio_path == output_path
    assert audio_path.exists()
    assert audio_path.stat().st_size > 0
