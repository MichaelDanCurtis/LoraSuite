from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from lorasuite_engine.cloud_providers import CloudProviderService
from lorasuite_engine.comfyui_handoff import inspect_comfy_runtime
from lorasuite_engine.models import utc_now
from lorasuite_engine.partner_qualification import PartnerQualificationService
from lorasuite_engine.state_migrations import StateMigrationService
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService, sha256_file


DIAGNOSTIC_FORMAT = "lorasuite.diagnostic-bundle.v1"
ENGINE_VERSION = "0.1.0"
SECRET_ENVIRONMENT_VARIABLES = (
    "RUNCOMFY_TOKEN",
    "RUNPOD_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY",
    "KIMI_CODE_API_KEY",
    "MOONSHOT_API_KEY",
    "XAI_API_KEY",
    "HF_TOKEN",
)


class DiagnosticBundleRecord(BaseModel):
    id: str
    format: Literal["lorasuite.diagnostic-bundle.v1"] = DIAGNOSTIC_FORMAT
    archive_path: Path
    archive_sha256: str
    size_bytes: int
    included_files: list[str]
    exclusions: list[str]
    state_ready: bool
    comfy_runtime_included: bool = False
    partner_qualification_included: bool = False
    created_at: Any = Field(default_factory=utc_now)


