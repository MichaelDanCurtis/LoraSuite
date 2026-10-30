import os
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.library_bridge import library_router, EXTENSION
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_recovery import RecoveredDatasetService
from lorasuite_engine.diagnostics import DiagnosticBundleService
from lorasuite_engine.caption_jobs import CaptionGenerationService
from lorasuite_engine.audio_cleaning import AudioCleaningService
from lorasuite_engine.benchmark_generation import (
    BenchmarkGenerationService,
    resolve_runcomfy_model_token,
)
from lorasuite_engine.curation import CurationService
from lorasuite_engine.exports import create_voice_dataset_export
from lorasuite_engine.instagram_browser import (
    InstagramBrowserScanError,
    scan_instagram_url_with_browser_cookies,
)
from lorasuite_engine.ingress import IngressService
from lorasuite_engine.ingress_analysis import IngressCandidateAnalyzer
from lorasuite_engine.id_lora_dataset import IdLoraDatasetService
from lorasuite_engine.id_lora_evaluation import IdLoraEvaluationService
from lorasuite_engine.media_reset import MediaResetService
from lorasuite_engine.native_dialog import pick_native_directory
from lorasuite_engine.model_metadata import LoraModelCardOverrides
from lorasuite_engine.evaluation_harness import EvaluationHarnessService, default_benchmark_suite
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.image_evaluation import ImageEvaluationHarnessService, default_image_benchmark_suite
from lorasuite_engine.improvement_loop import (
    ArtifactComparisonRequest,
    ImprovementDecisionRequest,
    ImprovementLoopService,
)
from lorasuite_engine.local_origins import DESKTOP_ORIGINS, LOCAL_UI_PATTERN, is_local_ui_origin
from lorasuite_engine.models import (
    AudioCleaningBatchOptions,
    AudioCleaningRecipe,
    CropKind,
    CropRecipeStatus,
    CurationReviewStatus,
    DatasetItemStatus,
    DatasetReviewStatus,
    DatasetView,
    MediaStatus,
    MediaType,
    NormalizedRect,
    RequestedOutput,
    SpeakerConfirmation,
    SourceKind,
    TrainingIntent,
    VisionProviderAuthMode,
    VisionProviderDialect,
    VideoBreakdownCommitRequest,
    VideoBreakdownOptions,
    VoiceExportTarget,
    VoiceSegmentStatus,
)
from lorasuite_engine.processing import ProcessingService
from lorasuite_engine.cloud_providers import CloudProviderService
from lorasuite_engine.comfyui_handoff import (
    ComfyEvaluationReportRequest,
    ComfyEvaluationReportService,
    inspect_comfy_runtime,
)
from lorasuite_engine.provider_readiness import ProviderReadinessService
from lorasuite_engine.partner_qualification import PartnerQualificationService
from lorasuite_engine.provider_smoke import ProviderSmokeService
from lorasuite_engine.runpod_bundle import RunPodBundleService
from lorasuite_engine.runpod_bootstrap import RunPodModelBootstrapService
from lorasuite_engine.runpod_infrastructure import (
    RunPodInfrastructureRequest,
    RunPodInfrastructureService,
    resolve_runpod_infrastructure_token,
)
from lorasuite_engine.runpod_runs import RunPodTrainingRunService, resolve_runpod_token
from lorasuite_engine.runpod_uploads import RunPodBundleUploadService
from lorasuite_engine.social_helper import scan_instagram_helper_payload
from lorasuite_engine.social_acquisition import (
    SocialAcquisitionRequest,
    SocialAcquisitionService,
)
from lorasuite_engine.speaker_identity import (
    SpeakerIdentityModelService,
    VoiceIdentityService,
)
from lorasuite_engine.state_migrations import StateMigrationService
from lorasuite_engine.syncnet_runtime import syncnet_capability
from lorasuite_engine.training_runs import TrainingRunService, resolve_runcomfy_token
from lorasuite_engine.training_estimates import (
    TrainingEstimateRequest,
    TrainingEstimateService,
)
from lorasuite_engine.training_workflow import TrainingWorkflowService
from lorasuite_engine.model_registry import ModelRegistryService, discover_comfy_installations
from lorasuite_engine.video_dataset import VideoDatasetService
from lorasuite_engine.training_targets import (
    get_training_target_profile,
    model_intent_recipes,
    training_target_profiles,
)
from lorasuite_engine.voice_dataset import VoiceDatasetService
from lorasuite_engine.voice_evaluation import VoiceArtifactEvaluationService
from lorasuite_engine.vault import VaultService, VaultSnapshotConflict
from lorasuite_engine.vision_caption import (
    VisionProviderConfig,
    auth_mode_for_provider,
    provider_presets,
    resolve_api_key,
    start_grok_oauth_login,
)
from lorasuite_engine.x_browser import XBrowserScanError, scan_x_url_with_browser_cookies
from lorasuite_engine.tiktok_browser import (
    TikTokBrowserScanError,
    scan_tiktok_url_with_browser_cookies,
)


class LocalImportRequest(BaseModel):
    paths: list[Path]


class RotateMediaRequest(BaseModel):
    degrees: Literal[90, 180, 270] = 90


class ClearAllMediaRequest(BaseModel):
    confirmation: str




class LocalIngressScanRequest(BaseModel):
    roots: list[Path]
    recursive: bool = True


class InstagramHelperScanRequest(BaseModel):
    payload: dict[str, Any]
    include_video_posters_as_image_candidates: bool = True


class InstagramBrowserScanRequest(BaseModel):
    url: str
    browser: str = "chrome"
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None
    scan_mode: Literal["all", "feed", "reels", "tagged"] = "all"
    date_from: date | None = None
    date_to: date | None = None


class XBrowserScanRequest(BaseModel):
    url: str
    browser: str = "chrome"
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class TikTokBrowserScanRequest(BaseModel):
    url: str
    browser: str = "chrome"
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class IngressJobRequest(BaseModel):
    source_kind: SourceKind
    candidate_ids: list[str]
    reviewed_candidate_ids: list[str] = Field(default_factory=list)
    options: dict[str, object] = Field(default_factory=dict)


class IngressCandidateAnalysisRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    target: Literal["image", "video", "voice", "id_lora"] = "image"


class ProcessingJobRequest(BaseModel):
    job_type: Literal["video_breakdown"]
    source_media_item_ids: list[str] = Field(min_length=1)
    options: VideoBreakdownOptions = Field(default_factory=VideoBreakdownOptions)


class VideoKeeperUpdateRequest(BaseModel):
    frame_ids: list[str] = Field(min_length=1)


class CurationHandoffRequest(BaseModel):
    media_item_ids: list[str] = Field(min_length=1)
    project_id: str | None = None
    requested_output: RequestedOutput | None = None


class CurationReviewUpdateRequest(BaseModel):
    review_status: CurationReviewStatus
    project_id: str | None = None
    requested_output: RequestedOutput | None = None
    speaker_confirmation: SpeakerConfirmation | None = None


class CurationRejectRequest(BaseModel):
    media_item_ids: list[str] = Field(min_length=1)


class CurationAnalysisRequest(BaseModel):
    media_item_ids: list[str] = Field(min_length=1)


class AudioCleaningBatchRequest(BaseModel):
    media_item_ids: list[str] = Field(min_length=1)
    force_voice_isolation: bool = False


class VoiceSegmentUpdateRequest(BaseModel):
    status: VoiceSegmentStatus | None = None
    transcript: str | None = None


class VoiceSegmentBulkDecisionRequest(BaseModel):
    decisions: dict[str, VoiceSegmentStatus] = Field(min_length=1)


class VoiceDatasetExportRequest(BaseModel):
    output_dir: Path
    target: VoiceExportTarget = VoiceExportTarget.VOICE_CLONING


class VoiceArtifactEvaluationRequest(BaseModel):
    project_id: str
    artifact_id: str
    samples_dir: Path


class IdLoraEvaluationRequest(BaseModel):
    runpod_run_id: str


class RunPodPreflightRequest(BaseModel):
    bundle_path: Path
    endpoint_id: str
    api_token: str | None = None


class RunPodBundleUploadRequest(BaseModel):
    bundle_path: Path
    volume_id: str
    s3_endpoint: str
    datacenter: str
    access_key: str | None = None
    secret_key: str | None = None


class RunPodBundleUploadResumeRequest(BaseModel):
    access_key: str | None = None
    secret_key: str | None = None


class RunPodInfrastructureProvisionRequest(RunPodInfrastructureRequest):
    api_token: str | None = None


class RunPodModelBootstrapRequest(BaseModel):
    endpoint_id: str
    training_target_profile_id: str
    api_token: str | None = None


class RunPodModelBootstrapActionRequest(BaseModel):
    api_token: str | None = None


class CharacterProjectCreateRequest(BaseModel):
    name: str = "Character Dataset"
    intent: TrainingIntent | None = None


class CharacterProjectUpdateRequest(BaseModel):
    name: str | None = None
    intent: TrainingIntent | None = None


class ProjectCandidatesRequest(BaseModel):
    media_item_ids: list[str] = Field(min_length=1)


class ProjectAnchorsRequest(BaseModel):
    media_item_ids: list[str] = Field(default_factory=list)


class VoiceSampleConfirmationRequest(BaseModel):
    media_item_id: str
    subject_label: str
    requested_output: RequestedOutput = RequestedOutput.VOICE


class ProjectObservationUpdateRequest(BaseModel):
    review_status: DatasetReviewStatus
    view: DatasetView | None = None


class SubjectFaceSelectionRequest(BaseModel):
    face_index: int = Field(ge=0)


class CropRecipeUpdateRequest(BaseModel):
    rect: NormalizedRect | None = None
    status: CropRecipeStatus | None = None
    kind: CropKind | None = None


class DatasetItemUpdateRequest(BaseModel):
    caption: str | None = None
    tags: list[str] | None = None
    status: DatasetItemStatus | None = None


class DatasetBulkStatusRequest(BaseModel):
    status: DatasetItemStatus
    item_ids: list[str] | None = None


class DatasetStrongestSetRequest(BaseModel):
    target_count: int | None = Field(default=None, ge=1)
    disqualified_item_ids: list[str] = Field(default_factory=list)
    included_item_ids: list[str] = Field(default_factory=list)


class DatasetModelCardUpdateRequest(LoraModelCardOverrides):
    pass


class DatasetSnapshotExportRequest(BaseModel):
    output_dir: Path


class DatasetCompileRequest(BaseModel):
    training_target_profile_id: str = "runcomfy_flux1_dev_character"


class RecoveredDatasetRegisterRequest(BaseModel):
    export_path: Path


