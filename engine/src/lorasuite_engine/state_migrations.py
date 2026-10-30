from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from lorasuite_engine.models import utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import sha256_file


STATE_SCHEMA_FORMAT = "lorasuite.state-schema.v1"


@dataclass(frozen=True)
class _StateFileSpec:
    filename: str
    current_version: int = 1
    collection_key: str | None = None
    embedded_version: bool = True


STATE_FILE_SPECS = (
    _StateFileSpec("vault.json"),
    _StateFileSpec("character_projects.json", collection_key="projects"),
    _StateFileSpec("ingress_candidates.json", collection_key="candidates"),
    _StateFileSpec("ingress_jobs.json", collection_key="jobs"),
    _StateFileSpec("dataset_snapshots.json", collection_key="snapshots"),
    _StateFileSpec("video_dataset_snapshots.json", collection_key="snapshots"),
    _StateFileSpec("id_lora_manifests.json", collection_key="manifests"),
    _StateFileSpec("model_artifacts.json", collection_key="artifacts"),
    _StateFileSpec("benchmark_runs.json", collection_key="runs"),
    _StateFileSpec("voice_artifact_evaluations.json", collection_key="runs"),
    _StateFileSpec("benchmark_generation_runs.json", collection_key="runs"),
    _StateFileSpec("artifact_comparisons.json", collection_key="comparisons"),
    _StateFileSpec("improvement_requests.json", collection_key="requests"),
    _StateFileSpec("dataset_revisions.json", collection_key="revisions"),
    _StateFileSpec("runpod_bundles.json", collection_key="bundles"),
    _StateFileSpec("image_benchmark_runs.json", collection_key="runs"),
    _StateFileSpec("recovered_dataset_exports.json", collection_key="exports"),
    _StateFileSpec("comfyui_evaluation_reports.json", collection_key="reports"),
    _StateFileSpec("runpod_model_bootstrap_runs.json", collection_key="runs"),
    _StateFileSpec("runpod_infrastructure_profiles.json", collection_key="profiles"),
    _StateFileSpec("id_lora_evaluation_runs.json", collection_key="runs"),
    _StateFileSpec("runpod_bundle_upload_jobs.json", collection_key="jobs"),
    _StateFileSpec("caption_jobs.json", collection_key="jobs"),
    _StateFileSpec("runpod_training_runs.json", collection_key="runs"),
    _StateFileSpec("runpod_preflight_reports.json", collection_key="reports"),
    _StateFileSpec("training_runs.json", collection_key="runs"),
    _StateFileSpec("diagnostic_bundles.json", collection_key="bundles"),
    _StateFileSpec("processing_jobs.json", embedded_version=False),
    _StateFileSpec("social_acquisition_jobs.json", embedded_version=False),
    _StateFileSpec("social_acquisition_cooldowns.json", embedded_version=False),
    _StateFileSpec("provider_smoke_runs.json", embedded_version=False),
    _StateFileSpec("voice_identity_profiles.json", embedded_version=False),
    _StateFileSpec("voice_datasets.json", embedded_version=False),
    _StateFileSpec("audio_cleaning_recipes.json", embedded_version=False),
    _StateFileSpec("curation_handoff.json", embedded_version=False),
)


class StateFileMigration(BaseModel):
    filename: str
    path: Path
    exists: bool
    current_version: int | None = None
    target_version: int = 1
    status: Literal[
        "missing",
        "current",
        "pending",
        "migrated",
        "registered",
        "invalid",
        "future",
    ]
    action: Literal["none", "register", "migrate"] = "none"
    embedded_version: bool = True
    sha256_before: str | None = None
    sha256_after: str | None = None
    backup_path: Path | None = None
    message: str = ""


class StateMigrationReport(BaseModel):
    format: Literal["lorasuite.state-schema.v1"] = STATE_SCHEMA_FORMAT
    vault_root: Path
    dry_run: bool
    ready: bool
    updated_count: int = 0
    pending_count: int = 0
    invalid_count: int = 0
    future_count: int = 0
    files: list[StateFileMigration] = Field(default_factory=list)
    ledger_path: Path
    backup_root: Path | None = None
    created_at: Any = Field(default_factory=utc_now)