class DiagnosticBundleService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def bundles_dir(self) -> Path:
        return self.vault_root / "diagnostics"

    @property
    def registry_path(self) -> Path:
        return self.vault_root / "diagnostic_bundles.json"

    def list_bundles(self) -> list[DiagnosticBundleRecord]:
        records = list(self._read().values())
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def get_bundle(self, bundle_id: str) -> DiagnosticBundleRecord | None:
        return self._read().get(bundle_id)

    def create(
        self,
        *,
        comfy_root: Path | None = None,
        comfy_base_url: str = "http://127.0.0.1:8188",
        project_id: str | None = None,
    ) -> DiagnosticBundleRecord:
        bundle_id = f"diagnostic_bundle_{uuid4().hex}"
        report = self._report(
            bundle_id=bundle_id,
            comfy_root=comfy_root,
            comfy_base_url=comfy_base_url,
        )
        partner_readiness = self._partner_readiness()
        partner_qualification = (
            PartnerQualificationService(self.vault_root)
            .report(project_id)
            .model_dump(mode="json")
            if project_id
            else None
        )
        readme = _readme(report)
        serialized_report = json.dumps(report, indent=2, sort_keys=True) + "\n"
        serialized_partner = json.dumps(partner_readiness, indent=2, sort_keys=True) + "\n"
        serialized_qualification = (
            json.dumps(partner_qualification, indent=2, sort_keys=True) + "\n"
            if partner_qualification is not None
            else None
        )
        _assert_private_safe(
            [
                serialized_report,
                serialized_partner,
                *([serialized_qualification] if serialized_qualification else []),
                readme,
            ],
            vault_root=self.vault_root,
        )

        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.bundles_dir / f"{bundle_id}.zip"
        temporary_path = archive_path.with_name(f".{archive_path.name}.{uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(
                temporary_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                archive.writestr("diagnostic_report.json", serialized_report)
                archive.writestr("partner_readiness.json", serialized_partner)
                if serialized_qualification is not None:
                    archive.writestr(
                        "partner_qualification.json",
                        serialized_qualification,
                    )
                archive.writestr("README.txt", readme)
            temporary_path.replace(archive_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        record = DiagnosticBundleRecord(
            id=bundle_id,
            archive_path=archive_path,
            archive_sha256=sha256_file(archive_path),
            size_bytes=archive_path.stat().st_size,
            included_files=[
                "diagnostic_report.json",
                "partner_readiness.json",
                *(
                    ["partner_qualification.json"]
                    if serialized_qualification is not None
                    else []
                ),
                "README.txt",
            ],
            exclusions=[
                "credentials and environment-variable values",
                "private media and generated previews",
                "captions, transcripts, prompts, and user-entered notes",
                "source URLs, account handles, and local absolute paths",
            ],
            state_ready=bool(report["state_schema"]["ready"]),
            comfy_runtime_included=comfy_root is not None,
            partner_qualification_included=serialized_qualification is not None,
        )
        with json_file_lock(self.registry_path):
            records = self._read_unlocked()
            records[record.id] = record
            atomic_write_json(
                self.registry_path,
                {
                    "version": 1,
                    "bundles": [
                        item.model_dump(mode="json")
                        for item in records.values()
                    ],
                },
            )
        return record

    def _report(
        self,
        *,
        bundle_id: str,
        comfy_root: Path | None,
        comfy_base_url: str,
    ) -> dict[str, Any]:
        state = StateMigrationService(self.vault_root).inspect()
        media_items = VaultService(self.vault_root).list_media_items()
        media_types = Counter(str(item.media_type.value) for item in media_items)
        media_statuses = Counter(str(item.status.value) for item in media_items)
        report: dict[str, Any] = {
            "format": DIAGNOSTIC_FORMAT,
            "bundle_id": bundle_id,
            "created_at": utc_now().isoformat(),
            "engine": {
                "version": ENGINE_VERSION,
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
            },
            "system": {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "machine": platform.machine(),
            },
            "privacy": {
                "credentials_included": False,
                "media_included": False,
                "captions_or_transcripts_included": False,
                "source_urls_or_handles_included": False,
                "absolute_paths_included": False,
            },
            "state_schema": {
                "format": state.format,
                "ready": state.ready,
                "pending_count": state.pending_count,
                "invalid_count": state.invalid_count,
                "future_count": state.future_count,
                "files": [
                    {
                        "filename": item.filename,
                        "exists": item.exists,
                        "current_version": item.current_version,
                        "target_version": item.target_version,
                        "status": item.status,
                        "embedded_version": item.embedded_version,
                    }
                    for item in state.files
                ],
            },
            "inventory": {
                "media_total": len(media_items),
                "media_by_type": dict(sorted(media_types.items())),
                "media_by_status": dict(sorted(media_statuses.items())),
                "persistent_records": _persistent_record_counts(self.vault_root),
                "storage": _storage_summary(self.vault_root),
            },
            "providers": self._partner_readiness()["providers"],
            "checks": {
                "state_schema_ready": state.ready,
                "vault_readable": True,
                "provider_contracts_available": True,
            },
        }
        if comfy_root is not None:
            runtime = inspect_comfy_runtime(
                comfy_root,
                base_url=comfy_base_url,
            )
            report["comfyui"] = {
                "root_name": Path(runtime.root).name,
                "root_digest": hashlib.sha256(
                    str(Path(runtime.root).expanduser().resolve(strict=False)).encode("utf-8"),
                ).hexdigest(),
                "base_url_origin": _safe_origin(runtime.base_url),
                "reachable": runtime.reachable,
                "extension_installed": runtime.extension_installed,
                "extension_version": runtime.extension_version,
                "required_nodes": runtime.required_nodes,
                "loaded_nodes": runtime.loaded_nodes,
                "missing_nodes": runtime.missing_nodes,
                "restart_required": runtime.restart_required,
                "error_category": "unreachable" if runtime.error else None,
            }
            report["checks"]["comfyui_reachable"] = runtime.reachable
            report["checks"]["comfyui_nodes_loaded"] = not runtime.missing_nodes
        return report

    def _partner_readiness(self) -> dict[str, Any]:
        descriptors = CloudProviderService(self.vault_root).descriptors()
        return {
            "format": "lorasuite.partner-readiness.v1",
            "created_at": utc_now().isoformat(),
            "providers": [
                {
                    "id": descriptor.id,
                    "label": descriptor.label,
                    "contract_version": descriptor.contract_version,
                    "target_profile_count": len(descriptor.target_profile_ids),
                    "modalities": descriptor.modalities,
                    "actions": descriptor.actions,
                    "gpu_families": descriptor.gpu_families,
                    "billing_models": descriptor.billing_models,
                    "credential_names": descriptor.auth_environment_variables,
                    "features": [
                        {
                            "id": feature.id,
                            "support": feature.support,
                        }
                        for feature in descriptor.features
                    ],
                    "warning_count": len(descriptor.warnings),
                }
                for descriptor in descriptors
            ],
            "comfyui_contract": "lorasuite.comfy-handoff.v1",
            "state_contract": "lorasuite.state-schema.v1",
            "recovery_contract": "lorasuite.recovered-dataset.v1",
        }

    def _read(self) -> dict[str, DiagnosticBundleRecord]:
        with json_file_lock(self.registry_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, DiagnosticBundleRecord]:
        if not self.registry_path.is_file():
            return {}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("bundles", []) if isinstance(payload, dict) else []
        return {
            item["id"]: DiagnosticBundleRecord.model_validate(item)
            for item in records
            if isinstance(item, dict) and item.get("id")
        }


def _persistent_record_counts(vault_root: Path) -> dict[str, int]:
    collection_keys = {
        "character_projects.json": "projects",
        "ingress_candidates.json": "candidates",
        "ingress_jobs.json": "jobs",
        "dataset_snapshots.json": "snapshots",
        "video_dataset_snapshots.json": "snapshots",
        "training_runs.json": "runs",
        "runpod_training_runs.json": "runs",
        "runpod_bundles.json": "bundles",
        "model_artifacts.json": "artifacts",
        "recovered_dataset_exports.json": "exports",
        "diagnostic_bundles.json": "bundles",
    }
    counts: dict[str, int] = {}
    for filename, collection_key in collection_keys.items():
        path = vault_root / filename
        if not path.is_file():
            counts[filename] = 0
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counts[filename] = -1
            continue
        values = payload.get(collection_key, []) if isinstance(payload, dict) else []
        counts[filename] = len(values) if isinstance(values, list) else -1
    for filename in (
        "processing_jobs.json",
        "social_acquisition_jobs.json",
        "provider_smoke_runs.json",
    ):
        path = vault_root / filename
        if not path.is_file():
            counts[filename] = 0
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counts[filename] = -1
            continue
        counts[filename] = len(payload) if isinstance(payload, dict) else -1
    return counts


def _storage_summary(vault_root: Path) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for name in ("raw", "derivatives", "previews", "uploads", "exports", "models"):
        root = vault_root / name
        file_count = 0
        size_bytes = 0
        if root.is_dir():
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    size_bytes += path.stat().st_size
                    file_count += 1
                except OSError:
                    continue
        summary[name] = {
            "file_count": file_count,
            "size_bytes": size_bytes,
        }
    return summary


def _safe_origin(value: str) -> str:
    if value.startswith("http://127.0.0.1"):
        return "http://127.0.0.1"
    if value.startswith("http://localhost"):
        return "http://localhost"
    return "configured-remote-origin"


def _assert_private_safe(contents: list[str], *, vault_root: Path) -> None:
    forbidden = [str(vault_root.expanduser().resolve(strict=False))]
    forbidden.extend(
        value
        for name in SECRET_ENVIRONMENT_VARIABLES
        if (value := os.environ.get(name)) and len(value) >= 8
    )
    combined = "\n".join(contents)
    for value in forbidden:
        if value and value in combined:
            raise ValueError("diagnostic bundle privacy check failed")


def _readme(report: dict[str, Any]) -> str:
    checks = report["checks"]
    return (
        "LoraSuite Diagnostic Bundle\n"
        "===========================\n\n"
        "This package contains structural state, runtime, and provider-contract\n"
        "information for support and partner qualification.\n\n"
        "It does not contain credentials, media, captions, transcripts, prompts,\n"
        "source URLs, account handles, or local absolute paths.\n\n"
        f"State schema ready: {checks['state_schema_ready']}\n"
        f"Vault readable: {checks['vault_readable']}\n"
        f"Provider contracts available: {checks['provider_contracts_available']}\n"
    )
