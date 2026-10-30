from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.id_lora_dataset import IdLoraDatasetService
from lorasuite_engine.id_lora_evaluation import IdLoraEvaluationService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.provider_smoke import ProviderSmokeRun, ProviderSmokeService
from lorasuite_engine.runpod_bundle import RunPodBundle, RunPodBundleService
from lorasuite_engine.runpod_bootstrap import BOOTSTRAP_PROFILE_IDS, RunPodModelBootstrapService
from lorasuite_engine.runpod_runs import RunPodPreflightReport, RunPodTrainingRun, RunPodTrainingRunService
from lorasuite_engine.runpod_uploads import RunPodBundleUploadService
from lorasuite_engine.training_runs import TrainingRun, TrainingRunService
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.video_dataset import VideoDatasetService
from lorasuite_engine.voice_dataset import VoiceDatasetService


ProviderLane = Literal["image", "video", "voice", "id_lora"]
ProviderName = Literal["runcomfy", "runpod"]
ProviderState = Literal["blocked", "dataset_ready", "bundle_ready", "endpoint_ready", "running", "outputs_ready", "complete"]


class ProviderReadinessItem(BaseModel):
    lane: ProviderLane
    provider: ProviderName
    profile_id: str
    state: ProviderState
    summary: str
    action_label: str
    source_export_path: Path | None = None
    snapshot_id: str | None = None
    bundle_id: str | None = None
    run_id: str | None = None
    endpoint_id: str | None = None
    release_artifact_id: str | None = None
    release_selected: bool = False
    smoke_run_id: str | None = None
    smoke_ready: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProviderReadinessMatrix(BaseModel):
    project_id: str
    ready_count: int
    total_count: int
    items: list[ProviderReadinessItem]


class ProviderReadinessService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def status(self, project_id: str) -> ProviderReadinessMatrix:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        image_snapshots = DatasetCompilerService(self.vault_root).list_snapshots(project_id)
        video_snapshots = VideoDatasetService(self.vault_root).list_snapshots(project_id)
        voice = VoiceDatasetService(self.vault_root).get(project_id)
        manifests = IdLoraDatasetService(self.vault_root).list_manifests(project_id)
        id_evaluations = IdLoraEvaluationService(self.vault_root).list_runs(project_id)
        bundles = RunPodBundleService(self.vault_root).list_bundles(project_id=project_id)
        runcomfy_runs = TrainingRunService(self.vault_root).list_runs()
        runpod_runs = [run for run in RunPodTrainingRunService(self.vault_root).list_runs() if run.project_id == project_id]
        preflights = RunPodTrainingRunService(self.vault_root).list_preflight_reports()
        uploads = RunPodBundleUploadService(self.vault_root).list_jobs()
        bootstrap_runs = RunPodModelBootstrapService(self.vault_root).list_runs()
        artifacts = ModelRegistryService(self.vault_root).list_artifacts()
        smoke_runs = ProviderSmokeService(self.vault_root).list_runs(project_id=project_id)
        artifact_run_ids = {artifact.training_run_id for artifact in artifacts}
        selected_by_run = {
            artifact.training_run_id: artifact.id
            for artifact in artifacts
            if artifact.project_id == project_id and artifact.selected_for_release and artifact.acceptance.release_ready
        }

        image = image_snapshots[0] if image_snapshots else None
        video = video_snapshots[0] if video_snapshots else None
        manifest = manifests[0] if manifests else None
        image_profile = image.training_target.profile_id if image is not None else "runcomfy_flux1_dev_character"
        video_profile = video.target_profile_id if video is not None else "runcomfy_wan22_14b_t2v_character"
        items = [
            _runcomfy_item("image", image_profile, image, runcomfy_runs, artifact_run_ids, selected_by_run),
            _runpod_item("image", image_profile, image, bundles, runpod_runs, preflights, uploads, artifact_run_ids, selected_by_run, bootstrap_runs),
            _runcomfy_item("video", video_profile, video, runcomfy_runs, artifact_run_ids, selected_by_run),
            _runpod_item("video", video_profile, video, bundles, runpod_runs, preflights, uploads, artifact_run_ids, selected_by_run, bootstrap_runs),
            _runpod_source_item(
                "voice",
                "runpod_fish_speech_s2_voice_lora",
                voice.export_path,
                project_id,
                bundles,
                runpod_runs,
                preflights, uploads,
                artifact_run_ids,
                bootstrap_runs=bootstrap_runs,
                source_ready=(
                    voice.export_target is not None
                    and str(voice.export_target) in {"voice_cloning", "both"}
                    and voice.balance.recipe_compliance is not None
                    and voice.balance.recipe_compliance.status == "ready"
                ),
                source_blocker=(
                    "Resolve the Fish Speech recipe checks and export a ready voice-cloning dataset."
                    if voice.export_path
                    else "Export a ready voice-cloning dataset before creating the RunPod bundle."
                ),
            ),
            _id_lora_item(manifest, bundles, runpod_runs, preflights, uploads, id_evaluations, bootstrap_runs),
        ]
        items = [_apply_smoke_evidence(item, smoke_runs) for item in items]
        return ProviderReadinessMatrix(
            project_id=project_id,
            ready_count=sum(item.state == "complete" for item in items),
            total_count=len(items),
            items=items,
        )


