import type { PreparationCheckpoint } from "./types";
import type { WorkspacePreference, WorkspaceSession } from "./workspace";
import type {
  AudioCleaningRecipe,
  AudioCleaningResult,
  AudioSeparationRuntimeStatus,
  CharacterProject,
  CropKind,
  CropRecipeStatus,
  CreateIngressJobRequest,
  CreateProcessingJobRequest,
  ExportPackage,
  InstagramScanMode,
  IdentityRuntimeStatus,
  IngressJob,
  IngressCandidateAnalysisResponse,
  IngressScanResult,
  LocalImportResponse,
  MediaItem,
  NormalizedRect,
  ProcessingJob,
  RequestedOutput,
  SpeakerConfirmation,
  SourceKind,
  TrainingIntent,
  DatasetReviewStatus,
  DatasetItemStatus,
  DatasetSnapshot,
  DatasetExportResponse,
  DatasetStrongestSetApplyResponse,
  DatasetStrongestSetProposal,
  DatasetDuplicateProposal,
  DatasetView,
  CaptionGenerationJob,
  CaptionGenerationRequest,
  ClearAllMediaResult,
  CurationHandoff,
  CurationReviewStatus,
  CurationSourceBundle,
  VisionProviderPreset,
  VideoBreakdownCommitRequest,
  VoiceIdentityProfile,
  VoiceSampleConfirmationResult,
  VoiceDatasetCompilation,
  VoiceDatasetExportResponse,
  VoiceExportTarget,
  VoiceSegmentStatus,
  CreateTrainingRunRequest,
  TrainingRun,
  TrainingTargetProfile,
  TrainingCostEstimate,
  TrainingEstimateRequest,
  ModelIntentRecipe,
  LoraModelCardOverrides,
  ModelArtifactRecord,
  ArtifactReleaseCandidate,
  VoiceArtifactEvaluationRun,
  CreateVoiceArtifactEvaluationRequest,
  IdLoraEvaluationRun,
  ComfyInstallation,
  ComfyRuntimeStatus,
  ComfyEvaluationReport,
  ComfyHandoffManifest,
  ArtifactComparison,
  ImprovementRequest,
  DatasetRevisionRecord,
  VideoDatasetSnapshot,
  VideoDatasetItemStatus,
  VideoDatasetExportResponse,
  IdLoraManifest,
  IdLoraExportResponse,
  BenchmarkCaseDefinition,
  BenchmarkRun,
  BenchmarkWorkspace,
  BenchmarkGenerationRun,
  CreateBenchmarkGenerationRequest,
  CreateRunPodBenchmarkGenerationRequest,
  ImageBenchmarkCaseDefinition,
  ImageBenchmarkRun,
  ImageBenchmarkWorkspace,
  RunPodBundle,
  CreateRunPodBundleRequest,
  RunPodTrainingRun,
  RunPodPreflightReport,
  CreateRunPodPreflightRequest,
  RunPodBundleUploadJob,
  CreateRunPodBundleUploadRequest,
  CreateRunPodTrainingRunRequest,
  RunPodArtifactDownloadRequest,
  TrainingWorkflowStatus,
  SyncNetCapability,
  ProviderReadinessMatrix,
  PartnerQualificationReport,
  CloudProviderDescriptor,
  CloudRunRecord,
  RunPodInfrastructureProfile,
  ProvisionRunPodInfrastructureRequest,
  RunPodModelBootstrapRun,
  CreateRunPodModelBootstrapRequest,
  ProviderSmokeRun,
  RecoveredDatasetExport,
  StateMigrationReport,
  DiagnosticBundleRecord,
  ExactDuplicateCluster,
  SocialAcquisitionJob,
  SocialAcquisitionRequest,
  VaultMediaPage,
} from "./types";
import type { LibraryArtifactOptions, LibraryCatalog, LibraryCategory, LibraryEntry, LibraryStatus, LibraryTrainingExport } from "./library";
import {
  credentialIdForVisionProvider,
  resolveCredential,
} from "./credentials";

interface EngineResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
  text?(): Promise<string>;
}

type FetchLike = (input: string, init: RequestInit) => Promise<EngineResponse>;

export interface ThemePreference { theme: string | null; updated_at: number }

