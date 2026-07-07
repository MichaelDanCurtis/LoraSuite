import json
from pathlib import Path

import pytest
from PIL import Image

import lorasuite_engine.exports as exports_module
from lorasuite_engine.exports import create_runcomfy_image_export
from lorasuite_engine.models import ExportType
from lorasuite_engine.vault import sha256_file


def create_frame(path: Path, color: tuple[int, int, int] = (200, 100, 50)) -> Path:
    Image.new("RGB", (32, 32), color=color).save(path)
    return path


def test_runcomfy_export_writes_images_captions_manifest_and_report(tmp_path):
    frame = create_frame(tmp_path / "frame.png")
    ignored_frame = create_frame(tmp_path / "ignored.png", color=(10, 20, 30))
    output_dir = tmp_path / "export"

    package = create_runcomfy_image_export(
        frames=[frame],
        output_dir=output_dir,
        caption_template="subject trigger_token, clean portrait\n\n",
        source_segment_ids=["segment-1"],
    )

    exported_image = output_dir / "images" / "000001.png"
    exported_caption = output_dir / "images" / "000001.txt"
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "export_report.md"

    assert package.export_type == ExportType.RUNCOMFY_IMAGE
    assert package.output_path == output_dir
    assert package.source_segment_ids == ["segment-1"]
    assert package.status == "complete"
    assert package.manifest_path == manifest_path
    assert exported_image.read_bytes() == frame.read_bytes()
    assert exported_caption.read_text(encoding="utf-8") == (
        "subject trigger_token, clean portrait\n"
    )
    assert not (output_dir / "images" / "000002.png").exists()
    assert ignored_frame.read_bytes() != exported_image.read_bytes()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "created_by": "LoraSuite",
        "export_id": package.id,
        "export_type": "runcomfy_image",
        "status": "complete",
        "source_segment_ids": ["segment-1"],
        "files": [
            {
                "image": str(exported_image),
                "caption": str(exported_caption),
                "sha256": sha256_file(exported_image),
            }
        ],
    }
    assert "RunComfy AI Toolkit Image Export" in report_path.read_text(
        encoding="utf-8"
    )


def test_runcomfy_export_rejects_webp(tmp_path):
    webp = tmp_path / "frame.webp"
    webp.write_bytes(b"fake")

    with pytest.raises(ValueError, match="WebP is not supported"):
        create_runcomfy_image_export(
            frames=[webp],
            output_dir=tmp_path / "export",
            caption_template="caption",
            source_segment_ids=[],
        )


def test_runcomfy_export_rejects_empty_frame_list(tmp_path):
    with pytest.raises(ValueError, match="At least one frame is required"):
        create_runcomfy_image_export(
            frames=[],
            output_dir=tmp_path / "export",
            caption_template="caption",
            source_segment_ids=[],
        )


def test_runcomfy_export_rejects_unsupported_suffix(tmp_path):
    unsupported = tmp_path / "frame.gif"
    unsupported.write_bytes(b"fake")

    with pytest.raises(ValueError, match="Unsupported image suffix"):
        create_runcomfy_image_export(
            frames=[unsupported],
            output_dir=tmp_path / "export",
            caption_template="caption",
            source_segment_ids=[],
        )


def test_runcomfy_export_rejects_missing_frame_without_complete_manifest(tmp_path):
    output_dir = tmp_path / "export"

    with pytest.raises(ValueError, match="Frame does not exist"):
        create_runcomfy_image_export(
            frames=[tmp_path / "missing.png"],
            output_dir=output_dir,
            caption_template="caption",
            source_segment_ids=["segment-1"],
        )

    assert not (output_dir / "manifest.json").exists()
    assert not (output_dir / "export_report.md").exists()


def test_runcomfy_export_rejects_corrupt_image_without_complete_manifest(tmp_path):
    corrupt_frame = tmp_path / "corrupt.png"
    corrupt_frame.write_bytes(b"not a png")
    output_dir = tmp_path / "export"

    with pytest.raises(ValueError, match="Frame image could not be read"):
        create_runcomfy_image_export(
            frames=[corrupt_frame],
            output_dir=output_dir,
            caption_template="caption",
            source_segment_ids=["segment-1"],
        )

    assert not (output_dir / "manifest.json").exists()
    assert not (output_dir / "export_report.md").exists()


def test_runcomfy_export_rejects_duplicate_frame_path(tmp_path):
    frame = create_frame(tmp_path / "frame.png")

    with pytest.raises(ValueError, match="Duplicate frame path"):
        create_runcomfy_image_export(
            frames=[frame, frame],
            output_dir=tmp_path / "export",
            caption_template="caption",
            source_segment_ids=[],
        )


def test_failed_runcomfy_export_removes_staged_output(tmp_path, monkeypatch):
    frame = create_frame(tmp_path / "frame.png")
    output_dir = tmp_path / "export"

    def fail_copy(source: Path, target: Path) -> None:
        target.write_bytes(b"partial")
        raise OSError("copy failed")

    monkeypatch.setattr(exports_module.shutil, "copy2", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        create_runcomfy_image_export(
            frames=[frame],
            output_dir=output_dir,
            caption_template="caption",
            source_segment_ids=[],
        )

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".export.staging.*"))


def test_runcomfy_export_rejects_unrelated_existing_directory_and_preserves_contents(
    tmp_path,
):
    frame = create_frame(tmp_path / "frame.png")
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    unrelated_file = output_dir / "notes.txt"
    unrelated_file.write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="output_dir is non-empty"):
        create_runcomfy_image_export(
            frames=[frame],
            output_dir=output_dir,
            caption_template="caption",
            source_segment_ids=[],
        )

    assert unrelated_file.read_text(encoding="utf-8") == "do not delete"
    assert not (output_dir / "manifest.json").exists()
    assert not list(tmp_path.glob(".export.staging.*"))


def test_runcomfy_export_replaces_prior_lorasuite_runcomfy_export(tmp_path):
    first_frame = create_frame(tmp_path / "first.png", color=(1, 2, 3))
    second_frame = create_frame(tmp_path / "second.png", color=(4, 5, 6))
    output_dir = tmp_path / "export"

    first_package = create_runcomfy_image_export(
        frames=[first_frame],
        output_dir=output_dir,
        caption_template="first caption",
        source_segment_ids=["segment-1"],
    )
    stale_file = output_dir / "images" / "stale.txt"
    stale_file.write_text("stale", encoding="utf-8")

    second_package = create_runcomfy_image_export(
        frames=[second_frame],
        output_dir=output_dir,
        caption_template="second caption",
        source_segment_ids=["segment-2"],
    )

    assert second_package.id != first_package.id
    assert not stale_file.exists()
    assert (output_dir / "images" / "000001.png").read_bytes() == (
        second_frame.read_bytes()
    )
    assert (output_dir / "images" / "000001.txt").read_text(
        encoding="utf-8"
    ) == "second caption\n"
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["created_by"] == "LoraSuite"
    assert manifest["export_type"] == "runcomfy_image"
    assert manifest["source_segment_ids"] == ["segment-2"]
