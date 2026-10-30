from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.runpod_runs import RunPodTrainingRun, RunPodTrainingRunService
from lorasuite_engine.training_runs import TrainingRun, TrainingRunService
from lorasuite_engine.training_targets import training_target_profiles
from lorasuite_engine.video_dataset import VideoDatasetService


CloudProviderName = Literal["runcomfy", "runpod"]
CloudFeatureSupport = Literal["native", "adapter", "partial", "unavailable"]
CloudRunState = Literal[
    "queued",
    "preparing",
    "running",
    "paused",
    "retrieving",
    "completed",
    "failed",
    "canceled",
]
CloudRunAction = Literal[
    "refresh",
    "cancel",
    "resume",
    "retry",
    "download_artifacts",
    "register_artifacts",
    "evaluate",
]


class CloudProviderFeature(BaseModel):
    id: str
    label: str
    support: CloudFeatureSupport
    detail: str


class CloudProviderDescriptor(BaseModel):
    id: CloudProviderName
    label: str
    contract_version: str = "lorasuite.cloud-provider.v1"
    auth_environment_variables: list[str]
    target_profile_ids: list[str]
    modalities: list[Literal["image", "video", "voice", "audio_visual"]]
    actions: list[str]
    gpu_families: list[str]
    billing_models: list[str]
    documentation_urls: list[str]
    pricing_snapshot_date: str = "2026-07-16"
    features: list[CloudProviderFeature]
    warnings: list[str] = Field(default_factory=list)


class CloudRunProgress(BaseModel):
    current: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = ""


class CloudRunRecord(BaseModel):
    id: str
    provider: CloudProviderName
    provider_job_id: str | None = None
    project_id: str | None = None
    snapshot_id: str | None = None
    training_target_profile_id: str = ""
    modality: Literal["image", "video", "voice", "audio_visual"] | None = None
    operation: Literal["train", "inference"] = "train"
    state: CloudRunState
    provider_status: str
    progress: CloudRunProgress
    dataset_fingerprint: str = ""
    config_digest: str = ""
    gpu: str | None = None
    artifact_count: int = 0
    local_artifact_count: int = 0
    checksum_artifact_count: int = 0
    registered_artifact_count: int = 0
    available_actions: list[CloudRunAction] = Field(default_factory=list)
    error: str | None = None
    failure_category: str | None = None
    created_at: Any = None
    updated_at: Any = None
    completed_at: Any | None = None


