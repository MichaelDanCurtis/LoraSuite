from __future__ import annotations

from typing import Any, Literal
from pathlib import Path

from pydantic import BaseModel, Field

from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.evaluation_harness import EvaluationHarnessService
from lorasuite_engine.id_lora_dataset import IdLoraDatasetService
from lorasuite_engine.id_lora_evaluation import IdLoraEvaluationService
from lorasuite_engine.image_evaluation import ImageEvaluationHarnessService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.models import DatasetReviewStatus, RequestedOutput, VoiceSegmentStatus, utc_now
from lorasuite_engine.speaker_identity import VoiceIdentityService
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.runpod_runs import RunPodTrainingRunService
from lorasuite_engine.video_dataset import VideoDatasetService
from lorasuite_engine.voice_dataset import VoiceDatasetService
from lorasuite_engine.voice_evaluation import VoiceArtifactEvaluationService


WorkflowLane = Literal["image", "video", "voice", "id_lora", "evaluate"]
WorkflowState = Literal["blocked", "ready", "working", "complete"]
WorkflowWorkspace = Literal["ingest", "curate", "identify", "train"]


class TrainingWorkflowLane(BaseModel):
    id: WorkflowLane
    label: str
    state: WorkflowState
    phase: str
    summary: str
    action_label: str
    target_mode: WorkflowLane
    target_workspace: WorkflowWorkspace
    counts: dict[str, int | float] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrainingWorkflowStatus(BaseModel):
    project_id: str
    project_name: str
    recommended_lane: WorkflowLane
    recommendation: str
    complete_count: int
    lanes: list[TrainingWorkflowLane]
    updated_at: Any = Field(default_factory=utc_now)