export interface EngineClient {
  getThemePreference(): Promise<ThemePreference>;
  setThemePreference(theme: string, onlyIfUnset?: boolean): Promise<ThemePreference>;
  libraryStatus(): Promise<LibraryStatus>;
  listLibraryModels(category: LibraryCategory, page: number, search: string): Promise<LibraryCatalog>;
  exportArtifactToLibrary(artifactId: string, options?: LibraryArtifactOptions): Promise<LibraryTrainingExport>;
  configureLibrary(port: number): Promise<{ port: number }>;
  createCompanionCode(): Promise<{ code: string; expires_in: number }>;
  revokeCompanion(): Promise<{ revoked: boolean }>;
  importLibraryFile(id: string, path: string, modelType: string): Promise<LibraryEntry>;
  archiveLibraryEntry(id: string, archived: boolean): Promise<LibraryEntry>;
  pickDirectory?(): Promise<{ path: string | null }>;
  importLocal(paths: string[]): Promise<LocalImportResponse>;
  listVaultMedia(): Promise<MediaItem[]>;
  listVaultMediaPage?(options?: {
    offset?: number;
    limit?: number;
    mediaType?: MediaItem["media_type"];
    status?: string;
    search?: string;
    includeIgnored?: boolean;
    snapshot?: string;
  }): Promise<VaultMediaPage>;
  listExactDuplicateClusters(): Promise<ExactDuplicateCluster[]>;
  clearAllMedia(confirmation: string): Promise<ClearAllMediaResult>;
  rotateVaultImage(mediaItemId: string, degrees?: 90 | 180 | 270): Promise<MediaItem>;
  listCurationBundles(): Promise<CurationSourceBundle[]>;
  getCurationHandoff(
    projectId?: string,
    requestedOutput?: RequestedOutput,
  ): Promise<CurationHandoff>;
  addCurationHandoff(
    mediaItemIds: string[],
    projectId?: string,
    requestedOutput?: RequestedOutput,
  ): Promise<CurationHandoff>;
  rejectCurationMedia(mediaItemIds: string[]): Promise<MediaItem[]>;
  restoreCurationAudio(mediaItemIds: string[]): Promise<MediaItem[]>;
  createCurationAnalysisJob(mediaItemIds: string[]): Promise<ProcessingJob>;
  getAudioCleaningRecipe(mediaItemId: string): Promise<AudioCleaningRecipe>;
  previewAudioCleaning(
    mediaItemId: string,
    recipe: AudioCleaningRecipe,
  ): Promise<AudioCleaningResult>;
  renderAudioCleaning(
    mediaItemId: string,
    recipe: AudioCleaningRecipe,
  ): Promise<AudioCleaningResult>;
  getAudioSeparationStatus(): Promise<AudioSeparationRuntimeStatus>;
  installAudioSeparationModel(): Promise<AudioSeparationRuntimeStatus>;
  createAudioCleaningJob(
    mediaItemIds: string[],
    forceVoiceIsolation?: boolean,
  ): Promise<ProcessingJob>;
  updateCurationReview(
    mediaItemId: string,
    reviewStatus: CurationReviewStatus,
    projectId?: string,
    requestedOutput?: RequestedOutput,
    speakerConfirmation?: SpeakerConfirmation,
  ): Promise<CurationHandoff>;
  getIdentityStatus(): Promise<IdentityRuntimeStatus>;
  installIdentityModels(): Promise<IdentityRuntimeStatus>;
  getVoiceIdentityStatus(): Promise<IdentityRuntimeStatus>;
  installVoiceIdentityModel(): Promise<IdentityRuntimeStatus>;
  getVoiceIdentityProfile(projectId: string): Promise<VoiceIdentityProfile>;
  setVoiceIdentityAnchors(
    projectId: string,
    mediaItemIds: string[],
  ): Promise<VoiceIdentityProfile>;
  confirmVoiceIdentitySample(
    projectId: string,
    mediaItemId: string,
    subjectLabel: string,
    requestedOutput?: RequestedOutput,
  ): Promise<VoiceSampleConfirmationResult>;
  analyzeVoiceIdentity(
    projectId: string,
    mediaItemIds: string[],
  ): Promise<VoiceIdentityProfile>;
  getVoiceDataset(projectId: string): Promise<VoiceDatasetCompilation>;
  compileVoiceDataset(
    projectId: string,
    mediaItemIds: string[],
  ): Promise<VoiceDatasetCompilation>;
  updateVoiceDatasetSegment(
    projectId: string,
    segmentId: string,
    update: { status?: VoiceSegmentStatus; transcript?: string },
  ): Promise<VoiceDatasetCompilation>;
  bulkUpdateVoiceDatasetSegments(
    projectId: string,
    decisions: Record<string, VoiceSegmentStatus>,
  ): Promise<VoiceDatasetCompilation>;
  rescoreVoiceDataset(projectId: string): Promise<VoiceDatasetCompilation>;
  analyzeVoiceDatasetQuality(projectId: string): Promise<VoiceDatasetCompilation>;
  exportVoiceDataset(
    projectId: string,
    outputDir: string,
    target?: VoiceExportTarget,
  ): Promise<VoiceDatasetExportResponse>;
  scanLocalIngress(roots: string[], recursive?: boolean): Promise<IngressScanResult>;
  uploadLocalIngress(files: File[]): Promise<IngressScanResult>;
  scanInstagramHelperPayload(
    payload: Record<string, unknown>,
    includeVideoPostersAsImageCandidates?: boolean,
  ): Promise<IngressScanResult>;
  scanInstagramBrowserUrl(
    url: string,
    browser?: string,
    limit?: number,
    cursor?: string,
    scanMode?: InstagramScanMode,
    dateFrom?: string,
    dateTo?: string,
  ): Promise<IngressScanResult>;
  scanXBrowserUrl?(
    url: string,
    browser?: string,
    limit?: number,
    cursor?: string,
    dateFrom?: string,
    dateTo?: string,
  ): Promise<IngressScanResult>;
  scanTikTokBrowserUrl?(
    url: string,
    browser?: string,
    limit?: number,
    cursor?: string,
    dateFrom?: string,
    dateTo?: string,
  ): Promise<IngressScanResult>;
  createSocialAcquisitionJob?(
    request: SocialAcquisitionRequest,
  ): Promise<SocialAcquisitionJob>;
  listSocialAcquisitionJobs?(): Promise<SocialAcquisitionJob[]>;
  getSocialAcquisitionJob?(jobId: string): Promise<SocialAcquisitionJob>;
  resumeSocialAcquisitionJob?(jobId: string): Promise<SocialAcquisitionJob>;
  cancelSocialAcquisitionJob?(jobId: string): Promise<SocialAcquisitionJob>;
  listIngressCandidates(sourceKind?: SourceKind): Promise<IngressScanResult>;
  ingressCandidateVideoPreviewUrl(candidateId: string): string;
  ingressCandidateThumbnailUrl(candidateId: string): string;
  analyzeIngressCandidates(
    candidateIds: string[],
    target: "image" | "video" | "voice" | "id_lora",
  ): Promise<IngressCandidateAnalysisResponse>;
  createIngressJob(request: CreateIngressJobRequest): Promise<IngressJob>;
  listIngressJobs(): Promise<IngressJob[]>;
  getIngressJob(jobId: string): Promise<IngressJob>;
  createProcessingJob(request: CreateProcessingJobRequest): Promise<ProcessingJob>;
  listProcessingJobs(): Promise<ProcessingJob[]>;
  getProcessingJob(jobId: string): Promise<ProcessingJob>;
  processProcessingJob(jobId: string): Promise<ProcessingJob>;
  updateVideoKeepers(jobId: string, frameIds: string[]): Promise<ProcessingJob>;
  commitVideoBreakdown(
    jobId: string,
    request: VideoBreakdownCommitRequest,
  ): Promise<ProcessingJob>;
  listCharacterProjects(): Promise<CharacterProject[]>;
  createCharacterProject(name?: string, intent?: TrainingIntent): Promise<CharacterProject>;
  getCharacterProject(projectId: string): Promise<CharacterProject>;
  updateCharacterProject(
    projectId: string,
    update: { name?: string; intent?: TrainingIntent },
  ): Promise<CharacterProject>;
  addCharacterProjectCandidates(
    projectId: string,
    mediaItemIds: string[],
  ): Promise<CharacterProject>;
  setCharacterProjectAnchors(
    projectId: string,
    mediaItemIds: string[],
  ): Promise<CharacterProject>;
  updateCharacterProjectObservation(
    projectId: string,
    mediaItemId: string,
    update: { review_status: DatasetReviewStatus; view?: DatasetView },
  ): Promise<CharacterProject>;
  analyzeCharacterProject(projectId: string): Promise<CharacterProject>;
  selectCharacterProjectFace(
    projectId: string,
    mediaItemId: string,
    faceIndex: number,
  ): Promise<CharacterProject>;
  updateCharacterProjectCrop(
    projectId: string,
    recipeId: string,
    update: { rect?: NormalizedRect; status?: CropRecipeStatus; kind?: CropKind },
  ): Promise<CharacterProject>;
  materializeCharacterProjectCrop(
    projectId: string,
    recipeId: string,
  ): Promise<{ project: CharacterProject; media_item: MediaItem }>;
  listDatasetSnapshots(projectId?: string): Promise<DatasetSnapshot[]>;
  getDatasetSnapshot(snapshotId: string): Promise<DatasetSnapshot>;
  listTrainingTargets(): Promise<TrainingTargetProfile[]>;
  listRecoveredDatasetExports?(): Promise<RecoveredDatasetExport[]>;
  registerRecoveredDatasetExport?(exportPath: string): Promise<RecoveredDatasetExport>;
  verifyRecoveredDatasetExport?(recordId: string): Promise<RecoveredDatasetExport>;
  inspectStateMigrations?(): Promise<StateMigrationReport>;
  applyStateMigrations?(): Promise<StateMigrationReport>;
  listDiagnosticBundles?(): Promise<DiagnosticBundleRecord[]>;
  createDiagnosticBundle?(request?: { comfy_root?: string; comfy_base_url?: string; project_id?: string }): Promise<DiagnosticBundleRecord>;
  diagnosticBundleDownloadUrl?(bundleId: string): string;
  estimateTraining?(request: TrainingEstimateRequest): Promise<TrainingCostEstimate>;
  listModelIntentRecipes?(): Promise<ModelIntentRecipe[]>;
  compileCharacterDataset(
    projectId: string,
    trainingTargetProfileId?: string,
  ): Promise<DatasetSnapshot>;
  updateDatasetItem(
    snapshotId: string,
    itemId: string,
    update: { caption?: string; tags?: string[]; status?: DatasetItemStatus },
  ): Promise<DatasetSnapshot>;
  updateDatasetModelCard?(
    snapshotId: string,
    update: LoraModelCardOverrides,
  ): Promise<DatasetSnapshot>;
  bulkUpdateDatasetItems(
    snapshotId: string,
    status: DatasetItemStatus,
    itemIds?: string[],
  ): Promise<DatasetSnapshot>;
  proposeDatasetStrongestSet(
    snapshotId: string,
    targetCount?: number,
    disqualifiedItemIds?: string[],
    includedItemIds?: string[],
  ): Promise<DatasetStrongestSetProposal>;
  proposeDatasetDuplicates(
    snapshotId: string,
  ): Promise<DatasetDuplicateProposal>;
  applyDatasetStrongestSet(
    snapshotId: string,
    targetCount?: number,
    disqualifiedItemIds?: string[],
    includedItemIds?: string[],
  ): Promise<DatasetStrongestSetApplyResponse>;
  restoreDatasetStrongestSet(snapshotId: string): Promise<DatasetSnapshot>;
  freezeDatasetSnapshot(snapshotId: string): Promise<DatasetSnapshot>;
  exportDatasetSnapshotRunComfy(
    snapshotId: string,
    outputDir: string,
  ): Promise<DatasetExportResponse>;
  listTrainingRuns(snapshotId?: string): Promise<TrainingRun[]>;
  getTrainingRun(runId: string): Promise<TrainingRun>;
  createTrainingRun(request: CreateTrainingRunRequest): Promise<TrainingRun>;
  refreshTrainingRun(runId: string, apiToken?: string): Promise<TrainingRun>;
  resumeTrainingRun(runId: string, apiToken?: string): Promise<TrainingRun>;
  cancelTrainingRun(runId: string, apiToken?: string): Promise<TrainingRun>;
  listModelArtifacts(snapshotId?: string): Promise<ModelArtifactRecord[]>;
  listModelReleaseCandidates(projectId: string, modality?: ModelArtifactRecord["modality"]): Promise<ArtifactReleaseCandidate[]>;
  selectModelRelease(artifactId: string): Promise<ModelArtifactRecord>;
  registerTrainingArtifacts(runId: string): Promise<ModelArtifactRecord[]>;
  listComfyInstallations(): Promise<ComfyInstallation[]>;
  getComfyRuntimeStatus(comfyRoot: string, baseUrl?: string): Promise<ComfyRuntimeStatus>;
  previewModelArtifactComfyHandoff?(artifactId: string, comfyRoot: string): Promise<ComfyHandoffManifest>;
  installModelArtifact(artifactId: string, comfyRoot: string): Promise<ModelArtifactRecord>;
  listComfyEvaluationReports?(filters?: { artifactId?: string; projectId?: string }): Promise<ComfyEvaluationReport[]>;
  listArtifactComparisons?(filters?: { projectId?: string; benchmarkKind?: "image" | "audio_visual" }): Promise<ArtifactComparison[]>;
  createArtifactComparison?(request: { project_id: string; benchmark_kind: "image" | "audio_visual"; candidate_artifact_id: string; reference_artifact_id?: string }): Promise<ArtifactComparison>;
  listImprovementRequests?(filters?: { projectId?: string; status?: "draft" | "approved" | "rejected" }): Promise<ImprovementRequest[]>;
  createImprovementRequest?(comparisonId: string): Promise<ImprovementRequest>;
  decideImprovementRequest?(requestId: string, decision: "approved" | "rejected", note?: string): Promise<ImprovementRequest>;
  listDatasetRevisions?(projectId?: string): Promise<DatasetRevisionRecord[]>;
  materializeDatasetRevision?(requestId: string): Promise<DatasetRevisionRecord>;
  listVideoDatasetCandidates(projectId?: string): Promise<MediaItem[]>;
  listVideoDatasetSnapshots(projectId?: string): Promise<VideoDatasetSnapshot[]>;
  getVideoDatasetSnapshot(snapshotId: string): Promise<VideoDatasetSnapshot>;
  compileVideoDataset(projectId: string, mediaItemIds?: string[], targetProfileId?: string, referenceImageMediaItemIds?: string[], referenceAudioMediaItemIds?: string[]): Promise<VideoDatasetSnapshot>;
  updateVideoDatasetItem(snapshotId: string, itemId: string, update: { caption?: string; status?: VideoDatasetItemStatus }): Promise<VideoDatasetSnapshot>;
  bulkUpdateVideoDataset(snapshotId: string, status: "approved" | "excluded"): Promise<VideoDatasetSnapshot>;
  freezeVideoDataset(snapshotId: string): Promise<VideoDatasetSnapshot>;
  exportVideoDataset(snapshotId: string, outputDir: string): Promise<VideoDatasetExportResponse>;
  listIdLoraManifests(projectId?: string): Promise<IdLoraManifest[]>;
  getIdLoraManifest(manifestId: string): Promise<IdLoraManifest>;
  compileIdLoraManifest(projectId: string, videoSnapshotId?: string): Promise<IdLoraManifest>;
  exportIdLoraManifest(manifestId: string, outputDir: string): Promise<IdLoraExportResponse>;
  getBenchmarkSuite(): Promise<BenchmarkCaseDefinition[]>;
  getSyncNetCapability(): Promise<SyncNetCapability>;
  prepareBenchmarkWorkspace(projectId: string, outputDir: string): Promise<BenchmarkWorkspace>;
  listBenchmarkGenerationRuns(projectId?: string, benchmarkKind?: "audio_visual" | "image"): Promise<BenchmarkGenerationRun[]>;
  getBenchmarkGenerationRun(runId: string): Promise<BenchmarkGenerationRun>;
  retryBenchmarkGenerationRun(runId: string, caseIds: string[], apiToken?: string): Promise<BenchmarkGenerationRun>;
  createBenchmarkGenerationRun(request: CreateBenchmarkGenerationRequest): Promise<BenchmarkGenerationRun>;
  createRunPodBenchmarkGenerationRun(request: CreateRunPodBenchmarkGenerationRequest): Promise<BenchmarkGenerationRun>;
  getImageBenchmarkSuite(): Promise<ImageBenchmarkCaseDefinition[]>;
  prepareImageBenchmarkWorkspace(projectId: string, outputDir: string): Promise<ImageBenchmarkWorkspace>;
  createImageBenchmarkGenerationRun(request: CreateBenchmarkGenerationRequest): Promise<BenchmarkGenerationRun>;
  createRunPodImageBenchmarkGenerationRun(request: CreateRunPodBenchmarkGenerationRequest): Promise<BenchmarkGenerationRun>;
  listImageBenchmarkRuns(projectId?: string): Promise<ImageBenchmarkRun[]>;
  getImageBenchmarkRun(runId: string): Promise<ImageBenchmarkRun>;
  createImageBenchmarkRun(request: { project_id: string; baseline_dir: string; lora_dir: string; artifact_id?: string }): Promise<ImageBenchmarkRun>;
  createRunPodBundle(request: CreateRunPodBundleRequest): Promise<RunPodBundle>;
  listProviderSmokeRuns?(filters?: { projectId?: string; provider?: "runcomfy" | "runpod"; trainingTargetProfileId?: string; bundleId?: string }): Promise<ProviderSmokeRun[]>;
  createRunComfyProviderSmokeRun?(request: { project_id: string; source_export_path: string; training_target_profile_id: string; config_file: string }): Promise<ProviderSmokeRun>;
  createRunPodProviderSmokeRun?(bundleId: string): Promise<ProviderSmokeRun>;
  listRunPodInfrastructureProfiles(): Promise<RunPodInfrastructureProfile[]>;
  provisionRunPodInfrastructure(request: ProvisionRunPodInfrastructureRequest): Promise<RunPodInfrastructureProfile>;
  listRunPodModelBootstrapRuns(endpointId?: string, trainingTargetProfileId?: string): Promise<RunPodModelBootstrapRun[]>;
  getRunPodModelBootstrapRun(runId: string): Promise<RunPodModelBootstrapRun>;
  createRunPodModelBootstrapRun(request: CreateRunPodModelBootstrapRequest): Promise<RunPodModelBootstrapRun>;
  refreshRunPodModelBootstrapRun(runId: string, apiToken?: string): Promise<RunPodModelBootstrapRun>;
  cancelRunPodModelBootstrapRun(runId: string, apiToken?: string): Promise<RunPodModelBootstrapRun>;
  listRunPodBundles(sourceExportPath?: string, trainingTargetProfileId?: string, projectId?: string): Promise<RunPodBundle[]>;
  listRunPodBundleUploadJobs(bundlePath?: string): Promise<RunPodBundleUploadJob[]>;
  getRunPodBundleUploadJob(jobId: string): Promise<RunPodBundleUploadJob>;
  createRunPodBundleUploadJob(request: CreateRunPodBundleUploadRequest): Promise<RunPodBundleUploadJob>;
  resumeRunPodBundleUploadJob(jobId: string, accessKey?: string, secretKey?: string): Promise<RunPodBundleUploadJob>;
  listRunPodPreflightReports(bundlePath?: string, endpointId?: string): Promise<RunPodPreflightReport[]>;
  createRunPodPreflightReport(request: CreateRunPodPreflightRequest): Promise<RunPodPreflightReport>;
  listRunPodTrainingRuns(bundlePath?: string): Promise<RunPodTrainingRun[]>;
  getRunPodTrainingRun(runId: string): Promise<RunPodTrainingRun>;
  createRunPodTrainingRun(request: CreateRunPodTrainingRunRequest): Promise<RunPodTrainingRun>;
  refreshRunPodTrainingRun(runId: string, apiToken?: string): Promise<RunPodTrainingRun>;
  cancelRunPodTrainingRun(runId: string, apiToken?: string): Promise<RunPodTrainingRun>;
  downloadRunPodTrainingArtifacts(runId: string, request: RunPodArtifactDownloadRequest): Promise<RunPodTrainingRun>;
  registerRunPodTrainingArtifacts(runId: string): Promise<ModelArtifactRecord[]>;
  listVoiceArtifactEvaluations(projectId?: string): Promise<VoiceArtifactEvaluationRun[]>;
  getVoiceArtifactEvaluation(runId: string): Promise<VoiceArtifactEvaluationRun>;
  getRecommendedVoiceArtifactEvaluation(projectId: string): Promise<VoiceArtifactEvaluationRun | null>;
  createVoiceArtifactEvaluation(request: CreateVoiceArtifactEvaluationRequest): Promise<VoiceArtifactEvaluationRun>;
  selectVoiceArtifactEvaluation(runId: string): Promise<VoiceArtifactEvaluationRun>;
  listIdLoraEvaluations(projectId?: string): Promise<IdLoraEvaluationRun[]>;
  getIdLoraEvaluation(runId: string): Promise<IdLoraEvaluationRun>;
  createIdLoraEvaluation(runpodRunId: string): Promise<IdLoraEvaluationRun>;
  getTrainingWorkflow(projectId: string): Promise<TrainingWorkflowStatus>;
  getProviderReadiness(projectId: string): Promise<ProviderReadinessMatrix>;
  getPartnerQualificationReport?(projectId: string): Promise<PartnerQualificationReport>;
  listCloudProviders?(): Promise<CloudProviderDescriptor[]>;
  listCloudRuns?(projectId?: string, provider?: "runcomfy" | "runpod"): Promise<CloudRunRecord[]>;
  listBenchmarkRuns(projectId?: string): Promise<BenchmarkRun[]>;
  getBenchmarkRun(runId: string): Promise<BenchmarkRun>;
  createBenchmarkRun(request: { project_id: string; baseline_dir: string; lora_dir: string; artifact_id?: string }): Promise<BenchmarkRun>;
  reviewBenchmarkCase(runId: string, caseId: string, decision: "pending" | "accepted" | "rejected", note?: string): Promise<BenchmarkRun>;
  listCaptionProviders(): Promise<VisionProviderPreset[]>;
  startGrokOAuthLogin(): Promise<{ started: boolean; message: string }>;
  listCaptionJobs(snapshotId?: string): Promise<CaptionGenerationJob[]>;
  getCaptionJob(jobId: string): Promise<CaptionGenerationJob>;
  cancelCaptionJob(jobId: string): Promise<CaptionGenerationJob>;
  createCaptionJob(
    snapshotId: string,
    request: CaptionGenerationRequest,
  ): Promise<CaptionGenerationJob>;
  getPreparationCheckpoint?(projectId: string, target: string): Promise<{ checkpoint: PreparationCheckpoint | null }>;
  savePreparationCheckpoint?(projectId: string, target: string, checkpoint: PreparationCheckpoint, onlyIfUnset?: boolean): Promise<{ checkpoint: PreparationCheckpoint | null }>;
  getWorkspacePreference(): Promise<WorkspacePreference>;
  setWorkspacePreference(patch: Partial<WorkspaceSession>, onlyIfUnset?: boolean): Promise<WorkspacePreference>;
  assetUrl(path: string): string;
}

