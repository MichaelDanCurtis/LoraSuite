from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from lorasuite_engine.comfyui_handoff import (
    ComfyHandoffManifest,
    build_and_write_handoff,
    install_comfy_extension,
    preview_handoff,
)
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.model_metadata import (
    LoraModelCard,
    build_snapshot_model_card,
    enrich_artifact_model_card,
    render_model_card_markdown,
)
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.revision_lineage import RevisionLineage
from lorasuite_engine.runpod_runs import RunPodRunArtifact, RunPodTrainingRunService
from lorasuite_engine.safetensors_metadata import (
    embed_safetensors_metadata,
    model_card_safetensors_metadata,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_runs import TrainingArtifact, TrainingRunService
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.video_dataset import VideoDatasetService


class ArtifactEvaluation(BaseModel):
    status: Literal["ready", "review", "failed"]
    checkpoint_valid: bool
    provenance_valid: bool
    config_present: bool
    sample_count: int = 0
    tensor_count: int = 0
    parameter_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: Any = Field(default_factory=utc_now)


class ArtifactAcceptance(BaseModel):
    status: Literal[
        "not_evaluated",
        "running",
        "screening_passed",
        "certified",
        "blocked",
        "failed",
        "error",
    ] = "not_evaluated"
    benchmark_run_id: str | None = None
    screening_ready: bool = False
    release_ready: bool = False
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    identity_similarity: float | None = None
    visual_quality: float | None = None
    subject_coverage: float | None = None
    temporal_stability: float | None = None
    speaker_similarity: float | None = None
    av_sync_proxy: float | None = None
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: Any | None = None


class ModelArtifactRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("model_artifact"))
    project_id: str = ""
    training_run_id: str
    snapshot_id: str
    dataset_fingerprint: str
    parent_snapshot_id: str | None = None
    parent_dataset_fingerprint: str | None = None
    improvement_request_id: str | None = None
    parent_artifact_id: str | None = None
    parent_checkpoint_sha256: str | None = None
    checkpoint_name: str
    checkpoint_path: Path
    checkpoint_sha256: str
    checkpoint_size_bytes: int
    config_path: Path | None = None
    sample_paths: list[Path] = Field(default_factory=list)
    trigger_token: str = ""
    base_model: str | None = None
    modality: Literal["image", "video", "voice", "audio_visual"] = "image"
    model_family: str = "unknown"
    model_card: LoraModelCard | None = None
    model_card_path: Path | None = None
    evaluation: ArtifactEvaluation
    acceptance: ArtifactAcceptance = Field(default_factory=ArtifactAcceptance)
    selected_for_release: bool = False
    release_selected_at: Any | None = None
    installed_paths: list[Path] = Field(default_factory=list)
    workflow_paths: list[Path] = Field(default_factory=list)
    handoff_paths: list[Path] = Field(default_factory=list)
    comfy_installations: list["ComfyArtifactInstallState"] = Field(default_factory=list)
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)


class ComfyInstallation(BaseModel):
    root: Path
    label: str
    models_path: Path
    workflows_path: Path


class ComfyArtifactInstallState(BaseModel):
    root: Path
    checkpoint_path: Path
    handoff_path: Path
    extension_path: Path
    extension_version: str
    compatibility_status: Literal["ready", "review", "blocked"]
    workflow_paths: list[Path] = Field(default_factory=list)
    runnable_workflow_count: int = 0
    installed_at: Any = Field(default_factory=utc_now)