class TrainingWorkflowService:
    """Derives the next training action from persisted compiler evidence."""

    def __init__(self, vault_root):
        self.vault_root = vault_root

    def status(self, project_id: str) -> TrainingWorkflowStatus:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)

        image_snapshots = DatasetCompilerService(self.vault_root).list_snapshots(project_id)
        video_service = VideoDatasetService(self.vault_root)
        video_snapshots = video_service.list_snapshots(project_id)
        voice = VoiceDatasetService(self.vault_root).get(project_id)
        voice_profile = VoiceIdentityService(self.vault_root).get_profile(project_id)
        id_manifests = IdLoraDatasetService(self.vault_root).list_manifests(project_id)
        id_inference_runs = [
            run for run in RunPodTrainingRunService(self.vault_root).list_runs()
            if run.project_id == project_id and run.action == "run_id_lora"
        ]
        id_evaluations = IdLoraEvaluationService(self.vault_root).list_runs(project_id)
        benchmark_runs = [
            *EvaluationHarnessService(self.vault_root).list_runs(project_id),
            *ImageEvaluationHarnessService(self.vault_root).list_runs(project_id),
        ]
        benchmark_runs.sort(key=lambda run: run.created_at, reverse=True)
        voice_handoff = CurationService(self.vault_root).get_handoff(
            project_id,
            RequestedOutput.VOICE,
        )

        accepted_audio = sum(
            1
            for item in voice_handoff.items
            if _value(item.lane) == "audio" and _value(item.review_status) == "accepted"
        )
        accepted_images = sum(
            1 for observation in project.observations.values()
            if observation.review_status == DatasetReviewStatus.ACCEPTED
        )
        video_candidates = len(video_service.candidate_media(project_id))

        image_lane = _image_lane(accepted_images, image_snapshots[0] if image_snapshots else None)
        video_target_profile_id = (
            project.intent.training_target_profile_ids.get(RequestedOutput.VIDEO)
            or (video_snapshots[0].target_profile_id if video_snapshots else None)
            or "runcomfy_wan22_14b_t2v_character"
        )
        video_lane = _video_lane(
            video_candidates,
            video_snapshots[0] if video_snapshots else None,
            video_target_profile_id,
        )
        all_artifacts = ModelRegistryService(self.vault_root).list_artifacts()
        voice_artifacts = [
            artifact for artifact in all_artifacts
            if artifact.modality == "voice"
            and (artifact.project_id == project_id or (not artifact.project_id and artifact.snapshot_id == project_id))
        ]
        voice_evaluations = VoiceArtifactEvaluationService(self.vault_root).list_runs(project_id)
        voice_evaluation = next((run for run in voice_evaluations if run.selected_for_release), None)
        voice_evaluation = voice_evaluation or (voice_evaluations[0] if voice_evaluations else None)
        voice_lane = _voice_lane(
            accepted_audio,
            len(voice_profile.anchor_media_item_ids),
            voice,
            len(voice_artifacts),
            voice_evaluation,
        )
        id_inference_run = id_inference_runs[0] if id_inference_runs else None
        id_evaluation = next((
            run for run in id_evaluations
            if id_inference_run is not None and run.runpod_run_id == id_inference_run.id
        ), None)
        id_lane = _id_lane(
            video_snapshots[0] if video_snapshots else None,
            id_manifests[0] if id_manifests else None,
            id_inference_run,
            id_evaluation,
        )

        snapshot_ids = {item.id for item in image_snapshots + video_snapshots}
        artifacts = [
            artifact for artifact in all_artifacts
            if artifact.modality != "voice"
            and (
                artifact.project_id == project.id
                or (not artifact.project_id and artifact.snapshot_id in snapshot_ids)
            )
        ]
        artifact_ids = {artifact.id for artifact in artifacts}
        linked_runs = [run for run in benchmark_runs if run.artifact_id in artifact_ids]
        evaluation_lane = _evaluation_lane(artifacts, linked_runs[0] if linked_runs else None)
        lanes = [image_lane, video_lane, voice_lane, id_lane, evaluation_lane]
        requested_lane_ids = {
            _value(output) for output in project.intent.requested_outputs
        }
        h3_reference_only = requested_lane_ids == {"video"} and video_target_profile_id == "comfyui_minimax_h3_ref2va"
        if h3_reference_only and not artifacts:
            evaluation_lane = _lane("evaluate", "Review H3 outputs", "ready" if video_lane.state == "complete" else "blocked", "handoff", "Review generated outputs in ComfyUI against your selected references. This reference workflow does not require a trained checkpoint.", "Open H3 package", {}, target_mode="video")
            lanes[-1] = evaluation_lane
        requested_lanes = [
            lane for lane in lanes if lane.id in requested_lane_ids
        ] or [image_lane]
        recommended = next((lane for lane in requested_lanes if lane.state == "working"), None)
        recommended = recommended or next((lane for lane in requested_lanes if lane.state == "ready"), None)
        recommended = recommended or next((lane for lane in requested_lanes if lane.state == "blocked"), None)
        recommended = recommended or (video_lane if h3_reference_only else evaluation_lane)

        return TrainingWorkflowStatus(
            project_id=project.id,
            project_name=project.name,
            recommended_lane=recommended.id,
            recommendation=f"{recommended.label}: {recommended.action_label}",
            complete_count=sum(1 for lane in lanes if lane.state == "complete"),
            lanes=lanes,
        )


def _image_lane(accepted: int, snapshot) -> TrainingWorkflowLane:
    counts: dict[str, int | float] = {"accepted_sources": accepted}
    if accepted == 0:
        return _lane("image", "Image LoRA", "blocked", "identity", "No accepted identity images.", "Review identity candidates", counts, ["Accept identity-confirmed images before compiling."])
    if snapshot is None:
        return _lane("image", "Image LoRA", "ready", "compile", f"{accepted} accepted images are ready.", "Build image dataset", counts)
    counts.update({"dataset_items": snapshot.balance.total_count, "approved": snapshot.balance.approved_count, "review": snapshot.balance.review_count})
    status = _value(snapshot.status)
    if status == "exported" and snapshot.export_path:
        if not (Path(snapshot.export_path) / "manifest.json").is_file():
            return _lane("image", "Image LoRA", "ready", "export", "The exported folder is missing. Your frozen dataset and reviews are preserved.", "Re-export image dataset", counts)
        return _lane("image", "Image LoRA", "complete", "handoff", "RunComfy and RunPod dataset handoffs are available.", "Open provider handoff", counts)
    if status == "frozen":
        return _lane("image", "Image LoRA", "ready", "export", "The reviewed dataset is immutable and ready to package.", "Export image dataset", counts)
    if snapshot.balance.review_count:
        return _lane("image", "Image LoRA", "working", "review", f"{snapshot.balance.review_count} captions still need confirmation.", "Continue caption review", counts)
    if snapshot.balance.approved_count == 0:
        return _lane("image", "Image LoRA", "blocked", "review", "The draft has no approved training images.", "Approve image examples", counts, ["At least one image must be approved."])
    return _lane("image", "Image LoRA", "ready", "freeze", "Every retained image has a decision.", "Freeze image dataset", counts)