def _apply_smoke_evidence(item: ProviderReadinessItem, runs: list[ProviderSmokeRun]) -> ProviderReadinessItem:
    candidates = [
        run for run in runs
        if run.provider == item.provider
        and run.training_target_profile_id == item.profile_id
        and (item.bundle_id is None or run.bundle_id == item.bundle_id)
        and (item.source_export_path is None or run.source_export_path == item.source_export_path)
    ]
    run = candidates[0] if candidates else None
    if run is None:
        needs_smoke = (
            item.provider == "runcomfy" and item.state == "dataset_ready"
        ) or (
            item.provider == "runpod" and item.state == "bundle_ready" and item.bundle_id is not None
        )
        if needs_smoke:
            label = "Smoke test RunPod bundle" if item.provider == "runpod" else "Smoke test RunComfy package"
            return item.model_copy(update={"action_label": label, "smoke_ready": False})
        return item
    update: dict[str, object] = {"smoke_run_id": run.id, "smoke_ready": run.ready}
    if run.ready and item.state in {"dataset_ready", "bundle_ready"}:
        update["summary"] = f"{item.summary} Provider contract smoke passed."
    elif not run.ready and item.state in {"dataset_ready", "bundle_ready"}:
        failures = [check.detail for check in run.checks if not check.passed]
        update.update({
            "state": "blocked",
            "summary": "Provider contract smoke failed.",
            "action_label": "Review and rerun provider smoke",
            "blockers": failures or [run.error or "Provider smoke did not complete."],
        })
    return item.model_copy(update=update)


def _local_reference_item(lane, provider, profile_id):
    try:
        profile = get_training_target_profile(profile_id)
    except (KeyError, ValueError):
        return None
    if profile.provider == "comfyui":
        return _item(lane, provider, profile_id, "blocked", "This recipe packages references for ComfyUI; it does not train a LoRA on this provider.", "Open reference package", blockers=["Use the reference package in ComfyUI with compatible models."])
    return None


def _runcomfy_item(lane, profile_id, snapshot, runs: list[TrainingRun], artifact_run_ids: set[str], selected_by_run=None) -> ProviderReadinessItem:
    if reference := _local_reference_item(lane, "runcomfy", profile_id):
        return reference
    if snapshot is None or not snapshot.export_path:
        return _item(lane, "runcomfy", profile_id, "blocked", "No exported provider dataset.", f"Export {lane} dataset", blockers=["Freeze and export the reviewed dataset first."])
    run = next((candidate for candidate in runs if candidate.snapshot_id == snapshot.id), None)
    base = dict(source_export_path=snapshot.export_path, snapshot_id=snapshot.id)
    if run is None:
        if not (Path(snapshot.export_path) / "manifest.json").is_file():
            return _item(lane, "runcomfy", profile_id, "blocked", "The exported dataset is missing from this computer.", f"Re-export {lane} dataset", blockers=["Re-export the frozen snapshot to restore its package without changing reviews."], **base)
        return _item(lane, "runcomfy", profile_id, "dataset_ready", "RunComfy dataset and AI Toolkit config are ready.", "Launch RunComfy training", **base)
    base["run_id"] = run.id
    if run.status in {"queued", "uploading", "dataset_ready", "in_queue", "running", "downloading"}:
        return _item(lane, "runcomfy", profile_id, "running", run.progress_message, "Monitor RunComfy job", **base)
    if run.status == "stopped":
        return _item(lane, "runcomfy", profile_id, "running", run.progress_message, "Resume RunComfy training", **base)
    if run.status == "completed" and run.id in artifact_run_ids:
        if selected_id := (selected_by_run or {}).get(run.id):
            return _item(lane, "runcomfy", profile_id, "complete", "Checkpoint is the selected release candidate.", "Review selected release", release_artifact_id=selected_id, release_selected=True, **base)
        return _item(lane, "runcomfy", profile_id, "complete", "Checkpoint downloaded and registered for evaluation.", "Open evaluation", **base)
    if run.status == "completed":
        return _item(lane, "runcomfy", profile_id, "outputs_ready", "Training artifacts are downloaded but not registered.", "Register RunComfy artifacts", **base)
    return _item(lane, "runcomfy", profile_id, "blocked", run.error or "The latest RunComfy run did not complete.", "Retry RunComfy training", blockers=[run.error] if run.error else [], **base)


