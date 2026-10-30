import subprocess
from pathlib import Path

import pytest

from lorasuite_engine.raw_images import RawImageError, raw_image_dimensions


def test_raw_image_dimensions_reads_apple_imageio_properties(monkeypatch):
    monkeypatch.setattr("lorasuite_engine.raw_images.shutil.which", lambda name: "/usr/bin/sips")
    monkeypatch.setattr(
        "lorasuite_engine.raw_images.subprocess.run",
        lambda *args, **kwargs: _ProcessResult(
            stdout="/tmp/portrait.dng\n  pixelWidth: 4032\n  pixelHeight: 3024\n"
        ),
    )

    assert raw_image_dimensions(Path("/tmp/portrait.dng")) == (4032, 3024)


def test_raw_image_dimensions_reports_missing_decoder(monkeypatch):
    monkeypatch.setattr("lorasuite_engine.raw_images.shutil.which", lambda name: None)

    with pytest.raises(RawImageError, match="Apple ImageIO"):
        raw_image_dimensions(Path("/tmp/portrait.dng"))


def test_raw_image_dimensions_reports_decoder_timeout(monkeypatch):
    monkeypatch.setattr("lorasuite_engine.raw_images.shutil.which", lambda name: "/usr/bin/sips")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("sips", 60)

    monkeypatch.setattr("lorasuite_engine.raw_images.subprocess.run", timeout)

    with pytest.raises(RawImageError, match="timed out"):
        raw_image_dimensions(Path("/tmp/portrait.dng"))


class _ProcessResult:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
