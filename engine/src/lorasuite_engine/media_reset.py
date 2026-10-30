from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4


MEDIA_DIRECTORIES = (
    "raw", "derivatives", "previews", "downloads", "uploads",
    "benchmark_inputs", "benchmark_work", "voice_evaluation_inputs",
    "id_lora_evaluation_inputs", "id_lora_evaluation_work",
)

MEDIA_STATE_FILES = (
    "vault.json", "ingress_candidates.json", "ingress_jobs.json",
    "processing_jobs.json", "social_acquisition_jobs.json",
    "social_acquisition_cooldowns.json", "curation_handoff.json", "character_projects.json",
    "dataset_snapshots.json", "video_dataset_snapshots.json", "voice_datasets.json",
    "id_lora_manifests.json", "caption_jobs.json", "audio_cleaning_recipes.json",
    "voice_identity_profiles.json", "benchmark_generation_runs.json",
    "benchmark_runs.json", "image_benchmark_runs.json", "id_lora_evaluation_runs.json",
    "voice_artifact_evaluations.json",
)

ACTIVE_JOB_FILES = (
    "ingress_jobs.json",
    "processing_jobs.json",
    "social_acquisition_jobs.json",
    "caption_jobs.json",
)
ACTIVE_STATUSES = {"queued", "running", "cooldown", "submitting", "downloading"}


class MediaResetService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def clear_all_media(self) -> dict[str, int | str]:
        active_jobs = self._active_jobs()
        if active_jobs:
            raise ValueError(f"cannot clear media while {active_jobs} media job(s) are active")

        targets = [
            self.vault_root / name
            for name in (*MEDIA_DIRECTORIES, *MEDIA_STATE_FILES)
            if (self.vault_root / name).exists()
        ]
        file_count, byte_count = _measure_targets(targets)
        quarantine = self.vault_root / f".media-clear-{uuid4().hex}"
        moved: list[tuple[Path, Path]] = []
        try:
            quarantine.mkdir(parents=True, exist_ok=False)
            for source in targets:
                destination = quarantine / source.name
                source.replace(destination)
                moved.append((source, destination))
        except OSError:
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    destination.replace(source)
            shutil.rmtree(quarantine, ignore_errors=True)
            raise

        shutil.rmtree(quarantine)
        return {"status": "cleared", "files_removed": file_count, "bytes_removed": byte_count}

    def _active_jobs(self) -> int:
        active = 0
        for filename in ACTIVE_JOB_FILES:
            path = self.vault_root / filename
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            active += _count_active_statuses(payload)
        return active


def _count_active_statuses(value: object) -> int:
    if isinstance(value, dict):
        current = 1 if str(value.get("status") or "").lower() in ACTIVE_STATUSES else 0
        return current + sum(_count_active_statuses(child) for child in value.values())
    if isinstance(value, list):
        return sum(_count_active_statuses(child) for child in value)
    return 0


def _measure_targets(targets: list[Path]) -> tuple[int, int]:
    file_count = 0
    byte_count = 0
    for target in targets:
        paths = target.rglob("*") if target.is_dir() else [target]
        for path in paths:
            if not path.is_file():
                continue
            file_count += 1
            try:
                byte_count += path.stat().st_size
            except OSError:
                continue
    return file_count, byte_count