def _video_lane(candidate_count: int, snapshot, target_profile_id: str = "runcomfy_wan22_14b_t2v_character") -> TrainingWorkflowLane:
    try:
        target = get_training_target_profile(snapshot.target_profile_id if snapshot is not None else target_profile_id)
    except (KeyError, ValueError):
        target = get_training_target_profile("runcomfy_wan22_14b_t2v_character")
    inference_only = target.recipe is not None and target.recipe.workflow_kind == "inference"
    label = "MiniMax H3" if inference_only else "Video LoRA"
    counts: dict[str, int | float] = {"accepted_clips": candidate_count}
    if snapshot is None and candidate_count == 0 and not inference_only:
        return _lane("video", label, "blocked", "curate", "No curated video clips are available.", "Curate video clips", counts, ["Commit stable video ranges in Curate first."])
    if snapshot is None:
        summary = f"{candidate_count} reviewed clips can be paired with optional still and voice references." if inference_only else f"{candidate_count} clips are ready for temporal compilation."
        action = "Choose H3 references" if inference_only else "Build video dataset"
        return _lane("video", label, "ready", "compile", summary, action, counts)
    counts.update({"dataset_items": snapshot.balance.total_count, "approved": snapshot.balance.approved_count, "review": snapshot.balance.review_count})
    if snapshot.status == "exported" and snapshot.export_path:
        if not (Path(snapshot.export_path) / "manifest.json").is_file():
            return _lane("video", label, "ready", "export", "The exported folder is missing. Your frozen references and reviews are preserved.", "Re-export H3 package" if inference_only else "Re-export video dataset", counts)
        if inference_only:
            return _lane("video", label, "complete", "handoff", "The reviewed H3 reference package is exported. ComfyUI must have compatible H3 models before generation.", "Open H3 package", counts)
        return _lane("video", label, "complete", "handoff", "WAN training handoffs are available for RunComfy and RunPod.", "Open provider handoff", counts)
    if snapshot.status == "frozen":
        summary = "The selected image, video, and audio references are frozen." if inference_only else "Temporal clips and source-safe splits are frozen."
        action = "Export H3 package" if inference_only else "Export video dataset"
        return _lane("video", label, "ready", "export", summary, action, counts)
    if snapshot.balance.review_count:
        return _lane("video", label, "working", "review", f"{snapshot.balance.review_count} clips need caption or keep decisions.", "Continue video review", counts)
    if snapshot.balance.approved_count == 0:
        return _lane("video", label, "blocked", "review", "The video draft has no approved clips.", "Approve video clips", counts, ["At least one temporal clip must be approved."])
    return _lane("video", label, "ready", "freeze", "Every retained clip has a decision.", "Freeze video dataset", counts)