class CloudProviderService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def descriptors(self) -> list[CloudProviderDescriptor]:
        profiles = training_target_profiles()
        runcomfy_profiles = [
            profile for profile in profiles
            if profile.ready and profile.provider == "runcomfy"
        ]
        runpod_profiles = [profile for profile in profiles if profile.ready]
        return [
            CloudProviderDescriptor(
                id="runcomfy",
                label="RunComfy Trainer",
                auth_environment_variables=["RUNCOMFY_TOKEN"],
                target_profile_ids=[profile.profile_id for profile in runcomfy_profiles],
                modalities=_modalities(runcomfy_profiles),
                actions=["train_lora", "resume_training"],
                gpu_families=["ADA_80_PLUS", "HOPPER_141"],
                billing_models=["active_gpu_time"],
                documentation_urls=[
                    "https://docs.runcomfy.com/trainer-apis/async-queue-endpoints-training-jobs",
                    "https://docs.runcomfy.com/trainer-apis/about-billing",
                ],
                features=[
                    _feature("estimates", "Time and cost estimates", "adapter", "LoraSuite combines versioned recipe baselines with the selected RunComfy GPU."),
                    _feature("upload_resume", "Restartable dataset upload", "adapter", "LoraSuite persists an immutable SHA-256 checkpoint after each accepted file and skips matching files after restart."),
                    _feature("immutable_config", "Immutable training config", "adapter", "LoraSuite fingerprints the submitted YAML and reuses runs only when dataset, config, and GPU agree."),
                    _feature("progress", "Step progress", "native", "RunComfy reports current step, total steps, queue state, and job state."),
                    _feature("logs", "Training logs", "partial", "Status and provider errors are retained; a first-class streaming log contract is not exposed."),
                    _feature("samples", "Training samples", "native", "Provider result artifacts are downloaded when supplied."),
                    _feature("checkpoints", "Checkpoint artifacts", "native", "A completed run is rejected unless a checkpoint artifact is present."),
                    _feature("cancel", "Cancel", "native", "Active provider jobs can be canceled."),
                    _feature("checkpoint_resume", "Checkpoint resume", "native", "A stopped RunComfy job can resume from its provider checkpoint."),
                    _feature("artifact_checksums", "Artifact checksums", "partial", "Downloads are atomic, but the provider result contract does not currently supply an expected checksum."),
                    _feature("failure_diagnosis", "Failure diagnosis", "partial", "Provider errors and failed lifecycle stage are retained without a structured provider error taxonomy."),
                    _feature("registry", "LoraSuite model registry", "adapter", "Downloaded checkpoints can be registered, evaluated, and selected for release."),
                ],
                warnings=[
                    "RunComfy does not expose byte-offset resume; an interrupted file restarts from byte zero.",
                    "A process exit after provider acceptance but before the local atomic checkpoint may retry that one file.",
                    "Remote artifact checksum truth depends on provider metadata that is not currently present.",
                ],
            ),
            CloudProviderDescriptor(
                id="runpod",
                label="RunPod Serverless",
                auth_environment_variables=[
                    "RUNPOD_API_KEY",
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                ],
                target_profile_ids=[profile.profile_id for profile in runpod_profiles],
                modalities=_modalities(runpod_profiles),
                actions=[
                    "train_lora",
                    "run_id_lora",
                    "preflight",
                    "smoke_test",
                    "bootstrap_models",
                ],
                gpu_families=["NVIDIA H100 80GB HBM3", "NVIDIA H200"],
                billing_models=["flex", "active_worker"],
                documentation_urls=[
                    "https://docs.runpod.io/api-reference/endpoints/GET/endpoints",
                    "https://docs.runpod.io/serverless/pricing",
                ],
                features=[
                    _feature("estimates", "Time and cost estimates", "adapter", "LoraSuite applies versioned recipe baselines to the selected RunPod GPU and billing mode."),
                    _feature("infrastructure", "Infrastructure provisioning", "native", "LoraSuite can provision or adopt a network volume, template, and Serverless endpoint."),
                    _feature("upload_resume", "Restartable bundle upload", "native", "A persisted upload job skips remote objects whose sizes already match."),
                    _feature("preflight", "Endpoint preflight", "native", "The worker verifies volume, bundle, config, launcher, commands, environment, models, and GPU."),
                    _feature("immutable_config", "Immutable training config", "native", "The local bundle, endpoint preflight, worker launch, and completion envelope must agree on one SHA-256 config digest."),
                    _feature("progress", "Job progress", "native", "RunPod queue and execution states plus worker progress messages are normalized."),
                    _feature("logs", "Worker logs", "native", "The worker returns a checksummed execution log artifact."),
                    _feature("samples", "Training and inference samples", "native", "The worker indexes and checksums image, audio, and video sample artifacts."),
                    _feature("checkpoints", "Checkpoint artifacts", "native", "Training completion requires a checkpoint; ID-LoRA inference requires a sample and inference contract."),
                    _feature("cancel", "Cancel", "native", "Active Serverless jobs can be canceled."),
                    _feature("checkpoint_resume", "Checkpoint resume", "unavailable", "The current worker contract does not resume a new job from a prior training checkpoint."),
                    _feature("artifact_checksums", "Artifact checksums", "native", "Every returned artifact includes size and SHA-256 and is verified after download."),
                    _feature("failure_diagnosis", "Failure diagnosis", "partial", "Preflight and lifecycle failures are structured, while trainer-specific failures remain in the worker log."),
                    _feature("model_bootstrap", "Pinned model bootstrap", "native", "Allowlisted model assets are downloaded at pinned revisions and recorded on the network volume."),
                    _feature("registry", "LoraSuite model registry", "adapter", "Downloaded checkpoints can be registered, evaluated, and selected for release."),
                ],
                warnings=[
                    "Checkpoint resume is not implemented for a new RunPod Serverless job.",
                    "Trainer-specific step progress depends on the trainer emitting worker progress updates.",
                ],
            ),
        ]

    def list_runs(
        self,
        *,
        project_id: str | None = None,
        provider: CloudProviderName | None = None,
    ) -> list[CloudRunRecord]:
        registered_counts: dict[str, int] = {}
        for artifact in ModelRegistryService(self.vault_root).list_artifacts():
            registered_counts[artifact.training_run_id] = registered_counts.get(artifact.training_run_id, 0) + 1

        records: list[CloudRunRecord] = []
        if provider in {None, "runcomfy"}:
            image_snapshots = DatasetCompilerService(self.vault_root).list_snapshots()
            video_snapshots = VideoDatasetService(self.vault_root).list_snapshots()
            snapshots = {snapshot.id: snapshot for snapshot in [*image_snapshots, *video_snapshots]}
            for run in TrainingRunService(self.vault_root).list_runs():
                snapshot = snapshots.get(run.snapshot_id)
                record = _runcomfy_record(run, snapshot, registered_counts.get(run.id, 0))
                if project_id is None or record.project_id == project_id:
                    records.append(record)
        if provider in {None, "runpod"}:
            for run in RunPodTrainingRunService(self.vault_root).list_runs():
                if project_id is None or run.project_id == project_id:
                    records.append(_runpod_record(run, registered_counts.get(run.id, 0)))
        return sorted(records, key=lambda item: str(item.created_at or ""), reverse=True)