const defaultBaseUrl =
  (import.meta.env.VITE_LORASUITE_ENGINE_URL as string | undefined) || "http://127.0.0.1:8765";

export function createEngineClient(
  baseUrl = defaultBaseUrl,
  fetcher: FetchLike = fetch,
): EngineClient {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");

  async function postJson<TResponse>(path: string, body: unknown): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  async function postForm<TResponse>(path: string, body: FormData): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "POST",
      body,
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  async function patchJson<TResponse>(path: string, body: unknown): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  async function getJson<TResponse>(path: string): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  return {
    getThemePreference: () => getJson<ThemePreference>("/preferences/theme"),
    getPreparationCheckpoint: (projectId, target) => getJson(`/preferences/preparation/${encodeURIComponent(projectId)}/${encodeURIComponent(target)}`),
    savePreparationCheckpoint: (projectId, target, checkpoint, onlyIfUnset = false) => postJson(`/preferences/preparation/${encodeURIComponent(projectId)}/${encodeURIComponent(target)}`, { checkpoint, only_if_unset: onlyIfUnset }),
    getWorkspacePreference: () => getJson<WorkspacePreference>("/preferences/workspace"),
    setWorkspacePreference: (patch, onlyIfUnset = false) => postJson<WorkspacePreference>("/preferences/workspace", { ...patch, only_if_unset: onlyIfUnset }),
    setThemePreference: (theme, onlyIfUnset = false) => postJson<ThemePreference>("/preferences/theme", {theme, only_if_unset: onlyIfUnset}),
    libraryStatus: () => getJson<LibraryStatus>('/library/status'),
    listLibraryModels: (category, page, search) => getJson<LibraryCatalog>(`/library/models?${new URLSearchParams({ category, page: String(page), search })}`),
    exportArtifactToLibrary: (artifactId, options) => postJson(`/library/training-artifacts/${encodeURIComponent(artifactId)}`, options ?? {}),
    configureLibrary: (port) => postJson('/library/config', { port }),
    createCompanionCode: () => postJson('/library/pairing-code', {}),
    revokeCompanion: () => postJson('/library/revoke', {}),
    importLibraryFile: (id, path, modelType) => postJson(`/library/inbox/${encodeURIComponent(id)}/import`, { path, model_type: modelType }),
    archiveLibraryEntry: (id, archived) => postJson(`/library/inbox/${encodeURIComponent(id)}/archive`, { archived }),
    pickDirectory() {
      return postJson<{ path: string | null }>("/system/folders/select", {});
    },
    importLocal(paths: string[]) {
      return postJson<LocalImportResponse>("/vault/import/local", { paths });
    },
    listVaultMedia() {
      return getJson<MediaItem[]>("/vault/media");
    },
    listVaultMediaPage(options = {}) {
      const query = new URLSearchParams();
      if (options.offset !== undefined) query.set("offset", String(options.offset));
      if (options.limit !== undefined) query.set("limit", String(options.limit));
      if (options.mediaType) query.set("media_type", options.mediaType);
      if (options.status) query.set("status", options.status);
      if (options.search) query.set("search", options.search);
      if (options.includeIgnored !== undefined) {
        query.set("include_ignored", String(options.includeIgnored));
      }
      if (options.snapshot) query.set("snapshot", options.snapshot);
      const suffix = query.size > 0 ? `?${query.toString()}` : "";
      return getJson<VaultMediaPage>(`/vault/media-page${suffix}`);
    },
    listExactDuplicateClusters() {
      return getJson<ExactDuplicateCluster[]>("/vault/duplicate-clusters");
    },
    clearAllMedia(confirmation: string) {
      return postJson<ClearAllMediaResult>("/vault/media/clear", { confirmation });
    },
    rotateVaultImage(mediaItemId: string, degrees: 90 | 180 | 270 = 90) {
      return postJson<MediaItem>(`/vault/media/${encodeURIComponent(mediaItemId)}/rotate`, {
        degrees,
      });
    },
    listCurationBundles() {
      return getJson<CurationSourceBundle[]>("/curation/bundles");
    },
    getCurationHandoff(projectId?: string, requestedOutput?: RequestedOutput) {
      const query = new URLSearchParams();
      if (projectId) query.set("project_id", projectId);
      if (requestedOutput) query.set("requested_output", requestedOutput);
      const suffix = query.size ? `?${query.toString()}` : "";
      return getJson<CurationHandoff>(`/curation/handoff${suffix}`);
    },
    addCurationHandoff(
      mediaItemIds: string[],
      projectId?: string,
      requestedOutput?: RequestedOutput,
    ) {
      return postJson<CurationHandoff>("/curation/handoff", {
        media_item_ids: mediaItemIds,
        project_id: projectId,
        requested_output: requestedOutput,
      });
    },
    rejectCurationMedia(mediaItemIds: string[]) {
      return postJson<MediaItem[]>("/curation/reject", {
        media_item_ids: mediaItemIds,
      });
    },
    restoreCurationAudio(mediaItemIds: string[]) {
      return postJson<MediaItem[]>("/curation/audio/restore", {
        media_item_ids: mediaItemIds,
      });
    },
    createCurationAnalysisJob(mediaItemIds: string[]) {
      return postJson<ProcessingJob>("/curation/analyze", {
        media_item_ids: mediaItemIds,
      });
    },
    getAudioCleaningRecipe(mediaItemId: string) {
      return getJson<AudioCleaningRecipe>(
        `/curation/audio/${encodeURIComponent(mediaItemId)}/cleaning-recipe`,
      );
    },
    previewAudioCleaning(mediaItemId: string, recipe: AudioCleaningRecipe) {
      return postJson<AudioCleaningResult>(
        `/curation/audio/${encodeURIComponent(mediaItemId)}/cleaning-preview`,
        recipe,
      );
    },
    renderAudioCleaning(mediaItemId: string, recipe: AudioCleaningRecipe) {
      return postJson<AudioCleaningResult>(
        `/curation/audio/${encodeURIComponent(mediaItemId)}/cleaning-render`,
        recipe,
      );
    },
    getAudioSeparationStatus() {
      return getJson<AudioSeparationRuntimeStatus>("/curation/audio/separation/status");
    },
    installAudioSeparationModel() {
      return postJson<AudioSeparationRuntimeStatus>(
        "/curation/audio/separation/install",
        {},
      );
    },
    createAudioCleaningJob(mediaItemIds: string[], forceVoiceIsolation = false) {
      return postJson<ProcessingJob>("/curation/audio/cleaning-jobs", {
        media_item_ids: mediaItemIds,
        force_voice_isolation: forceVoiceIsolation,
      });
    },
    updateCurationReview(
      mediaItemId: string,
      reviewStatus: CurationReviewStatus,
      projectId?: string,
      requestedOutput?: RequestedOutput,
      speakerConfirmation?: SpeakerConfirmation,
    ) {
      return patchJson<CurationHandoff>(
        `/curation/handoff/${encodeURIComponent(mediaItemId)}`,
        {
          review_status: reviewStatus,
          project_id: projectId,
          requested_output: requestedOutput,
          speaker_confirmation: speakerConfirmation,
        },
      );
    },
    getIdentityStatus() {
      return getJson<IdentityRuntimeStatus>("/identity/status");
    },
    installIdentityModels() {
      return postJson<IdentityRuntimeStatus>("/identity/install", {});
    },
    getVoiceIdentityStatus() {
      return getJson<IdentityRuntimeStatus>("/identity/voice/status");
    },
    installVoiceIdentityModel() {
      return postJson<IdentityRuntimeStatus>("/identity/voice/install", {});
    },
    getVoiceIdentityProfile(projectId: string) {
      return getJson<VoiceIdentityProfile>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-identity`,
      );
    },
    setVoiceIdentityAnchors(projectId: string, mediaItemIds: string[]) {
      return postJson<VoiceIdentityProfile>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-identity/anchors`,
        { media_item_ids: mediaItemIds },
      );
    },
    confirmVoiceIdentitySample(
      projectId: string,
      mediaItemId: string,
      subjectLabel: string,
      requestedOutput: RequestedOutput = "voice",
    ) {
      return postJson<VoiceSampleConfirmationResult>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-identity/confirm`,
        {
          media_item_id: mediaItemId,
          subject_label: subjectLabel,
          requested_output: requestedOutput,
        },
      );
    },
    analyzeVoiceIdentity(projectId: string, mediaItemIds: string[]) {
      return postJson<VoiceIdentityProfile>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-identity/analyze`,
        { media_item_ids: mediaItemIds },
      );
    },
    getVoiceDataset(projectId: string) {
      return getJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset`,
      );
    },
    compileVoiceDataset(projectId: string, mediaItemIds: string[]) {
      return postJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/compile`,
        { media_item_ids: mediaItemIds },
      );
    },
    updateVoiceDatasetSegment(
      projectId: string,
      segmentId: string,
      update: { status?: VoiceSegmentStatus; transcript?: string },
    ) {
      return patchJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/segments/${encodeURIComponent(segmentId)}`,
        update,
      );
    },
    bulkUpdateVoiceDatasetSegments(projectId: string, decisions: Record<string, VoiceSegmentStatus>) {
      return postJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/segments/bulk-status`,
        { decisions },
      );
    },
    rescoreVoiceDataset(projectId: string) {
      return postJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/rescore`,
        {},
      );
    },
    analyzeVoiceDatasetQuality(projectId: string) {
      return postJson<VoiceDatasetCompilation>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/quality-gate`,
        {},
      );
    },
    exportVoiceDataset(projectId: string, outputDir: string, target: VoiceExportTarget = "voice_cloning") {
      return postJson<VoiceDatasetExportResponse>(
        `/character-projects/${encodeURIComponent(projectId)}/voice-dataset/export`,
        { output_dir: outputDir, target },
      );
    },
    scanLocalIngress(roots: string[], recursive = true) {
      return postJson<IngressScanResult>("/ingress/local/scan", { roots, recursive });
    },
    uploadLocalIngress(files: File[]) {
      const body = new FormData();
      for (const file of files) {
        body.append("files", file, uploadFileName(file));
      }
      return postForm<IngressScanResult>("/ingress/local/upload-scan", body);
    },
    scanInstagramHelperPayload(
      payload: Record<string, unknown>,
      includeVideoPostersAsImageCandidates = true,
    ) {
      return postJson<IngressScanResult>("/ingress/instagram/helper-scan", {
        payload,
        include_video_posters_as_image_candidates: includeVideoPostersAsImageCandidates,
      });
    },
    scanInstagramBrowserUrl(
      url: string,
      browser = "chrome",
      limit = 24,
      cursor?: string,
      scanMode: InstagramScanMode = "all",
      dateFrom?: string,
      dateTo?: string,
    ) {
      return postJson<IngressScanResult>("/ingress/instagram/browser-scan", {
        url,
        browser,
        limit,
        cursor,
        scan_mode: scanMode,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
    },
    scanXBrowserUrl(
      url: string,
      browser = "chrome",
      limit = 24,
      cursor?: string,
      dateFrom?: string,
      dateTo?: string,
    ) {
      return postJson<IngressScanResult>("/ingress/x/browser-scan", {
        url,
        browser,
        limit,
        cursor,
        date_from: dateFrom,
        date_to: dateTo,
      });
    },
    scanTikTokBrowserUrl(
      url: string,
      browser = "chrome",
      limit = 24,
      cursor?: string,
      dateFrom?: string,
      dateTo?: string,
    ) {
      return postJson<IngressScanResult>("/ingress/tiktok/browser-scan", {
        url,
        browser,
        limit,
        cursor,
        date_from: dateFrom,
        date_to: dateTo,
      });
    },
    createSocialAcquisitionJob(request: SocialAcquisitionRequest) {
      return postJson<SocialAcquisitionJob>("/ingress/social-acquisitions", request);
    },
    listSocialAcquisitionJobs() {
      return getJson<SocialAcquisitionJob[]>("/ingress/social-acquisitions");
    },
    getSocialAcquisitionJob(jobId: string) {
      return getJson<SocialAcquisitionJob>(
        `/ingress/social-acquisitions/${encodeURIComponent(jobId)}`,
      );
    },
    resumeSocialAcquisitionJob(jobId: string) {
      return postJson<SocialAcquisitionJob>(
        `/ingress/social-acquisitions/${encodeURIComponent(jobId)}/resume`,
        {},
      );
    },
    cancelSocialAcquisitionJob(jobId: string) {
      return postJson<SocialAcquisitionJob>(
        `/ingress/social-acquisitions/${encodeURIComponent(jobId)}/cancel`,
        {},
      );
    },
    listIngressCandidates(sourceKind?: SourceKind) {
      const query = sourceKind ? `?source_kind=${encodeURIComponent(sourceKind)}` : "";
      return getJson<IngressScanResult>(`/ingress/candidates${query}`);
    },
    ingressCandidateVideoPreviewUrl(candidateId: string) {
      return `${normalizedBaseUrl}/ingress/candidates/${encodeURIComponent(candidateId)}/video-preview`;
    },
    ingressCandidateThumbnailUrl(candidateId: string) {
      return `${normalizedBaseUrl}/ingress/candidates/${encodeURIComponent(candidateId)}/thumbnail`;
    },
    analyzeIngressCandidates(candidateIds, target) {
      return postJson<IngressCandidateAnalysisResponse>("/ingress/candidates/analyze", {
        candidate_ids: candidateIds,
        target,
      });
    },
    createIngressJob(request: CreateIngressJobRequest) {
      return postJson<IngressJob>("/ingress/jobs", request);
    },
    listIngressJobs() {
      return getJson<IngressJob[]>("/ingress/jobs");
    },
    getIngressJob(jobId: string) {
      return getJson<IngressJob>(`/ingress/jobs/${jobId}`);
    },
    createProcessingJob(request: CreateProcessingJobRequest) {
      return postJson<ProcessingJob>("/processing/jobs", request);
    },
    listProcessingJobs() {
      return getJson<ProcessingJob[]>("/processing/jobs");
    },
    getProcessingJob(jobId: string) {
      return getJson<ProcessingJob>(`/processing/jobs/${jobId}`);
    },
    processProcessingJob(jobId: string) {
      return postJson<ProcessingJob>(`/processing/jobs/${jobId}/process`, {});
    },
    updateVideoKeepers(jobId: string, frameIds: string[]) {
      return postJson<ProcessingJob>(`/processing/jobs/${jobId}/keepers`, {
        frame_ids: frameIds,
      });
    },
    commitVideoBreakdown(jobId: string, request: VideoBreakdownCommitRequest) {
      return postJson<ProcessingJob>(`/processing/jobs/${jobId}/commit`, request);
    },
    listCharacterProjects() {
      return getJson<CharacterProject[]>("/character-projects");
    },
    createCharacterProject(name = "Character Dataset", intent?: TrainingIntent) {
      return postJson<CharacterProject>("/character-projects", { name, intent });
    },
    getCharacterProject(projectId: string) {
      return getJson<CharacterProject>(`/character-projects/${projectId}`);
    },
    updateCharacterProject(
      projectId: string,
      update: { name?: string; intent?: TrainingIntent },
    ) {
      return patchJson<CharacterProject>(`/character-projects/${projectId}`, update);
    },
    addCharacterProjectCandidates(projectId: string, mediaItemIds: string[]) {
      return postJson<CharacterProject>(`/character-projects/${projectId}/candidates`, {
        media_item_ids: mediaItemIds,
      });
    },
    setCharacterProjectAnchors(projectId: string, mediaItemIds: string[]) {
      return postJson<CharacterProject>(`/character-projects/${projectId}/anchors`, {
        media_item_ids: mediaItemIds,
      });
    },
    updateCharacterProjectObservation(
      projectId: string,
      mediaItemId: string,
      update: { review_status: DatasetReviewStatus; view?: DatasetView },
    ) {
      return patchJson<CharacterProject>(
        `/character-projects/${projectId}/observations/${mediaItemId}`,
        update,
      );
    },
    analyzeCharacterProject(projectId: string) {
      return postJson<CharacterProject>(`/character-projects/${projectId}/analyze`, {});
    },
    selectCharacterProjectFace(projectId: string, mediaItemId: string, faceIndex: number) {
      return postJson<CharacterProject>(
        `/character-projects/${encodeURIComponent(projectId)}/observations/${encodeURIComponent(mediaItemId)}/face`,
        { face_index: faceIndex },
      );
    },
    updateCharacterProjectCrop(
      projectId: string,
      recipeId: string,
      update: { rect?: NormalizedRect; status?: CropRecipeStatus; kind?: CropKind },
    ) {
      return patchJson<CharacterProject>(
        `/character-projects/${encodeURIComponent(projectId)}/crops/${encodeURIComponent(recipeId)}`,
        update,
      );
    },
    materializeCharacterProjectCrop(projectId: string, recipeId: string) {
      return postJson<{ project: CharacterProject; media_item: MediaItem }>(
        `/character-projects/${encodeURIComponent(projectId)}/crops/${encodeURIComponent(recipeId)}/materialize`,
        {},
      );
    },
    listDatasetSnapshots(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<DatasetSnapshot[]>(`/dataset-snapshots${query}`);
    },
    getDatasetSnapshot(snapshotId: string) {
      return getJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}`,
      );
    },
    listRecoveredDatasetExports() {
      return getJson<RecoveredDatasetExport[]>("/recovered-dataset-exports");
    },
    registerRecoveredDatasetExport(exportPath: string) {
      return postJson<RecoveredDatasetExport>(
        "/recovered-dataset-exports",
        { export_path: exportPath },
      );
    },
    verifyRecoveredDatasetExport(recordId: string) {
      return postJson<RecoveredDatasetExport>(
        `/recovered-dataset-exports/${encodeURIComponent(recordId)}/verify`,
        {},
      );
    },
    inspectStateMigrations() {
      return getJson<StateMigrationReport>("/state-migrations");
    },
    applyStateMigrations() {
      return postJson<StateMigrationReport>("/state-migrations/apply", {});
    },
    listDiagnosticBundles() {
      return getJson<DiagnosticBundleRecord[]>("/diagnostic-bundles");
    },
    createDiagnosticBundle(request = {}) {
      return postJson<DiagnosticBundleRecord>("/diagnostic-bundles", request);
    },
    diagnosticBundleDownloadUrl(bundleId: string) {
      return `${normalizedBaseUrl}/diagnostic-bundles/${encodeURIComponent(bundleId)}/download`;
    },
    listTrainingTargets() {
      return getJson<TrainingTargetProfile[]>("/training-targets");
    },
    estimateTraining(request: TrainingEstimateRequest) {
      return postJson<TrainingCostEstimate>("/training-estimates", request);
    },
    listModelIntentRecipes() {
      return getJson<ModelIntentRecipe[]>("/model-intent-recipes");
    },
    compileCharacterDataset(projectId: string, trainingTargetProfileId = "runcomfy_flux1_dev_character") {
      return postJson<DatasetSnapshot>(
        `/character-projects/${encodeURIComponent(projectId)}/dataset/compile`,
        { training_target_profile_id: trainingTargetProfileId },
      );
    },
    updateDatasetItem(
      snapshotId: string,
      itemId: string,
      update: { caption?: string; tags?: string[]; status?: DatasetItemStatus },
    ) {
      return patchJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/items/${encodeURIComponent(itemId)}`,
        update,
      );
    },
    updateDatasetModelCard(snapshotId: string, update: LoraModelCardOverrides) {
      return patchJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/model-card`,
        update,
      );
    },
    bulkUpdateDatasetItems(
      snapshotId: string,
      status: DatasetItemStatus,
      itemIds?: string[],
    ) {
      return postJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/items/bulk-status`,
        { status, item_ids: itemIds },
      );
    },
    proposeDatasetStrongestSet(
      snapshotId: string,
      targetCount?: number,
      disqualifiedItemIds?: string[],
      includedItemIds?: string[],
    ) {
      return postJson<DatasetStrongestSetProposal>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/strongest-set/propose`,
        {
          target_count: targetCount,
          disqualified_item_ids: disqualifiedItemIds ?? [],
          included_item_ids: includedItemIds ?? [],
        },
      );
    },
    proposeDatasetDuplicates(snapshotId: string) {
      return postJson<DatasetDuplicateProposal>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/duplicates/propose`,
        {},
      );
    },
    applyDatasetStrongestSet(
      snapshotId: string,
      targetCount?: number,
      disqualifiedItemIds?: string[],
      includedItemIds?: string[],
    ) {
      return postJson<DatasetStrongestSetApplyResponse>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/strongest-set/apply`,
        {
          target_count: targetCount,
          disqualified_item_ids: disqualifiedItemIds ?? [],
          included_item_ids: includedItemIds ?? [],
        },
      );
    },
    restoreDatasetStrongestSet(snapshotId: string) {
      return postJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/strongest-set/restore`,
        {},
      );
    },
    freezeDatasetSnapshot(snapshotId: string) {
      return postJson<DatasetSnapshot>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/freeze`,
        {},
      );
    },
    exportDatasetSnapshotRunComfy(snapshotId: string, outputDir: string) {
      return postJson<DatasetExportResponse>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/export/runcomfy`,
        { output_dir: outputDir },
      );
    },
    listTrainingRuns(snapshotId?: string) {
      const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
      return getJson<TrainingRun[]>(`/training-runs${query}`);
    },
    getTrainingRun(runId: string) {
      return getJson<TrainingRun>(`/training-runs/${encodeURIComponent(runId)}`);
    },
    async createTrainingRun(request: CreateTrainingRunRequest) {
      return postJson<TrainingRun>("/training-runs/runcomfy", {
        ...request,
        api_token: await resolveCredential("runcomfy_api", request.api_token),
      });
    },
    async refreshTrainingRun(runId: string, apiToken?: string) {
      return postJson<TrainingRun>(
        `/training-runs/${encodeURIComponent(runId)}/refresh`,
        { api_token: await resolveCredential("runcomfy_api", apiToken) },
      );
    },
    async resumeTrainingRun(runId: string, apiToken?: string) {
      return postJson<TrainingRun>(
        `/training-runs/${encodeURIComponent(runId)}/resume`,
        { api_token: await resolveCredential("runcomfy_api", apiToken) },
      );
    },
    async cancelTrainingRun(runId: string, apiToken?: string) {
      return postJson<TrainingRun>(
        `/training-runs/${encodeURIComponent(runId)}/cancel`,
        { api_token: await resolveCredential("runcomfy_api", apiToken) },
      );
    },
    listModelArtifacts(snapshotId?: string) {
      const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
      return getJson<ModelArtifactRecord[]>(`/model-artifacts${query}`);
    },
    listModelReleaseCandidates(projectId: string, modality?: ModelArtifactRecord["modality"]) {
      const query = new URLSearchParams({ project_id: projectId });
      if (modality) query.set("modality", modality);
      return getJson<ArtifactReleaseCandidate[]>(`/model-artifacts/release-candidates?${query.toString()}`);
    },
    selectModelRelease(artifactId: string) {
      return postJson<ModelArtifactRecord>(`/model-artifacts/${encodeURIComponent(artifactId)}/select-release`, {});
    },
    registerTrainingArtifacts(runId: string) {
      return postJson<ModelArtifactRecord[]>(
        `/training-runs/${encodeURIComponent(runId)}/register-artifacts`,
        {},
      );
    },
    listComfyInstallations() {
      return getJson<ComfyInstallation[]>("/comfyui/installations");
    },
    getComfyRuntimeStatus(comfyRoot: string, baseUrl = "http://127.0.0.1:8188") {
      const query = new URLSearchParams({ comfy_root: comfyRoot, base_url: baseUrl });
      return getJson<ComfyRuntimeStatus>(`/comfyui/runtime-status?${query.toString()}`);
    },
    previewModelArtifactComfyHandoff(artifactId: string, comfyRoot: string) {
      const query = new URLSearchParams({ comfy_root: comfyRoot });
      return getJson<ComfyHandoffManifest>(
        `/model-artifacts/${encodeURIComponent(artifactId)}/comfyui-handoff?${query.toString()}`,
      );
    },
    installModelArtifact(artifactId: string, comfyRoot: string) {
      return postJson<ModelArtifactRecord>(
        `/model-artifacts/${encodeURIComponent(artifactId)}/install`,
        { comfy_root: comfyRoot },
      );
    },
    listComfyEvaluationReports(filters = {}) {
      const query = new URLSearchParams();
      if (filters.artifactId) query.set("artifact_id", filters.artifactId);
      if (filters.projectId) query.set("project_id", filters.projectId);
      const suffix = query.size ? `?${query.toString()}` : "";
      return getJson<ComfyEvaluationReport[]>(`/comfyui/evaluation-reports${suffix}`);
    },
    listArtifactComparisons(filters = {}) {
      const query = new URLSearchParams();
      if (filters.projectId) query.set("project_id", filters.projectId);
      if (filters.benchmarkKind) query.set("benchmark_kind", filters.benchmarkKind);
      const suffix = query.size ? `?${query.toString()}` : "";
      return getJson<ArtifactComparison[]>(`/artifact-comparisons${suffix}`);
    },
    createArtifactComparison(request) {
      return postJson<ArtifactComparison>("/artifact-comparisons", request);
    },
    listImprovementRequests(filters = {}) {
      const query = new URLSearchParams();
      if (filters.projectId) query.set("project_id", filters.projectId);
      if (filters.status) query.set("status", filters.status);
      const suffix = query.size ? `?${query.toString()}` : "";
      return getJson<ImprovementRequest[]>(`/improvement-requests${suffix}`);
    },
    createImprovementRequest(comparisonId: string) {
      return postJson<ImprovementRequest>(
        `/artifact-comparisons/${encodeURIComponent(comparisonId)}/improvement-request`,
        {},
      );
    },
    decideImprovementRequest(requestId: string, decision: "approved" | "rejected", note = "") {
      return patchJson<ImprovementRequest>(
        `/improvement-requests/${encodeURIComponent(requestId)}`,
        { decision, note },
      );
    },
    listDatasetRevisions(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<DatasetRevisionRecord[]>(`/dataset-revisions${query}`);
    },
    materializeDatasetRevision(requestId: string) {
      return postJson<DatasetRevisionRecord>(
        `/improvement-requests/${encodeURIComponent(requestId)}/materialize-revision`,
        {},
      );
    },
    listVideoDatasetCandidates(projectId?: string) {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<MediaItem[]>(`/video-dataset/candidates${suffix}`);
    },
    listVideoDatasetSnapshots(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<VideoDatasetSnapshot[]>(`/video-dataset-snapshots${query}`);
    },
    getVideoDatasetSnapshot(snapshotId: string) {
      return getJson<VideoDatasetSnapshot>(`/video-dataset-snapshots/${encodeURIComponent(snapshotId)}`);
    },
    compileVideoDataset(projectId: string, mediaItemIds?: string[], targetProfileId?: string, referenceImageMediaItemIds?: string[], referenceAudioMediaItemIds?: string[]) {
      return postJson<VideoDatasetSnapshot>("/video-dataset-snapshots/compile", {
        project_id: projectId,
        media_item_ids: mediaItemIds,
        target_profile_id: targetProfileId,
        reference_image_media_item_ids: referenceImageMediaItemIds,
        reference_audio_media_item_ids: referenceAudioMediaItemIds,
      });
    },
    updateVideoDatasetItem(snapshotId: string, itemId: string, update: { caption?: string; status?: VideoDatasetItemStatus }) {
      return patchJson<VideoDatasetSnapshot>(
        `/video-dataset-snapshots/${encodeURIComponent(snapshotId)}/items/${encodeURIComponent(itemId)}`,
        update,
      );
    },
    bulkUpdateVideoDataset(snapshotId: string, status: "approved" | "excluded") {
      return postJson<VideoDatasetSnapshot>(
        `/video-dataset-snapshots/${encodeURIComponent(snapshotId)}/bulk-status`,
        { status },
      );
    },
    freezeVideoDataset(snapshotId: string) {
      return postJson<VideoDatasetSnapshot>(
        `/video-dataset-snapshots/${encodeURIComponent(snapshotId)}/freeze`,
        {},
      );
    },
    exportVideoDataset(snapshotId: string, outputDir: string) {
      return postJson<VideoDatasetExportResponse>(
        `/video-dataset-snapshots/${encodeURIComponent(snapshotId)}/export`,
        { output_dir: outputDir },
      );
    },
    listIdLoraManifests(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<IdLoraManifest[]>(`/id-lora-manifests${query}`);
    },
    getIdLoraManifest(manifestId: string) {
      return getJson<IdLoraManifest>(`/id-lora-manifests/${encodeURIComponent(manifestId)}`);
    },
    compileIdLoraManifest(projectId: string, videoSnapshotId?: string) {
      return postJson<IdLoraManifest>("/id-lora-manifests/compile", {
        project_id: projectId,
        video_snapshot_id: videoSnapshotId,
      });
    },
    exportIdLoraManifest(manifestId: string, outputDir: string) {
      return postJson<IdLoraExportResponse>(
        `/id-lora-manifests/${encodeURIComponent(manifestId)}/export`,
        { output_dir: outputDir },
      );
    },
    getBenchmarkSuite() {
      return getJson<BenchmarkCaseDefinition[]>("/benchmark-suite");
    },
    getSyncNetCapability() {
      return getJson<SyncNetCapability>("/evaluation/capabilities/syncnet");
    },
    prepareBenchmarkWorkspace(projectId: string, outputDir: string) {
      return postJson<BenchmarkWorkspace>("/benchmark-suite/prepare", {
        project_id: projectId,
        output_dir: outputDir,
      });
    },
    listBenchmarkGenerationRuns(projectId?: string, benchmarkKind?: "audio_visual" | "image") {
      const parameters = [
        projectId ? `project_id=${encodeURIComponent(projectId)}` : "",
        benchmarkKind ? `benchmark_kind=${encodeURIComponent(benchmarkKind)}` : "",
      ].filter(Boolean);
      const query = parameters.length ? `?${parameters.join("&")}` : "";
      return getJson<BenchmarkGenerationRun[]>(`/benchmark-generation-runs${query}`);
    },
    getBenchmarkGenerationRun(runId: string) {
      return getJson<BenchmarkGenerationRun>(`/benchmark-generation-runs/${encodeURIComponent(runId)}`);
    },
    retryBenchmarkGenerationRun(runId: string, caseIds: string[], apiToken?: string) {
      return postJson<BenchmarkGenerationRun>(`/benchmark-generation-runs/${encodeURIComponent(runId)}/retry`, {
        case_ids: caseIds,
        api_token: apiToken || undefined,
      });
    },
    async createBenchmarkGenerationRun(request: CreateBenchmarkGenerationRequest) {
      return postJson<BenchmarkGenerationRun>("/benchmark-generation-runs/runcomfy", {
        ...request,
        api_token: await resolveCredential("runcomfy_api", request.api_token),
      });
    },
    async createRunPodBenchmarkGenerationRun(request: CreateRunPodBenchmarkGenerationRequest) {
      return postJson<BenchmarkGenerationRun>("/benchmark-generation-runs/runpod", {
        ...request,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    getImageBenchmarkSuite() {
      return getJson<ImageBenchmarkCaseDefinition[]>("/image-benchmark-suite");
    },
    prepareImageBenchmarkWorkspace(projectId: string, outputDir: string) {
      return postJson<ImageBenchmarkWorkspace>("/image-benchmark-suite/prepare", { project_id: projectId, output_dir: outputDir });
    },
    async createImageBenchmarkGenerationRun(request: CreateBenchmarkGenerationRequest) {
      return postJson<BenchmarkGenerationRun>("/image-benchmark-generation-runs/runcomfy", {
        ...request,
        api_token: await resolveCredential("runcomfy_api", request.api_token),
      });
    },
    async createRunPodImageBenchmarkGenerationRun(request: CreateRunPodBenchmarkGenerationRequest) {
      return postJson<BenchmarkGenerationRun>("/image-benchmark-generation-runs/runpod", {
        ...request,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    listImageBenchmarkRuns(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<ImageBenchmarkRun[]>(`/image-benchmark-runs${query}`);
    },
    getImageBenchmarkRun(runId: string) {
      return getJson<ImageBenchmarkRun>(`/image-benchmark-runs/${encodeURIComponent(runId)}`);
    },
    createImageBenchmarkRun(request: { project_id: string; baseline_dir: string; lora_dir: string; artifact_id?: string }) {
      return postJson<ImageBenchmarkRun>("/image-benchmark-runs", request);
    },
    createRunPodBundle(request: CreateRunPodBundleRequest) {
      return postJson<RunPodBundle>("/runpod-bundles", request);
    },
    listProviderSmokeRuns(filters = {}) {
      const params = new URLSearchParams();
      if (filters.projectId) params.set("project_id", filters.projectId);
      if (filters.provider) params.set("provider", filters.provider);
      if (filters.trainingTargetProfileId) params.set("training_target_profile_id", filters.trainingTargetProfileId);
      if (filters.bundleId) params.set("bundle_id", filters.bundleId);
      const query = params.size ? `?${params.toString()}` : "";
      return getJson<ProviderSmokeRun[]>(`/provider-smoke-runs${query}`);
    },
    createRunComfyProviderSmokeRun(request) {
      return postJson<ProviderSmokeRun>("/provider-smoke-runs/runcomfy", request);
    },
    createRunPodProviderSmokeRun(bundleId: string) {
      return postJson<ProviderSmokeRun>("/provider-smoke-runs/runpod", { bundle_id: bundleId });
    },
    listRunPodInfrastructureProfiles() {
      return getJson<RunPodInfrastructureProfile[]>("/runpod-infrastructure-profiles");
    },
    async provisionRunPodInfrastructure(request: ProvisionRunPodInfrastructureRequest) {
      const runtimeEnvironment = { ...(request.runtime_environment ?? {}) };
      const huggingFaceToken = await resolveCredential(
        "huggingface_token",
        runtimeEnvironment.HF_TOKEN,
      );
      if (huggingFaceToken) runtimeEnvironment.HF_TOKEN = huggingFaceToken;
      return postJson<RunPodInfrastructureProfile>("/runpod-infrastructure-profiles/provision", {
        ...request,
        runtime_environment: runtimeEnvironment,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    listRunPodModelBootstrapRuns(endpointId?: string, trainingTargetProfileId?: string) {
      const params = new URLSearchParams();
      if (endpointId) params.set("endpoint_id", endpointId);
      if (trainingTargetProfileId) params.set("training_target_profile_id", trainingTargetProfileId);
      const query = params.size ? `?${params.toString()}` : "";
      return getJson<RunPodModelBootstrapRun[]>(`/runpod-model-bootstrap-runs${query}`);
    },
    getRunPodModelBootstrapRun(runId: string) {
      return getJson<RunPodModelBootstrapRun>(`/runpod-model-bootstrap-runs/${encodeURIComponent(runId)}`);
    },
    async createRunPodModelBootstrapRun(request: CreateRunPodModelBootstrapRequest) {
      return postJson<RunPodModelBootstrapRun>("/runpod-model-bootstrap-runs", {
        ...request,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    async refreshRunPodModelBootstrapRun(runId: string, apiToken?: string) {
      return postJson<RunPodModelBootstrapRun>(`/runpod-model-bootstrap-runs/${encodeURIComponent(runId)}/refresh`, {
        api_token: await resolveCredential("runpod_api", apiToken),
      });
    },
    async cancelRunPodModelBootstrapRun(runId: string, apiToken?: string) {
      return postJson<RunPodModelBootstrapRun>(`/runpod-model-bootstrap-runs/${encodeURIComponent(runId)}/cancel`, {
        api_token: await resolveCredential("runpod_api", apiToken),
      });
    },
    listRunPodBundles(sourceExportPath?: string, trainingTargetProfileId?: string, projectId?: string) {
      const params = new URLSearchParams();
      if (sourceExportPath) params.set("source_export_path", sourceExportPath);
      if (trainingTargetProfileId) params.set("training_target_profile_id", trainingTargetProfileId);
      if (projectId) params.set("project_id", projectId);
      const query = params.size ? `?${params.toString()}` : "";
      return getJson<RunPodBundle[]>(`/runpod-bundles${query}`);
    },
    listRunPodBundleUploadJobs(bundlePath?: string) {
      const query = bundlePath ? `?bundle_path=${encodeURIComponent(bundlePath)}` : "";
      return getJson<RunPodBundleUploadJob[]>(`/runpod-bundle-upload-jobs${query}`);
    },
    getRunPodBundleUploadJob(jobId: string) {
      return getJson<RunPodBundleUploadJob>(`/runpod-bundle-upload-jobs/${encodeURIComponent(jobId)}`);
    },
    async createRunPodBundleUploadJob(request: CreateRunPodBundleUploadRequest) {
      return postJson<RunPodBundleUploadJob>("/runpod-bundle-upload-jobs", {
        ...request,
        access_key: await resolveCredential("runpod_s3_access", request.access_key),
        secret_key: await resolveCredential("runpod_s3_secret", request.secret_key),
      });
    },
    async resumeRunPodBundleUploadJob(jobId: string, accessKey?: string, secretKey?: string) {
      return postJson<RunPodBundleUploadJob>(`/runpod-bundle-upload-jobs/${encodeURIComponent(jobId)}/resume`, {
        access_key: await resolveCredential("runpod_s3_access", accessKey),
        secret_key: await resolveCredential("runpod_s3_secret", secretKey),
      });
    },
    listRunPodPreflightReports(bundlePath?: string, endpointId?: string) {
      const params = new URLSearchParams();
      if (bundlePath) params.set("bundle_path", bundlePath);
      if (endpointId) params.set("endpoint_id", endpointId);
      const query = params.size ? `?${params.toString()}` : "";
      return getJson<RunPodPreflightReport[]>(`/runpod-preflight-reports${query}`);
    },
    async createRunPodPreflightReport(request: CreateRunPodPreflightRequest) {
      return postJson<RunPodPreflightReport>("/runpod-preflight-reports", {
        ...request,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    listRunPodTrainingRuns(bundlePath?: string) {
      const query = bundlePath ? `?bundle_path=${encodeURIComponent(bundlePath)}` : "";
      return getJson<RunPodTrainingRun[]>(`/runpod-training-runs${query}`);
    },
    getRunPodTrainingRun(runId: string) {
      return getJson<RunPodTrainingRun>(`/runpod-training-runs/${encodeURIComponent(runId)}`);
    },
    async createRunPodTrainingRun(request: CreateRunPodTrainingRunRequest) {
      return postJson<RunPodTrainingRun>("/runpod-training-runs", {
        ...request,
        api_token: await resolveCredential("runpod_api", request.api_token),
      });
    },
    async refreshRunPodTrainingRun(runId: string, apiToken?: string) {
      return postJson<RunPodTrainingRun>(`/runpod-training-runs/${encodeURIComponent(runId)}/refresh`, {
        api_token: await resolveCredential("runpod_api", apiToken),
      });
    },
    async cancelRunPodTrainingRun(runId: string, apiToken?: string) {
      return postJson<RunPodTrainingRun>(`/runpod-training-runs/${encodeURIComponent(runId)}/cancel`, {
        api_token: await resolveCredential("runpod_api", apiToken),
      });
    },
    async downloadRunPodTrainingArtifacts(runId: string, request: RunPodArtifactDownloadRequest) {
      return postJson<RunPodTrainingRun>(`/runpod-training-runs/${encodeURIComponent(runId)}/download-artifacts`, {
        ...request,
        access_key: await resolveCredential("runpod_s3_access", request.access_key),
        secret_key: await resolveCredential("runpod_s3_secret", request.secret_key),
      });
    },
    registerRunPodTrainingArtifacts(runId: string) {
      return postJson<ModelArtifactRecord[]>(`/runpod-training-runs/${encodeURIComponent(runId)}/register-artifacts`, {});
    },
    listVoiceArtifactEvaluations(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<VoiceArtifactEvaluationRun[]>(`/voice-artifact-evaluations${query}`);
    },
    getVoiceArtifactEvaluation(runId: string) {
      return getJson<VoiceArtifactEvaluationRun>(`/voice-artifact-evaluations/${encodeURIComponent(runId)}`);
    },
    getRecommendedVoiceArtifactEvaluation(projectId: string) {
      return getJson<VoiceArtifactEvaluationRun | null>(`/voice-artifact-evaluations/recommended?project_id=${encodeURIComponent(projectId)}`);
    },
    createVoiceArtifactEvaluation(request: CreateVoiceArtifactEvaluationRequest) {
      return postJson<VoiceArtifactEvaluationRun>("/voice-artifact-evaluations", request);
    },
    selectVoiceArtifactEvaluation(runId: string) {
      return postJson<VoiceArtifactEvaluationRun>(`/voice-artifact-evaluations/${encodeURIComponent(runId)}/select`, {});
    },
    listIdLoraEvaluations(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<IdLoraEvaluationRun[]>(`/id-lora-evaluations${query}`);
    },
    getIdLoraEvaluation(runId: string) {
      return getJson<IdLoraEvaluationRun>(`/id-lora-evaluations/${encodeURIComponent(runId)}`);
    },
    createIdLoraEvaluation(runpodRunId: string) {
      return postJson<IdLoraEvaluationRun>("/id-lora-evaluations", { runpod_run_id: runpodRunId });
    },
    getTrainingWorkflow(projectId: string) {
      return getJson<TrainingWorkflowStatus>(`/training-workflow/${encodeURIComponent(projectId)}`);
    },
    getProviderReadiness(projectId: string) {
      return getJson<ProviderReadinessMatrix>(`/provider-readiness/${encodeURIComponent(projectId)}`);
    },
    getPartnerQualificationReport(projectId: string) {
      return getJson<PartnerQualificationReport>(`/partner-qualification/${encodeURIComponent(projectId)}`);
    },
    listCloudProviders() {
      return getJson<CloudProviderDescriptor[]>("/cloud-providers");
    },
    listCloudRuns(projectId?: string, provider?: "runcomfy" | "runpod") {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (provider) params.set("provider", provider);
      const query = params.size ? `?${params.toString()}` : "";
      return getJson<CloudRunRecord[]>(`/cloud-runs${query}`);
    },
    listBenchmarkRuns(projectId?: string) {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return getJson<BenchmarkRun[]>(`/benchmark-runs${query}`);
    },
    getBenchmarkRun(runId: string) {
      return getJson<BenchmarkRun>(`/benchmark-runs/${encodeURIComponent(runId)}`);
    },
    createBenchmarkRun(request: { project_id: string; baseline_dir: string; lora_dir: string; artifact_id?: string }) {
      return postJson<BenchmarkRun>("/benchmark-runs", request);
    },
    reviewBenchmarkCase(runId: string, caseId: string, decision: "pending" | "accepted" | "rejected", note = "") {
      return patchJson<BenchmarkRun>(
        `/benchmark-runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review`,
        { decision, note },
      );
    },
    listCaptionProviders() {
      return getJson<VisionProviderPreset[]>("/caption/providers");
    },
    startGrokOAuthLogin() {
      return postJson<{ started: boolean; message: string }>(
        "/caption/providers/grok-oauth/login",
        {},
      );
    },
    listCaptionJobs(snapshotId?: string) {
      const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
      return getJson<CaptionGenerationJob[]>(`/caption-jobs${query}`);
    },
    getCaptionJob(jobId: string) {
      return getJson<CaptionGenerationJob>(
        `/caption-jobs/${encodeURIComponent(jobId)}`,
      );
    },
    cancelCaptionJob(jobId: string) {
      return postJson<CaptionGenerationJob>(
        `/caption-jobs/${encodeURIComponent(jobId)}/cancel`,
        {},
      );
    },
    async createCaptionJob(snapshotId: string, request: CaptionGenerationRequest) {
      const credentialId = credentialIdForVisionProvider(request.provider_id);
      return postJson<CaptionGenerationJob>(
        `/dataset-snapshots/${encodeURIComponent(snapshotId)}/caption-jobs`,
        {
          ...request,
          api_key: credentialId
            ? await resolveCredential(credentialId, request.api_key)
            : request.api_key,
        },
      );
    },
    assetUrl(path: string) {
      return `${normalizedBaseUrl}/assets/file?path=${encodeURIComponent(path)}`;
    },
  };
}

function uploadFileName(file: File): string {
  const webkitRelativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (webkitRelativePath?.trim()) {
    return webkitRelativePath;
  }
  return file.name;
}

async function readEngineError(response: EngineResponse): Promise<string> {
  try {
    const body = await response.json();
    if (isDetailBody(body)) {
      return body.detail;
    }
    if (body && typeof body === "object") {
      return JSON.stringify(body);
    }
  } catch {
    const text = await response.text?.();
    if (text) {
      return text;
    }
  }

  return `Engine request failed: ${response.status}`;
}

function isDetailBody(value: unknown): value is { detail: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "detail" in value &&
    typeof (value as { detail: unknown }).detail === "string"
  );
}