class StateMigrationService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def ledger_path(self) -> Path:
        return self.vault_root / "state_schema.json"

    @property
    def backups_dir(self) -> Path:
        return self.vault_root / "state_backups"

    def inspect(self) -> StateMigrationReport:
        return self._run(dry_run=True)

    def migrate(self) -> StateMigrationReport:
        return self._run(dry_run=False)

    def _run(self, *, dry_run: bool) -> StateMigrationReport:
        with json_file_lock(self.ledger_path):
            ledger = self._read_ledger()
            ledger_files = ledger.setdefault("files", {})
            migration_id = f"migration_{uuid4().hex}"
            backup_root = self.backups_dir / migration_id
            reports: list[StateFileMigration] = []
            ledger_changed = False

            for spec in STATE_FILE_SPECS:
                report, ledger_entry, changed = self._process_file(
                    spec,
                    ledger_files.get(spec.filename),
                    dry_run=dry_run,
                    backup_root=backup_root,
                )
                reports.append(report)
                if dry_run or ledger_entry is None:
                    continue
                if ledger_files.get(spec.filename) != ledger_entry:
                    ledger_files[spec.filename] = ledger_entry
                    ledger_changed = True
                ledger_changed = ledger_changed or changed

            if not dry_run and ledger_changed:
                ledger.update(
                    {
                        "format": STATE_SCHEMA_FORMAT,
                        "version": 1,
                        "last_migration_id": migration_id,
                        "updated_at": utc_now().isoformat(),
                    },
                )
                atomic_write_json(self.ledger_path, ledger)

            pending_count = sum(item.status == "pending" for item in reports)
            invalid_count = sum(item.status == "invalid" for item in reports)
            future_count = sum(item.status == "future" for item in reports)
            updated_count = sum(
                item.status in {"migrated", "registered"}
                for item in reports
            )
            return StateMigrationReport(
                vault_root=self.vault_root,
                dry_run=dry_run,
                ready=invalid_count == 0 and future_count == 0 and pending_count == 0,
                updated_count=updated_count,
                pending_count=pending_count,
                invalid_count=invalid_count,
                future_count=future_count,
                files=reports,
                ledger_path=self.ledger_path,
                backup_root=backup_root if backup_root.is_dir() else None,
            )

    def _process_file(
        self,
        spec: _StateFileSpec,
        ledger_entry: Any,
        *,
        dry_run: bool,
        backup_root: Path,
    ) -> tuple[StateFileMigration, dict[str, Any] | None, bool]:
        path = self.vault_root / spec.filename
        if not path.is_file():
            return (
                StateFileMigration(
                    filename=spec.filename,
                    path=path,
                    exists=False,
                    target_version=spec.current_version,
                    status="missing",
                    embedded_version=spec.embedded_version,
                    message="State file has not been created.",
                ),
                None,
                False,
            )

        before_sha = sha256_file(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return (
                StateFileMigration(
                    filename=spec.filename,
                    path=path,
                    exists=True,
                    target_version=spec.current_version,
                    status="invalid",
                    embedded_version=spec.embedded_version,
                    sha256_before=before_sha,
                    message=f"JSON could not be read: {error}",
                ),
                None,
                False,
            )

        shape_error = _shape_error(spec, payload)
        if shape_error:
            return (
                StateFileMigration(
                    filename=spec.filename,
                    path=path,
                    exists=True,
                    target_version=spec.current_version,
                    status="invalid",
                    embedded_version=spec.embedded_version,
                    sha256_before=before_sha,
                    message=shape_error,
                ),
                None,
                False,
            )

        current_version = _current_version(spec, payload, ledger_entry)
        if current_version > spec.current_version:
            return (
                StateFileMigration(
                    filename=spec.filename,
                    path=path,
                    exists=True,
                    current_version=current_version,
                    target_version=spec.current_version,
                    status="future",
                    embedded_version=spec.embedded_version,
                    sha256_before=before_sha,
                    sha256_after=before_sha,
                    message="State file was created by a newer LoraSuite schema.",
                ),
                None,
                False,
            )

        needs_payload_migration = spec.embedded_version and current_version < spec.current_version
        needs_registration = (
            not isinstance(ledger_entry, dict)
            or int(ledger_entry.get("version", 0)) != spec.current_version
            or ledger_entry.get("sha256") != before_sha
        )
        action: Literal["none", "register", "migrate"] = (
            "migrate" if needs_payload_migration else "register" if needs_registration else "none"
        )
        if dry_run:
            status = "pending" if needs_payload_migration or (not spec.embedded_version and needs_registration) else "current"
            return (
                StateFileMigration(
                    filename=spec.filename,
                    path=path,
                    exists=True,
                    current_version=current_version,
                    target_version=spec.current_version,
                    status=status,
                    action=action,
                    embedded_version=spec.embedded_version,
                    sha256_before=before_sha,
                    sha256_after=before_sha,
                    message=_migration_message(spec, action, dry_run=True),
                ),
                None,
                False,
            )

        backup_path: Path | None = None
        after_sha = before_sha
        if needs_payload_migration:
            migrated = _migrate_v0_to_v1(spec, payload)
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_path = backup_root / spec.filename
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            with json_file_lock(path):
                atomic_write_json(path, migrated)
            after_sha = sha256_file(path)

        status: Literal["current", "migrated", "registered"] = (
            "migrated" if needs_payload_migration else "registered" if needs_registration else "current"
        )
        ledger_value = (
            ledger_entry
            if status == "current" and isinstance(ledger_entry, dict)
            else {
                "version": spec.current_version,
                "embedded_version": spec.embedded_version,
                "sha256": after_sha,
                "updated_at": utc_now().isoformat(),
            }
        )
        return (
            StateFileMigration(
                filename=spec.filename,
                path=path,
                exists=True,
                current_version=spec.current_version,
                target_version=spec.current_version,
                status=status,
                action=action,
                embedded_version=spec.embedded_version,
                sha256_before=before_sha,
                sha256_after=after_sha,
                backup_path=backup_path,
                message=_migration_message(spec, action, dry_run=False),
            ),
            ledger_value,
            status in {"migrated", "registered"},
        )

    def _read_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.is_file():
            return {
                "format": STATE_SCHEMA_FORMAT,
                "version": 1,
                "files": {},
            }
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "format": STATE_SCHEMA_FORMAT,
                "version": 1,
                "files": {},
            }
        if not isinstance(payload, dict) or payload.get("format") != STATE_SCHEMA_FORMAT:
            return {
                "format": STATE_SCHEMA_FORMAT,
                "version": 1,
                "files": {},
            }
        if not isinstance(payload.get("files"), dict):
            payload["files"] = {}
        return payload