def _runpod_item(lane, profile_id, snapshot, bundles, runs, preflights, uploads, artifact_run_ids, selected_by_run=None, bootstrap_runs=None):
    export_path = snapshot.export_path if snapshot is not None else None
    snapshot_id = snapshot.id if snapshot is not None else None
    return _runpod_source_item(
        lane, profile_id, export_path, getattr(snapshot, "project_id", None), bundles, runs, preflights, uploads,
        artifact_run_ids, selected_by_run=selected_by_run, bootstrap_runs=bootstrap_runs, source_ready=bool(export_path), source_blocker=f"Export the {lane} dataset before creating the RunPod bundle.", snapshot_id=snapshot_id,
    )


def _runpod_source_item(
    lane, profile_id, export_path, project_id, bundles, runs, preflights, uploads, artifact_run_ids,
    *, source_ready: bool, source_blocker: str, snapshot_id: str | None = None, selected_by_run=None, bootstrap_runs=None,
):
    if reference := _local_reference_item(lane, "runpod", profile_id):
        return reference
    if not source_ready or not export_path:
        return _item(lane, "runpod", profile_id, "blocked", "No exported provider dataset.", f"Export {lane.replace('_', ' ')} dataset", blockers=[source_blocker])
    source = Path(export_path).resolve(strict=False)
    bundle = next((candidate for candidate in bundles if candidate.source_export_path == source and candidate.training_target_profile_id == profile_id), None)
    base = dict(source_export_path=source, snapshot_id=snapshot_id)
    if bundle is None:
        if not (source / "manifest.json").is_file():
            return _item(lane, "runpod", profile_id, "blocked", "The exported dataset is missing from this computer.", f"Re-export {lane.replace('_', ' ')} dataset", blockers=["Restore the exported package before creating a RunPod bundle."], **base)
        return _item(lane, "runpod", profile_id, "dataset_ready", "Dataset is ready for RunPod packaging.", "Create RunPod bundle", **base)
    return _bundle_state(lane, profile_id, bundle, runs, preflights, artifact_run_ids, uploads=uploads, selected_by_run=selected_by_run, bootstrap_runs=bootstrap_runs, **base)


def _bundle_state(lane, profile_id, bundle: RunPodBundle, runs, preflights, artifact_run_ids, uploads=None, selected_by_run=None, bootstrap_runs=None, **base):
    base.update(bundle_id=bundle.id)
    if not bundle.available:
        return _item(lane, "runpod", profile_id, "blocked", "The registered bundle folder is missing.", "Recreate RunPod bundle", blockers=[str(bundle.output_path)], **base)
    if not bundle.ready:
        return _item(lane, "runpod", profile_id, "blocked", "The RunPod bundle has unresolved trainer requirements.", "Review bundle warnings", blockers=list(bundle.warnings), **base)
    upload = next((candidate for candidate in (uploads or []) if candidate.bundle_path == bundle.output_path), None)
    if upload is None:
        return _item(lane, "runpod", profile_id, "bundle_ready", "Bundle is ready to upload to the RunPod network volume.", "Upload RunPod bundle", **base)
    if upload.status in {"queued", "running"}:
        return _item(lane, "runpod", profile_id, "running", f"Uploading {upload.files_uploaded} of {upload.files_total} bundle files.", "Monitor bundle upload", **base)
    if upload.status == "failed":
        return _item(lane, "runpod", profile_id, "blocked", upload.error or "RunPod bundle upload failed.", "Resume bundle upload", blockers=[upload.error] if upload.error else [], **base)
    run = next((candidate for candidate in runs if candidate.bundle_path == bundle.output_path), None)
    report = next((candidate for candidate in preflights if candidate.bundle_path == bundle.output_path and (run is None or candidate.endpoint_id == run.endpoint_id)), None)
    if report is None:
        bootstrap = next((candidate for candidate in (bootstrap_runs or []) if candidate.training_target_profile_id == profile_id), None)
        if bootstrap is not None and bootstrap.status in {"queued", "in_queue", "running"}:
            return _item(lane, "runpod", profile_id, "running", bootstrap.progress_message, "Monitor model installation", endpoint_id=bootstrap.endpoint_id, **base)
        if bootstrap is not None and bootstrap.status in {"failed", "timed_out", "canceled"}:
            error = bootstrap.error or bootstrap.progress_message
            return _item(lane, "runpod", profile_id, "blocked", error, "Retry model installation", endpoint_id=bootstrap.endpoint_id, blockers=[error], **base)
        if bootstrap is not None and bootstrap.status == "completed":
            return _item(lane, "runpod", profile_id, "bundle_ready", "Bundle uploaded and required models installed.", "Verify RunPod endpoint", endpoint_id=bootstrap.endpoint_id, **base)
        if profile_id in BOOTSTRAP_PROFILE_IDS:
            return _item(lane, "runpod", profile_id, "bundle_ready", "Bundle uploaded; install required models or verify a preinstalled endpoint.", "Install or verify models", **base)
        return _item(lane, "runpod", profile_id, "bundle_ready", "Bundle and provider configuration are ready.", "Verify RunPod endpoint", **base)
    base["endpoint_id"] = report.endpoint_id
    if not report.ready:
        return _item(lane, "runpod", profile_id, "blocked", "RunPod endpoint preflight failed.", "Fix endpoint requirements", blockers=[check.detail for check in report.checks if not check.passed], **base)
    if run is None:
        return _item(lane, "runpod", profile_id, "endpoint_ready", "Bundle and RunPod endpoint passed preflight.", "Start RunPod", **base)
    base["run_id"] = run.id
    if run.status in {"queued", "in_queue", "running"}:
        return _item(lane, "runpod", profile_id, "running", run.progress_message, "Monitor RunPod job", **base)
    if run.status == "completed" and run.id in artifact_run_ids:
        if selected_id := (selected_by_run or {}).get(run.id):
            return _item(lane, "runpod", profile_id, "complete", "Checkpoint is the selected release candidate.", "Review selected release", release_artifact_id=selected_id, release_selected=True, **base)
        return _item(lane, "runpod", profile_id, "complete", "Checkpoint downloaded and registered for evaluation.", "Open evaluation", **base)
    if run.status == "completed" and run.artifacts and all(artifact.local_path for artifact in run.artifacts):
        return _item(lane, "runpod", profile_id, "outputs_ready", "RunPod outputs are downloaded and ready to register.", "Register RunPod artifacts", **base)
    if run.status == "completed":
        return _item(lane, "runpod", profile_id, "outputs_ready", "RunPod outputs are ready to download.", "Download RunPod outputs", **base)
    return _item(lane, "runpod", profile_id, "blocked", run.error or "The latest RunPod run did not complete.", "Retry RunPod job", blockers=[run.error] if run.error else [], **base)