def _voice_lane(accepted_audio: int, anchor_count: int, compilation, artifact_count: int = 0, evaluation=None) -> TrainingWorkflowLane:
    segments = list(compilation.segments.values())
    review = sum(1 for item in segments if item.status == VoiceSegmentStatus.NEEDS_REVIEW)
    approved = sum(1 for item in segments if item.status == VoiceSegmentStatus.APPROVED)
    quality_gated = sum(1 for item in segments if item.quality is not None)
    counts: dict[str, int | float] = {
        "accepted_sources": accepted_audio,
        "voice_anchors": anchor_count,
        "segments": len(segments),
        "quality_gated": quality_gated,
        "approved": approved,
        "review": review,
        "registered_artifacts": artifact_count,
    }
    if anchor_count == 0:
        return _lane("voice", "Voice Dataset", "blocked", "identity", "No trusted speaker anchors are selected.", "Select voice anchors", counts, ["Speaker identity must be anchored before segmentation."])
    if not segments and accepted_audio == 0:
        return _lane("voice", "Voice Dataset", "blocked", "curate", "No approved speech sources are available.", "Curate speech sources", counts, ["Approve original speech audio before compiling."])
    if not segments:
        return _lane("voice", "Voice Dataset", "ready", "compile", f"{accepted_audio} audio sources can be segmented and transcribed.", "Build voice dataset", counts)
    if compilation.export_path:
        if compilation.export_target == "av_lora":
            return _lane("voice", "Voice Dataset", "complete", "handoff", "AV reference audio is packaged for ID-LoRA pairing.", "Open voice handoff", counts)
        compliance = compilation.balance.recipe_compliance
        if compliance is None or compliance.status != "ready":
            return _lane(
                "voice",
                "Voice Dataset",
                "working",
                "review",
                "The exported Fish Speech package still has unresolved recipe checks.",
                "Review voice dataset",
                counts,
                warnings=list(compilation.balance.warnings),
            )
        if artifact_count == 0:
            return _lane("voice", "Voice LoRA", "ready", "train", "The Fish Speech dataset is packaged; no trained checkpoint has returned yet.", "Launch voice training", counts)
        if evaluation is None:
            return _lane("voice", "Voice LoRA", "ready", "evaluate", "A trained voice checkpoint is registered and needs rendered-phrase screening.", "Evaluate voice checkpoint", counts)
        counts.update({
            "evaluation_passed": evaluation.summary.passed_count,
            "evaluation_failed": evaluation.summary.failed_count,
            "evaluation_blocked": evaluation.summary.blocked_count,
        })
        if evaluation.status in {"queued", "running"}:
            return _lane("voice", "Voice LoRA", "working", "evaluate", "Speaker, transcript, and signal checks are running.", "Monitor voice evaluation", counts)
        if evaluation.selected_for_release:
            return _lane("voice", "Voice LoRA", "complete", "selected", f"{evaluation.checkpoint_name} is the selected release checkpoint.", "Review selected voice", counts)
        if evaluation.status == "complete" and evaluation.summary.screening_ready:
            return _lane("voice", "Voice LoRA", "ready", "select", "The checkpoint passed screening and awaits release confirmation.", "Select voice checkpoint", counts)
        if evaluation.status == "complete":
            return _lane("voice", "Voice LoRA", "working", "review", "Voice screening found failed or blocked evidence.", "Review voice failures", counts, warnings=list(evaluation.summary.warnings))
        return _lane("voice", "Voice LoRA", "working", "evaluate", "The voice evaluation did not complete.", "Retry voice evaluation", counts, warnings=[evaluation.error] if evaluation.error else [])
    if quality_gated < len(segments):
        return _lane("voice", "Voice Dataset", "working", "quality", f"{len(segments) - quality_gated} segments still need the audio quality gate.", "Run audio quality gate", counts)
    if review:
        return _lane("voice", "Voice Dataset", "working", "review", f"{review} speaker-verified segments need a final decision.", "Continue voice review", counts)
    if approved == 0:
        return _lane("voice", "Voice Dataset", "blocked", "review", "No voice segments were approved.", "Review rejected segments", counts, ["Approve clean, single-speaker segments before export."])
    compliance = compilation.balance.recipe_compliance
    return _lane(
        "voice",
        "Voice Dataset",
        "ready" if compliance is not None and compliance.status == "ready" else "working",
        "export" if compliance is not None and compliance.status == "ready" else "review",
        (
            f"{approved} approved segments pass the Fish Speech recipe and are ready to package."
            if compliance is not None and compliance.status == "ready"
            else f"{approved} approved segments still need recipe review before training."
        ),
        "Export voice dataset" if compliance is not None and compliance.status == "ready" else "Review voice dataset",
        counts,
        warnings=list(compilation.balance.warnings),
    )