def _runcomfy_record(run: TrainingRun, snapshot: Any, registered_count: int) -> CloudRunRecord:
    profile_id = ""
    modality = None
    project_id = None
    if snapshot is not None:
        project_id = str(snapshot.project_id)
        target = getattr(snapshot, "training_target", None)
        profile_id = str(getattr(target, "profile_id", "") or getattr(snapshot, "target_profile_id", ""))
        modality = "video" if hasattr(snapshot, "target_profile_id") else "image"
    state = {
        "queued": "queued",
        "uploading": "preparing",
        "dataset_ready": "preparing",
        "in_queue": "queued",
        "running": "running",
        "stopped": "paused",
        "downloading": "retrieving",
        "completed": "completed",
        "failed": "failed",
        "canceled": "canceled",
    }[run.status]
    actions: list[CloudRunAction] = []
    if run.status in {"queued", "uploading", "dataset_ready", "in_queue", "running", "downloading"}:
        actions = ["refresh", "cancel"]
    elif run.status == "stopped":
        actions = ["resume", "cancel"]
    elif run.status == "completed":
        if registered_count == 0 and run.artifacts:
            actions.append("register_artifacts")
        actions.append("evaluate")
    elif run.status in {"failed", "canceled"}:
        actions = ["retry"]
    return CloudRunRecord(
        id=run.id,
        provider="runcomfy",
        provider_job_id=run.provider_job_id,
        project_id=project_id,
        snapshot_id=run.snapshot_id,
        training_target_profile_id=profile_id,
        modality=modality,
        state=state,
        provider_status=run.status,
        progress=CloudRunProgress(
            current=run.progress_current,
            total=run.progress_total,
            percent=run.progress_percent,
            message=run.progress_message,
        ),
        dataset_fingerprint=run.dataset_fingerprint,
        config_digest=run.config_digest,
        gpu=run.gpu_type,
        artifact_count=len(run.artifacts),
        local_artifact_count=sum(artifact.local_path is not None for artifact in run.artifacts),
        checksum_artifact_count=0,
        registered_artifact_count=registered_count,
        available_actions=actions,
        error=run.error,
        failure_category=_failure_category(run.error),
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _runpod_record(run: RunPodTrainingRun, registered_count: int) -> CloudRunRecord:
    state = {
        "queued": "queued",
        "in_queue": "queued",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "canceled": "canceled",
        "timed_out": "failed",
    }[run.status]
    local_count = sum(artifact.local_path is not None for artifact in run.artifacts)
    actions: list[CloudRunAction] = []
    if run.status in {"queued", "in_queue", "running"}:
        actions = ["refresh", "cancel"]
    elif run.status == "completed":
        if run.artifacts and local_count < len(run.artifacts):
            actions.append("download_artifacts")
        if run.action == "train_lora" and local_count == len(run.artifacts) and registered_count == 0:
            actions.append("register_artifacts")
        actions.append("evaluate")
    elif run.status in {"failed", "canceled", "timed_out"}:
        actions = ["retry"]
    percent = 100.0 if run.status == "completed" else 0.0
    return CloudRunRecord(
        id=run.id,
        provider="runpod",
        provider_job_id=run.provider_job_id,
        project_id=run.project_id,
        snapshot_id=run.snapshot_id,
        training_target_profile_id=run.training_target_profile_id,
        modality=run.modality,
        operation="inference" if run.action == "run_id_lora" else "train",
        state=state,
        provider_status=run.status,
        progress=CloudRunProgress(percent=percent, message=run.progress_message),
        dataset_fingerprint=run.bundle_fingerprint,
        config_digest=run.config_digest,
        artifact_count=len(run.artifacts),
        local_artifact_count=local_count,
        checksum_artifact_count=sum(bool(artifact.sha256) for artifact in run.artifacts),
        registered_artifact_count=registered_count,
        available_actions=actions,
        error=run.error,
        failure_category=_failure_category(run.error),
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _feature(feature_id: str, label: str, support: CloudFeatureSupport, detail: str) -> CloudProviderFeature:
    return CloudProviderFeature(id=feature_id, label=label, support=support, detail=detail)


def _modalities(profiles: list[Any]) -> list[Literal["image", "video", "voice", "audio_visual"]]:
    order = {"image": 0, "video": 1, "voice": 2, "audio_visual": 3}
    values = {profile.modality for profile in profiles}
    return sorted(values, key=order.__getitem__)


def _failure_category(error: str | None) -> str | None:
    if not error:
        return None
    normalized = error.lower()
    if any(token in normalized for token in ("token", "unauthorized", "forbidden", "401", "403")):
        return "authentication"
    if any(token in normalized for token in ("quota", "capacity", "gpu unavailable", "out of memory", "oom")):
        return "capacity"
    if any(token in normalized for token in ("upload", "dataset", "volume", "s3")):
        return "data_transfer"
    if any(token in normalized for token in ("config", "contract", "digest", "fingerprint", "provenance")):
        return "configuration"
    if any(token in normalized for token in ("artifact", "checkpoint", "download", "checksum")):
        return "artifact"
    if any(token in normalized for token in ("timeout", "timed out")):
        return "timeout"
    return "provider"