class ArtifactReleaseCandidate(BaseModel):
    rank: int
    score: float
    eligible: bool
    selected: bool
    artifact: ModelArtifactRecord
    metrics: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class ModelRegistryService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def registry_path(self) -> Path:
        return self.vault_root / "model_artifacts.json"

    def list_artifacts(self, snapshot_id: str | None = None) -> list[ModelArtifactRecord]:
        records = self._read_records().values()
        if snapshot_id:
            records = (record for record in records if record.snapshot_id == snapshot_id)
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def get_artifact(self, artifact_id: str) -> ModelArtifactRecord | None:
        return self._read_records().get(artifact_id)

    def release_candidates(
        self,
        project_id: str,
        modality: Literal["image", "video", "voice", "audio_visual"] | None = None,
    ) -> list[ArtifactReleaseCandidate]:
        records = [
            record for record in self._read_records().values()
            if record.project_id == project_id and (modality is None or record.modality == modality)
        ]
        scored = sorted(
            ((_release_score(record), record) for record in records),
            key=lambda value: (value[0][1], value[0][0], value[1].updated_at),
            reverse=True,
        )
        return [
            ArtifactReleaseCandidate(
                rank=index,
                score=score,
                eligible=eligible,
                selected=record.selected_for_release,
                artifact=record,
                metrics=metrics,
                reasons=reasons,
            )
            for index, ((score, eligible, metrics, reasons), record) in enumerate(scored, start=1)
        ]

    def select_release(self, artifact_id: str) -> ModelArtifactRecord:
        records = self._read_records()
        selected = records.get(artifact_id)
        if selected is None:
            raise KeyError(artifact_id)
        if not selected.project_id:
            raise ValueError("model artifact has no character project provenance")
        if selected.evaluation.status == "failed" or not selected.acceptance.release_ready:
            raise ValueError("only a release-ready artifact can be selected")
        selected_at = utc_now()
        for record in records.values():
            if record.project_id == selected.project_id and record.modality == selected.modality:
                record.selected_for_release = record.id == selected.id
                record.release_selected_at = selected_at if record.id == selected.id else None
                record.updated_at = selected_at
        self._write_records(records)
        return records[selected.id]

    def register_training_run(self, run_id: str) -> list[ModelArtifactRecord]:
        run = TrainingRunService(self.vault_root).get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != "completed":
            raise ValueError("training must complete before artifacts can be registered")
        checkpoints = [artifact for artifact in run.artifacts if artifact.kind == "checkpoint"]
        if not checkpoints:
            raise ValueError("training run has no downloaded checkpoints")
        snapshot = DatasetCompilerService(self.vault_root).get_snapshot(run.snapshot_id)
        target_profile = None
        recovered = None
        if snapshot is None:
            snapshot = VideoDatasetService(self.vault_root).get_snapshot(run.snapshot_id)
            if snapshot is not None:
                target_profile = get_training_target_profile(snapshot.target_profile_id)
        if snapshot is None:
            recovered = RecoveredDatasetService(self.vault_root).find_by_snapshot_id(
                run.snapshot_id
            )
        if snapshot is None and recovered is None:
            raise ValueError("dataset snapshot and recovered export are no longer available")
        if recovered is not None:
            target_profile = get_training_target_profile(
                recovered.training_target.profile_id
            )
            trigger_token = recovered.trigger_token
            base_model_card = recovered.model_card
            lineage = recovered.revision_lineage
            actual_fingerprint = recovered.fingerprint
            project_id = recovered.project_id
        else:
            if target_profile is None:
                target_profile = get_training_target_profile(snapshot.training_target.profile_id)
            trigger_token = snapshot.trigger_token if hasattr(snapshot, "trigger_token") else snapshot.intent.trigger_token
            base_model_card = (
                snapshot.model_card or build_snapshot_model_card(snapshot)
                if hasattr(snapshot, "training_target")
                else None
            )
            lineage = RevisionLineage.from_snapshot(snapshot)
            actual_fingerprint = snapshot.fingerprint or ""
            project_id = snapshot.project_id
        records = self._read_records()
        config_artifact = next((item for item in run.artifacts if item.kind == "config"), None)
        sample_artifacts = [item for item in run.artifacts if item.kind == "sample"]
        registered: list[ModelArtifactRecord] = []
        for checkpoint in checkpoints:
            checkpoint_path = _local_artifact_path(checkpoint)
            existing = next(
                (
                    record
                    for record in records.values()
                    if record.training_run_id == run.id and record.checkpoint_path == checkpoint_path
                ),
                None,
            )
            evaluation = _evaluate_artifact(
                checkpoint_path=checkpoint_path,
                expected_fingerprint=run.dataset_fingerprint,
                actual_fingerprint=actual_fingerprint,
                config_artifact=config_artifact,
                sample_artifacts=sample_artifacts,
            )
            config_path = _optional_local_path(config_artifact)
            if existing:
                record = existing
                record.evaluation = evaluation
                _apply_revision_lineage(record, lineage)
                record.updated_at = utc_now()
            else:
                record = ModelArtifactRecord(
                    project_id=project_id,
                    training_run_id=run.id,
                    snapshot_id=run.snapshot_id,
                    dataset_fingerprint=run.dataset_fingerprint,
                    **lineage.model_dump(),
                    checkpoint_name=checkpoint_path.name,
                    checkpoint_path=checkpoint_path,
                    checkpoint_sha256=_sha256(checkpoint_path),
                    checkpoint_size_bytes=checkpoint_path.stat().st_size,
                    config_path=config_path,
                    sample_paths=[path for item in sample_artifacts if (path := _optional_local_path(item))],
                    trigger_token=trigger_token,
                    base_model=_base_model(config_path) or target_profile.base_model,
                    modality=target_profile.modality,
                    model_family=target_profile.model_family,
                    evaluation=evaluation,
                )
            _attach_model_card(record, base_model_card)
            records[record.id] = record
            registered.append(record)
        self._write_records(records)
        return registered

    def register_runpod_run(self, run_id: str) -> list[ModelArtifactRecord]:
        run = RunPodTrainingRunService(self.vault_root).get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != "completed":
            raise ValueError("RunPod training must complete before artifacts can be registered")
        checkpoints = [artifact for artifact in run.artifacts if artifact.kind == "checkpoint"]
        if not checkpoints:
            raise ValueError("RunPod training run has no checkpoint artifacts")
        missing = [artifact.name for artifact in run.artifacts if not artifact.local_path]
        if missing:
            raise ValueError("Download every RunPod artifact before registration")

        manifest = _runpod_bundle_manifest(run.bundle_path)
        manifest_fingerprint = str(manifest.get("fingerprint") or "")
        provenance_valid = bool(run.bundle_fingerprint) and run.bundle_fingerprint == manifest_fingerprint
        snapshot_id = run.snapshot_id or run.project_id or run.bundle_fingerprint
        trigger_token = str(manifest.get("trigger_token") or "")
        profile = get_training_target_profile(run.training_target_profile_id)
        actual_fingerprint = manifest_fingerprint
        project_id = run.project_id or ""
        base_model_card: LoraModelCard | None = None
        lineage = RevisionLineage(
            parent_snapshot_id=run.parent_snapshot_id,
            parent_dataset_fingerprint=run.parent_dataset_fingerprint,
            improvement_request_id=run.improvement_request_id,
            parent_artifact_id=run.parent_artifact_id,
            parent_checkpoint_sha256=run.parent_checkpoint_sha256,
        )
        if run.modality == "image":
            snapshot = DatasetCompilerService(self.vault_root).get_snapshot(snapshot_id)
            if snapshot is None:
                recovered = RecoveredDatasetService(self.vault_root).find_by_snapshot_id(
                    snapshot_id
                )
                if recovered is None:
                    raise ValueError("image dataset snapshot and recovered export are no longer available")
                actual_fingerprint = recovered.fingerprint
                trigger_token = recovered.trigger_token
                project_id = project_id or recovered.project_id
                base_model_card = recovered.model_card
                lineage = recovered.revision_lineage
            else:
                actual_fingerprint = snapshot.fingerprint or ""
                trigger_token = snapshot.intent.trigger_token
                project_id = project_id or snapshot.project_id
                base_model_card = snapshot.model_card or build_snapshot_model_card(snapshot)
                lineage = RevisionLineage.from_snapshot(snapshot)
        elif run.modality == "video":
            snapshot = VideoDatasetService(self.vault_root).get_snapshot(snapshot_id)
            if snapshot is None:
                recovered = RecoveredDatasetService(self.vault_root).find_by_snapshot_id(
                    snapshot_id
                )
                if recovered is None:
                    raise ValueError("video dataset snapshot and recovered export are no longer available")
                actual_fingerprint = recovered.fingerprint
                trigger_token = recovered.trigger_token
                project_id = project_id or recovered.project_id
                base_model_card = recovered.model_card
                lineage = recovered.revision_lineage
            else:
                actual_fingerprint = snapshot.fingerprint or ""
                trigger_token = snapshot.trigger_token
                project_id = project_id or snapshot.project_id
                lineage = RevisionLineage.from_snapshot(snapshot)
        provenance_valid = provenance_valid and run.bundle_fingerprint == actual_fingerprint

        config_path = _runpod_config_path(run.bundle_path, run.artifacts)
        records = self._read_records()
        registered: list[ModelArtifactRecord] = []
        for checkpoint in checkpoints:
            checkpoint_path = _runpod_local_artifact_path(checkpoint)
            sample_artifacts = [
                artifact for artifact in run.artifacts
                if artifact.kind == "sample"
                and artifact.local_path
                and (not checkpoint.group_id or artifact.group_id == checkpoint.group_id)
            ]
            sample_paths = [Path(artifact.local_path) for artifact in sample_artifacts if artifact.local_path]
            existing = next((
                record for record in records.values()
                if record.training_run_id == run.id and record.checkpoint_path == checkpoint_path
            ), None)
            if run.modality == "voice":
                evaluation = _evaluate_opaque_artifact(
                    checkpoint_path=checkpoint_path,
                    provenance_valid=provenance_valid,
                    config_path=config_path,
                    sample_paths=sample_paths,
                )
            else:
                evaluation = _evaluate_artifact_paths(
                    checkpoint_path=checkpoint_path,
                    provenance_valid=provenance_valid,
                    config_path=config_path,
                    sample_paths=sample_paths,
                )
            if existing:
                record = existing
                record.evaluation = evaluation
                _apply_revision_lineage(record, lineage)
                record.updated_at = utc_now()
            else:
                record = ModelArtifactRecord(
                    project_id=project_id,
                    training_run_id=run.id,
                    snapshot_id=snapshot_id,
                    dataset_fingerprint=run.bundle_fingerprint,
                    **lineage.model_dump(),
                    checkpoint_name=checkpoint_path.name,
                    checkpoint_path=checkpoint_path,
                    checkpoint_sha256=_sha256(checkpoint_path),
                    checkpoint_size_bytes=checkpoint_path.stat().st_size,
                    config_path=config_path,
                    sample_paths=[
                        path for path in sample_paths
                        if path.is_file() and (run.modality == "voice" or _valid_image(path))
                    ],
                    trigger_token=trigger_token,
                    base_model=_base_model(config_path) or profile.base_model,
                    modality=run.modality,
                    model_family=profile.model_family,
                    evaluation=evaluation,
                )
            _attach_model_card(record, base_model_card)
            records[record.id] = record
            registered.append(record)
        self._write_records(records)
        return registered

    def begin_acceptance(self, artifact_id: str, benchmark_run_id: str) -> ModelArtifactRecord:
        records = self._read_records()
        record = records.get(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        record.acceptance = ArtifactAcceptance(
            status="running",
            benchmark_run_id=benchmark_run_id,
        )
        record.updated_at = utc_now()
        records[record.id] = record
        self._write_records(records)
        return record

    def record_acceptance(
        self,
        artifact_id: str,
        benchmark_run_id: str,
        *,
        screening_ready: bool = False,
        release_ready: bool = False,
        passed_count: int = 0,
        failed_count: int = 0,
        blocked_count: int = 0,
        identity_similarity: float | None = None,
        visual_quality: float | None = None,
        subject_coverage: float | None = None,
        temporal_stability: float | None = None,
        speaker_similarity: float | None = None,
        av_sync_proxy: float | None = None,
        warnings: list[str] | None = None,
        error: str | None = None,
    ) -> ModelArtifactRecord:
        records = self._read_records()
        record = records.get(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        if error:
            status = "error"
        elif blocked_count:
            status = "blocked"
        elif release_ready:
            status = "certified"
        elif screening_ready:
            status = "screening_passed"
        else:
            status = "failed"
        record.acceptance = ArtifactAcceptance(
            status=status,
            benchmark_run_id=benchmark_run_id,
            screening_ready=screening_ready,
            release_ready=release_ready,
            passed_count=passed_count,
            failed_count=failed_count,
            blocked_count=blocked_count,
            identity_similarity=identity_similarity,
            visual_quality=visual_quality,
            subject_coverage=subject_coverage,
            temporal_stability=temporal_stability,
            speaker_similarity=speaker_similarity,
            av_sync_proxy=av_sync_proxy,
            warnings=[item for item in [*(warnings or []), error] if item],
            evaluated_at=utc_now(),
        )
        if not release_ready:
            record.selected_for_release = False
            record.release_selected_at = None
        if record.model_card is not None:
            _attach_model_card(record, record.model_card)
        record.updated_at = utc_now()
        records[record.id] = record
        self._write_records(records)
        return record

    def install_artifact(self, artifact_id: str, comfy_root: Path) -> ModelArtifactRecord:
        records = self._read_records()
        record = records.get(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        if record.evaluation.status == "failed":
            raise ValueError("failed artifact validation must be resolved before installation")
        if record.modality in {"voice", "audio_visual"}:
            raise ValueError(f"{record.modality} artifacts are not ComfyUI LoRA checkpoints")
        installation = resolve_comfy_installation(Path(comfy_root), require_existing=True)
        loras_dir = installation.models_path / "loras"
        workflows_dir = installation.workflows_path / "LoraSuite"
        loras_dir.mkdir(parents=True, exist_ok=True)
        workflows_dir.mkdir(parents=True, exist_ok=True)
        destination = loras_dir / record.checkpoint_name
        _atomic_copy(record.checkpoint_path, destination)
        if _sha256(destination) != record.checkpoint_sha256:
            raise ValueError("installed checkpoint SHA-256 does not match the registered artifact")
        extension_path = install_comfy_extension(installation.root)
        legacy_workflow = workflows_dir / f"{destination.stem}-starter.json"
        if _owned_workflow(legacy_workflow, record.id):
            legacy_workflow.unlink()
            record.workflow_paths = [
                path
                for path in record.workflow_paths
                if path.resolve(strict=False) != legacy_workflow.resolve(strict=False)
            ]
        sidecar = destination.with_suffix(destination.suffix + ".lorasuite.json")
        installed_model_card = destination.with_suffix(
            destination.suffix + ".model-card.json"
        )
        if record.model_card is not None:
            atomic_write_json(
                installed_model_card,
                record.model_card.model_dump(mode="json"),
            )
            installed_model_card.with_suffix(".md").write_text(
                render_model_card_markdown(record.model_card),
                encoding="utf-8",
            )
        atomic_write_json(
            sidecar,
            {
                "created_by": "LoraSuite",
                "artifact_id": record.id,
                "training_run_id": record.training_run_id,
                "dataset_snapshot_id": record.snapshot_id,
                "dataset_fingerprint": record.dataset_fingerprint,
                "checkpoint_sha256": record.checkpoint_sha256,
                "trigger_token": record.trigger_token,
                "base_model": record.base_model,
                "modality": record.modality,
                "model_family": record.model_family,
                "model_card_path": str(installed_model_card)
                if record.model_card is not None
                else None,
                "model_card": record.model_card.model_dump(mode="json")
                if record.model_card is not None
                else None,
                "evaluation": record.evaluation.model_dump(mode="json"),
            },
        )
        handoff, handoff_path = build_and_write_handoff(
            record=record,
            installation=installation,
            checkpoint_path=destination,
            extension_path=extension_path,
            engine_url=os.environ.get("LORASUITE_ENGINE_URL", "http://127.0.0.1:8765"),
        )
        sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
        sidecar_payload.update(
            {
                "handoff_format": handoff.format,
                "handoff_path": str(handoff_path),
            }
        )
        atomic_write_json(sidecar, sidecar_payload)
        if destination not in record.installed_paths:
            record.installed_paths.append(destination)
        if record.model_card is not None and installed_model_card not in record.installed_paths:
            record.installed_paths.append(installed_model_card)
        if handoff_path not in record.handoff_paths:
            record.handoff_paths.append(handoff_path)
        for workflow in handoff.workflows:
            if workflow.path not in record.workflow_paths:
                record.workflow_paths.append(workflow.path)
        state = ComfyArtifactInstallState(
            root=installation.root,
            checkpoint_path=destination,
            handoff_path=handoff_path,
            extension_path=extension_path,
            extension_version=str(handoff.extension["version"]),
            compatibility_status=handoff.compatibility.status,
            workflow_paths=[workflow.path for workflow in handoff.workflows],
            runnable_workflow_count=sum(workflow.runnable for workflow in handoff.workflows),
        )
        record.comfy_installations = [
            state,
            *[
                existing
                for existing in record.comfy_installations
                if existing.root.resolve(strict=False)
                != installation.root.resolve(strict=False)
            ],
        ]
        record.updated_at = utc_now()
        records[record.id] = record
        self._write_records(records)
        return record

    def preview_comfy_handoff(
        self,
        artifact_id: str,
        comfy_root: Path,
    ) -> ComfyHandoffManifest:
        record = self.get_artifact(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        installation = resolve_comfy_installation(Path(comfy_root), require_existing=True)
        return preview_handoff(
            record=record,
            installation=installation,
            engine_url=os.environ.get("LORASUITE_ENGINE_URL", "http://127.0.0.1:8765"),
        )

    def _read_records(self) -> dict[str, ModelArtifactRecord]:
        with json_file_lock(self.registry_path):
            if not self.registry_path.exists():
                return {}
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return {
                item["id"]: ModelArtifactRecord.model_validate(item)
                for item in payload.get("artifacts", [])
            }

    def _write_records(self, records: dict[str, ModelArtifactRecord]) -> None:
        with json_file_lock(self.registry_path):
            atomic_write_json(
                self.registry_path,
                {
                    "version": 1,
                    "artifacts": [record.model_dump(mode="json") for record in records.values()],
                },
            )


def discover_comfy_installations() -> list[ComfyInstallation]:
    home = Path.home()
    candidates = [
        Path(value).expanduser()
        for value in [
            os.environ.get("COMFYUI_ROOT", ""),
            home / "ComfyUI",
            home / "Documents" / "ComfyUI",
            home / "Documents" / "ComfyUI" / "ComfyUI",
            home / "ComfyUI-Shared",
        ]
        if value
    ]
    found: list[ComfyInstallation] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            installation = resolve_comfy_installation(candidate, require_existing=True)
        except ValueError:
            continue
        if not (installation.root / "main.py").is_file():
            continue
        key = str(installation.root.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            found.append(installation)
    return found


def resolve_comfy_installation(root: Path, *, require_existing: bool) -> ComfyInstallation:
    root = root.expanduser().resolve(strict=False)
    roots = [root]
    if root.name == "models":
        roots.insert(0, root.parent)
    if (root / "ComfyUI").is_dir():
        roots.insert(0, root / "ComfyUI")
    selected = next((candidate for candidate in roots if (candidate / "models").is_dir()), None)
    if selected is None:
        if require_existing:
            raise ValueError("choose a ComfyUI root containing a models folder")
        selected = root
    models_path = selected / "models"
    if (selected / "user" / "default").is_dir():
        workflows_path = selected / "user" / "default" / "workflows"
    else:
        workflows_path = selected / "user" / "default" / "workflows"
    return ComfyInstallation(
        root=selected,
        label=selected.name or str(selected),
        models_path=models_path,
        workflows_path=workflows_path,
    )


def _evaluate_artifact(
    *,
    checkpoint_path: Path,
    expected_fingerprint: str,
    actual_fingerprint: str,
    config_artifact: TrainingArtifact | None,
    sample_artifacts: list[TrainingArtifact],
) -> ArtifactEvaluation:
    warnings: list[str] = []
    checkpoint_valid = False
    tensor_count = 0
    parameter_count = 0
    try:
        tensor_count, parameter_count = _safetensors_summary(checkpoint_path)
        checkpoint_valid = tensor_count > 0 and parameter_count > 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Checkpoint validation failed: {error}")
    provenance_valid = bool(expected_fingerprint) and expected_fingerprint == actual_fingerprint
    if not provenance_valid:
        warnings.append("Dataset fingerprint no longer matches the frozen snapshot.")
    config_path = _optional_local_path(config_artifact)
    config_present = bool(config_path and config_path.is_file())
    if not config_present:
        warnings.append("Resolved training configuration is missing.")
    valid_samples = 0
    for artifact in sample_artifacts:
        path = _optional_local_path(artifact)
        if path and _valid_image(path):
            valid_samples += 1
    if not valid_samples:
        warnings.append("No valid training preview sample was downloaded.")
    if not checkpoint_valid or not provenance_valid:
        status: Literal["ready", "review", "failed"] = "failed"
    elif not config_present or not valid_samples:
        status = "review"
    else:
        status = "ready"
    return ArtifactEvaluation(
        status=status,
        checkpoint_valid=checkpoint_valid,
        provenance_valid=provenance_valid,
        config_present=config_present,
        sample_count=valid_samples,
        tensor_count=tensor_count,
        parameter_count=parameter_count,
        warnings=warnings,
    )


def _evaluate_artifact_paths(
    *,
    checkpoint_path: Path,
    provenance_valid: bool,
    config_path: Path | None,
    sample_paths: list[Path],
) -> ArtifactEvaluation:
    warnings: list[str] = []
    checkpoint_valid = False
    tensor_count = 0
    parameter_count = 0
    try:
        tensor_count, parameter_count = _safetensors_summary(checkpoint_path)
        checkpoint_valid = tensor_count > 0 and parameter_count > 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Checkpoint validation failed: {error}")
    if not provenance_valid:
        warnings.append("Dataset fingerprint no longer matches the RunPod bundle source.")
    config_present = bool(config_path and config_path.is_file())
    if not config_present:
        warnings.append("Resolved training configuration is missing.")
    sample_count = sum(1 for path in sample_paths if _valid_image(path))
    if not sample_count:
        warnings.append("No valid training preview sample was downloaded.")
    if not checkpoint_valid or not provenance_valid:
        status: Literal["ready", "review", "failed"] = "failed"
    elif not config_present or not sample_count:
        status = "review"
    else:
        status = "ready"
    return ArtifactEvaluation(
        status=status,
        checkpoint_valid=checkpoint_valid,
        provenance_valid=provenance_valid,
        config_present=config_present,
        sample_count=sample_count,
        tensor_count=tensor_count,
        parameter_count=parameter_count,
        warnings=warnings,
    )


def _evaluate_opaque_artifact(
    *,
    checkpoint_path: Path,
    provenance_valid: bool,
    config_path: Path | None,
    sample_paths: list[Path],
) -> ArtifactEvaluation:
    checkpoint_valid = checkpoint_path.is_file() and checkpoint_path.stat().st_size > 0
    config_present = bool(config_path and config_path.is_file())
    warnings = ["Voice checkpoint is verified by size and checksum; framework loading is evaluated in the voice harness."]
    if not provenance_valid:
        warnings.append("Dataset fingerprint no longer matches the RunPod bundle source.")
    if not config_present:
        warnings.append("Resolved training configuration is missing.")
    if not checkpoint_valid or not provenance_valid:
        status: Literal["ready", "review", "failed"] = "failed"
    else:
        status = "review"
    return ArtifactEvaluation(
        status=status,
        checkpoint_valid=checkpoint_valid,
        provenance_valid=provenance_valid,
        config_present=config_present,
        sample_count=sum(1 for path in sample_paths if path.is_file() and path.suffix.lower() in {".wav", ".flac", ".mp3", ".m4a"}),
        warnings=warnings,
    )


def _safetensors_summary(path: Path) -> tuple[int, int]:
    if path.suffix.lower() != ".safetensors":
        raise ValueError("checkpoint is not a .safetensors file")
    with path.open("rb") as handle:
        header_size_bytes = handle.read(8)
        if len(header_size_bytes) != 8:
            raise ValueError("checkpoint header is truncated")
        header_size = struct.unpack("<Q", header_size_bytes)[0]
        if header_size <= 2 or header_size > 100_000_000:
            raise ValueError("checkpoint header size is invalid")
        header = json.loads(handle.read(header_size))
    tensors = [value for key, value in header.items() if key != "__metadata__" and isinstance(value, dict)]
    parameters = 0
    for tensor in tensors:
        shape = tensor.get("shape")
        if not isinstance(shape, list) or not shape:
            continue
        count = 1
        for dimension in shape:
            count *= int(dimension)
        parameters += count
    return len(tensors), parameters


def _starter_workflow(record: ModelArtifactRecord, lora_name: str) -> dict[str, Any]:
    checkpoint_name = record.base_model or "SELECT_BASE_MODEL.safetensors"
    prompt = f"portrait of {record.trigger_token}" if record.trigger_token else "portrait"
    nodes = [
        _node(1, "CheckpointLoaderSimple", "Checkpoint", [checkpoint_name], [40, 120], [_widget("ckpt_name", "COMBO")], [_output("MODEL", "MODEL", [1], 0), _output("CLIP", "CLIP", [2], 1), _output("VAE", "VAE", [10], 2)]),
        _node(2, "LoraLoader", "LoRA", [lora_name, 1.0, 1.0], [330, 120], [_input("model", "MODEL", 1), _input("clip", "CLIP", 2), _widget("lora_name", "COMBO"), _widget("strength_model", "FLOAT"), _widget("strength_clip", "FLOAT")], [_output("MODEL", "MODEL", [3], 0), _output("CLIP", "CLIP", [4, 5], 1)]),
        _node(3, "CLIPTextEncode", "Positive", [prompt], [620, 40], [_input("clip", "CLIP", 4), _widget("text", "STRING")], [_output("CONDITIONING", "CONDITIONING", [6], 0)]),
        _node(4, "CLIPTextEncode", "Negative", ["blurry, distorted, low quality"], [620, 220], [_input("clip", "CLIP", 5), _widget("text", "STRING")], [_output("CONDITIONING", "CONDITIONING", [7], 0)]),
        _node(5, "EmptyLatentImage", "Latent", [1024, 1024, 1], [620, 400], [_widget("width", "INT"), _widget("height", "INT"), _widget("batch_size", "INT")], [_output("LATENT", "LATENT", [8], 0)]),
        _node(6, "KSampler", "Sampler", [123456789, "randomize", 24, 4.0, "euler", "normal", 1.0], [920, 160], [_input("model", "MODEL", 3), _input("positive", "CONDITIONING", 6), _input("negative", "CONDITIONING", 7), _input("latent_image", "LATENT", 8), _widget("seed", "INT"), _widget("steps", "INT"), _widget("cfg", "FLOAT"), _widget("sampler_name", "COMBO"), _widget("scheduler", "COMBO"), _widget("denoise", "FLOAT")], [_output("LATENT", "LATENT", [9], 0)]),
        _node(7, "VAEDecode", "Decode", [], [1210, 180], [_input("samples", "LATENT", 9), _input("vae", "VAE", 10)], [_output("IMAGE", "IMAGE", [11], 0)]),
        _node(8, "SaveImage", "Save", ["LoraSuite", False], [1450, 180], [_input("images", "IMAGE", 11), _widget("filename_prefix", "STRING"), _widget("strip_metadata", "BOOLEAN")], [_output("images", "IMAGE", [], 0)]),
    ]
    links = [
        [1, 1, 0, 2, 0, "MODEL"], [2, 1, 1, 2, 1, "CLIP"],
        [3, 2, 0, 6, 0, "MODEL"], [4, 2, 1, 3, 0, "CLIP"],
        [5, 2, 1, 4, 0, "CLIP"], [6, 3, 0, 6, 1, "CONDITIONING"],
        [7, 4, 0, 6, 2, "CONDITIONING"], [8, 5, 0, 6, 3, "LATENT"],
        [9, 6, 0, 7, 0, "LATENT"], [10, 1, 2, 7, 1, "VAE"],
        [11, 7, 0, 8, 0, "IMAGE"],
    ]
    return {
        "id": new_id("workflow"),
        "revision": 0,
        "last_node_id": 8,
        "last_link_id": 11,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "definitions": {"subgraphs": []},
        "config": {},
        "extra": {
            "ds": {"scale": 0.8, "offset": [0, 0]},
            "lorasuite": {
                "artifact_id": record.id,
                "dataset_fingerprint": record.dataset_fingerprint,
                "checkpoint_sha256": record.checkpoint_sha256,
            },
        },
        "version": 0.4,
    }


def _node(
    node_id: int,
    node_type: str,
    title: str,
    widgets: list[Any],
    pos: list[int],
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    sizes = {
        "CheckpointLoaderSimple": [280, 100], "LoraLoader": [260, 130],
        "CLIPTextEncode": [270, 130], "EmptyLatentImage": [260, 110],
        "KSampler": [270, 260], "VAEDecode": [210, 70], "SaveImage": [220, 90],
    }
    return {
        "id": node_id, "type": node_type, "pos": pos, "size": sizes[node_type],
        "flags": {}, "order": node_id - 1, "mode": 0, "inputs": inputs, "outputs": outputs,
        "properties": {"Node name for S&R": node_type}, "widgets_values": widgets,
        "title": title,
    }


def _input(name: str, input_type: str, link: int) -> dict[str, Any]:
    return {"name": name, "type": input_type, "link": link}


def _widget(name: str, input_type: str) -> dict[str, Any]:
    return {"name": name, "type": input_type, "widget": {"name": name}, "link": None}


def _output(name: str, output_type: str, links: list[int], slot_index: int) -> dict[str, Any]:
    return {"name": name, "type": output_type, "links": links, "slot_index": slot_index}


def _local_artifact_path(artifact: TrainingArtifact) -> Path:
    path = _optional_local_path(artifact)
    if path is None or not path.is_file():
        raise ValueError(f"downloaded artifact is missing: {artifact.name}")
    return path


def _runpod_local_artifact_path(artifact: RunPodRunArtifact) -> Path:
    if not artifact.local_path:
        raise ValueError(f"downloaded RunPod artifact is missing: {artifact.name}")
    path = Path(artifact.local_path)
    if not path.is_file():
        raise ValueError(f"downloaded RunPod artifact is missing: {artifact.name}")
    return path


def _runpod_bundle_manifest(bundle_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads((Path(bundle_path) / "bundle_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("RunPod bundle manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("format") != "lorasuite-runpod-v1":
        raise ValueError("RunPod bundle provenance is invalid")
    return payload


def _runpod_config_path(bundle_path: Path, artifacts: list[RunPodRunArtifact]) -> Path | None:
    downloaded = next((
        Path(artifact.local_path)
        for artifact in artifacts
        if artifact.kind == "config" and artifact.local_path and Path(artifact.local_path).is_file()
    ), None)
    if downloaded:
        return downloaded
    config_root = Path(bundle_path) / "config"
    return next((
        candidate
        for name in ("serverless_train.yaml", "train.yaml")
        if (candidate := config_root / name).is_file()
    ), None)


def _optional_local_path(artifact: TrainingArtifact | None) -> Path | None:
    return Path(artifact.local_path) if artifact and artifact.local_path else None


def _base_model(config_path: Path | None) -> str | None:
    if not config_path or not config_path.is_file():
        return None
    content = config_path.read_text(encoding="utf-8", errors="replace")
    for pattern in (r"(?:name_or_path|model_path|model_name):\s*['\"]?([^'\"\n]+)",):
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            return Path(value).name if value.endswith((".safetensors", ".ckpt")) else value
    return None


def _valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError):
        return False


def _apply_revision_lineage(
    record: ModelArtifactRecord,
    lineage: RevisionLineage,
) -> None:
    record.parent_snapshot_id = lineage.parent_snapshot_id
    record.parent_dataset_fingerprint = lineage.parent_dataset_fingerprint
    record.improvement_request_id = lineage.improvement_request_id
    record.parent_artifact_id = lineage.parent_artifact_id
    record.parent_checkpoint_sha256 = lineage.parent_checkpoint_sha256


def _attach_model_card(
    record: ModelArtifactRecord,
    base_card: LoraModelCard | None,
) -> None:
    if base_card is None:
        return
    source_checkpoint_sha256 = (
        str(record.model_card.artifact.get("source_checkpoint_sha256"))
        if record.model_card is not None
        and isinstance(record.model_card.artifact, dict)
        and record.model_card.artifact.get("source_checkpoint_sha256")
        else record.checkpoint_sha256
    )
    if record.checkpoint_path.suffix.casefold() == ".safetensors":
        embed_safetensors_metadata(
            record.checkpoint_path,
            model_card_safetensors_metadata(
                base_card,
                artifact_id=record.id,
                training_run_id=record.training_run_id,
                source_checkpoint_sha256=source_checkpoint_sha256,
            ),
        )
        record.checkpoint_sha256 = _sha256(record.checkpoint_path)
        record.checkpoint_size_bytes = record.checkpoint_path.stat().st_size
    card = enrich_artifact_model_card(
        base_card,
        artifact_id=record.id,
        training_run_id=record.training_run_id,
        checkpoint_name=record.checkpoint_name,
        checkpoint_sha256=record.checkpoint_sha256,
        checkpoint_size_bytes=record.checkpoint_size_bytes,
        evaluation=record.evaluation.model_dump(mode="json"),
        acceptance=record.acceptance.model_dump(mode="json"),
        source_checkpoint_sha256=source_checkpoint_sha256,
    )
    model_card_path = record.checkpoint_path.with_suffix(
        record.checkpoint_path.suffix + ".model-card.json"
    )
    atomic_write_json(model_card_path, card.model_dump(mode="json"))
    model_card_path.with_suffix(".md").write_text(
        render_model_card_markdown(card),
        encoding="utf-8",
    )
    record.model_card = card
    record.model_card_path = model_card_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_score(record: ModelArtifactRecord) -> tuple[float, bool, dict[str, float], list[str]]:
    acceptance = record.acceptance
    metric_weights = {
        "identity_similarity": 0.30,
        "visual_quality": 0.15,
        "subject_coverage": 0.10,
        "temporal_stability": 0.15,
        "speaker_similarity": 0.20,
        "av_sync_proxy": 0.10,
    }
    metrics = {
        name: max(0.0, min(1.0, float(value)))
        for name, weight in metric_weights.items()
        if weight and (value := getattr(acceptance, name)) is not None
    }
    available_weight = sum(metric_weights[name] for name in metrics)
    metric_score = (
        sum(metrics[name] * metric_weights[name] for name in metrics) / available_weight
        if available_weight else 0.0
    )
    decided = acceptance.passed_count + acceptance.failed_count + acceptance.blocked_count
    gate_score = acceptance.passed_count / decided if decided else 0.0
    score = round((metric_score * 0.8 + gate_score * 0.2) * 100.0, 1)
    eligible = record.evaluation.status != "failed" and acceptance.release_ready
    reasons = []
    if record.evaluation.status == "failed":
        reasons.append("checkpoint validation failed")
    if not acceptance.release_ready:
        reasons.append("acceptance gates are incomplete")
    if not metrics:
        reasons.append("no comparable acceptance metrics are available")
    return score, eligible, metrics, reasons


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _owned_workflow(path: Path, artifact_id: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("extra", {})
        .get("lorasuite", {})
        .get("artifact_id")
        == artifact_id
    )