def _id_lane(video_snapshot, manifest, inference_run=None, evaluation=None) -> TrainingWorkflowLane:
    counts: dict[str, int | float] = {}
    if video_snapshot is None or video_snapshot.status not in {"frozen", "exported"} or not video_snapshot.fingerprint:
        return _lane("id_lora", "ID-LoRA", "blocked", "video", "A frozen video identity dataset is required.", "Finish video dataset", counts, ["Freeze video examples before aligning audio-visual identity."], target_mode="video")
    counts["approved_video"] = video_snapshot.balance.approved_count
    if manifest is None:
        return _lane("id_lora", "ID-LoRA", "ready", "compile", "Video identity is frozen; synchronized voice can now be aligned.", "Compile ID-LoRA contract", counts)
    counts.update({
        "visual_examples": manifest.balance.visual_example_count,
        "synchronized_pairs": manifest.balance.synchronized_pair_count,
        "voice_references": manifest.balance.voice_reference_count,
    })
    if manifest.status == "blocked":
        return _lane("id_lora", "ID-LoRA", "working", "alignment", "The multimodal contract has unresolved pairing gaps.", "Review AV alignment", counts, warnings=list(manifest.balance.warnings))
    if manifest.export_path:
        if inference_run is None:
            return _lane("id_lora", "ID-LoRA", "ready", "inference", "Identity and voice references are packaged for the official zero-shot adapter.", "Launch ID-LoRA inference", counts, warnings=["The generic adapter is loaded at inference; it is not retrained per person."])
        counts["inference_outputs"] = sum(artifact.kind == "sample" for artifact in inference_run.artifacts)
        if inference_run.status in {"queued", "in_queue", "running"}:
            return _lane("id_lora", "ID-LoRA", "working", "inference", "Zero-shot LTX-2.3 generation is running on RunPod.", "Monitor ID-LoRA inference", counts)
        if inference_run.status != "completed":
            return _lane("id_lora", "ID-LoRA", "working", "inference", "The latest zero-shot generation did not complete.", "Retry ID-LoRA inference", counts, warnings=[inference_run.error] if inference_run.error else [])
        if any(not artifact.local_path for artifact in inference_run.artifacts):
            return _lane("id_lora", "ID-LoRA", "working", "download", "Zero-shot outputs are ready on RunPod and must be downloaded.", "Download ID-LoRA outputs", counts)
        if evaluation is None:
            return _lane("id_lora", "ID-LoRA", "ready", "evaluate", "Downloaded zero-shot outputs are ready for face, voice, transcript, and sync checks.", "Evaluate ID-LoRA outputs", counts)
        counts.update({
            "evaluation_passed": evaluation.summary.passed_count,
            "evaluation_failed": evaluation.summary.failed_count,
            "evaluation_blocked": evaluation.summary.blocked_count,
        })
        if evaluation.status in {"queued", "running"}:
            return _lane("id_lora", "ID-LoRA", "working", "evaluate", "ID-LoRA audio-visual acceptance is running.", "Monitor ID-LoRA acceptance", counts)
        if evaluation.status == "complete" and evaluation.summary.release_ready:
            return _lane("id_lora", "ID-LoRA", "complete", "certified", "Zero-shot appearance, voice, transcript, motion, and certified sync gates passed.", "Review certified ID-LoRA", counts)
        if evaluation.status == "complete" and evaluation.summary.screening_ready:
            return _lane("id_lora", "ID-LoRA", "working", "certification", "Local AV screening passed; certified SyncNet evidence is still required.", "Complete sync certification", counts, warnings=list(evaluation.summary.warnings))
        if evaluation.status == "complete":
            return _lane("id_lora", "ID-LoRA", "working", "review", "ID-LoRA acceptance found failed or blocked evidence.", "Review ID-LoRA failures", counts, warnings=list(evaluation.summary.warnings))
        return _lane("id_lora", "ID-LoRA", "working", "evaluate", "ID-LoRA acceptance failed to complete.", "Retry ID-LoRA acceptance", counts, warnings=[evaluation.error] if evaluation.error else [])
    return _lane("id_lora", "ID-LoRA", "ready", "export", "The synchronized identity references passed their data gates.", "Export ID-LoRA package", counts, warnings=["The package drives a pre-trained ID-LoRA adapter and its evaluation harness."])


