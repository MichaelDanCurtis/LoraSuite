from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from lorasuite_engine.ffmpeg import render_clean_audio
from lorasuite_engine.models import (
    AudioCleaningRecipe,
    AudioCleaningResult,
    AudioSeparationRuntimeStatus,
    DerivativeType,
    MediaItem,
    MediaType,
    utc_now,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService


class AudioCleaningService:
    separator_model = "UVR-MDX-NET-Inst_HQ_3.onnx"
    separator_model_sha256 = "317554b07fe1ea5279a77f2b1520a41ea4b93432560c4ffd08792c30fddf9adc"
    separator_model_size_bytes = 66_759_214

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.vault = VaultService(self.vault_root)

    @property
    def recipes_path(self) -> Path:
        return self.vault_root / "audio_cleaning_recipes.json"

    @property
    def derivatives_dir(self) -> Path:
        return self.vault_root / "derivatives" / "audio_cleaning"

    @property
    def separator_model_dir(self) -> Path:
        return Path.home() / ".cache" / "lorasuite" / "models" / "audio-separator"

    @property
    def separator_model_path(self) -> Path:
        return self.separator_model_dir / self.separator_model

    @property
    def separator_manifest_path(self) -> Path:
        return self.separator_model_dir / "lorasuite-manifest.json"

    def separation_status(self) -> AudioSeparationRuntimeStatus:
        separator_path, model_path = self._separator_runtime()
        runtime_installed = separator_path is not None
        model_installed = self._valid_separator_model(model_path)
        ready = runtime_installed and model_installed
        if ready:
            message = "UVR vocal isolation is ready"
        elif not runtime_installed:
            message = "The audio-separator helper is not installed"
        else:
            message = "The pinned UVR vocal-isolation model is not installed"
        return AudioSeparationRuntimeStatus(
            model_name=self.separator_model,
            model_sha256=self.separator_model_sha256,
            download_size_bytes=self.separator_model_size_bytes,
            runtime_installed=runtime_installed,
            model_installed=model_installed,
            ready=ready,
            message=message,
        )

    def install_separator_model(self) -> AudioSeparationRuntimeStatus:
        separator_path, model_path = self._separator_runtime()
        if separator_path is None:
            raise RuntimeError(
                "The audio-separator helper is required before LoraSuite can download the vocal model."
            )
        if self._valid_separator_model(model_path):
            return self.separation_status()
        with json_file_lock(self.separator_manifest_path):
            self.separator_model_dir.mkdir(parents=True, exist_ok=True)
            if model_path.exists():
                model_path.unlink()
            command = [
                separator_path,
                "--model_file_dir",
                str(self.separator_model_dir),
                "--model_filename",
                self.separator_model,
                "--download_model_only",
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    shell=False,
                    text=True,
                )
            except OSError as error:
                raise RuntimeError(f"Vocal model download could not start: {error}") from error
            if result.returncode != 0:
                detail = " ".join((result.stderr or result.stdout).split())[-1000:]
                raise RuntimeError(
                    f"Vocal model download failed: {detail or 'no diagnostic output'}"
                )
            if not self._valid_separator_model(model_path):
                model_path.unlink(missing_ok=True)
                raise RuntimeError("Vocal model checksum verification failed")
            atomic_write_json(
                self.separator_manifest_path,
                {
                    "backend": "audio-separator-uvr-mdx",
                    "model": self.separator_model,
                    "sha256": self.separator_model_sha256,
                    "size_bytes": self.separator_model_size_bytes,
                },
            )
        return self.separation_status()

    def get_recipe(self, media_item_id: str) -> AudioCleaningRecipe:
        item = self._audio_item(media_item_id)
        recipes = self._read_recipes()
        payload = recipes.get(item.id)
        if payload is None:
            return AudioCleaningRecipe(media_item_id=item.id)
        return AudioCleaningRecipe.model_validate(payload)

    def save_recipe(self, recipe: AudioCleaningRecipe) -> AudioCleaningRecipe:
        self._audio_item(recipe.media_item_id)
        recipe.updated_at = utc_now()
        with json_file_lock(self.recipes_path):
            recipes = self._read_recipes_unlocked()
            recipes[recipe.media_item_id] = recipe.model_dump(mode="json")
            atomic_write_json(self.recipes_path, recipes)
        return recipe

    def preview(self, recipe: AudioCleaningRecipe) -> AudioCleaningResult:
        source_item = self._audio_item(recipe.media_item_id)
        recipe = self.save_recipe(recipe)
        digest = self._recipe_digest(recipe)
        preview_path = self.derivatives_dir / "previews" / source_item.id / f"{digest}.wav"
        separator_path, separator_model_path = self._separator_runtime()
        separation_available = (
            separator_path is not None
            and self._valid_separator_model(separator_model_path)
        )
        isolation_applied = False
        input_path = source_item.raw_path
        warnings: list[str] = []
        if recipe.isolate_voice and separation_available and separator_path is not None:
            input_path = self._isolate_voice(
                source_item,
                separator_path=separator_path,
                model_path=separator_model_path,
            )
            isolation_applied = True
        elif recipe.isolate_voice:
            warnings.append(
                "Voice isolation requires the optional audio-separator runtime and vocal model."
            )
        if not preview_path.exists():
            render_clean_audio(
                input_path,
                preview_path,
                high_pass_hz=recipe.high_pass_hz,
                low_pass_hz=recipe.low_pass_hz,
                noise_floor_db=recipe.noise_floor_db,
                noise_reduction_db=recipe.noise_reduction_db,
                gate_threshold_db=recipe.gate_threshold_db,
                presence_gain_db=recipe.presence_gain_db,
                normalize=recipe.normalize,
            )
        return AudioCleaningResult(
            recipe=recipe,
            preview_path=preview_path,
            recipe_digest=digest,
            separation_available=separation_available,
            isolation_applied=isolation_applied,
            warnings=warnings,
        )

    def render(self, recipe: AudioCleaningRecipe) -> AudioCleaningResult:
        result = self.preview(recipe)
        source_item = self._audio_item(recipe.media_item_id)
        for item in self.vault.list_media_items():
            if (
                item.metadata_json.get("derivative_type") == DerivativeType.AUDIO_CLEAN
                and item.metadata_json.get("audio_cleaning_recipe_digest") == result.recipe_digest
            ):
                result.rendered_media_item = item
                return result

        rendered_path = (
            self.derivatives_dir
            / "rendered"
            / source_item.id
            / f"clean_{result.recipe_digest}.wav"
        )
        rendered_path.parent.mkdir(parents=True, exist_ok=True)
        if not rendered_path.exists():
            shutil.copy2(result.preview_path, rendered_path)
        derivative = self.vault.build_derivative_media_item(
            source_item=source_item,
            derivative_path=rendered_path,
            media_type=MediaType.AUDIO,
            derivative_type=DerivativeType.AUDIO_CLEAN,
            metadata={
                "audio_cleaning_recipe": result.recipe.model_dump(mode="json"),
                "audio_cleaning_recipe_digest": result.recipe_digest,
                "voice_isolation_applied": result.isolation_applied,
                "generator": {"name": "ffmpeg-speech-cleaner-v1"},
            },
        )
        derivative.duration = source_item.duration
        derivative = self.vault.append_media_items([derivative])[0]
        result.rendered_media_item = derivative
        return result

    def _audio_item(self, media_item_id: str) -> MediaItem:
        item = self.vault.get_media_item(media_item_id)
        if item is None:
            raise KeyError(media_item_id)
        if item.media_type != MediaType.AUDIO:
            raise ValueError("audio cleaning requires an audio media item")
        return item

    def _recipe_digest(self, recipe: AudioCleaningRecipe) -> str:
        payload = recipe.model_dump(mode="json", exclude={"updated_at"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()[:16]

    def _separator_runtime(self) -> tuple[str | None, Path]:
        candidates = [
            os.getenv("LORASUITE_AUDIO_SEPARATOR_BIN"),
            shutil.which("audio-separator"),
            str(Path(sys.executable).resolve().parent / "audio-separator"),
            str(Path.home() / ".local" / "bin" / "audio-separator"),
        ]
        separator_path = next(
            (
                str(Path(candidate).expanduser())
                for candidate in candidates
                if candidate
                and Path(candidate).expanduser().is_file()
                and os.access(Path(candidate).expanduser(), os.X_OK)
            ),
            None,
        )
        return separator_path, self.separator_model_path

    def _valid_separator_model(self, path: Path) -> bool:
        if not path.is_file() or path.stat().st_size != self.separator_model_size_bytes:
            return False
        digest = sha256()
        with path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == self.separator_model_sha256

    def _isolate_voice(
        self,
        source_item: MediaItem,
        *,
        separator_path: str,
        model_path: Path,
    ) -> Path:
        stem_dir = self.derivatives_dir / "stems" / source_item.id
        existing = sorted(stem_dir.glob("*Vocals*.wav"))
        if existing:
            return existing[0]
        stem_dir.mkdir(parents=True, exist_ok=True)
        command = [
            separator_path,
            str(source_item.raw_path),
            "--model_file_dir",
            str(model_path.parent),
            "--model_filename",
            model_path.name,
            "--output_dir",
            str(stem_dir),
            "--output_format",
            "WAV",
            "--single_stem",
            "Vocals",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                shell=False,
                text=True,
            )
        except OSError as error:
            raise RuntimeError(f"Voice isolation could not start: {error}") from error
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout).split())[-1000:]
            raise RuntimeError(f"Voice isolation failed: {detail or 'no diagnostic output'}")
        generated = sorted(stem_dir.glob("*Vocals*.wav"))
        if not generated:
            raise RuntimeError("Voice isolation completed without producing a vocal stem")
        return generated[0]

    def _read_recipes(self) -> dict[str, object]:
        with json_file_lock(self.recipes_path):
            return self._read_recipes_unlocked()

    def _read_recipes_unlocked(self) -> dict[str, object]:
        if not self.recipes_path.exists():
            return {}
        try:
            payload = json.loads(self.recipes_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