class DiagnosticBundleRequest(BaseModel):
    comfy_root: Path | None = None
    comfy_base_url: str = "http://127.0.0.1:8188"
    project_id: str | None = None


class RunComfyTrainingRunRequest(BaseModel):
    snapshot_id: str
    config_file: str
    gpu_type: Literal["ADA_80_PLUS", "HOPPER_141"] = "ADA_80_PLUS"
    api_token: str | None = None


class RunComfyTrainingActionRequest(BaseModel):
    api_token: str | None = None


class ModelArtifactInstallRequest(BaseModel):
    comfy_root: Path


class VideoDatasetCompileRequest(BaseModel):
    project_id: str
    media_item_ids: list[str] | None = None
    target_profile_id: str | None = None
    reference_image_media_item_ids: list[str] | None = None
    reference_audio_media_item_ids: list[str] | None = None


class VideoDatasetItemUpdateRequest(BaseModel):
    caption: str | None = None
    status: Literal["needs_review", "approved", "excluded"] | None = None


class VideoDatasetBulkStatusRequest(BaseModel):
    status: Literal["approved", "excluded"]


class VideoDatasetExportRequest(BaseModel):
    output_dir: Path


class IdLoraCompileRequest(BaseModel):
    project_id: str
    video_snapshot_id: str | None = None


class IdLoraExportRequest(BaseModel):
    output_dir: Path


class BenchmarkRunRequest(BaseModel):
    project_id: str
    baseline_dir: Path
    lora_dir: Path
    artifact_id: str | None = None


class BenchmarkWorkspaceRequest(BaseModel):
    project_id: str
    output_dir: Path


class BenchmarkCaseReviewRequest(BaseModel):
    decision: Literal["pending", "accepted", "rejected"]
    note: str = ""


class BenchmarkGenerationRequest(BaseModel):
    project_id: str
    workspace_root: Path
    model_id: str = ""
    endpoint_id: str | None = None
    lora_path: str
    artifact_id: str | None = None
    baseline_payload: dict[str, Any] | None = None
    lora_payload: dict[str, Any] | None = None
    seed_base: int = 8675309
    auto_evaluate: bool = True
    api_token: str | None = None


class BenchmarkGenerationRetryRequest(BaseModel):
    case_ids: list[str]
    api_token: str | None = None


class RunPodBundleRequest(BaseModel):
    source_export_path: Path
    output_path: Path
    modality: Literal["image", "video", "voice", "audio_visual"]
    trigger_token: str
    fingerprint: str
    training_target_profile_id: str | None = None
    remote_root: str = "/workspace/lorasuite"
    endpoint_id: str | None = None


class RunComfyProviderSmokeRequest(BaseModel):
    project_id: str
    source_export_path: Path
    training_target_profile_id: str
    config_file: str


class RunPodProviderSmokeRequest(BaseModel):
    bundle_id: str


class RunPodTrainingRunRequest(BaseModel):
    bundle_path: Path
    endpoint_id: str
    api_token: str | None = None


class RunPodTrainingActionRequest(BaseModel):
    api_token: str | None = None


class RunPodArtifactDownloadRequest(BaseModel):
    output_dir: Path
    volume_id: str
    s3_endpoint: str
    datacenter: str
    access_key: str | None = None
    secret_key: str | None = None


class CaptionGenerationJobRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1)
    provider_id: str
    provider_label: str
    dialect: VisionProviderDialect
    base_url: str
    model: str
    api_key: str | None = None


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    resolved_vault_root = vault_root or default_vault_root()
    social_acquisition_service = SocialAcquisitionService(resolved_vault_root)
    caption_service = CaptionGenerationService(resolved_vault_root)
    def resume_social_acquisition_jobs() -> None:
        for job in social_acquisition_service.recover_interrupted_jobs():
            threading.Thread(
                target=social_acquisition_service.process_job,
                args=(job.id,),
                name=f"lorasuite-{job.id}",
                daemon=True,
            ).start()

    def resume_caption_generation_jobs() -> None:
        for job, config in caption_service.recover_interrupted_jobs():
            threading.Thread(
                target=caption_service.process_job,
                args=(job.id, config),
                name=f"lorasuite-{job.id}",
                daemon=True,
            ).start()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        resume_social_acquisition_jobs()
        resume_caption_generation_jobs()
        yield

    app = FastAPI(title="LoraSuite Engine", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DESKTOP_ORIGINS),
        allow_origin_regex=LOCAL_UI_PATTERN,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.vault_root = resolved_vault_root
    app.include_router(library_router(resolved_vault_root))
    from lorasuite_engine.preferences import preferences_router
    app.include_router(preferences_router(resolved_vault_root))

    @app.middleware("http")
    async def companion_cors(request, call_next):
        # Extension CORS applies ONLY to the narrow paired bridge, never the
        # existing engine endpoints (which expose much more local authority).
        from fastapi.responses import Response
        origin = request.headers.get("origin", "")
        is_bridge = request.url.path.startswith("/library/")
        # CORS alone only prevents reading responses; reject cross-site writes
        # before handlers can act on the local filesystem or launch work.
        local_origin = is_local_ui_origin(origin)
        if origin and not local_origin and not (is_bridge and EXTENSION.fullmatch(origin)):
            return Response("This engine accepts only local application origins", status_code=403)
        if EXTENSION.fullmatch(origin) and not is_bridge:
            return Response("Browser extensions must use the paired library bridge", status_code=403)
        if is_bridge and request.method == "POST":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 65536:
                return Response("Companion request too large", status_code=413)
        if is_bridge and EXTENSION.fullmatch(origin):
            response = Response(status_code=204) if request.method == "OPTIONS" else await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Vary"] = "Origin"
            return response
        return await call_next(request)
    app.state.state_migration_report = StateMigrationService(
        app.state.vault_root,
    ).inspect()
    def ingress_service() -> IngressService:
        return IngressService(app.state.vault_root)

    def processing_service() -> ProcessingService:
        return ProcessingService(app.state.vault_root)

    def character_project_service() -> CharacterProjectService:
        return CharacterProjectService(app.state.vault_root)

    def training_run_service() -> TrainingRunService:
        return TrainingRunService(app.state.vault_root)

    def training_estimate_service() -> TrainingEstimateService:
        return TrainingEstimateService(app.state.vault_root)

    def runpod_training_run_service() -> RunPodTrainingRunService:
        return RunPodTrainingRunService(app.state.vault_root)

    def runpod_bundle_upload_service() -> RunPodBundleUploadService:
        return RunPodBundleUploadService(app.state.vault_root)

    def runpod_bundle_service() -> RunPodBundleService:
        return RunPodBundleService(app.state.vault_root)

    def provider_smoke_service() -> ProviderSmokeService:
        return ProviderSmokeService(app.state.vault_root)

    def require_runcomfy_smoke(snapshot_id: str, config_file: str) -> None:
        snapshot = dataset_compiler_service().get_snapshot(snapshot_id)
        profile_id = snapshot.training_target.profile_id if snapshot is not None else None
        recovered = None
        if snapshot is None:
            snapshot = video_dataset_service().get_snapshot(snapshot_id)
            profile_id = snapshot.target_profile_id if snapshot is not None else None
        if snapshot is None:
            recovered = recovered_dataset_service().find_by_snapshot_id(snapshot_id)
            profile_id = recovered.training_target.profile_id if recovered is not None else None
        if snapshot is None and recovered is None:
            raise KeyError(snapshot_id)
        source_export_path = recovered.export_path if recovered is not None else snapshot.export_path
        project_id = recovered.project_id if recovered is not None else snapshot.project_id
        if recovered is not None and (not recovered.ready or not recovered.source_available):
            raise ValueError("recovered dataset export must pass integrity verification before validating the provider contract")
        if not source_export_path or not profile_id:
            raise ValueError("export the dataset before validating the provider contract")
        smoke = provider_smoke_service().run_runcomfy(
            project_id=project_id,
            source_export_path=source_export_path,
            training_target_profile_id=profile_id,
            config_file=config_file,
        )
        if not smoke.ready:
            failures = [check.detail for check in smoke.checks if not check.passed]
            raise ValueError(f"RunComfy provider smoke failed: {'; '.join(failures) or smoke.error or 'unknown contract failure'}")

    def require_runpod_smoke(bundle_path: Path) -> None:
        normalized = Path(bundle_path).expanduser().resolve(strict=False)
        bundle = next((item for item in runpod_bundle_service().list_bundles() if item.output_path == normalized), None)
        if bundle is None:
            raise ValueError("RunPod bundle must be registered before cloud submission")
        smoke = provider_smoke_service().run_runpod(bundle.id)
        if not smoke.ready:
            failures = [check.detail for check in smoke.checks if not check.passed]
            raise ValueError(f"RunPod provider smoke failed: {'; '.join(failures) or smoke.error or 'unknown contract failure'}")

    def runpod_model_bootstrap_service() -> RunPodModelBootstrapService:
        return RunPodModelBootstrapService(app.state.vault_root)

    def runpod_infrastructure_service() -> RunPodInfrastructureService:
        return RunPodInfrastructureService(app.state.vault_root)

    def training_workflow_service() -> TrainingWorkflowService:
        return TrainingWorkflowService(app.state.vault_root)

    def provider_readiness_service() -> ProviderReadinessService:
        return ProviderReadinessService(app.state.vault_root)

    def partner_qualification_service() -> PartnerQualificationService:
        return PartnerQualificationService(app.state.vault_root)

    def cloud_provider_service() -> CloudProviderService:
        return CloudProviderService(app.state.vault_root)

    def model_registry_service() -> ModelRegistryService:
        return ModelRegistryService(app.state.vault_root)

    def comfy_evaluation_report_service() -> ComfyEvaluationReportService:
        return ComfyEvaluationReportService(app.state.vault_root)

    def improvement_loop_service() -> ImprovementLoopService:
        return ImprovementLoopService(app.state.vault_root)

    def video_dataset_service() -> VideoDatasetService:
        return VideoDatasetService(app.state.vault_root)

    def id_lora_dataset_service() -> IdLoraDatasetService:
        return IdLoraDatasetService(app.state.vault_root)

    def id_lora_evaluation_service() -> IdLoraEvaluationService:
        return IdLoraEvaluationService(app.state.vault_root)

    def evaluation_harness_service() -> EvaluationHarnessService:
        return EvaluationHarnessService(app.state.vault_root)

    def image_evaluation_harness_service() -> ImageEvaluationHarnessService:
        return ImageEvaluationHarnessService(app.state.vault_root)

    def voice_artifact_evaluation_service() -> VoiceArtifactEvaluationService:
        return VoiceArtifactEvaluationService(app.state.vault_root)

    def benchmark_generation_service() -> BenchmarkGenerationService:
        return BenchmarkGenerationService(app.state.vault_root)

    def identity_model_service() -> IdentityModelService:
        return IdentityModelService(app.state.vault_root)

    def dataset_compiler_service() -> DatasetCompilerService:
        return DatasetCompilerService(app.state.vault_root)

    def recovered_dataset_service() -> RecoveredDatasetService:
        return RecoveredDatasetService(app.state.vault_root)

    def state_migration_service() -> StateMigrationService:
        return StateMigrationService(app.state.vault_root)

    def diagnostic_bundle_service() -> DiagnosticBundleService:
        return DiagnosticBundleService(app.state.vault_root)

    def caption_generation_service() -> CaptionGenerationService:
        return caption_service

    def curation_service() -> CurationService:
        return CurationService(app.state.vault_root)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.post("/system/folders/select")
    def select_native_folder() -> dict[str, str | None]:
        try:
            path = pick_native_directory()
        except ValueError as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        return {"path": str(path) if path else None}

    @app.get("/state-migrations")
    def inspect_state_migrations() -> dict[str, object]:
        report = state_migration_service().inspect()
        app.state.state_migration_report = report
        return report.model_dump(mode="json")

    @app.post("/state-migrations/apply")
    def apply_state_migrations() -> dict[str, object]:
        report = state_migration_service().migrate()
        app.state.state_migration_report = report
        return report.model_dump(mode="json")

    @app.get("/diagnostic-bundles")
    def list_diagnostic_bundles() -> list[dict[str, object]]:
        return [
            record.model_dump(mode="json")
            for record in diagnostic_bundle_service().list_bundles()
        ]

    @app.post("/diagnostic-bundles")
    def create_diagnostic_bundle(
        request: DiagnosticBundleRequest,
    ) -> dict[str, object]:
        try:
            record = diagnostic_bundle_service().create(
                comfy_root=request.comfy_root,
                comfy_base_url=request.comfy_base_url,
                project_id=request.project_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return record.model_dump(mode="json")

    @app.get("/diagnostic-bundles/{bundle_id}/download")
    def download_diagnostic_bundle(bundle_id: str) -> FileResponse:
        record = diagnostic_bundle_service().get_bundle(bundle_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Diagnostic bundle not found")
        if not record.archive_path.is_file():
            raise HTTPException(status_code=410, detail="Diagnostic bundle archive is unavailable")
        return FileResponse(
            record.archive_path,
            media_type="application/zip",
            filename=record.archive_path.name,
        )

    @app.get("/evaluation/capabilities/syncnet")
    def syncnet_evaluation_capability() -> dict[str, object]:
        return syncnet_capability().model_dump(mode="json")

    @app.get("/identity/status")
    def identity_status() -> dict[str, object]:
        return identity_model_service().status().model_dump(mode="json")

    @app.post("/identity/install")
    def install_identity_models() -> dict[str, object]:
        try:
            status = identity_model_service().install()
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return status.model_dump(mode="json")

    @app.get("/caption/providers")
    def list_caption_providers() -> list[dict[str, object]]:
        return [preset.model_dump(mode="json") for preset in provider_presets()]

    @app.post("/caption/providers/grok-oauth/login")
    def begin_grok_oauth_login() -> dict[str, object]:
        try:
            message = start_grok_oauth_login()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"started": True, "message": message}

    @app.get("/caption-jobs")
    def list_caption_jobs(snapshot_id: str | None = None) -> list[dict[str, object]]:
        return [
            job.model_dump(mode="json")
            for job in caption_generation_service().list_jobs(snapshot_id)
        ]

    @app.get("/caption-jobs/{job_id}")
    def get_caption_job(job_id: str) -> dict[str, object]:
        job = caption_generation_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Caption job not found")
        return job.model_dump(mode="json")

    @app.post("/caption-jobs/{job_id}/cancel")
    def cancel_caption_job(job_id: str) -> dict[str, object]:
        try:
            job = caption_generation_service().cancel_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Caption job not found") from error
        return job.model_dump(mode="json")

    @app.get("/assets/file")
    def read_vault_asset(path: Path = Query(...)) -> FileResponse:
        asset_path = _validated_vault_asset_path(path, app.state.vault_root)
        if asset_path is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(asset_path)

    @app.post("/vault/import/local")
    def import_local(request: LocalImportRequest) -> dict[str, list[dict]]:
        result = VaultService(app.state.vault_root).import_local_paths(request.paths)
        return result.model_dump(mode="json")

    @app.get("/vault/media")
    def list_vault_media() -> list[dict[str, object]]:
        return [
            item.model_dump(mode="json")
            for item in VaultService(app.state.vault_root).list_media_items()
        ]

    @app.get("/vault/media-page")
    def query_vault_media(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        media_type: MediaType | None = None,
        status: MediaStatus | None = None,
        search: str | None = None,
        include_ignored: bool = False,
        snapshot: str | None = None,
    ) -> dict[str, object]:
        try:
            page = VaultService(app.state.vault_root).query_media_items(
                offset=offset,
                limit=limit,
                media_type=media_type,
                status=status,
                search=search,
                include_ignored=include_ignored,
                snapshot=snapshot,
            )
        except VaultSnapshotConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return page.model_dump(mode="json")

    @app.get("/vault/duplicate-clusters")
    def list_vault_duplicate_clusters() -> list[dict[str, object]]:
        return [
            cluster.model_dump(mode="json")
            for cluster in VaultService(app.state.vault_root).list_exact_duplicate_clusters()
        ]

    @app.post("/vault/media/clear")
    def clear_all_media(request: ClearAllMediaRequest) -> dict[str, object]:
        if request.confirmation != "CLEAR ALL MEDIA":
            raise HTTPException(status_code=400, detail="clear-all confirmation did not match")
        try:
            return MediaResetService(app.state.vault_root).clear_all_media()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/vault/media/{media_item_id}/rotate")
    def rotate_vault_image(
        media_item_id: str,
        request: RotateMediaRequest,
    ) -> dict[str, object]:
        try:
            item = VaultService(app.state.vault_root).rotate_image(
                media_item_id,
                request.degrees,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return item.model_dump(mode="json")

    @app.get("/curation/bundles")
    def list_curation_bundles() -> list[dict[str, object]]:
        return [
            bundle.model_dump(mode="json")
            for bundle in curation_service().list_source_bundles()
        ]

    @app.get("/curation/handoff")
    def get_curation_handoff(
        project_id: str | None = None,
        requested_output: RequestedOutput | None = None,
    ) -> dict[str, object]:
        return curation_service().get_handoff(
            project_id,
            requested_output,
        ).model_dump(mode="json")

    @app.post("/curation/handoff")
    def add_curation_handoff(
        request: CurationHandoffRequest,
    ) -> dict[str, object]:
        try:
            handoff = curation_service().add_to_handoff(
                request.media_item_ids,
                project_id=request.project_id,
                requested_output=request.requested_output,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return handoff.model_dump(mode="json")

    @app.patch("/curation/handoff/{media_item_id}")
    def update_curation_handoff_item(
        media_item_id: str,
        request: CurationReviewUpdateRequest,
    ) -> dict[str, object]:
        try:
            handoff = curation_service().update_review_status(
                media_item_id,
                request.review_status,
                project_id=request.project_id,
                requested_output=request.requested_output,
                speaker_confirmation=request.speaker_confirmation,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Handoff item not found") from error
        return handoff.model_dump(mode="json")

    @app.post("/curation/reject")
    def reject_curation_media(
        request: CurationRejectRequest,
    ) -> list[dict[str, object]]:
        try:
            items = curation_service().reject_media_items(request.media_item_ids)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        return [item.model_dump(mode="json") for item in items]

    @app.post("/curation/audio/restore")
    def restore_curation_audio(
        request: CurationRejectRequest,
    ) -> list[dict[str, object]]:
        try:
            items = curation_service().restore_audio_items(request.media_item_ids)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [item.model_dump(mode="json") for item in items]

    @app.get("/curation/audio/{media_item_id}/cleaning-recipe")
    def get_audio_cleaning_recipe(media_item_id: str) -> dict[str, object]:
        try:
            recipe = AudioCleaningService(app.state.vault_root).get_recipe(media_item_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return recipe.model_dump(mode="json")

    @app.get("/curation/audio/separation/status")
    def get_audio_separation_status() -> dict[str, object]:
        return AudioCleaningService(app.state.vault_root).separation_status().model_dump(
            mode="json"
        )

    @app.post("/curation/audio/separation/install")
    def install_audio_separation_model() -> dict[str, object]:
        try:
            status = AudioCleaningService(
                app.state.vault_root
            ).install_separator_model()
        except (OSError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return status.model_dump(mode="json")

    @app.post("/curation/audio/{media_item_id}/cleaning-preview")
    def preview_audio_cleaning(
        media_item_id: str,
        recipe: AudioCleaningRecipe,
    ) -> dict[str, object]:
        if recipe.media_item_id != media_item_id:
            raise HTTPException(status_code=400, detail="Recipe media item does not match URL")
        try:
            result = AudioCleaningService(app.state.vault_root).preview(recipe)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return result.model_dump(mode="json")

    @app.post("/curation/audio/{media_item_id}/cleaning-render")
    def render_audio_cleaning(
        media_item_id: str,
        recipe: AudioCleaningRecipe,
    ) -> dict[str, object]:
        if recipe.media_item_id != media_item_id:
            raise HTTPException(status_code=400, detail="Recipe media item does not match URL")
        try:
            result = AudioCleaningService(app.state.vault_root).render(recipe)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return result.model_dump(mode="json")

    @app.post("/curation/analyze")
    def analyze_curation_media(
        request: CurationAnalysisRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = processing_service()
        job = service.create_curation_analysis_job(
            source_media_item_ids=request.media_item_ids,
        )
        background_tasks.add_task(service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.post("/curation/audio/cleaning-jobs")
    def create_audio_cleaning_job(
        request: AudioCleaningBatchRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = processing_service()
        job = service.create_audio_cleaning_job(
            source_media_item_ids=request.media_item_ids,
            options=AudioCleaningBatchOptions(
                force_voice_isolation=request.force_voice_isolation,
            ),
        )
        background_tasks.add_task(service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.post("/exports/runcomfy-image")
    def retired_raw_image_export():
        raise HTTPException(410, "Raw frame exports are retired. Review and freeze a dataset, then export it from Build & Train.")

    @app.post("/ingress/local/scan")
    def scan_local_ingress(request: LocalIngressScanRequest) -> dict[str, object]:
        result = ingress_service().scan_local_roots(
            request.roots,
            recursive=request.recursive,
        )
        return result.model_dump(mode="json")

    @app.post("/ingress/local/upload-scan")
    async def scan_local_upload_ingress(
        files: list[UploadFile] = File(...),
    ) -> dict[str, object]:
        upload_root = app.state.vault_root / "uploads" / f"upload_{uuid4().hex}"
        upload_root.mkdir(parents=True, exist_ok=True)
        uploaded_paths: list[Path] = []

        for uploaded_file in files:
            relative_path = _safe_upload_relative_path(uploaded_file.filename)
            target_path = _unique_upload_path(upload_root, relative_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(await uploaded_file.read())
            uploaded_paths.append(target_path)

        result = ingress_service().scan_local_roots(uploaded_paths, recursive=False)
        result.metadata_json["upload_root"] = str(upload_root)
        return result.model_dump(mode="json")

    @app.post("/ingress/instagram/helper-scan")
    def scan_instagram_helper(request: InstagramHelperScanRequest) -> dict[str, object]:
        try:
            result = scan_instagram_helper_payload(
                request.payload,
                app.state.vault_root,
                include_video_posters_as_image_candidates=(
                    request.include_video_posters_as_image_candidates
                ),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.post("/ingress/instagram/browser-scan")
    def scan_instagram_browser(request: InstagramBrowserScanRequest) -> dict[str, object]:
        try:
            result = scan_instagram_url_with_browser_cookies(
                request.url,
                app.state.vault_root,
                browser=request.browser,
                limit=request.limit,
                cursor=request.cursor,
                scan_mode=request.scan_mode,
                date_from=request.date_from,
                date_to=request.date_to,
            )
        except InstagramBrowserScanError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.post("/ingress/social-acquisitions")
    def create_social_acquisition(
        request: SocialAcquisitionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        job = social_acquisition_service.create_job(request)
        if job.status not in {"complete", "canceled"}:
            background_tasks.add_task(social_acquisition_service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/ingress/social-acquisitions")
    def list_social_acquisitions() -> list[dict[str, object]]:
        return [
            job.model_dump(mode="json")
            for job in social_acquisition_service.list_jobs()
        ]

    @app.get("/ingress/social-acquisitions/{job_id}")
    def get_social_acquisition(job_id: str) -> dict[str, object]:
        job = social_acquisition_service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Social acquisition job not found")
        return job.model_dump(mode="json")

    @app.post("/ingress/social-acquisitions/{job_id}/resume")
    def resume_social_acquisition(
        job_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            job = social_acquisition_service.resume_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Social acquisition job not found") from error
        if job.status != "complete":
            background_tasks.add_task(social_acquisition_service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.post("/ingress/social-acquisitions/{job_id}/cancel")
    def cancel_social_acquisition(job_id: str) -> dict[str, object]:
        try:
            job = social_acquisition_service.cancel_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Social acquisition job not found") from error
        return job.model_dump(mode="json")

    @app.post("/ingress/x/browser-scan")
    def scan_x_browser(request: XBrowserScanRequest) -> dict[str, object]:
        try:
            result = scan_x_url_with_browser_cookies(
                request.url,
                app.state.vault_root,
                browser=request.browser,
                limit=request.limit,
                cursor=request.cursor,
                date_from=request.date_from,
                date_to=request.date_to,
            )
        except XBrowserScanError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.post("/ingress/tiktok/browser-scan")
    def scan_tiktok_browser(request: TikTokBrowserScanRequest) -> dict[str, object]:
        try:
            result = scan_tiktok_url_with_browser_cookies(
                request.url,
                app.state.vault_root,
                browser=request.browser,
                limit=request.limit,
                cursor=request.cursor,
                date_from=request.date_from,
                date_to=request.date_to,
            )
        except TikTokBrowserScanError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.get("/ingress/candidates")
    def list_ingress_candidates(source_kind: SourceKind | None = None) -> dict[str, object]:
        candidates = ingress_service().list_candidates(source_kind)
        return {
            "candidates": [
                candidate.model_dump(mode="json") for candidate in candidates
            ],
            "errors": [],
        }

    @app.get("/ingress/candidates/{candidate_id}/video-preview")
    def preview_ingress_candidate_video(candidate_id: str) -> FileResponse:
        try:
            preview_path = ingress_service().prepare_candidate_video_preview(candidate_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Ingress candidate not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (HTTPError, OSError, URLError) as error:
            raise HTTPException(status_code=502, detail=f"Social video preview failed: {error}") from error
        return FileResponse(preview_path, media_type="video/mp4")

    @app.get("/ingress/candidates/{candidate_id}/thumbnail")
    def preview_ingress_candidate_thumbnail(candidate_id: str) -> FileResponse:
        try:
            preview_path = ingress_service().prepare_candidate_thumbnail(candidate_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Ingress candidate not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (HTTPError, OSError, RuntimeError, URLError) as error:
            raise HTTPException(status_code=502, detail=f"X thumbnail generation failed: {error}") from error
        media_type = "image/png" if preview_path.suffix.lower() == ".png" else "image/jpeg"
        return FileResponse(preview_path, media_type=media_type)

    @app.post("/ingress/candidates/analyze")
    def analyze_ingress_candidates(
        request: IngressCandidateAnalysisRequest,
    ) -> dict[str, object]:
        candidates_by_id = {
            candidate.id: candidate for candidate in ingress_service().list_candidates()
        }
        candidates = [
            candidates_by_id[candidate_id]
            for candidate_id in request.candidate_ids
            if candidate_id in candidates_by_id
        ]
        missing_ids = [
            candidate_id
            for candidate_id in request.candidate_ids
            if candidate_id not in candidates_by_id
        ]
        analyses = IngressCandidateAnalyzer().analyze(candidates, request.target)
        return {
            "analyses": analyses,
            "errors": [
                {"candidate_id": candidate_id, "message": "candidate not found"}
                for candidate_id in missing_ids
            ],
        }

    @app.post("/ingress/jobs")
    def create_ingress_job(
        request: IngressJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        job = ingress_service().create_job(
            request.source_kind,
            request.candidate_ids,
            request.options,
            reviewed_candidate_ids=request.reviewed_candidate_ids,
        )
        background_tasks.add_task(ingress_service().process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/ingress/jobs")
    def list_ingress_jobs() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in ingress_service().list_jobs()]

    @app.get("/ingress/jobs/{job_id}")
    def get_ingress_job(job_id: str) -> dict[str, object]:
        job = ingress_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Ingress job not found")
        return job.model_dump(mode="json")

    @app.post("/processing/jobs")
    def create_processing_job(
        request: ProcessingJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = processing_service()
        job = service.create_video_breakdown_job(
            source_media_item_ids=request.source_media_item_ids,
            options=request.options,
        )
        background_tasks.add_task(service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/processing/jobs")
    def list_processing_jobs() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in processing_service().list_jobs()]

    @app.post("/processing/jobs/{job_id}/process")
    def process_processing_job(
        job_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = processing_service()
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Processing job not found")
        background_tasks.add_task(service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/processing/jobs/{job_id}")
    def get_processing_job(job_id: str) -> dict[str, object]:
        job = processing_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Processing job not found")
        return job.model_dump(mode="json")

    @app.post("/processing/jobs/{job_id}/keepers")
    def update_video_keepers(
        job_id: str,
        request: VideoKeeperUpdateRequest,
    ) -> dict[str, object]:
        service = processing_service()
        try:
            job = service.update_video_keepers(job_id, request.frame_ids)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Processing job not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return job.model_dump(mode="json")

    @app.post("/processing/jobs/{job_id}/commit")
    def commit_video_breakdown(
        job_id: str,
        request: VideoBreakdownCommitRequest,
    ) -> dict[str, object]:
        service = processing_service()
        try:
            job = service.commit_video_breakdown(job_id, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Processing job not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return job.model_dump(mode="json")

    @app.get("/character-projects")
    def list_character_projects() -> list[dict[str, object]]:
        return [
            project.model_dump(mode="json")
            for project in character_project_service().list_projects()
        ]

    @app.post("/character-projects")
    def create_character_project(
        request: CharacterProjectCreateRequest,
    ) -> dict[str, object]:
        project = character_project_service().create_project(
            name=request.name,
            intent=request.intent,
        )
        return project.model_dump(mode="json")

    @app.get("/character-projects/{project_id}")
    def get_character_project(project_id: str) -> dict[str, object]:
        project = character_project_service().get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        return project.model_dump(mode="json")

    @app.patch("/character-projects/{project_id}")
    def update_character_project(
        project_id: str,
        request: CharacterProjectUpdateRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().update_project(
                project_id,
                name=request.name,
                intent=request.intent,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        return project.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/candidates")
    def add_character_project_candidates(
        project_id: str,
        request: ProjectCandidatesRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().add_candidates(
                project_id,
                request.media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return project.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/anchors")
    def set_character_project_anchors(
        project_id: str,
        request: ProjectAnchorsRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().set_anchors(
                project_id,
                request.media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return project.model_dump(mode="json")

    @app.patch("/character-projects/{project_id}/observations/{media_item_id}")
    def update_character_project_observation(
        project_id: str,
        media_item_id: str,
        request: ProjectObservationUpdateRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().update_observation(
                project_id,
                media_item_id,
                review_status=request.review_status,
                view=request.view,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return project.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/observations/{media_item_id}/face")
    def select_character_project_subject_face(
        project_id: str,
        media_item_id: str,
        request: SubjectFaceSelectionRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().select_subject_face(
                project_id,
                media_item_id,
                request.face_index,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return project.model_dump(mode="json")

    @app.patch("/character-projects/{project_id}/crops/{recipe_id}")
    def update_character_project_crop(
        project_id: str,
        recipe_id: str,
        request: CropRecipeUpdateRequest,
    ) -> dict[str, object]:
        try:
            project = character_project_service().update_crop_recipe(
                project_id,
                recipe_id,
                rect=request.rect,
                status=request.status,
                kind=request.kind,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return project.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/crops/{recipe_id}/materialize")
    def materialize_character_project_crop(
        project_id: str,
        recipe_id: str,
    ) -> dict[str, object]:
        try:
            project, media_item = character_project_service().materialize_crop(
                project_id,
                recipe_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "project": project.model_dump(mode="json"),
            "media_item": media_item.model_dump(mode="json"),
        }

    @app.post("/character-projects/{project_id}/analyze")
    def analyze_character_project(project_id: str) -> dict[str, object]:
        try:
            project = character_project_service().analyze_project(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        return project.model_dump(mode="json")

    @app.get("/identity/voice/status")
    def get_voice_identity_status() -> dict[str, object]:
        return SpeakerIdentityModelService().status().model_dump(mode="json")

    @app.post("/identity/voice/install")
    def install_voice_identity_model() -> dict[str, object]:
        try:
            status = SpeakerIdentityModelService().install()
        except (OSError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return status.model_dump(mode="json")

    @app.get("/character-projects/{project_id}/voice-identity")
    def get_voice_identity_profile(project_id: str) -> dict[str, object]:
        if character_project_service().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        return VoiceIdentityService(app.state.vault_root).get_profile(project_id).model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-identity/anchors")
    def set_voice_identity_anchors(
        project_id: str,
        request: ProjectAnchorsRequest,
    ) -> dict[str, object]:
        if character_project_service().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        try:
            profile = VoiceIdentityService(app.state.vault_root).set_anchors(
                project_id,
                request.media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return profile.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-identity/confirm")
    def confirm_voice_identity_sample(
        project_id: str,
        request: VoiceSampleConfirmationRequest,
    ) -> dict[str, object]:
        project = character_project_service().get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        subject_label = request.subject_label.strip()
        if not subject_label:
            raise HTTPException(status_code=400, detail="Subject label is required")
        if request.requested_output not in {RequestedOutput.VOICE, RequestedOutput.ID_LORA}:
            raise HTTPException(
                status_code=400,
                detail="Voice confirmation requires a voice-capable output",
            )

        voice_service = VoiceIdentityService(app.state.vault_root)
        previous_anchors = voice_service.get_profile(project_id).anchor_media_item_ids
        next_anchors = list(dict.fromkeys([*previous_anchors, request.media_item_id]))
        try:
            profile = voice_service.set_anchors(project_id, next_anchors)
            service = curation_service()
            handoff = service.get_handoff(project_id, request.requested_output)
            if request.media_item_id not in {
                item.media_item_id for item in handoff.items
            }:
                service.add_to_handoff(
                    [request.media_item_id],
                    project_id=project_id,
                    requested_output=request.requested_output,
                )
            handoff = service.update_review_status(
                request.media_item_id,
                CurationReviewStatus.ACCEPTED,
                project_id=project_id,
                requested_output=request.requested_output,
                speaker_confirmation=SpeakerConfirmation.ANCHOR,
            )
            if (
                project.intent.subject_name != subject_label
                or request.requested_output not in project.intent.requested_outputs
            ):
                next_intent = project.intent.model_copy(deep=True)
                next_intent.subject_name = subject_label
                next_intent.requested_outputs = list(
                    dict.fromkeys(
                        [*next_intent.requested_outputs, request.requested_output]
                    )
                )
                project = character_project_service().update_project(
                    project_id,
                    intent=next_intent,
                )
        except (KeyError, ValueError) as error:
            voice_service.set_anchors(project_id, previous_anchors)
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "project": project.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "handoff": handoff.model_dump(mode="json"),
        }

    @app.post("/character-projects/{project_id}/voice-identity/analyze")
    def analyze_voice_identity(
        project_id: str,
        request: ProjectAnchorsRequest,
    ) -> dict[str, object]:
        if character_project_service().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        try:
            profile = VoiceIdentityService(app.state.vault_root).analyze(
                project_id,
                request.media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return profile.model_dump(mode="json")

    @app.get("/character-projects/{project_id}/voice-dataset")
    def get_voice_dataset(project_id: str) -> dict[str, object]:
        if character_project_service().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        return VoiceDatasetService(app.state.vault_root).get(project_id).model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-dataset/compile")
    def compile_voice_dataset(
        project_id: str,
        request: ProjectAnchorsRequest,
    ) -> dict[str, object]:
        if character_project_service().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="Character project not found")
        try:
            compilation = VoiceDatasetService(app.state.vault_root).compile(
                project_id,
                request.media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return compilation.model_dump(mode="json")

    @app.patch("/character-projects/{project_id}/voice-dataset/segments/{segment_id}")
    def update_voice_dataset_segment(
        project_id: str,
        segment_id: str,
        request: VoiceSegmentUpdateRequest,
    ) -> dict[str, object]:
        try:
            compilation = VoiceDatasetService(app.state.vault_root).update_segment(
                project_id,
                segment_id,
                status=request.status,
                transcript=request.transcript,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Voice segment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return compilation.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-dataset/segments/bulk-status")
    def bulk_update_voice_dataset_segments(
        project_id: str,
        request: VoiceSegmentBulkDecisionRequest,
    ) -> dict[str, object]:
        try:
            compilation = VoiceDatasetService(app.state.vault_root).bulk_update_segments(
                project_id,
                request.decisions,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Voice segment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return compilation.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-dataset/rescore")
    def rescore_voice_dataset(project_id: str) -> dict[str, object]:
        try:
            compilation = VoiceDatasetService(app.state.vault_root).rescore(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return compilation.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-dataset/quality-gate")
    def analyze_voice_dataset_quality(project_id: str) -> dict[str, object]:
        try:
            compilation = VoiceDatasetService(app.state.vault_root).analyze_quality(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Media item not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return compilation.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/voice-dataset/export")
    def export_voice_dataset(
        project_id: str,
        request: VoiceDatasetExportRequest,
    ) -> dict[str, object]:
        service = VoiceDatasetService(app.state.vault_root)
        compilation = service.get(project_id)
        try:
            package = create_voice_dataset_export(
                compilation=compilation,
                output_dir=request.output_dir,
                target=request.target,
            )
            compilation = service.mark_exported(
                project_id,
                package.output_path,
                request.target,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "compilation": compilation.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
        }

    @app.get("/dataset-snapshots")
    def list_dataset_snapshots(project_id: str | None = None) -> list[dict[str, object]]:
        return [
            snapshot.model_dump(mode="json")
            for snapshot in dataset_compiler_service().list_snapshots(project_id)
        ]

    @app.get("/training-targets")
    def list_training_targets() -> list[dict[str, object]]:
        return [profile.model_dump(mode="json") for profile in training_target_profiles()]

    @app.post("/training-estimates")
    def create_training_estimate(
        request: TrainingEstimateRequest,
    ) -> dict[str, object]:
        try:
            estimate = training_estimate_service().estimate(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return estimate.model_dump(mode="json")

    @app.get("/model-intent-recipes")
    def list_model_intent_recipes() -> list[dict[str, object]]:
        return [recipe.model_dump(mode="json") for recipe in model_intent_recipes()]

    @app.get("/training-workflow/{project_id}")
    def get_training_workflow(project_id: str) -> dict[str, object]:
        try:
            workflow = training_workflow_service().status(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        return workflow.model_dump(mode="json")

    @app.get("/provider-readiness/{project_id}")
    def get_provider_readiness(project_id: str) -> dict[str, object]:
        try:
            matrix = provider_readiness_service().status(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        return matrix.model_dump(mode="json")

    @app.get("/partner-qualification/{project_id}")
    def get_partner_qualification(project_id: str) -> dict[str, object]:
        try:
            report = partner_qualification_service().report(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        return report.model_dump(mode="json")

    @app.get("/cloud-providers")
    def list_cloud_providers() -> list[dict[str, object]]:
        return [
            descriptor.model_dump(mode="json")
            for descriptor in cloud_provider_service().descriptors()
        ]

    @app.get("/cloud-runs")
    def list_cloud_runs(
        project_id: str | None = None,
        provider: Literal["runcomfy", "runpod"] | None = None,
    ) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in cloud_provider_service().list_runs(
                project_id=project_id,
                provider=provider,
            )
        ]

    @app.get("/runpod-bundles")
    def list_runpod_bundles(
        source_export_path: Path | None = None,
        training_target_profile_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            bundle.model_dump(mode="json")
            for bundle in runpod_bundle_service().list_bundles(
                source_export_path=source_export_path,
                training_target_profile_id=training_target_profile_id,
                project_id=project_id,
            )
        ]

    @app.post("/runpod-bundles")
    def create_runpod_bundle(request: RunPodBundleRequest) -> dict[str, object]:
        try:
            bundle = runpod_bundle_service().create_bundle(
                source_export_path=request.source_export_path,
                output_path=request.output_path,
                modality=request.modality,
                trigger_token=request.trigger_token,
                fingerprint=request.fingerprint,
                training_target_profile_id=request.training_target_profile_id,
                remote_root=request.remote_root,
                endpoint_id=request.endpoint_id,
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return bundle.model_dump(mode="json")

    @app.get("/provider-smoke-runs")
    def list_provider_smoke_runs(
        project_id: str | None = None,
        provider: Literal["runcomfy", "runpod"] | None = None,
        training_target_profile_id: str | None = None,
        bundle_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in provider_smoke_service().list_runs(
                project_id=project_id,
                provider=provider,
                training_target_profile_id=training_target_profile_id,
                bundle_id=bundle_id,
            )
        ]

    @app.get("/provider-smoke-runs/{run_id}")
    def get_provider_smoke_run(run_id: str) -> dict[str, object]:
        run = provider_smoke_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Provider smoke run not found")
        return run.model_dump(mode="json")

    @app.post("/provider-smoke-runs/runcomfy")
    def create_runcomfy_provider_smoke_run(request: RunComfyProviderSmokeRequest) -> dict[str, object]:
        try:
            run = provider_smoke_service().run_runcomfy(
                project_id=request.project_id,
                source_export_path=request.source_export_path,
                training_target_profile_id=request.training_target_profile_id,
                config_file=request.config_file,
            )
        except (KeyError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/provider-smoke-runs/runpod")
    def create_runpod_provider_smoke_run(request: RunPodProviderSmokeRequest) -> dict[str, object]:
        try:
            run = provider_smoke_service().run_runpod(request.bundle_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod bundle not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.get("/runpod-infrastructure-profiles")
    def list_runpod_infrastructure_profiles() -> list[dict[str, object]]:
        return [
            profile.model_dump(mode="json")
            for profile in runpod_infrastructure_service().list_profiles()
        ]

    @app.post("/runpod-infrastructure-profiles/provision")
    def provision_runpod_infrastructure(
        request: RunPodInfrastructureProvisionRequest,
    ) -> dict[str, object]:
        try:
            token = resolve_runpod_infrastructure_token(request.api_token)
            profile_request = RunPodInfrastructureRequest.model_validate(
                request.model_dump(exclude={"api_token"})
            )
            profile = runpod_infrastructure_service().provision(profile_request, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod infrastructure profile not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return profile.model_dump(mode="json")

    @app.get("/runpod-training-runs")
    def list_runpod_training_runs(bundle_path: Path | None = None) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in runpod_training_run_service().list_runs(bundle_path=bundle_path)
        ]

    @app.get("/runpod-model-bootstrap-runs")
    def list_runpod_model_bootstrap_runs(
        endpoint_id: str | None = None,
        training_target_profile_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in runpod_model_bootstrap_service().list_runs(
                endpoint_id=endpoint_id,
                training_target_profile_id=training_target_profile_id,
            )
        ]

    @app.get("/runpod-model-bootstrap-runs/{run_id}")
    def get_runpod_model_bootstrap_run(run_id: str) -> dict[str, object]:
        run = runpod_model_bootstrap_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="RunPod model bootstrap run not found")
        return run.model_dump(mode="json")

    @app.post("/runpod-model-bootstrap-runs")
    def create_runpod_model_bootstrap_run(request: RunPodModelBootstrapRequest) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            service = runpod_model_bootstrap_service()
            run = service.create_run(
                endpoint_id=request.endpoint_id,
                training_target_profile_id=request.training_target_profile_id,
            )
            run = service.submit_run(run.id, token)
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-model-bootstrap-runs/{run_id}/refresh")
    def refresh_runpod_model_bootstrap_run(
        run_id: str,
        request: RunPodModelBootstrapActionRequest,
    ) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            run = runpod_model_bootstrap_service().refresh_run(run_id, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod model bootstrap run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-model-bootstrap-runs/{run_id}/cancel")
    def cancel_runpod_model_bootstrap_run(
        run_id: str,
        request: RunPodModelBootstrapActionRequest,
    ) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            run = runpod_model_bootstrap_service().cancel_run(run_id, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod model bootstrap run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.get("/runpod-preflight-reports")
    def list_runpod_preflight_reports(
        bundle_path: Path | None = None,
        endpoint_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            report.model_dump(mode="json")
            for report in runpod_training_run_service().list_preflight_reports(
                bundle_path=bundle_path,
                endpoint_id=endpoint_id,
            )
        ]

    @app.post("/runpod-preflight-reports")
    def create_runpod_preflight_report(request: RunPodPreflightRequest) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            report = runpod_training_run_service().preflight(
                bundle_path=request.bundle_path,
                endpoint_id=request.endpoint_id,
                token=token,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return report.model_dump(mode="json")

    @app.get("/runpod-bundle-upload-jobs")
    def list_runpod_bundle_upload_jobs(bundle_path: Path | None = None) -> list[dict[str, object]]:
        return [
            job.model_dump(mode="json")
            for job in runpod_bundle_upload_service().list_jobs(bundle_path=bundle_path)
        ]

    @app.get("/runpod-bundle-upload-jobs/{job_id}")
    def get_runpod_bundle_upload_job(job_id: str) -> dict[str, object]:
        job = runpod_bundle_upload_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="RunPod bundle upload job not found")
        return job.model_dump(mode="json")

    @app.post("/runpod-bundle-upload-jobs")
    def create_runpod_bundle_upload_job(
        request: RunPodBundleUploadRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = runpod_bundle_upload_service()
        try:
            require_runpod_smoke(request.bundle_path)
            job = service.create_job(
                bundle_path=request.bundle_path,
                volume_id=request.volume_id,
                endpoint_url=request.s3_endpoint,
                datacenter=request.datacenter,
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if job.status != "complete":
            background_tasks.add_task(service.process_job, job.id, request.access_key, request.secret_key)
        return job.model_dump(mode="json")

    @app.post("/runpod-bundle-upload-jobs/{job_id}/resume")
    def resume_runpod_bundle_upload_job(
        job_id: str,
        request: RunPodBundleUploadResumeRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = runpod_bundle_upload_service()
        try:
            job = service.resume_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod bundle upload job not found") from error
        if job.status != "complete":
            background_tasks.add_task(service.process_job, job.id, request.access_key, request.secret_key)
        return job.model_dump(mode="json")

    @app.get("/runpod-training-runs/{run_id}")
    def get_runpod_training_run(run_id: str) -> dict[str, object]:
        run = runpod_training_run_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="RunPod training run not found")
        return run.model_dump(mode="json")

    @app.post("/runpod-training-runs")
    def create_runpod_training_run(request: RunPodTrainingRunRequest) -> dict[str, object]:
        try:
            require_runpod_smoke(request.bundle_path)
            token = resolve_runpod_token(request.api_token)
            service = runpod_training_run_service()
            run = service.create_run(bundle_path=request.bundle_path, endpoint_id=request.endpoint_id)
            run = service.submit_run(run.id, token)
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-training-runs/{run_id}/refresh")
    def refresh_runpod_training_run(run_id: str, request: RunPodTrainingActionRequest) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            run = runpod_training_run_service().refresh_run(run_id, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod training run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-training-runs/{run_id}/cancel")
    def cancel_runpod_training_run(run_id: str, request: RunPodTrainingActionRequest) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            run = runpod_training_run_service().cancel_run(run_id, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod training run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-training-runs/{run_id}/download-artifacts")
    def download_runpod_training_artifacts(run_id: str, request: RunPodArtifactDownloadRequest) -> dict[str, object]:
        try:
            run = runpod_training_run_service().download_artifacts(
                run_id,
                output_dir=request.output_dir,
                volume_id=request.volume_id,
                endpoint_url=request.s3_endpoint,
                region=request.datacenter,
                access_key=request.access_key,
                secret_key=request.secret_key,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod training run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/runpod-training-runs/{run_id}/register-artifacts")
    def register_runpod_training_artifacts(run_id: str) -> list[dict[str, object]]:
        try:
            records = model_registry_service().register_runpod_run(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod training run not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [record.model_dump(mode="json") for record in records]

    @app.get("/dataset-snapshots/{snapshot_id}")
    def get_dataset_snapshot(snapshot_id: str) -> dict[str, object]:
        snapshot = dataset_compiler_service().get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found")
        return snapshot.model_dump(mode="json")

    @app.post("/character-projects/{project_id}/dataset/compile")
    def compile_character_dataset(
        project_id: str,
        request: DatasetCompileRequest,
    ) -> dict[str, object]:
        try:
            target = get_training_target_profile(request.training_target_profile_id)
            snapshot = dataset_compiler_service().compile_project(project_id, target.spec())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.patch("/dataset-snapshots/{snapshot_id}/items/{item_id}")
    def update_dataset_item(
        snapshot_id: str,
        item_id: str,
        request: DatasetItemUpdateRequest,
    ) -> dict[str, object]:
        try:
            snapshot = dataset_compiler_service().update_item(
                snapshot_id,
                item_id,
                caption=request.caption,
                tags=request.tags,
                status=request.status,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/items/bulk-status")
    def bulk_update_dataset_items(
        snapshot_id: str,
        request: DatasetBulkStatusRequest,
    ) -> dict[str, object]:
        try:
            snapshot = dataset_compiler_service().bulk_update_status(
                snapshot_id,
                status=request.status,
                item_ids=request.item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/strongest-set/propose")
    def propose_dataset_strongest_set(
        snapshot_id: str,
        request: DatasetStrongestSetRequest,
    ) -> dict[str, object]:
        try:
            proposal = dataset_compiler_service().propose_strongest_set(
                snapshot_id,
                target_count=request.target_count,
                disqualified_item_ids=request.disqualified_item_ids,
                included_item_ids=request.included_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return proposal.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/duplicates/propose")
    def propose_dataset_duplicates(snapshot_id: str) -> dict[str, object]:
        try:
            proposal = dataset_compiler_service().propose_duplicate_groups(
                snapshot_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return proposal.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/strongest-set/apply")
    def apply_dataset_strongest_set(
        snapshot_id: str,
        request: DatasetStrongestSetRequest,
    ) -> dict[str, object]:
        try:
            snapshot, proposal = dataset_compiler_service().apply_strongest_set(
                snapshot_id,
                target_count=request.target_count,
                disqualified_item_ids=request.disqualified_item_ids,
                included_item_ids=request.included_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        }

    @app.post("/dataset-snapshots/{snapshot_id}/strongest-set/restore")
    def restore_dataset_strongest_set(snapshot_id: str) -> dict[str, object]:
        try:
            snapshot = dataset_compiler_service().restore_strongest_set(snapshot_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.patch("/dataset-snapshots/{snapshot_id}/model-card")
    def update_dataset_model_card(
        snapshot_id: str,
        request: DatasetModelCardUpdateRequest,
    ) -> dict[str, object]:
        try:
            snapshot = dataset_compiler_service().update_model_card(
                snapshot_id,
                LoraModelCardOverrides.model_validate(
                    request.model_dump(exclude_unset=True)
                ),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/freeze")
    def freeze_dataset_snapshot(snapshot_id: str) -> dict[str, object]:
        try:
            snapshot = dataset_compiler_service().freeze_snapshot(snapshot_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/export/runcomfy")
    def export_dataset_snapshot_runcomfy(
        snapshot_id: str,
        request: DatasetSnapshotExportRequest,
    ) -> dict[str, object]:
        try:
            snapshot, package = dataset_compiler_service().export_runcomfy(
                snapshot_id,
                request.output_dir,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
        }

    @app.get("/training-runs")
    def list_training_runs(snapshot_id: str | None = None) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in training_run_service().list_runs(snapshot_id=snapshot_id)
        ]

    @app.get("/recovered-dataset-exports")
    def list_recovered_dataset_exports() -> list[dict[str, object]]:
        return [
            record.model_dump(mode="json")
            for record in recovered_dataset_service().list_exports()
        ]

    @app.post("/recovered-dataset-exports")
    def register_recovered_dataset_export(
        request: RecoveredDatasetRegisterRequest,
    ) -> dict[str, object]:
        try:
            record = recovered_dataset_service().register(request.export_path)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return record.model_dump(mode="json")

    @app.post("/recovered-dataset-exports/{record_id}/verify")
    def verify_recovered_dataset_export(record_id: str) -> dict[str, object]:
        try:
            record = recovered_dataset_service().verify(record_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Recovered dataset export not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return record.model_dump(mode="json")

    @app.get("/training-runs/{run_id}")
    def get_training_run(run_id: str) -> dict[str, object]:
        run = training_run_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Training run not found")
        return run.model_dump(mode="json")

    @app.post("/training-runs/runcomfy")
    def create_runcomfy_training_run(
        request: RunComfyTrainingRunRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            require_runcomfy_smoke(request.snapshot_id, request.config_file)
            token = resolve_runcomfy_token(request.api_token)
            service = training_run_service()
            run = service.create_run(
                snapshot_id=request.snapshot_id,
                config_file=request.config_file,
                gpu_type=request.gpu_type,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if run.status not in {"completed", "canceled"}:
            background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.post("/training-runs/{run_id}/refresh")
    def refresh_training_run(
        run_id: str,
        request: RunComfyTrainingActionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runcomfy_token(request.api_token)
            service = training_run_service()
            run = service.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Training run not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if run.status not in {"completed", "canceled"}:
            if run.status == "failed":
                run = service.prepare_retry(run.id)
                background_tasks.add_task(service.process_run, run.id, token)
            else:
                background_tasks.add_task(service.refresh_run, run.id, token)
        return run.model_dump(mode="json")

    @app.post("/training-runs/{run_id}/cancel")
    def cancel_training_run(
        run_id: str,
        request: RunComfyTrainingActionRequest,
    ) -> dict[str, object]:
        try:
            token = resolve_runcomfy_token(request.api_token)
            run = training_run_service().cancel_run(run_id, token)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Training run not found") from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/training-runs/{run_id}/resume")
    def resume_training_run(
        run_id: str,
        request: RunComfyTrainingActionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runcomfy_token(request.api_token)
            service = training_run_service()
            run = service.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status != "stopped":
                raise ValueError("only a stopped RunComfy training job can be resumed")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Training run not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.resume_run, run.id, token)
        return run.model_dump(mode="json")

    @app.get("/model-artifacts")
    def list_model_artifacts(snapshot_id: str | None = None) -> list[dict[str, object]]:
        return [
            artifact.model_dump(mode="json")
            for artifact in model_registry_service().list_artifacts(snapshot_id=snapshot_id)
        ]

    @app.get("/model-artifacts/release-candidates")
    def list_model_release_candidates(
        project_id: str,
        modality: Literal["image", "video", "voice", "audio_visual"] | None = None,
    ) -> list[dict[str, object]]:
        return [
            candidate.model_dump(mode="json")
            for candidate in model_registry_service().release_candidates(project_id, modality)
        ]

    @app.post("/model-artifacts/{artifact_id}/select-release")
    def select_model_release(artifact_id: str) -> dict[str, object]:
        try:
            artifact = model_registry_service().select_release(artifact_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Model artifact not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return artifact.model_dump(mode="json")

    @app.post("/training-runs/{run_id}/register-artifacts")
    def register_training_artifacts(run_id: str) -> list[dict[str, object]]:
        try:
            artifacts = model_registry_service().register_training_run(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Training run not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [artifact.model_dump(mode="json") for artifact in artifacts]

    @app.get("/comfyui/installations")
    def list_comfyui_installations() -> list[dict[str, object]]:
        return [installation.model_dump(mode="json") for installation in discover_comfy_installations()]

    @app.get("/comfyui/runtime-status")
    def get_comfyui_runtime_status(
        comfy_root: str = Query(...),
        base_url: str = Query(default="http://127.0.0.1:8188"),
    ) -> dict[str, object]:
        return inspect_comfy_runtime(
            Path(comfy_root),
            base_url=base_url,
        ).model_dump(mode="json")

    @app.get("/model-artifacts/{artifact_id}/comfyui-handoff")
    def preview_model_artifact_comfy_handoff(
        artifact_id: str,
        comfy_root: str = Query(...),
    ) -> dict[str, object]:
        try:
            handoff = model_registry_service().preview_comfy_handoff(
                artifact_id,
                Path(comfy_root),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Model artifact not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return handoff.model_dump(mode="json")

    @app.post("/model-artifacts/{artifact_id}/install")
    def install_model_artifact(
        artifact_id: str,
        request: ModelArtifactInstallRequest,
    ) -> dict[str, object]:
        try:
            artifact = model_registry_service().install_artifact(artifact_id, request.comfy_root)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Model artifact not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return artifact.model_dump(mode="json")

    @app.get("/comfyui/evaluation-reports")
    def list_comfyui_evaluation_reports(
        artifact_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            report.model_dump(mode="json")
            for report in comfy_evaluation_report_service().list_reports(
                artifact_id=artifact_id,
                project_id=project_id,
            )
        ]

    @app.post("/comfyui/evaluation-reports")
    def create_comfyui_evaluation_report(
        request: ComfyEvaluationReportRequest,
    ) -> dict[str, object]:
        artifact = model_registry_service().get_artifact(request.artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Model artifact not found")
        try:
            report = comfy_evaluation_report_service().record(
                request,
                project_id=artifact.project_id,
                expected_checkpoint_sha256=artifact.checkpoint_sha256,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return report.model_dump(mode="json")

    @app.get("/artifact-comparisons")
    def list_artifact_comparisons(
        project_id: str | None = None,
        benchmark_kind: Literal["image", "audio_visual"] | None = None,
    ) -> list[dict[str, object]]:
        return [
            comparison.model_dump(mode="json")
            for comparison in improvement_loop_service().list_comparisons(
                project_id=project_id,
                benchmark_kind=benchmark_kind,
            )
        ]

    @app.get("/artifact-comparisons/{comparison_id}")
    def get_artifact_comparison(comparison_id: str) -> dict[str, object]:
        comparison = improvement_loop_service().get_comparison(comparison_id)
        if comparison is None:
            raise HTTPException(status_code=404, detail="Artifact comparison not found")
        return comparison.model_dump(mode="json")

    @app.post("/artifact-comparisons")
    def create_artifact_comparison(
        request: ArtifactComparisonRequest,
    ) -> dict[str, object]:
        try:
            comparison = improvement_loop_service().create_comparison(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Model artifact not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return comparison.model_dump(mode="json")

    @app.post("/artifact-comparisons/{comparison_id}/improvement-request")
    def create_improvement_request(
        comparison_id: str,
    ) -> dict[str, object]:
        try:
            request = improvement_loop_service().create_request(comparison_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Artifact comparison not found") from error
        return request.model_dump(mode="json")

    @app.get("/improvement-requests")
    def list_improvement_requests(
        project_id: str | None = None,
        status: Literal["draft", "approved", "rejected"] | None = None,
    ) -> list[dict[str, object]]:
        return [
            request.model_dump(mode="json")
            for request in improvement_loop_service().list_requests(
                project_id=project_id,
                status=status,
            )
        ]

    @app.get("/improvement-requests/{request_id}")
    def get_improvement_request(request_id: str) -> dict[str, object]:
        request = improvement_loop_service().get_request(request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="Improvement request not found")
        return request.model_dump(mode="json")

    @app.patch("/improvement-requests/{request_id}")
    def decide_improvement_request(
        request_id: str,
        decision: ImprovementDecisionRequest,
    ) -> dict[str, object]:
        try:
            request = improvement_loop_service().decide_request(
                request_id,
                decision,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Improvement request not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return request.model_dump(mode="json")

    @app.get("/dataset-revisions")
    def list_dataset_revisions(
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            revision.model_dump(mode="json")
            for revision in improvement_loop_service().list_revisions(
                project_id=project_id,
            )
        ]

    @app.post("/improvement-requests/{request_id}/materialize-revision")
    def materialize_dataset_revision(
        request_id: str,
    ) -> dict[str, object]:
        try:
            revision = improvement_loop_service().materialize_revision(request_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Improvement request not found",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return revision.model_dump(mode="json")

    @app.get("/video-dataset/candidates")
    def list_video_dataset_candidates(
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            item.model_dump(mode="json")
            for item in video_dataset_service().candidate_media(project_id)
        ]

    @app.get("/video-dataset-snapshots")
    def list_video_dataset_snapshots(project_id: str | None = None) -> list[dict[str, object]]:
        return [
            snapshot.model_dump(mode="json")
            for snapshot in video_dataset_service().list_snapshots(project_id=project_id)
        ]

    @app.get("/video-dataset-snapshots/{snapshot_id}")
    def get_video_dataset_snapshot(snapshot_id: str) -> dict[str, object]:
        snapshot = video_dataset_service().get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found")
        return snapshot.model_dump(mode="json")

    @app.post("/video-dataset-snapshots/compile")
    def compile_video_dataset(request: VideoDatasetCompileRequest) -> dict[str, object]:
        try:
            snapshot = video_dataset_service().compile_project(
                request.project_id,
                media_item_ids=request.media_item_ids,
                target_profile_id=request.target_profile_id,
                reference_image_media_item_ids=request.reference_image_media_item_ids,
                reference_audio_media_item_ids=request.reference_audio_media_item_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.patch("/video-dataset-snapshots/{snapshot_id}/items/{item_id}")
    def update_video_dataset_item(
        snapshot_id: str,
        item_id: str,
        request: VideoDatasetItemUpdateRequest,
    ) -> dict[str, object]:
        try:
            snapshot = video_dataset_service().update_item(
                snapshot_id,
                item_id,
                caption=request.caption,
                status=request.status,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/video-dataset-snapshots/{snapshot_id}/bulk-status")
    def bulk_update_video_dataset(
        snapshot_id: str,
        request: VideoDatasetBulkStatusRequest,
    ) -> dict[str, object]:
        try:
            snapshot = video_dataset_service().bulk_status(snapshot_id, request.status)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/video-dataset-snapshots/{snapshot_id}/freeze")
    def freeze_video_dataset(snapshot_id: str) -> dict[str, object]:
        try:
            snapshot = video_dataset_service().freeze(snapshot_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return snapshot.model_dump(mode="json")

    @app.post("/video-dataset-snapshots/{snapshot_id}/export")
    def export_video_dataset(
        snapshot_id: str,
        request: VideoDatasetExportRequest,
    ) -> dict[str, object]:
        try:
            snapshot, package = video_dataset_service().export(snapshot_id, request.output_dir)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
        }

    @app.get("/id-lora-manifests")
    def list_id_lora_manifests(project_id: str | None = None) -> list[dict[str, object]]:
        return [
            manifest.model_dump(mode="json")
            for manifest in id_lora_dataset_service().list_manifests(project_id)
        ]

    @app.get("/id-lora-manifests/{manifest_id}")
    def get_id_lora_manifest(manifest_id: str) -> dict[str, object]:
        manifest = id_lora_dataset_service().get_manifest(manifest_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="ID-LoRA manifest not found")
        return manifest.model_dump(mode="json")

    @app.post("/id-lora-manifests/compile")
    def compile_id_lora_manifest(request: IdLoraCompileRequest) -> dict[str, object]:
        try:
            manifest = id_lora_dataset_service().compile_project(
                request.project_id,
                request.video_snapshot_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video dataset snapshot not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return manifest.model_dump(mode="json")

    @app.post("/id-lora-manifests/{manifest_id}/export")
    def export_id_lora_manifest(
        manifest_id: str,
        request: IdLoraExportRequest,
    ) -> dict[str, object]:
        try:
            manifest, package = id_lora_dataset_service().export(manifest_id, request.output_dir)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="ID-LoRA manifest not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "manifest": manifest.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
        }

    @app.get("/benchmark-suite")
    def get_benchmark_suite() -> list[dict[str, object]]:
        return [definition.model_dump(mode="json") for definition in default_benchmark_suite()]

    @app.get("/voice-artifact-evaluations")
    def list_voice_artifact_evaluations(project_id: str | None = None) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in voice_artifact_evaluation_service().list_runs(project_id)
        ]

    @app.get("/id-lora-evaluations")
    def list_id_lora_evaluations(project_id: str | None = None) -> list[dict[str, object]]:
        return [run.model_dump(mode="json") for run in id_lora_evaluation_service().list_runs(project_id)]

    @app.get("/id-lora-evaluations/{run_id}")
    def get_id_lora_evaluation(run_id: str) -> dict[str, object]:
        run = id_lora_evaluation_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ID-LoRA evaluation run not found")
        return run.model_dump(mode="json")

    @app.post("/id-lora-evaluations")
    def create_id_lora_evaluation(
        request: IdLoraEvaluationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = id_lora_evaluation_service()
        try:
            run = service.create_run(request.runpod_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RunPod inference run not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if run.status not in {"complete", "failed"}:
            background_tasks.add_task(service.process_run, run.id)
        return run.model_dump(mode="json")

    @app.get("/voice-artifact-evaluations/recommended")
    def get_recommended_voice_artifact_evaluation(project_id: str) -> dict[str, object] | None:
        run = voice_artifact_evaluation_service().recommended_run(project_id)
        return run.model_dump(mode="json") if run else None

    @app.get("/voice-artifact-evaluations/{run_id}")
    def get_voice_artifact_evaluation(run_id: str) -> dict[str, object]:
        run = voice_artifact_evaluation_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Voice evaluation run not found")
        return run.model_dump(mode="json")

    @app.post("/voice-artifact-evaluations")
    def create_voice_artifact_evaluation(
        request: VoiceArtifactEvaluationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = voice_artifact_evaluation_service()
        try:
            run = service.create_run(
                project_id=request.project_id,
                artifact_id=request.artifact_id,
                samples_dir=request.samples_dir,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id)
        return run.model_dump(mode="json")

    @app.post("/voice-artifact-evaluations/{run_id}/select")
    def select_voice_artifact_evaluation(run_id: str) -> dict[str, object]:
        try:
            run = voice_artifact_evaluation_service().select_for_release(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Voice evaluation run not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/benchmark-suite/prepare")
    def prepare_benchmark_workspace(request: BenchmarkWorkspaceRequest) -> dict[str, object]:
        try:
            workspace = evaluation_harness_service().prepare_workspace(
                request.project_id,
                request.output_dir,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except OSError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return workspace.model_dump(mode="json")

    @app.get("/benchmark-generation-runs")
    def list_benchmark_generation_runs(
        project_id: str | None = None,
        benchmark_kind: Literal["audio_visual", "image"] | None = None,
    ) -> list[dict[str, object]]:
        return [
            run.model_dump(mode="json")
            for run in benchmark_generation_service().list_runs(project_id, benchmark_kind)
        ]

    @app.get("/benchmark-generation-runs/{run_id}")
    def get_benchmark_generation_run(run_id: str) -> dict[str, object]:
        run = benchmark_generation_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Benchmark generation run not found")
        return run.model_dump(mode="json")

    @app.post("/benchmark-generation-runs/{run_id}/retry")
    def retry_benchmark_generation_run(
        run_id: str,
        request: BenchmarkGenerationRetryRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = benchmark_generation_service()
        source = service.get_run(run_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Benchmark generation run not found")
        try:
            token = resolve_runpod_token(request.api_token) if source.provider == "runpod_serverless" else resolve_runcomfy_model_token(request.api_token)
            run = service.create_retry_run(run_id, request.case_ids)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.post("/benchmark-generation-runs/runcomfy")
    def create_benchmark_generation_run(
        request: BenchmarkGenerationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runcomfy_model_token(request.api_token)
            service = benchmark_generation_service()
            run = service.create_run(
                project_id=request.project_id,
                workspace_root=request.workspace_root,
                model_id=request.model_id,
                lora_path=request.lora_path,
                provider="runcomfy_model_api",
                benchmark_kind="audio_visual",
                artifact_id=request.artifact_id,
                baseline_payload=request.baseline_payload,
                lora_payload=request.lora_payload,
                seed_base=request.seed_base,
                auto_evaluate=request.auto_evaluate,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.post("/benchmark-generation-runs/runpod")
    def create_runpod_benchmark_generation_run(
        request: BenchmarkGenerationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            service = benchmark_generation_service()
            run = service.create_run(
                project_id=request.project_id,
                workspace_root=request.workspace_root,
                model_id=request.model_id,
                endpoint_id=request.endpoint_id,
                lora_path=request.lora_path,
                provider="runpod_serverless",
                benchmark_kind="audio_visual",
                artifact_id=request.artifact_id,
                baseline_payload=request.baseline_payload,
                lora_payload=request.lora_payload,
                seed_base=request.seed_base,
                auto_evaluate=request.auto_evaluate,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.get("/image-benchmark-suite")
    def get_image_benchmark_suite() -> list[dict[str, object]]:
        return [definition.model_dump(mode="json") for definition in default_image_benchmark_suite()]

    @app.post("/image-benchmark-suite/prepare")
    def prepare_image_benchmark_workspace(request: BenchmarkWorkspaceRequest) -> dict[str, object]:
        try:
            workspace = image_evaluation_harness_service().prepare_workspace(
                request.project_id,
                request.output_dir,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except OSError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return workspace.model_dump(mode="json")

    @app.post("/image-benchmark-generation-runs/runcomfy")
    def create_runcomfy_image_benchmark_generation_run(
        request: BenchmarkGenerationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runcomfy_model_token(request.api_token)
            service = benchmark_generation_service()
            run = service.create_run(
                project_id=request.project_id,
                workspace_root=request.workspace_root,
                model_id=request.model_id,
                lora_path=request.lora_path,
                provider="runcomfy_model_api",
                benchmark_kind="image",
                artifact_id=request.artifact_id,
                baseline_payload=request.baseline_payload,
                lora_payload=request.lora_payload,
                seed_base=request.seed_base,
                auto_evaluate=request.auto_evaluate,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.post("/image-benchmark-generation-runs/runpod")
    def create_runpod_image_benchmark_generation_run(
        request: BenchmarkGenerationRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            token = resolve_runpod_token(request.api_token)
            service = benchmark_generation_service()
            run = service.create_run(
                project_id=request.project_id,
                workspace_root=request.workspace_root,
                model_id=request.model_id,
                endpoint_id=request.endpoint_id,
                lora_path=request.lora_path,
                provider="runpod_serverless",
                benchmark_kind="image",
                artifact_id=request.artifact_id,
                baseline_payload=request.baseline_payload,
                lora_payload=request.lora_payload,
                seed_base=request.seed_base,
                auto_evaluate=request.auto_evaluate,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id, token)
        return run.model_dump(mode="json")

    @app.get("/image-benchmark-runs")
    def list_image_benchmark_runs(project_id: str | None = None) -> list[dict[str, object]]:
        return [run.model_dump(mode="json") for run in image_evaluation_harness_service().list_runs(project_id)]

    @app.get("/image-benchmark-runs/{run_id}")
    def get_image_benchmark_run(run_id: str) -> dict[str, object]:
        run = image_evaluation_harness_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Image benchmark run not found")
        return run.model_dump(mode="json")

    @app.post("/image-benchmark-runs")
    def create_image_benchmark_run(
        request: BenchmarkRunRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = image_evaluation_harness_service()
        try:
            run = service.create_run(
                project_id=request.project_id,
                baseline_dir=request.baseline_dir,
                lora_dir=request.lora_dir,
                artifact_id=request.artifact_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id)
        return run.model_dump(mode="json")

    @app.get("/benchmark-runs")
    def list_benchmark_runs(project_id: str | None = None) -> list[dict[str, object]]:
        return [run.model_dump(mode="json") for run in evaluation_harness_service().list_runs(project_id)]

    @app.get("/benchmark-runs/{run_id}")
    def get_benchmark_run(run_id: str) -> dict[str, object]:
        run = evaluation_harness_service().get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Benchmark run not found")
        return run.model_dump(mode="json")

    @app.post("/benchmark-runs")
    def create_benchmark_run(
        request: BenchmarkRunRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = evaluation_harness_service()
        try:
            run = service.create_run(
                project_id=request.project_id,
                baseline_dir=request.baseline_dir,
                lora_dir=request.lora_dir,
                artifact_id=request.artifact_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_run, run.id)
        return run.model_dump(mode="json")

    @app.patch("/benchmark-runs/{run_id}/cases/{case_id}/review")
    def review_benchmark_case(
        run_id: str,
        case_id: str,
        request: BenchmarkCaseReviewRequest,
    ) -> dict[str, object]:
        try:
            run = evaluation_harness_service().review_case(
                run_id,
                case_id,
                request.decision,
                request.note,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Benchmark run or case not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run.model_dump(mode="json")

    @app.post("/dataset-snapshots/{snapshot_id}/caption-jobs")
    def create_caption_generation_job(
        snapshot_id: str,
        request: CaptionGenerationJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        auth_mode = auth_mode_for_provider(request.provider_id)
        api_key = (
            resolve_api_key(request.provider_id, request.api_key)
            if auth_mode == VisionProviderAuthMode.API_KEY
            else ""
        )
        config = VisionProviderConfig(
            provider_id=request.provider_id,
            provider_label=request.provider_label,
            dialect=request.dialect,
            base_url=request.base_url,
            model=request.model.strip(),
            api_key=api_key,
            auth_mode=auth_mode,
        )
        service = caption_generation_service()
        try:
            job = service.create_job(
                snapshot_id=snapshot_id,
                item_ids=request.item_ids,
                config=config,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset snapshot not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        background_tasks.add_task(service.process_job, job.id, config)
        return job.model_dump(mode="json")

    return app


def _validated_vault_asset_path(path: Path, vault_root: Path) -> Path | None:
    try:
        resolved_path = Path(path).resolve(strict=True)
        resolved_vault = Path(vault_root).resolve(strict=True)
    except OSError:
        return None

    if not resolved_path.is_file() or not resolved_path.is_relative_to(resolved_vault):
        return None
    return resolved_path


def _safe_upload_relative_path(filename: str | None) -> Path:
    raw_filename = (filename or f"upload-{uuid4().hex}").replace("\\", "/")
    pure_path = PurePosixPath(raw_filename)
    safe_parts = [
        part
        for part in pure_path.parts
        if part not in {"", ".", "..", "/"} and "\x00" not in part and not part.endswith(":")
    ]
    if not safe_parts:
        return Path(f"upload-{uuid4().hex}")
    return Path(*safe_parts)


def _unique_upload_path(upload_root: Path, relative_path: Path) -> Path:
    target_path = upload_root / relative_path
    if not target_path.exists():
        return target_path

    counter = 2
    while True:
        candidate = target_path.with_name(
            f"{target_path.stem}-{counter}{target_path.suffix}"
        )
        if not candidate.exists():
            return candidate
        counter += 1
