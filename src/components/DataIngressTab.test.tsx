import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataIngressTab } from "./DataIngressTab";
import type { EngineClient } from "../lib/api";
import type { IngressCandidate, IngressJob } from "../lib/types";

const { openMock } = vi.hoisted(() => ({
  openMock: vi.fn(),
}));
const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
}));

interface TestHostBridge {
  pickMediaPaths?: () => Promise<string | string[] | null>;
  pickDestinationPath?: () => Promise<string | string[] | null>;
}

type WindowWithHostBridge = Window & {
  loraSuiteHost?: TestHostBridge;
  showDirectoryPicker?: () => Promise<TestDirectoryHandle>;
};

interface TestDirectoryHandle {
  name: string;
  getFileHandle: ReturnType<typeof vi.fn>;
}

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: openMock,
}));
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: isTauriMock,
}));

describe("DataIngressTab", () => {
  const instagramVideoCandidate: IngressCandidate = {
    id: "candidate_video",
    source_kind: "instagram",
    source_locator: "https://www.instagram.com/reel/example/",
    display_name: "example reel",
    media_type: "video",
    duration: 9.5,
    width: 720,
    height: 1280,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    poster_asset_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: false,
    metadata_json: {
      download_url: "https://cdninstagram.example/video.mp4",
    },
  };
  const instagramPosterCandidate: IngressCandidate = {
    id: "candidate_poster",
    source_kind: "instagram",
    source_locator: "/tmp/vault/previews/social/example.jpg",
    display_name: "example reel poster",
    media_type: "image",
    width: 720,
    height: 1280,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: true,
    metadata_json: {
      source_video_candidate_id: "candidate_video",
      local_import_path: "/tmp/vault/previews/social/example.jpg",
      asset_role: "video_poster",
    },
  };
  const instagramVoiceCandidate: IngressCandidate = {
    id: "candidate_voice",
    source_kind: "instagram",
    source_locator: "https://www.instagram.com/reel/example/#audio",
    display_name: "example reel voice",
    media_type: "audio",
    duration: 9.5,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: false,
    metadata_json: {
      source_video_candidate_id: "candidate_video",
      download_url: "https://cdninstagram.example/video.mp4",
      asset_role: "video_audio",
    },
  };
  const nonOriginalAudioVideoCandidate: IngressCandidate = {
    ...instagramVideoCandidate,
    id: "candidate_reused_audio_video",
    display_name: "reused audio reel",
    metadata_json: {
      ...instagramVideoCandidate.metadata_json,
      audio_original: false,
      audio_kind: "reused_or_music",
      audio_label: "Trending sound",
    },
  };
  const nonOriginalAudioPosterCandidate: IngressCandidate = {
    ...instagramPosterCandidate,
    id: "candidate_reused_audio_poster",
    display_name: "reused audio reel poster",
    metadata_json: {
      ...instagramPosterCandidate.metadata_json,
      source_video_candidate_id: "candidate_reused_audio_video",
      audio_original: false,
      audio_kind: "reused_or_music",
      audio_label: "Trending sound",
    },
  };
  const nonOriginalAudioVoiceCandidate: IngressCandidate = {
    ...instagramVoiceCandidate,
    id: "candidate_reused_audio_voice",
    display_name: "reused audio reel voice",
    metadata_json: {
      ...instagramVoiceCandidate.metadata_json,
      source_video_candidate_id: "candidate_reused_audio_video",
      audio_original: false,
      audio_kind: "reused_or_music",
      audio_label: "Trending sound",
    },
  };

  function engineWith(overrides: Partial<EngineClient> = {}): EngineClient {
    return {
      getWorkspacePreference: vi.fn().mockResolvedValue({ workspace: null, updated_at: 0 }),
    setWorkspacePreference: vi.fn().mockResolvedValue({ workspace: null, updated_at: 0 }),
    getThemePreference: vi.fn(),
      setThemePreference: vi.fn(),
      libraryStatus: vi.fn(),
      listLibraryModels: vi.fn(),
      exportArtifactToLibrary: vi.fn(),
      configureLibrary: vi.fn(),
      createCompanionCode: vi.fn(),
      revokeCompanion: vi.fn(),
      importLibraryFile: vi.fn(),
      archiveLibraryEntry: vi.fn(),
      importLocal: vi.fn(),
      listVaultMedia: vi.fn().mockResolvedValue([]),
      listExactDuplicateClusters: vi.fn().mockResolvedValue([]),
      clearAllMedia: vi.fn(),
      rotateVaultImage: vi.fn(),
      listCurationBundles: vi.fn().mockResolvedValue([]),
      getCurationHandoff: vi.fn().mockResolvedValue({ items: [], updated_at: "2026-07-10T00:00:00Z" }),
      addCurationHandoff: vi.fn(),
      rejectCurationMedia: vi.fn(),
      restoreCurationAudio: vi.fn(),
      createCurationAnalysisJob: vi.fn(),
      getAudioCleaningRecipe: vi.fn(),
      previewAudioCleaning: vi.fn(),
      renderAudioCleaning: vi.fn(),
      getAudioSeparationStatus: vi.fn(),
      installAudioSeparationModel: vi.fn(),
      createAudioCleaningJob: vi.fn(),
      updateCurationReview: vi.fn(),
      confirmVoiceIdentitySample: vi.fn(),
      getIdentityStatus: vi.fn().mockResolvedValue({
        backend: "opencv-sface",
        model_version: "test",
        installed: true,
        ready: true,
        download_size_bytes: 0,
        message: "ready",
      }),
      installIdentityModels: vi.fn(),
      getVoiceIdentityStatus: vi.fn(),
      getSyncNetCapability: vi.fn().mockResolvedValue({ configured: false, ready: false, mode: "unconfigured", problems: [], setup: [] }),
      installVoiceIdentityModel: vi.fn(),
      getVoiceIdentityProfile: vi.fn(),
      setVoiceIdentityAnchors: vi.fn(),
      analyzeVoiceIdentity: vi.fn(),
      getVoiceDataset: vi.fn(),
      compileVoiceDataset: vi.fn(),
      updateVoiceDatasetSegment: vi.fn(),
      bulkUpdateVoiceDatasetSegments: vi.fn(),
      rescoreVoiceDataset: vi.fn(),
      analyzeVoiceDatasetQuality: vi.fn(),
      exportVoiceDataset: vi.fn(),
      scanLocalIngress: vi.fn(),
      uploadLocalIngress: vi.fn(),
      scanInstagramBrowserUrl: vi.fn(),
      scanInstagramHelperPayload: vi.fn(),
      listIngressCandidates: vi.fn(),
      ingressCandidateVideoPreviewUrl: vi.fn((candidateId: string) => `http://engine.test/ingress/candidates/${candidateId}/video-preview`),
      ingressCandidateThumbnailUrl: vi.fn((candidateId: string) => `http://engine.test/ingress/candidates/${candidateId}/thumbnail`),
      analyzeIngressCandidates: vi.fn(),
      createIngressJob: vi.fn(),
      listIngressJobs: vi.fn().mockResolvedValue([]),
      getIngressJob: vi.fn(),
      createProcessingJob: vi.fn(),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      getProcessingJob: vi.fn(),
      processProcessingJob: vi.fn(),
      updateVideoKeepers: vi.fn(),
      commitVideoBreakdown: vi.fn(),
      listCharacterProjects: vi.fn().mockResolvedValue([]),
      createCharacterProject: vi.fn(),
      getCharacterProject: vi.fn(),
      updateCharacterProject: vi.fn(),
      addCharacterProjectCandidates: vi.fn(),
      setCharacterProjectAnchors: vi.fn(),
      updateCharacterProjectObservation: vi.fn(),
      analyzeCharacterProject: vi.fn(),
      selectCharacterProjectFace: vi.fn(),
      updateCharacterProjectCrop: vi.fn(),
      materializeCharacterProjectCrop: vi.fn(),
      listDatasetSnapshots: vi.fn().mockResolvedValue([]),
      listTrainingTargets: vi.fn().mockResolvedValue([]),
      getDatasetSnapshot: vi.fn(),
      compileCharacterDataset: vi.fn(),
      updateDatasetItem: vi.fn(),
      bulkUpdateDatasetItems: vi.fn(),
      proposeDatasetStrongestSet: vi.fn(),
      proposeDatasetDuplicates: vi.fn(),
      applyDatasetStrongestSet: vi.fn(),
      restoreDatasetStrongestSet: vi.fn(),
      freezeDatasetSnapshot: vi.fn(),
      exportDatasetSnapshotRunComfy: vi.fn(),
      listVideoDatasetCandidates: vi.fn().mockResolvedValue([]),
      listVideoDatasetSnapshots: vi.fn().mockResolvedValue([]),
      getVideoDatasetSnapshot: vi.fn(),
      compileVideoDataset: vi.fn(),
      updateVideoDatasetItem: vi.fn(),
      bulkUpdateVideoDataset: vi.fn(),
      freezeVideoDataset: vi.fn(),
      exportVideoDataset: vi.fn(),
      listIdLoraManifests: vi.fn().mockResolvedValue([]),
      getIdLoraManifest: vi.fn(),
      compileIdLoraManifest: vi.fn(),
      exportIdLoraManifest: vi.fn(),
      createRunPodBundle: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      listRunPodModelBootstrapRuns: vi.fn().mockResolvedValue([]),
      getRunPodModelBootstrapRun: vi.fn(),
      createRunPodModelBootstrapRun: vi.fn(),
      refreshRunPodModelBootstrapRun: vi.fn(),
      cancelRunPodModelBootstrapRun: vi.fn(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([]),
      createRunPodPreflightReport: vi.fn(),
      getProviderReadiness: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
      listVoiceArtifactEvaluations: vi.fn().mockResolvedValue([]),
      getVoiceArtifactEvaluation: vi.fn(),
      getRecommendedVoiceArtifactEvaluation: vi.fn().mockResolvedValue(null),
      createVoiceArtifactEvaluation: vi.fn(),
      selectVoiceArtifactEvaluation: vi.fn(),
      listIdLoraEvaluations: vi.fn().mockResolvedValue([]),
      getIdLoraEvaluation: vi.fn(),
      createIdLoraEvaluation: vi.fn(),
      getTrainingWorkflow: vi.fn(),
      getBenchmarkSuite: vi.fn().mockResolvedValue([]),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      getImageBenchmarkSuite: vi.fn().mockResolvedValue([]),
      prepareImageBenchmarkWorkspace: vi.fn(),
      createImageBenchmarkGenerationRun: vi.fn(),
      createRunPodImageBenchmarkGenerationRun: vi.fn(),
      listImageBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getImageBenchmarkRun: vi.fn(),
      createImageBenchmarkRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn(),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      listModelReleaseCandidates: vi.fn().mockResolvedValue([]),
      selectModelRelease: vi.fn(),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      getComfyRuntimeStatus: vi.fn(),
      installModelArtifact: vi.fn(),
      listCaptionProviders: vi.fn().mockResolvedValue([]),
      startGrokOAuthLogin: vi.fn(),
      listCaptionJobs: vi.fn().mockResolvedValue([]),
      getCaptionJob: vi.fn(),
      cancelCaptionJob: vi.fn(),
      createCaptionJob: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine.test/assets/file?path=${encodeURIComponent(path)}`),
      ...overrides,
    };
  }

  beforeEach(() => {
    openMock.mockReset();
    isTauriMock.mockReturnValue(true);
    delete (window as WindowWithHostBridge).loraSuiteHost;
    delete (window as WindowWithHostBridge).showDirectoryPicker;
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function scanInstagramUrl(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));
  }

  it("reloads existing ingress jobs from the engine after a page refresh", async () => {
    const importedMediaItem = {
      id: "media_imported",
      raw_path: "/tmp/vault/raw/imported.png",
      media_type: "image",
    } as const;
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      reviewed_candidate_ids: [instagramPosterCandidate.id, instagramVideoCandidate.id],
      candidate_count: 2,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 1,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; candidates deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [importedMediaItem],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const listIngressJobs = vi.fn().mockResolvedValue([completedJob]);
    const engine = engineWith({ listIngressJobs });
    const onMediaItemsImported = vi.fn();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={onMediaItemsImported}
      />,
    );

    expect(listIngressJobs).toHaveBeenCalledOnce();
    await waitFor(() => expect(onMediaItemsImported).toHaveBeenCalledWith([importedMediaItem]));
    const jobsTable = await screen.findByRole("table");
    const jobCells = within(within(jobsTable).getAllByRole("row")[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(jobCells).toEqual([
      "complete",
      "instagram",
      "1",
      "1",
      "1",
      "0",
      "Ingress complete; candidates deferred",
    ]);
  });

  it("restores and saves the data ingress draft across page refreshes", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      "lorasuite:data-ingress:draft:v1",
      JSON.stringify({
        manualPaths: "/Volumes/source",
        candidates: [instagramPosterCandidate],
        activeBatchCandidateIds: [instagramPosterCandidate.id],
        activeBatchConfirmed: false,
        selectedIds: [instagramPosterCandidate.id],
        viewMode: "list",
        mediaFilter: "all",
        surfaceFilter: "all",
        uploaderFilter: "all",
        showInstagramHelper: true,
        showAdvancedFallbacks: false,
        mediaDestination: "/Volumes/Training/MarySue",
        instagramUrl: "https://www.instagram.com/marysuecurtis/reels/",
        instagramBrowser: "firefox",
        instagramScanLimit: "36",
        instagramScanMode: "tagged",
        instagramNextCursor: "cursor_2",
        instagramBatchNumber: 1,
        instagramPayloadText: "{\n  \"helper_version\": \"fixture\",\n  \"media\": []\n}",
      }),
    );
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Instagram URL")).toHaveValue(
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    expect(screen.getByLabelText("Browser cookies")).toHaveValue("firefox");
    expect(screen.getByLabelText("Scan limit")).toHaveValue(36);
    expect(screen.getByRole("button", { name: "Tagged" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("/Volumes/Training/MarySue")).toBeInTheDocument();
    expect(screen.getByText("example reel poster")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next Batch" })).toBeDisabled();

    await user.clear(screen.getByLabelText("Instagram URL"));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/tagged/",
    );

    await waitFor(() => {
      const saved = JSON.parse(
        window.localStorage.getItem("lorasuite:data-ingress:draft:v1") ?? "{}",
      ) as { instagramUrl?: string };
      expect(saved.instagramUrl).toBe("https://www.instagram.com/marysuecurtis/tagged/");
    });
  });

  it("groups Instagram reel poster candidates under separate image and video selectors", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(await screen.findByText("example reel")).toBeInTheDocument();
    expect(screen.queryByText("example reel poster")).not.toBeInTheDocument();
    expect(screen.queryByText("example reel voice")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Select as image: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();
  });

  it("renders compact review tiles with metadata over the image", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    const tile = screen.getByRole("article", { name: "example reel" });
    expect(within(tile).getByText("720x1280")).toHaveClass("thumb-meta");
    expect(within(tile).getAllByText("ready")[0]).toHaveClass("thumb-status");
    expect(within(tile).getByText("image")).toHaveClass("role-chip-label");
    expect(within(tile).getByText("video")).toHaveClass("role-chip-label");
    expect(within(tile).getByText("voice")).toHaveClass("role-chip-label");
    expect(within(tile).queryByText("Select as image")).not.toBeInTheDocument();
    expect(container.querySelector(".role-statuses")).toBeNull();
  });

  it("selects all image, video, or voice roles independently", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Images" }));

    expect(screen.getByLabelText("Select as image: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Videos" }));

    expect(screen.getByLabelText("Select as image: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Voice" }));

    expect(screen.getByLabelText("Select as image: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).toBeChecked();
  });

  it("uses one Tauri local media picker for files and folders", async () => {
    const user = userEvent.setup();
    openMock.mockResolvedValue(["/tmp/portrait.png", "/tmp/session-folder"]);
    const scanLocalIngress = vi.fn().mockResolvedValue({
      id: "scan_local",
      candidates: [instagramPosterCandidate],
      errors: [],
    });
    const engine = engineWith({ scanLocalIngress });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Import Media" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Files" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Folder" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import Media" }));

    expect(openMock).toHaveBeenCalledWith({
      multiple: true,
      recursive: true,
      title: "Choose files or folders",
    });
    expect(scanLocalIngress).toHaveBeenCalledWith(["/tmp/portrait.png", "/tmp/session-folder"], true);
  });

  it("uses browser-safe local controls outside Tauri", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const uploadLocalIngress = vi.fn().mockResolvedValue({
      id: "scan_upload",
      candidates: [instagramPosterCandidate],
      errors: [],
    });
    const engine = engineWith({ uploadLocalIngress });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Import Media" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Destination" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Destination Path" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Path Scan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desktop Picker" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desktop Only" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Media destination")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Media destination path")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Default LoraSuite vault")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import Media" }));

    expect(screen.getByText("Browser Local Import")).toBeInTheDocument();
    expect(screen.queryByLabelText("Instagram helper payload")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Local media paths")).not.toBeInTheDocument();
    expect(openMock).not.toHaveBeenCalled();

    const uploadInput = container.querySelector<HTMLInputElement>(
      '[data-testid="browser-file-input"]',
    );
    expect(uploadInput).not.toBeNull();
    const file = new File(["image-bytes"], "portrait.png", { type: "image/png" });
    await user.upload(uploadInput as HTMLInputElement, file);

    expect(uploadLocalIngress).toHaveBeenCalledWith([file]);
    expect(await screen.findByText("example reel poster")).toBeInTheDocument();
  });

  it("adds browser file selections to the active local review batch", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const firstCandidate = {
      ...instagramPosterCandidate,
      id: "candidate_local_first",
      display_name: "first local image",
    };
    const secondCandidate = {
      ...instagramPosterCandidate,
      id: "candidate_local_second",
      display_name: "second local image",
    };
    const uploadLocalIngress = vi
      .fn()
      .mockResolvedValueOnce({ id: "scan_upload_1", candidates: [firstCandidate], errors: [] })
      .mockResolvedValueOnce({ id: "scan_upload_2", candidates: [secondCandidate], errors: [] });

    const { container } = render(
      <DataIngressTab
        engine={engineWith({ uploadLocalIngress })}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Import Media" }));
    const uploadInput = container.querySelector<HTMLInputElement>(
      '[data-testid="browser-file-input"]',
    );
    expect(uploadInput).not.toBeNull();

    await user.upload(
      uploadInput as HTMLInputElement,
      new File(["first"], "first.png", { type: "image/png" }),
    );
    expect(await screen.findByText("first local image")).toBeInTheDocument();

    await user.upload(
      uploadInput as HTMLInputElement,
      new File(["second"], "second.png", { type: "image/png" }),
    );

    expect(screen.getByText("first local image")).toBeInTheDocument();
    expect(await screen.findByText("second local image")).toBeInTheDocument();
    expect(screen.getByText("2 visible")).toBeInTheDocument();
  });

  it("uses a browser directory picker for media destinations when available", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const write = vi.fn();
    const close = vi.fn();
    const createWritable = vi.fn().mockResolvedValue({ write, close });
    const getFileHandle = vi.fn().mockResolvedValue({ createWritable });
    const directoryHandle = {
      name: "Training Output",
      getFileHandle,
    };
    (window as WindowWithHostBridge).showDirectoryPicker = vi
      .fn()
      .mockResolvedValue(directoryHandle);
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [
        {
          id: "media_1",
          raw_path: "/tmp/vault/raw/imported.png",
          media_type: "image",
        },
      ],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const responseBlob = new Blob(["copied-image"], { type: "image/png" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => responseBlob,
      }),
    );
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose Destination" }));

    expect((window as WindowWithHostBridge).showDirectoryPicker).toHaveBeenCalledOnce();
    expect(screen.getByText("Training Output")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Default LoraSuite vault")).not.toBeInTheDocument();

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      reviewed_candidate_ids: [instagramPosterCandidate.id],
    });
    expect(fetch).toHaveBeenCalledWith(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fraw%2Fimported.png",
    );
    expect(getFileHandle).toHaveBeenCalledWith("imported.png", { create: true });
    expect(write).toHaveBeenCalledWith(responseBlob);
    expect(close).toHaveBeenCalledOnce();
    expect(screen.getByText(/mirrored 1 file/)).toBeInTheDocument();
  });

  it("handles canceled browser destination selection without a native picker error", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    (window as WindowWithHostBridge).showDirectoryPicker = vi
      .fn()
      .mockRejectedValue(new DOMException("The user aborted a request.", "AbortError"));
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose Destination" }));

    expect(screen.getByText("Destination selection canceled.")).toBeInTheDocument();
    expect(screen.queryByText(/Native file picker unavailable/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Media destination")).not.toBeInTheDocument();
    expect(screen.queryByText("Default LoraSuite vault")).not.toBeInTheDocument();
  });

  it("uses a host file picker bridge when a non-Tauri wrapper exposes one", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const pickMediaPaths = vi.fn().mockResolvedValue(["/host/portrait.png", "/host/session"]);
    const pickDestinationPath = vi.fn().mockResolvedValue("/host/output");
    (window as WindowWithHostBridge).loraSuiteHost = {
      pickMediaPaths,
      pickDestinationPath,
    };
    const scanLocalIngress = vi.fn().mockResolvedValue({
      id: "scan_local",
      candidates: [instagramPosterCandidate],
      errors: [],
    });
    const engine = engineWith({ scanLocalIngress });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Import Media" }));

    expect(pickMediaPaths).toHaveBeenCalledOnce();
    expect(openMock).not.toHaveBeenCalled();
    expect(scanLocalIngress).toHaveBeenCalledWith(["/host/portrait.png", "/host/session"], true);

    await user.click(screen.getByRole("button", { name: "Choose Destination" }));

    expect(pickDestinationPath).toHaveBeenCalledOnce();
    expect(screen.getByText("/host/output")).toBeInTheDocument();
  });

  it("keeps ingress counters in the top header", () => {
    render(
      <DataIngressTab
        engine={engineWith()}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    const summary = screen.getByLabelText("Ingress summary");

    expect(summary.closest(".section-header")).not.toBeNull();
    expect(summary.closest(".ingress-status-strip")).toBeNull();
  });

  it("selects the media destination with a folder picker", async () => {
    const user = userEvent.setup();
    openMock.mockResolvedValue("/Volumes/Training/MarySue");
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose Destination" }));

    expect(openMock).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: "Choose media destination",
      canCreateDirectories: true,
    });
    expect(screen.getByText("/Volumes/Training/MarySue")).toBeInTheDocument();
  });

  it("sends the selected media destination with the ingress job", async () => {
    const user = userEvent.setup();
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; candidates deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    openMock.mockResolvedValue("/Volumes/Training/MarySue");
    await user.click(screen.getByRole("button", { name: "Choose Destination" }));
    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      reviewed_candidate_ids: [instagramPosterCandidate.id],
      options: {
        destination_root: "/Volumes/Training/MarySue",
      },
    });
  });

  it("sends a browser-entered media destination with the ingress job", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Destination Path" }));
    await user.type(
      screen.getByLabelText("Media destination path"),
      "/Volumes/Training/WebVault",
    );
    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      reviewed_candidate_ids: [instagramPosterCandidate.id],
      options: {
        destination_root: "/Volumes/Training/WebVault",
      },
    });
  });

  it("sends the selected Instagram scan limit to the engine", async () => {
    const user = userEvent.setup();
    const scanInstagramBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_1",
      candidates: [],
      errors: [],
    });
    const engine = engineWith({ scanInstagramBrowserUrl });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "8");
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(scanInstagramBrowserUrl).toHaveBeenCalledWith(
      "https://www.instagram.com/marysuecurtis/reels/",
      "chrome",
      8,
      undefined,
      "all",
      undefined,
      undefined,
    );
  });

  it("scans X with browser cookies, dates, and a bounded candidate batch", async () => {
    const user = userEvent.setup();
    const scanXBrowserUrl = vi.fn().mockResolvedValue({
      id: "x-scan-1",
      candidates: [{
        id: "x-image-1",
        source_kind: "x_twitter",
        source_locator: "https://x.com/subject/status/1",
        display_name: "X portrait",
        media_type: "image",
        status: "ready",
        selected: true,
        metadata_json: { download_url: "https://pbs.twimg.com/media/1.jpg" },
      }],
      errors: [],
      metadata_json: { next_cursor: "12", has_more: true },
    });
    const engine = engineWith({ scanXBrowserUrl });

    render(<DataIngressTab engine={engine} mediaItems={[]} onMediaItemsImported={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "X Source" }));
    await user.type(screen.getByLabelText("X URL"), "https://x.com/subject");
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "12");
    await user.selectOptions(screen.getByLabelText("Browser cookies"), "firefox");
    await user.type(screen.getByLabelText("From"), "2026-01-01");
    await user.click(screen.getByRole("button", { name: "Scan X" }));

    expect(scanXBrowserUrl).toHaveBeenCalledWith(
      "https://x.com/subject",
      "firefox",
      12,
      undefined,
      "2026-01-01",
      undefined,
    );
    expect(await screen.findByText("X portrait")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next Batch" })).toBeDisabled();
  });

  it("scans TikTok with browser cookies, dates, and a bounded candidate batch", async () => {
    const user = userEvent.setup();
    const scanTikTokBrowserUrl = vi.fn().mockResolvedValue({
      id: "tiktok-scan-1",
      candidates: [{
        id: "tiktok-video-1",
        source_kind: "tiktok",
        source_locator: "https://www.tiktok.com/@subject/video/1",
        display_name: "TikTok speaking clip",
        media_type: "video",
        status: "ready",
        selected: false,
        metadata_json: {
          source_url: "https://www.tiktok.com/@subject/video/1",
          audio_original: true,
        },
      }],
      errors: [],
      metadata_json: { next_cursor: "12", has_more: true },
    });
    const engine = engineWith({ scanTikTokBrowserUrl });

    render(<DataIngressTab engine={engine} mediaItems={[]} onMediaItemsImported={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "TikTok Source" }));
    await user.type(screen.getByLabelText("TikTok URL"), "https://www.tiktok.com/@subject");
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "12");
    await user.selectOptions(screen.getByLabelText("Browser cookies"), "firefox");
    await user.type(screen.getByLabelText("From"), "2026-01-01");
    await user.click(screen.getByRole("button", { name: "Scan TikTok" }));

    expect(scanTikTokBrowserUrl).toHaveBeenCalledWith(
      "https://www.tiktok.com/@subject",
      "firefox",
      12,
      undefined,
      "2026-01-01",
      undefined,
    );
    expect(await screen.findByText("TikTok speaking clip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next Batch" })).toBeDisabled();
  });

  it("sends the selected Instagram scan target to the engine", async () => {
    const user = userEvent.setup();
    const scanInstagramBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_1",
      candidates: [],
      errors: [],
    });
    const engine = engineWith({ scanInstagramBrowserUrl });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/",
    );
    const scanTarget = screen.getByRole("group", { name: "Scan target" });
    expect(within(scanTarget).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(within(scanTarget).getByRole("button", { name: "Reels" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(scanInstagramBrowserUrl).toHaveBeenCalledWith(
      "https://www.instagram.com/marysuecurtis/",
      "chrome",
      24,
      undefined,
      "reels",
      undefined,
      undefined,
    );
  });

  it("sends an optional Instagram post date range to the engine", async () => {
    const user = userEvent.setup();
    const scanInstagramBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_1",
      candidates: [],
      errors: [],
    });
    const engine = engineWith({ scanInstagramBrowserUrl });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/",
    );
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2025-12-31" } });
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(scanInstagramBrowserUrl).toHaveBeenCalledWith(
      "https://www.instagram.com/marysuecurtis/",
      "chrome",
      24,
      undefined,
      "all",
      "2024-01-01",
      "2025-12-31",
    );
  });

  it("shows Instagram surface warnings returned with a partial batch", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [
          {
            code: "instagram_surface_error",
            surface: "reels",
            message: "Instagram request failed with HTTP 401.",
          },
        ],
        metadata_json: {
          failed_scan_surfaces: ["reels"],
        },
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(
      await screen.findByText(
        "Loaded Instagram batch 1: 1 candidate(s). No more batches. Warning: reels skipped.",
      ),
    ).toBeInTheDocument();
  });

  it("requires confirming the current Instagram batch before loading the next batch", async () => {
    const user = userEvent.setup();
    const firstSelectedCandidate: IngressCandidate = {
      id: "candidate_first_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/FIRST/",
      display_name: "first batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/first.jpg",
      status: "ready",
      selected: true,
    };
    const firstDeferredCandidate: IngressCandidate = {
      id: "candidate_deferred_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/DEFERRED/",
      display_name: "deferred batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/deferred.jpg",
      status: "ready",
      selected: false,
    };
    const secondBatchCandidate: IngressCandidate = {
      id: "candidate_second_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/SECOND/",
      display_name: "second batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/second.jpg",
      status: "ready",
      selected: true,
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [firstSelectedCandidate.id],
      candidate_count: 2,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 1,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; candidates deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const scanInstagramBrowserUrl = vi
      .fn()
      .mockResolvedValueOnce({
        id: "scan_1",
        candidates: [firstSelectedCandidate, firstDeferredCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: true,
          next_cursor: "cursor_2",
        },
      })
      .mockResolvedValueOnce({
        id: "scan_2",
        candidates: [secondBatchCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: false,
        },
      });
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const engine = engineWith({
      scanInstagramBrowserUrl,
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "2");
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));
    expect(await screen.findByLabelText("Select as image: first batch image")).toBeChecked();
    expect(screen.getByLabelText("Select as image: deferred batch image")).not.toBeChecked();

    const reviewHeader = screen
      .getByRole("heading", { name: "Review" })
      .closest(".review-header");
    expect(reviewHeader).not.toBeNull();
    const confirmButton = within(reviewHeader as HTMLElement).getByRole("button", {
      name: "Confirm Ingest",
    });
    const nextBatchButton = within(reviewHeader as HTMLElement).getByRole("button", {
      name: "Next Batch",
    });
    expect(nextBatchButton).toBeDisabled();

    await user.click(confirmButton);

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [firstSelectedCandidate.id],
      reviewed_candidate_ids: [firstSelectedCandidate.id, firstDeferredCandidate.id],
    });
    const jobsTable = await screen.findByRole("table");
    const jobCells = within(within(jobsTable).getAllByRole("row")[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(jobCells).toEqual([
      "complete",
      "instagram",
      "1",
      "1",
      "1",
      "0",
      "Ingress complete; candidates deferred",
    ]);
    expect(
      screen.getByText("Ingress complete; candidates deferred: 1 imported, 1 deferred, 0 failed."),
    ).toBeInTheDocument();
    expect(screen.queryByText("first batch image")).not.toBeInTheDocument();
    expect(screen.queryByText("deferred batch image")).not.toBeInTheDocument();
    expect(nextBatchButton).not.toBeDisabled();

    await user.click(nextBatchButton);

    expect(await screen.findByText("second batch image")).toBeInTheDocument();
    expect(screen.queryByText("first batch image")).not.toBeInTheDocument();
    expect(screen.queryByText("deferred batch image")).not.toBeInTheDocument();
    expect(scanInstagramBrowserUrl).toHaveBeenLastCalledWith(
      "https://www.instagram.com/marysuecurtis/reels/",
      "chrome",
      2,
      "cursor_2",
      "all",
      undefined,
      undefined,
    );
    expect(screen.getByRole("button", { name: "Next Batch" })).toBeDisabled();
  });

  it("can confirm an Instagram batch with no selections to defer it all", async () => {
    const user = userEvent.setup();
    const firstBatchCandidate: IngressCandidate = {
      id: "candidate_first_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/FIRST/",
      display_name: "first batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/first.jpg",
      status: "ready",
      selected: true,
    };
    const secondBatchCandidate: IngressCandidate = {
      id: "candidate_second_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/SECOND/",
      display_name: "second batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/second.jpg",
      status: "ready",
      selected: true,
    };
    const scanInstagramBrowserUrl = vi
      .fn()
      .mockResolvedValueOnce({
        id: "scan_1",
        candidates: [firstBatchCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: true,
          next_cursor: "cursor_2",
        },
      })
      .mockResolvedValueOnce({
        id: "scan_2",
        candidates: [secondBatchCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: false,
        },
      });
    const createIngressJob = vi.fn();
    const engine = engineWith({
      scanInstagramBrowserUrl,
      createIngressJob,
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));
    await user.click(await screen.findByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).not.toHaveBeenCalled();
    expect(screen.queryByText("first batch image")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next Batch" })).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next Batch" }));

    expect(await screen.findByText("second batch image")).toBeInTheDocument();
  });

  it("removes confirmed candidates from the review page", async () => {
    const user = userEvent.setup();
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
      createIngressJob: vi.fn().mockResolvedValue({
        ...completedJob,
        status: "queued",
        progress_message: "Queued",
      }),
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    expect(await screen.findByText("example reel poster")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(screen.queryByText("example reel poster")).not.toBeInTheDocument();
    expect(screen.getByText("No candidates scanned yet.")).toBeInTheDocument();
  });

  it("filters scanned Instagram candidates by surface and uploader ownership", async () => {
    const user = userEvent.setup();
    const ownedReelCandidate: IngressCandidate = {
      ...instagramPosterCandidate,
      id: "candidate_owned_reel",
      display_name: "owned reel poster",
      metadata_json: {
        ...instagramPosterCandidate.metadata_json,
        scan_surface: "reels",
        owner_username: "marysuecurtis",
        uploader_username: "marysuecurtis",
      },
    };
    const taggedCandidate: IngressCandidate = {
      ...instagramPosterCandidate,
      id: "candidate_tagged_reel",
      display_name: "tagged birthday poster",
      metadata_json: {
        ...instagramPosterCandidate.metadata_json,
        scan_surface: "tagged",
        owner_username: "marysuecurtis",
        uploader_username: "ileannageorginna",
      },
    };
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [ownedReelCandidate, taggedCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(await screen.findByText("owned reel poster")).toBeInTheDocument();
    expect(screen.getByText("tagged birthday poster")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Surface"), "tagged");

    expect(screen.queryByText("owned reel poster")).not.toBeInTheDocument();
    expect(screen.getByText("tagged birthday poster")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Surface"), "all");
    await user.selectOptions(screen.getByLabelText("Uploader"), "other");

    expect(screen.queryByText("owned reel poster")).not.toBeInTheDocument();
    expect(screen.getByText("tagged birthday poster")).toBeInTheDocument();
  });

  it("opens a source preview for video candidates", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Preview video: example reel" }));

    expect(
      screen.getByRole("dialog", { name: "Video preview: example reel" }),
    ).toBeInTheDocument();
    expect(container.querySelector("video")?.getAttribute("src")).toBe(
      "https://cdninstagram.example/video.mp4",
    );
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("routes X video previews through the local engine", async () => {
    const user = userEvent.setup();
    const xVideoCandidate: IngressCandidate = {
      id: "x-video-1",
      source_kind: "x_twitter",
      source_locator: "https://x.com/subject/status/1",
      display_name: "X speaking clip",
      media_type: "video",
      status: "ready",
      selected: false,
      metadata_json: {
        download_url: "https://video.twimg.com/ext_tw_video/1/clip.mp4",
      },
    };
    const engine = engineWith({
      scanXBrowserUrl: vi.fn().mockResolvedValue({
        id: "x-scan-1",
        candidates: [xVideoCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "X Source" }));
    await user.type(screen.getByLabelText("X URL"), "https://x.com/subject");
    await user.click(screen.getByRole("button", { name: "Scan X" }));
    await user.click(await screen.findByRole("button", { name: "Preview video: X speaking clip" }));

    expect(engine.ingressCandidateVideoPreviewUrl).toHaveBeenCalledWith("x-video-1");
    expect(container.querySelector("video")?.getAttribute("src")).toBe(
      "http://engine.test/ingress/candidates/x-video-1/video-preview",
    );
  });

  it("dims reels with non-original audio while keeping voice selectable", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [
          nonOriginalAudioVideoCandidate,
          nonOriginalAudioPosterCandidate,
          nonOriginalAudioVoiceCandidate,
        ],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    const tile = screen.getByRole("article", { name: "reused audio reel" });
    const voiceSelector = screen.getByLabelText("Select as voice: reused audio reel");

    expect(tile).not.toHaveClass("audio-not-original");
    expect(voiceSelector.closest(".role-chip")).toHaveClass("audio-ineligible");
    expect(voiceSelector).not.toBeDisabled();
    expect(voiceSelector).not.toBeChecked();

    await user.click(voiceSelector);

    expect(voiceSelector).toBeChecked();
  });

  it("renders a compact video preview popout", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Preview video: example reel" }));

    expect(container.querySelector(".video-preview-dialog")).toHaveClass("compact");
  });

  it("renders delayed enlarged image previews for thumbnails", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(screen.getByAltText("Enlarged preview for example reel poster")).toHaveClass(
      "hover-preview",
    );
  });

  it("keeps helper payload and local media paths behind advanced controls", async () => {
    const user = userEvent.setup();
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));

    expect(screen.getByLabelText("Instagram URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Browser cookies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan Instagram" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Instagram helper payload")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Local media paths")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));

    expect(screen.getByLabelText("Instagram helper payload")).toBeInTheDocument();
    expect(screen.getByLabelText("Local media paths")).toBeInTheDocument();
  });

  it("includes thumbnails in list view", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "List" }));

    const image = container.querySelector(".candidate-list img");
    expect(image).not.toBeNull();
    expect(image?.getAttribute("src")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fsocial%2Fexample.jpg",
    );
  });

  it("shows deferred original downloads in the ingress job table", async () => {
    const user = userEvent.setup();
    const candidate: IngressCandidate = {
      id: "candidate_video",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/reel/example/",
      display_name: "example reel",
      media_type: "video",
      duration: 9.5,
      status: "ready",
      selected: true,
      metadata_json: {
        download_url: "https://cdninstagram.example/video.mp4",
      },
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [candidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 0,
      deferred_count: 1,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; original downloads deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const engine: EngineClient = engineWith({
      scanInstagramBrowserUrl: vi.fn(),
      scanInstagramHelperPayload: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [candidate],
        errors: [],
      }),
      createIngressJob: vi.fn().mockResolvedValue({
        ...completedJob,
        status: "queued",
        progress_message: "Queued",
      }),
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram Helper Payload" }));
    await user.click(await screen.findByRole("button", { name: "Confirm Ingest" }));

    const jobsTable = await screen.findByRole("table");
    expect(within(jobsTable).getByRole("columnheader", { name: "Deferred" })).toBeInTheDocument();
    expect(within(jobsTable).getAllByRole("cell", { name: "1" })).toHaveLength(2);
    expect(
      screen.getByText("Ingress complete; original downloads deferred: 0 imported, 1 deferred, 0 failed."),
    ).toBeInTheDocument();
  });

  it("renders scanned thumbnails through the engine asset endpoint", async () => {
    const user = userEvent.setup();
    const candidate: IngressCandidate = {
      id: "candidate_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/reel/example/#poster",
      display_name: "example poster",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/poster.jpg",
      status: "ready",
      selected: true,
    };
    const engine: EngineClient = engineWith({
      scanInstagramHelperPayload: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [candidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram Helper Payload" }));

    const image = container.querySelector("img");
    expect(image).not.toBeNull();
    expect(image?.getAttribute("src")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fsocial%2Fposter.jpg",
    );
    expect(engine.assetUrl).toHaveBeenCalledWith("/tmp/vault/previews/social/poster.jpg");
  });

  it("exposes queue and vault reset controls in Advanced Studio", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      "lorasuite:data-ingress:draft:v1",
      JSON.stringify({
        candidates: [instagramPosterCandidate],
        activeBatchCandidateIds: [instagramPosterCandidate.id],
        activeBatchConfirmed: false,
        selectedIds: [instagramPosterCandidate.id],
      }),
    );
    const clearAllMedia = vi.fn().mockResolvedValue({
      status: "cleared",
      files_removed: 7,
      bytes_removed: 2048,
    });
    const onAllMediaCleared = vi.fn();

    render(
      <DataIngressTab
        engine={engineWith({ clearAllMedia })}
        mediaItems={[{ id: "media_1", media_type: "image", raw_path: "/vault/raw/media.jpg" }]}
        onMediaItemsImported={vi.fn()}
        onAllMediaCleared={onAllMediaCleared}
      />,
    );

    expect(screen.getByText("example reel poster")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear queue" }));
    expect(screen.queryByText("example reel poster")).not.toBeInTheDocument();
    expect(screen.getByText("Candidate queue cleared. Confirmed vault media was not changed.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear all media" }));
    expect(clearAllMedia).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm clear all" }));

    await waitFor(() => expect(clearAllMedia).toHaveBeenCalledWith("CLEAR ALL MEDIA"));
    expect(onAllMediaCleared).toHaveBeenCalledOnce();
    expect(screen.getByText("All imported media and dependent workspace data were cleared.")).toBeInTheDocument();
  });
});
