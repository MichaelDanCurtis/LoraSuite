from __future__ import annotations

import shutil
import wave
from array import array
from pathlib import Path

import lorasuite_engine.audio_cleaning as audio_cleaning_module
from lorasuite_engine.audio_cleaning import AudioCleaningService
from lorasuite_engine.models import AudioCleaningRecipe, DerivativeType
from lorasuite_engine.vault import VaultService


def test_audio_cleaning_persists_recipe_and_renders_one_derivative(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "voice.wav"
    with wave.open(str(source_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(array("h", [0, 1200, -1200, 0] * 2000).tobytes())

    vault = VaultService(tmp_path / "vault")
    source_item = vault.import_local_paths([source_path]).media_items[0]

    def fake_render(input_path: Path, output_path: Path, **_options) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path

    monkeypatch.setattr(audio_cleaning_module, "render_clean_audio", fake_render)
    service = AudioCleaningService(tmp_path / "vault")
    monkeypatch.setattr(
        service,
        "_separator_runtime",
        lambda: (None, tmp_path / "missing-model.onnx"),
    )
    recipe = AudioCleaningRecipe(
        media_item_id=source_item.id,
        high_pass_hz=110,
        presence_gain_db=2.5,
        isolate_voice=True,
    )

    preview = service.preview(recipe)
    rendered = service.render(recipe)
    rendered_again = service.render(recipe)

    assert preview.preview_path.exists()
    assert service.get_recipe(source_item.id).high_pass_hz == 110
    assert preview.isolation_applied is False
    assert preview.warnings
    assert rendered.rendered_media_item is not None
    assert rendered.rendered_media_item.id == rendered_again.rendered_media_item.id
    assert rendered.rendered_media_item.metadata_json["derivative_type"] == DerivativeType.AUDIO_CLEAN
    assert len(vault.list_media_items()) == 2


def test_audio_cleaning_rejects_non_audio_media(tmp_path: Path) -> None:
    image_path = tmp_path / "not-audio.png"
    from PIL import Image

    Image.new("RGB", (12, 12)).save(image_path)
    vault = VaultService(tmp_path / "vault")
    item = vault.import_local_paths([image_path]).media_items[0]

    service = AudioCleaningService(tmp_path / "vault")

    try:
        service.get_recipe(item.id)
    except ValueError as error:
        assert str(error) == "audio cleaning requires an audio media item"
    else:
        raise AssertionError("expected non-audio recipe lookup to fail")


def test_audio_separation_status_reports_runtime_and_model_independently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = AudioCleaningService(tmp_path / "vault")
    model_path = tmp_path / service.separator_model
    monkeypatch.setattr(
        service,
        "_separator_runtime",
        lambda: ("/opt/audio-separator", model_path),
    )
    monkeypatch.setattr(
        service,
        "_valid_separator_model",
        lambda path: path == model_path and path.exists(),
    )

    missing = service.separation_status()
    model_path.write_bytes(b"model")
    ready = service.separation_status()

    assert missing.runtime_installed is True
    assert missing.model_installed is False
    assert missing.ready is False
    assert ready.model_installed is True
    assert ready.ready is True


def test_audio_separation_installer_downloads_and_verifies_pinned_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = AudioCleaningService(tmp_path / "vault")
    model_path = tmp_path / "models" / service.separator_model
    monkeypatch.setattr(
        service,
        "_separator_runtime",
        lambda: ("/opt/audio-separator", model_path),
    )
    monkeypatch.setattr(
        service,
        "_valid_separator_model",
        lambda path: path == model_path and path.exists(),
    )
    monkeypatch.setattr(
        AudioCleaningService,
        "separator_model_dir",
        property(lambda _self: model_path.parent),
    )
    monkeypatch.setattr(
        AudioCleaningService,
        "separator_manifest_path",
        property(lambda _self: model_path.parent / "manifest.json"),
    )

    def fake_run(command, **_options):
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"model")
        assert "--download_model_only" in command
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(audio_cleaning_module.subprocess, "run", fake_run)

    status = service.install_separator_model()

    assert status.ready is True
    assert service.separator_manifest_path.exists()