def _shape_error(spec: _StateFileSpec, payload: Any) -> str | None:
    if not isinstance(payload, (dict, list)):
        return "State payload must be a JSON object or a legacy collection list."
    if not spec.embedded_version:
        return None if isinstance(payload, dict) else "Map-style state payload must be a JSON object."
    if spec.filename == "vault.json":
        if not isinstance(payload, dict):
            return "Vault state must be a JSON object."
        if not isinstance(payload.get("sources", []), list) or not isinstance(payload.get("media_items", []), list):
            return "Vault sources and media_items must be lists."
        return None
    if spec.collection_key is None:
        return None if isinstance(payload, dict) else "State payload must be a JSON object."
    if isinstance(payload, list):
        return None
    collection = payload.get(spec.collection_key, [])
    return None if isinstance(collection, list) else f"{spec.collection_key} must be a list."


def _current_version(
    spec: _StateFileSpec,
    payload: Any,
    ledger_entry: Any,
) -> int:
    if spec.embedded_version and isinstance(payload, dict):
        try:
            return max(0, int(payload.get("version", 0)))
        except (TypeError, ValueError):
            return 0
    if isinstance(ledger_entry, dict):
        try:
            return max(0, int(ledger_entry.get("version", 0)))
        except (TypeError, ValueError):
            return 0
    return 0


def _migrate_v0_to_v1(spec: _StateFileSpec, payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        if spec.collection_key is None:
            raise ValueError(f"{spec.filename} has no collection key for legacy list migration")
        return {"version": 1, spec.collection_key: payload}
    migrated = dict(payload)
    migrated["version"] = 1
    if spec.filename == "vault.json":
        migrated.setdefault("sources", [])
        migrated.setdefault("media_items", [])
    elif spec.collection_key is not None:
        migrated.setdefault(spec.collection_key, [])
    return migrated


def _migration_message(
    spec: _StateFileSpec,
    action: Literal["none", "register", "migrate"],
    *,
    dry_run: bool,
) -> str:
    if action == "migrate":
        return (
            "A backup will be created before adding the versioned state envelope."
            if dry_run
            else "State payload migrated after creating a byte-for-byte backup."
        )
    if action == "register":
        return (
            "Schema version will be recorded in the state ledger."
            if dry_run
            else "Current payload registered in the state schema ledger."
        )
    return f"{spec.filename} is current."
