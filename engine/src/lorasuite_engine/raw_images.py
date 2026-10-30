import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4


RAW_IMAGE_SUFFIXES = frozenset({".dng"})


class RawImageError(ValueError):
    pass


def is_raw_image(path: Path) -> bool:
    return Path(path).suffix.lower() in RAW_IMAGE_SUFFIXES


def raw_image_dimensions(path: Path) -> tuple[int, int]:
    result = _run_sips(
        ["-g", "pixelWidth", "-g", "pixelHeight", str(Path(path))]
    )
    width = _property(result.stdout, "pixelWidth")
    height = _property(result.stdout, "pixelHeight")
    if width <= 0 or height <= 0:
        raise RawImageError("Apple ImageIO did not report valid RAW dimensions")
    return width, height


def materialize_raw_image(path: Path, output_path: Path) -> Path:
    source = Path(path)
    output = Path(output_path)
    if output.suffix.lower() not in {".jpg", ".jpeg"}:
        raise RawImageError("RAW images must be normalized to a JPEG path")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid4().hex}.jpg")
    try:
        _run_sips(["-s", "format", "jpeg", str(source), "--out", str(temporary)])
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RawImageError("Apple ImageIO did not produce a JPEG")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _run_sips(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("sips")
    if executable is None:
        raise RawImageError(
            "DNG decoding requires Apple ImageIO on macOS; a portable LibRaw decoder is not installed"
        )
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as error:
        raise RawImageError("DNG decoding timed out after 60 seconds") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ImageIO error"
        raise RawImageError(f"DNG could not be decoded: {detail}")
    return result


def _property(output: str, name: str) -> int:
    match = re.search(rf"^\s*{re.escape(name)}:\s*(\d+)\s*$", output, re.MULTILINE)
    if match is None:
        raise RawImageError(f"Apple ImageIO did not report {name}")
    return int(match.group(1))