def _evaluation_lane(artifacts, run) -> TrainingWorkflowLane:
    valid_artifacts = [artifact for artifact in artifacts if _value(artifact.evaluation.status) != "failed"]
    certified = sum(1 for artifact in valid_artifacts if artifact.acceptance.release_ready)
    selected = sum(1 for artifact in valid_artifacts if artifact.selected_for_release and artifact.acceptance.release_ready)
    counts: dict[str, int | float] = {
        "registered_artifacts": len(artifacts),
        "validated_artifacts": len(valid_artifacts),
        "certified_artifacts": certified,
        "selected_releases": selected,
    }
    if not artifacts:
        return _lane("evaluate", "Evaluate", "blocked", "artifact", "No trained model artifact is registered for this project.", "Train or register a model", counts, ["Evaluation starts after a cloud training artifact returns."])
    if not valid_artifacts:
        return _lane("evaluate", "Evaluate", "blocked", "artifact", "Every registered artifact failed checkpoint or provenance validation.", "Review model artifacts", counts, ["Resolve artifact integrity failures before acceptance testing."])
    if selected:
        return _lane("evaluate", "Evaluate", "complete", "release", "A certified checkpoint is selected as this project's release candidate.", "Review selected release", counts)
    if certified:
        return _lane("evaluate", "Evaluate", "ready", "select", f"{certified} certified checkpoint(s) are ready for release selection.", "Select release candidate", counts)
    if run is None:
        return _lane("evaluate", "Evaluate", "ready", "prepare", f"{len(valid_artifacts)} validated artifact(s) need matched baseline and LoRA tests.", "Prepare AV benchmark", counts)
    counts.update({"passed": run.summary.passed_count, "failed": run.summary.failed_count, "blocked": run.summary.blocked_count})
    if run.status in {"queued", "running"}:
        return _lane("evaluate", "Evaluate", "working", "running", "The matched audio-visual benchmark is running.", "Monitor benchmark", counts)
    if run.status == "complete" and run.summary.release_ready:
        return _lane("evaluate", "Evaluate", "ready", "select", "The artifact passed certified identity, motion, voice, and sync gates.", "Select release candidate", counts)
    if run.status == "complete":
        return _lane("evaluate", "Evaluate", "working", "review", "Screening finished, but release gates did not all pass.", "Review benchmark failures", counts, warnings=list(run.summary.warnings))
    return _lane("evaluate", "Evaluate", "working", "failed", "The last benchmark failed to complete.", "Retry AV benchmark", counts, warnings=[run.error] if run.error else [])


def _lane(
    lane_id: WorkflowLane,
    label: str,
    state: WorkflowState,
    phase: str,
    summary: str,
    action_label: str,
    counts: dict[str, int | float],
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    target_mode: WorkflowLane | None = None,
) -> TrainingWorkflowLane:
    return TrainingWorkflowLane(
        id=lane_id,
        label=label,
        state=state,
        phase=phase,
        summary=summary,
        action_label=action_label,
        target_mode=target_mode or lane_id,
        target_workspace=_workspace_for_phase(phase),
        counts=counts,
        blockers=[item for item in (blockers or []) if item],
        warnings=[item for item in (warnings or []) if item],
    )


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _workspace_for_phase(phase: str) -> WorkflowWorkspace:
    if phase == "curate":
        return "curate"
    if phase == "identity":
        return "identify"
    return "train"