def _id_lora_item(manifest, bundles, runs, preflights, uploads, evaluations, bootstrap_runs=None):
    profile_id = "runpod_id_lora_ltx23_inference"
    if manifest is None or not manifest.export_path:
        return _item("id_lora", "runpod", profile_id, "blocked", "No exported ID-LoRA reference package.", "Export ID-LoRA package", blockers=["Compile and export synchronized identity references first."])
    source = Path(manifest.export_path).resolve(strict=False)
    bundle = next((candidate for candidate in bundles if candidate.source_export_path == source and candidate.training_target_profile_id == profile_id), None)
    if bundle is None:
        if not (source / "manifest.json").is_file():
            return _item("id_lora", "runpod", profile_id, "blocked", "The exported reference package is missing from this computer.", "Re-export ID-LoRA package", blockers=["Restore the approved reference package before creating a RunPod bundle."], source_export_path=source)
        return _item("id_lora", "runpod", profile_id, "dataset_ready", "Zero-shot reference package is ready for RunPod.", "Create ID-LoRA RunPod bundle", source_export_path=source)
    run = next((candidate for candidate in runs if candidate.bundle_path == bundle.output_path and candidate.action == "run_id_lora"), None)
    base = _bundle_state("id_lora", profile_id, bundle, runs, preflights, set(), uploads=uploads, bootstrap_runs=bootstrap_runs, source_export_path=source)
    if run is None or run.status != "completed" or any(not artifact.local_path for artifact in run.artifacts):
        return base
    evaluation = next((item for item in evaluations if item.runpod_run_id == run.id), None)
    if evaluation is None:
        return base.model_copy(update={"summary": "Downloaded zero-shot outputs need AV acceptance.", "action_label": "Evaluate ID-LoRA outputs"})
    if evaluation.status in {"queued", "running"}:
        return base.model_copy(update={"state": "running", "summary": "ID-LoRA AV acceptance is running.", "action_label": "Monitor ID-LoRA acceptance"})
    if evaluation.status == "complete" and evaluation.summary.release_ready:
        return base.model_copy(update={"state": "complete", "summary": "Zero-shot identity, voice, transcript, motion, and sync are certified.", "action_label": "Review certified ID-LoRA"})
    if evaluation.status == "complete":
        return base.model_copy(update={"state": "blocked", "summary": "ID-LoRA outputs did not pass every release gate.", "action_label": "Review ID-LoRA failures", "blockers": list(evaluation.summary.warnings)})
    return base.model_copy(update={"state": "blocked", "summary": evaluation.error or "ID-LoRA acceptance failed.", "action_label": "Retry ID-LoRA acceptance"})


def _item(lane, provider, profile_id, state, summary, action_label, **values):
    return ProviderReadinessItem(lane=lane, provider=provider, profile_id=profile_id, state=state, summary=summary, action_label=action_label, **values)
