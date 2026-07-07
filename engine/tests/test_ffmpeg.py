from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import lorasuite_engine.ffmpeg as ffmpeg_module
from lorasuite_engine.ffmpeg import extract_frames


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
