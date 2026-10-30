import { ProjectMediaLibrary } from "./ProjectMediaLibrary";
import { useProjectMedia } from "../lib/useProjectMedia";
import type { WizardTarget } from "./WorkflowWizard";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { ArrowRight, AtSign, CalendarRange, Check, Folder, FolderInput, FolderOpen, Instagram, Music2, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent } from "react";

import type { EngineClient } from "../lib/api";
import { acquireSocialMedia, socialAcquisitionError } from "../lib/socialAcquisition";
import type {
  IngressCandidate,
  IngressJob,
  IngressScanResult,
  InstagramScanMode,
  MediaItem,
  SocialAcquisitionJob,
} from "../lib/types";

type ViewMode = "tile" | "list" | "gallery";
type MediaFilter = "all" | "image" | "video" | "audio";
type CandidateRole = "image" | "video" | "audio";
type SurfaceFilter = "all" | "feed" | "reels" | "tagged" | "direct" | "unknown";
type UploaderFilter = "all" | "owner" | "other" | "unknown";
type PathSelection = string | string[] | null;
type SocialSource = "instagram" | "x" | "tiktok";

interface RuntimeCapabilities {
  pickLocalMedia?: () => Promise<PathSelection>;
  pickMediaDestination?: () => Promise<PathSelection>;
  pickBrowserDestination?: () => Promise<BrowserDirectoryHandle>;
}

interface HostPathBridge {
  pickMediaPaths?: () => Promise<PathSelection>;
  pickDestinationPath?: () => Promise<PathSelection>;
}

interface BrowserDirectoryHandle {
  name: string;
  getFileHandle(
    name: string,
    options: { create: boolean },
  ): Promise<BrowserFileHandle>;
}

interface BrowserFileHandle {
  createWritable(): Promise<BrowserWritableFileStream>;
}

interface BrowserWritableFileStream {
  write(data: Blob): Promise<void> | void;
  close(): Promise<void> | void;
}

interface DataIngressDraft {
  manualPaths?: string;
  candidates?: IngressCandidate[];
  activeBatchCandidateIds?: string[] | null;
  activeBatchConfirmed?: boolean;
  selectedIds?: string[];
  viewMode?: ViewMode;
  mediaFilter?: MediaFilter;
  surfaceFilter?: SurfaceFilter;
  uploaderFilter?: UploaderFilter;
  showBrowserLocalImport?: boolean;
  showInstagramHelper?: boolean;
  showXHelper?: boolean;
  showTikTokHelper?: boolean;
  showAdvancedFallbacks?: boolean;
  mediaDestination?: string;
  instagramUrl?: string;
  instagramBrowser?: string;
  instagramScanLimit?: string;
  instagramScanMode?: InstagramScanMode;
  instagramDateFrom?: string;
  instagramDateTo?: string;
  instagramNextCursor?: string;
  instagramBatchNumber?: number;
  instagramPayloadText?: string;
  xUrl?: string;
  xBrowser?: string;
  xScanLimit?: string;
  xDateFrom?: string;
  xDateTo?: string;
  xNextCursor?: string;
  xBatchNumber?: number;
  tiktokUrl?: string;
  tiktokBrowser?: string;
  tiktokScanLimit?: string;
  tiktokDateFrom?: string;
  tiktokDateTo?: string;
  tiktokNextCursor?: string;
  tiktokBatchNumber?: number;
  activeSocialSource?: SocialSource;
  activeAcquisitionJobId?: string;
}

interface CandidateReviewItem {
  id: string;
  displayName: string;
  sourceLocator: string;
  imageCandidate?: IngressCandidate;
  videoCandidate?: IngressCandidate;
  audioCandidate?: IngressCandidate;
  thumbnailCandidate: IngressCandidate;
  candidates: IngressCandidate[];
}

interface DataIngressTabProps {
  activeProjectId?: string;
  target?: WizardTarget;
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
  onAllMediaCleared?(): void;
}

const viewModes: ViewMode[] = ["tile", "list", "gallery"];
const instagramScanModes: InstagramScanMode[] = ["all", "feed", "reels", "tagged"];
const browserCookieSources = ["chrome", "brave", "chromium", "edge", "firefox", "safari"] as const;
const dataIngressDraftStorageKey = "lorasuite:data-ingress:draft:v1";
const defaultInstagramPayloadText = '{\n  "helper_version": "fixture",\n  "media": []\n}';
const surfaceFilterOptions: SurfaceFilter[] = [
  "all",
  "feed",
  "reels",
  "tagged",
  "direct",
  "unknown",
];
const uploaderFilterOptions: UploaderFilter[] = ["all", "owner", "other", "unknown"];

export function DataIngressTab({
  activeProjectId = "", target = "image",
  engine,
  mediaItems,
  onMediaItemsImported,
  onAllMediaCleared,
}: DataIngressTabProps) {
  const draftKey = activeProjectId ? `lorasuite:data-ingress:draft:v2:${activeProjectId}:${target}` : dataIngressDraftStorageKey;
  const projectMedia = useProjectMedia(engine, mediaItems, activeProjectId);
  const [initialDraft] = useState<DataIngressDraft>(() => loadDataIngressDraft(draftKey));
  const [manualPaths, setManualPaths] = useState(initialDraft.manualPaths ?? "");
  const [status, setStatus] = useState("Idle");
  const [candidates, setCandidates] = useState<IngressCandidate[]>(
    () => initialDraft.candidates ?? [],
  );
  const [activeBatchCandidateIds, setActiveBatchCandidateIds] = useState<Set<string> | null>(() =>
    initialDraft.activeBatchCandidateIds ? new Set(initialDraft.activeBatchCandidateIds) : null,
  );
  const [activeBatchConfirmed, setActiveBatchConfirmed] = useState(
    initialDraft.activeBatchConfirmed ?? true,
  );
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(initialDraft.selectedIds ?? []),
  );
  const [viewMode, setViewMode] = useState<ViewMode>(initialDraft.viewMode ?? "tile");
  const [mediaFilter, setMediaFilter] = useState<MediaFilter>(initialDraft.mediaFilter ?? "all");
  const [surfaceFilter, setSurfaceFilter] = useState<SurfaceFilter>(
    initialDraft.surfaceFilter ?? "all",
  );
  const [uploaderFilter, setUploaderFilter] = useState<UploaderFilter>(
    initialDraft.uploaderFilter ?? "all",
  );
  const [galleryIndex, setGalleryIndex] = useState(0);
  const [jobs, setJobs] = useState<IngressJob[]>([]);
  const [showBrowserLocalImport, setShowBrowserLocalImport] = useState(
    initialDraft.showBrowserLocalImport ?? false,
  );
  const [showInstagramHelper, setShowInstagramHelper] = useState(
    initialDraft.showInstagramHelper ?? false,
  );
  const [showXHelper, setShowXHelper] = useState(initialDraft.showXHelper ?? false);
  const [showTikTokHelper, setShowTikTokHelper] = useState(
    initialDraft.showTikTokHelper ?? false,
  );
  const [showAdvancedFallbacks, setShowAdvancedFallbacks] = useState(
    initialDraft.showAdvancedFallbacks ?? false,
  );
  const [mediaDestination, setMediaDestination] = useState(initialDraft.mediaDestination ?? "");
  const [browserDestinationHandle, setBrowserDestinationHandle] =
    useState<BrowserDirectoryHandle | null>(null);
  const [instagramUrl, setInstagramUrl] = useState(initialDraft.instagramUrl ?? "");
  const [instagramBrowser, setInstagramBrowser] = useState(
    initialDraft.instagramBrowser ?? "chrome",
  );
  const [instagramScanLimit, setInstagramScanLimit] = useState(
    initialDraft.instagramScanLimit ?? "24",
  );
  const [instagramScanMode, setInstagramScanMode] = useState<InstagramScanMode>(
    initialDraft.instagramScanMode ?? "all",
  );
  const [instagramDateFrom, setInstagramDateFrom] = useState(
    initialDraft.instagramDateFrom ?? "",
  );
  const [instagramDateTo, setInstagramDateTo] = useState(
    initialDraft.instagramDateTo ?? "",
  );
  const [instagramNextCursor, setInstagramNextCursor] = useState<string | undefined>(
    initialDraft.instagramNextCursor,
  );
  const [instagramBatchNumber, setInstagramBatchNumber] = useState(
    initialDraft.instagramBatchNumber ?? 0,
  );
  const [xUrl, setXUrl] = useState(initialDraft.xUrl ?? "");
  const [xBrowser, setXBrowser] = useState(initialDraft.xBrowser ?? "chrome");
  const [xScanLimit, setXScanLimit] = useState(initialDraft.xScanLimit ?? "24");
  const [xDateFrom, setXDateFrom] = useState(initialDraft.xDateFrom ?? "");
  const [xDateTo, setXDateTo] = useState(initialDraft.xDateTo ?? "");
  const [xNextCursor, setXNextCursor] = useState<string | undefined>(initialDraft.xNextCursor);
  const [xBatchNumber, setXBatchNumber] = useState(initialDraft.xBatchNumber ?? 0);
  const [tiktokUrl, setTikTokUrl] = useState(initialDraft.tiktokUrl ?? "");
  const [tiktokBrowser, setTikTokBrowser] = useState(initialDraft.tiktokBrowser ?? "chrome");
  const [tiktokScanLimit, setTikTokScanLimit] = useState(initialDraft.tiktokScanLimit ?? "24");
  const [tiktokDateFrom, setTikTokDateFrom] = useState(initialDraft.tiktokDateFrom ?? "");
  const [tiktokDateTo, setTikTokDateTo] = useState(initialDraft.tiktokDateTo ?? "");
  const [tiktokNextCursor, setTikTokNextCursor] = useState<string | undefined>(initialDraft.tiktokNextCursor);
  const [tiktokBatchNumber, setTikTokBatchNumber] = useState(initialDraft.tiktokBatchNumber ?? 0);
  const [activeSocialSource, setActiveSocialSource] = useState<SocialSource | undefined>(initialDraft.activeSocialSource);
  const [activeAcquisitionJob, setActiveAcquisitionJob] = useState<SocialAcquisitionJob | null>(null);
  const [videoPreviewItem, setVideoPreviewItem] = useState<CandidateReviewItem | null>(null);
  const [clearingAllMedia, setClearingAllMedia] = useState(false);
  const [confirmingClearAll, setConfirmingClearAll] = useState(false);
  const [instagramPayloadText, setInstagramPayloadText] = useState(
    initialDraft.instagramPayloadText ?? defaultInstagramPayloadText,
  );
  const browserFileInputRef = useRef<HTMLInputElement>(null);
  const browserFolderInputRef = useRef<HTMLInputElement>(null);
  const runtimeCapabilities = detectRuntimeCapabilities();

  const activeCandidates = activeBatchCandidateIds
    ? candidates.filter((candidate) => activeBatchCandidateIds.has(candidate.id))
    : candidates;
  const reviewItems = buildReviewItems(activeCandidates);
  const visibleReviewItems = reviewItems.filter((item) =>
    itemMatchesReviewFilters(item, mediaFilter, surfaceFilter, uploaderFilter),
  );
  const selectedReadyCount = activeCandidates.filter(
    (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
  ).length;
  const skippedCount = candidates.filter((candidate) => candidate.status !== "ready").length;
  const hasActiveBatchCandidates = activeCandidates.length > 0;
  const activeSocialNextCursor = activeSocialSource === "x"
    ? xNextCursor
    : activeSocialSource === "tiktok"
      ? tiktokNextCursor
      : instagramNextCursor;
  const activeSocialBatchNumber = activeSocialSource === "x"
    ? xBatchNumber
    : activeSocialSource === "tiktok"
      ? tiktokBatchNumber
      : instagramBatchNumber;
  const canLoadNextSocialBatch = Boolean(activeSocialNextCursor && activeBatchConfirmed);
  const canLoadNextInstagramBatch = Boolean(instagramNextCursor && activeBatchConfirmed);
  const safeGalleryIndex =
    visibleReviewItems.length === 0
      ? 0
      : Math.min(galleryIndex, visibleReviewItems.length - 1);
  const galleryItem = visibleReviewItems[safeGalleryIndex];
  const hasVisibleItems = visibleReviewItems.length > 0;
  const hasVisibleImageCandidates = visibleReviewItems.some((item) =>
    candidateForRole(item, "image"),
  );
  const hasVisibleVideoCandidates = visibleReviewItems.some((item) =>
    candidateForRole(item, "video"),
  );
  const hasVisibleAudioCandidates = visibleReviewItems.some((item) =>
    candidateForRole(item, "audio"),
  );
  const hasUploaderMetadata = reviewItems.some((item) =>
    item.candidates.some((candidate) => {
      const owner = candidate.metadata_json?.owner_username;
      const uploader = candidate.metadata_json?.uploader_username;
      return typeof owner === "string" && typeof uploader === "string";
    }),
  );
  const canChooseMediaDestination = Boolean(
    runtimeCapabilities.pickMediaDestination || runtimeCapabilities.pickBrowserDestination,
  );

  useEffect(() => {
    let canceled = false;

    async function loadJobs() {
      try {
        const loadedJobs = await engine.listIngressJobs();
        if (!canceled && Array.isArray(loadedJobs)) {
          const scopedJobs = activeProjectId ? loadedJobs.filter((job) => job.options?.project_id === activeProjectId) : loadedJobs;
          setJobs(scopedJobs);
          const importedMediaItems = scopedJobs.flatMap(
            (job) => job.imported_media_items ?? [],
          );
          if (importedMediaItems.length > 0) {
            onMediaItemsImported(importedMediaItems);
          }
        }
      } catch (error) {
        if (!canceled) {
          setStatus(error instanceof Error ? error.message : "Could not reload ingress jobs.");
        }
      }
    }

    void loadJobs();

    return () => {
      canceled = true;
    };
  }, [engine, onMediaItemsImported, activeProjectId]);

  useEffect(() => {
    if (!confirmingClearAll) return undefined;
    const timer = window.setTimeout(() => setConfirmingClearAll(false), 5000);
    return () => window.clearTimeout(timer);
  }, [confirmingClearAll]);

  useEffect(() => {
    saveDataIngressDraft({
      manualPaths,
      candidates,
      activeBatchCandidateIds: activeBatchCandidateIds
        ? Array.from(activeBatchCandidateIds)
        : null,
      activeBatchConfirmed,
      selectedIds: Array.from(selectedIds),
      viewMode,
      mediaFilter,
      surfaceFilter,
      uploaderFilter,
      showBrowserLocalImport,
      showInstagramHelper,
      showXHelper,
      showTikTokHelper,
      showAdvancedFallbacks,
      mediaDestination: browserDestinationHandle ? "" : mediaDestination,
      instagramUrl,
      instagramBrowser,
      instagramScanLimit,
      instagramScanMode,
      instagramDateFrom,
      instagramDateTo,
      instagramNextCursor,
      instagramBatchNumber,
      instagramPayloadText,
      xUrl,
      xBrowser,
      xScanLimit,
      xDateFrom,
      xDateTo,
      xNextCursor,
      xBatchNumber,
      tiktokUrl,
      tiktokBrowser,
      tiktokScanLimit,
      tiktokDateFrom,
      tiktokDateTo,
      tiktokNextCursor,
      tiktokBatchNumber,
      activeSocialSource,
      activeAcquisitionJobId: activeAcquisitionJob?.id,
    }, draftKey);
  }, [
    manualPaths,
    candidates,
    activeBatchCandidateIds,
    activeBatchConfirmed,
    selectedIds,
    viewMode,
    mediaFilter,
    surfaceFilter,
    uploaderFilter,
    showBrowserLocalImport,
    showInstagramHelper,
    showXHelper,
    showTikTokHelper,
    showAdvancedFallbacks,
    mediaDestination,
    browserDestinationHandle,
    instagramUrl,
    instagramBrowser,
    instagramScanLimit,
    instagramScanMode,
    instagramDateFrom,
    instagramDateTo,
    instagramNextCursor,
    instagramBatchNumber,
    instagramPayloadText,
    xUrl,
    xBrowser,
    xScanLimit,
    xDateFrom,
    xDateTo,
    xNextCursor,
    xBatchNumber,
    tiktokUrl,
    tiktokBrowser,
    tiktokScanLimit,
    tiktokDateFrom,
    tiktokDateTo,
    tiktokNextCursor,
    tiktokBatchNumber,
    activeSocialSource,
    activeAcquisitionJob?.id,
  ]);

  useEffect(() => {
    const jobId = initialDraft.activeAcquisitionJobId;
    const getJob = engine.getSocialAcquisitionJob;
    if (!jobId || !getJob) return undefined;
    const restoredJobId = jobId;
    const loadJob = getJob;
    let canceled = false;

    async function restoreAcquisition() {
      try {
        let job = await loadJob(restoredJobId);
        if (!job || canceled) return;
        if (job.status === "queued" && engine.resumeSocialAcquisitionJob) {
          job = await engine.resumeSocialAcquisitionJob(job.id);
        }
        if (canceled) return;
        setActiveAcquisitionJob(job);
        setStatus(job.progress_message);
        if (job.status === "complete" && job.result) {
          applyRecoveredAcquisition(job);
          setActiveAcquisitionJob(null);
        } else if (job.status === "failed") {
          setStatus(socialAcquisitionError(job));
          setActiveAcquisitionJob(null);
        } else if (job.status === "canceled") {
          setActiveAcquisitionJob(null);
        }
      } catch (error) {
        if (!canceled) {
          setStatus(error instanceof Error ? error.message : "Could not restore social retrieval.");
          setActiveAcquisitionJob(null);
        }
      }
    }

    void restoreAcquisition();
    return () => {
      canceled = true;
    };
  }, [engine, initialDraft.activeAcquisitionJobId]);

  useEffect(() => {
    const jobId = activeAcquisitionJob?.id;
    const getJob = engine.getSocialAcquisitionJob;
    if (
      !jobId
      || !getJob
      || ["complete", "failed", "canceled"].includes(activeAcquisitionJob.status)
    ) {
      return undefined;
    }
    const polledJobId = jobId;
    const loadJob = getJob;
    let canceled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const job = await loadJob(polledJobId);
        if (!job || canceled) return;
        setActiveAcquisitionJob(job);
        setStatus(job.progress_message);
        if (job.status === "complete" && job.result) {
          applyRecoveredAcquisition(job);
          setActiveAcquisitionJob(null);
          return;
        }
        if (job.status === "failed") {
          setStatus(socialAcquisitionError(job));
          setActiveAcquisitionJob(null);
          return;
        }
        if (job.status === "canceled") {
          setActiveAcquisitionJob(null);
          return;
        }
        timer = window.setTimeout(() => void poll(), 500);
      } catch (error) {
        if (!canceled) {
          setStatus(error instanceof Error ? error.message : "Could not monitor social retrieval.");
        }
      }
    }

    timer = window.setTimeout(() => void poll(), 500);
    return () => {
      canceled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeAcquisitionJob?.id, engine]);

  async function chooseLocalMedia() {
    if (!runtimeCapabilities.pickLocalMedia) {
      setShowBrowserLocalImport((visible) => !visible);
      setStatus("Choose local files or a folder to upload for review.");
      return;
    }

    try {
      const selected = await runtimeCapabilities.pickLocalMedia();
      await scanDialogSelection(selected);
    } catch (error) {
      if (isPickerAbortError(error)) {
        setStatus("Media selection canceled.");
        return;
      }
      setStatus(dialogErrorMessage(error));
    }
  }

  async function chooseMediaDestination() {
    if (runtimeCapabilities.pickBrowserDestination) {
      try {
        const selected = await runtimeCapabilities.pickBrowserDestination();
        setBrowserDestinationHandle(selected);
        setMediaDestination(selected.name);
      } catch (error) {
        if (isPickerAbortError(error)) {
          setStatus("Destination selection canceled.");
          return;
        }
        setStatus(dialogErrorMessage(error));
      }
      return;
    }

    if (!runtimeCapabilities.pickMediaDestination) {
      setStatus("Enter a destination path directly in this runtime.");
      return;
    }

    try {
      const selected = await runtimeCapabilities.pickMediaDestination();
      if (!selected) {
        return;
      }
      setBrowserDestinationHandle(null);
      setMediaDestination(Array.isArray(selected) ? selected[0] ?? "" : selected);
    } catch (error) {
      if (isPickerAbortError(error)) {
        setStatus("Destination selection canceled.");
        return;
      }
      setStatus(dialogErrorMessage(error));
    }
  }

  async function scanManualPaths() {
    const paths = manualPaths
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    await scanPaths(paths);
  }

  async function scanBrowserLocalFiles(files: File[]) {
    if (files.length === 0) {
      setStatus("No local media selected.");
      return;
    }

    setStatus("Uploading local media for review.");
    try {
      const result = await engine.uploadLocalIngress(files);
      applyScanResult(result.candidates, { append: true });
      clearInstagramBatchState();
      setStatus(
        `Uploaded and scanned ${result.candidates.length} candidate(s). ${result.errors.length} upload error(s).`,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Local upload scan failed.");
    }
  }

  async function handleBrowserLocalFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    await scanBrowserLocalFiles(files);
  }

  function openBrowserFilePicker() {
    browserFileInputRef.current?.click();
  }

  function openBrowserFolderPicker() {
    browserFolderInputRef.current?.setAttribute("webkitdirectory", "");
    browserFolderInputRef.current?.click();
  }

  async function scanDialogSelection(selection: string | string[] | null) {
    if (!selection) {
      setStatus("No local media selected.");
      return;
    }
    const paths = Array.isArray(selection) ? selection : [selection];
    await scanPaths(paths);
  }

  async function scanPaths(paths: string[]) {
    if (paths.length === 0) {
      setStatus("Choose files, choose a folder, or enter at least one path.");
      return;
    }

    setStatus("Scanning local media.");
    try {
      const result = await engine.scanLocalIngress(paths, true);
      applyScanResult(result.candidates, { append: true });
      clearInstagramBatchState();
      setStatus(
        `Scanned ${result.candidates.length} candidate(s). ${result.errors.length} root error(s).`,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Scan failed.");
    }
  }

  async function scanInstagramHelperPayload() {
    try {
      const payload = JSON.parse(instagramPayloadText) as Record<string, unknown>;
      setStatus("Scanning Instagram helper payload.");
      const result = await engine.scanInstagramHelperPayload(payload, true);
      applyScanResult(result.candidates);
      clearInstagramBatchState();
      setStatus(`Scanned ${result.candidates.length} Instagram candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram helper scan failed.");
    }
  }

  async function scanInstagramBrowserUrl() {
    const url = instagramUrl.trim();
    if (!url) {
      setStatus("Enter an Instagram URL.");
      return;
    }
    const scanLimit = parseScanLimit(instagramScanLimit);
    if (scanLimit === null) {
      setStatus("Enter a scan limit between 1 and 100.");
      return;
    }
    if (instagramDateFrom && instagramDateTo && instagramDateFrom > instagramDateTo) {
      setStatus("Instagram start date must be on or before end date.");
      return;
    }

    try {
      setStatus("Scanning Instagram with browser cookies.");
      const result = await acquireSocialMedia(engine, {
        provider: "instagram",
        url,
        browser: instagramBrowser,
        limit: scanLimit,
        scan_mode: instagramScanMode,
        date_from: instagramDateFrom || undefined,
        date_to: instagramDateTo || undefined,
      }, updateAcquisitionProgress);
      applyScanResult(result.candidates, { append: false });
      applyInstagramBatchMetadata(result, { append: false });
      setActiveSocialSource("instagram");
      setStatus(instagramScanStatus(result, 1));
      setActiveAcquisitionJob(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram URL scan failed.");
      setActiveAcquisitionJob(null);
    }
  }

  async function loadNextInstagramBatch() {
    const url = instagramUrl.trim();
    const scanLimit = parseScanLimit(instagramScanLimit);
    if (!url || scanLimit === null || !instagramNextCursor) {
      setStatus("No next Instagram batch is available.");
      return;
    }
    if (!activeBatchConfirmed) {
      setStatus("Confirm the current batch before loading the next Instagram batch.");
      return;
    }

    try {
      setStatus("Loading next Instagram batch.");
      const result = await acquireSocialMedia(engine, {
        provider: "instagram",
        url,
        browser: instagramBrowser,
        limit: scanLimit,
        cursor: instagramNextCursor,
        scan_mode: instagramScanMode,
        date_from: instagramDateFrom || undefined,
        date_to: instagramDateTo || undefined,
      }, updateAcquisitionProgress);
      applyScanResult(result.candidates, { append: false });
      applyInstagramBatchMetadata(result, { append: true });
      setStatus(instagramScanStatus(result, instagramBatchNumber + 1));
      setActiveAcquisitionJob(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram batch load failed.");
      setActiveAcquisitionJob(null);
    }
  }

  async function scanXBrowserUrl(cursor?: string) {
    const url = xUrl.trim();
    const scanLimit = parseScanLimit(xScanLimit);
    if (!url) {
      setStatus("Enter an X profile or post URL.");
      return;
    }
    if (scanLimit === null) {
      setStatus("Enter an X scan limit between 1 and 100.");
      return;
    }
    if (xDateFrom && xDateTo && xDateFrom > xDateTo) {
      setStatus("X start date must be on or before end date.");
      return;
    }
    if (!engine.scanXBrowserUrl) {
      setStatus("This engine does not include X ingestion.");
      return;
    }
    try {
      const nextBatch = Boolean(cursor);
      setStatus(nextBatch ? "Loading next X batch." : "Scanning X with browser cookies.");
      const result = await acquireSocialMedia(engine, {
        provider: "x",
        url,
        browser: xBrowser,
        limit: scanLimit,
        cursor,
        date_from: xDateFrom || undefined,
        date_to: xDateTo || undefined,
      }, updateAcquisitionProgress);
      applyScanResult(result.candidates, { append: false });
      setXNextCursor(resultNextCursor(result));
      setXBatchNumber((current) => nextBatch ? current + 1 : 1);
      setActiveSocialSource("x");
      const batch = nextBatch ? xBatchNumber + 1 : 1;
      setStatus(`X batch ${batch}: ${result.candidates.length} candidate(s).`);
      setActiveAcquisitionJob(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "X scan failed.");
      setActiveAcquisitionJob(null);
    }
  }

  async function scanTikTokBrowserUrl(cursor?: string) {
    const url = tiktokUrl.trim();
    const scanLimit = parseScanLimit(tiktokScanLimit);
    if (!url) {
      setStatus("Enter a TikTok profile or post URL.");
      return;
    }
    if (scanLimit === null) {
      setStatus("Enter a TikTok scan limit between 1 and 100.");
      return;
    }
    if (tiktokDateFrom && tiktokDateTo && tiktokDateFrom > tiktokDateTo) {
      setStatus("TikTok start date must be on or before end date.");
      return;
    }
    if (!engine.scanTikTokBrowserUrl) {
      setStatus("This engine does not include TikTok ingestion.");
      return;
    }
    try {
      const nextBatch = Boolean(cursor);
      setStatus(nextBatch ? "Loading next TikTok batch." : "Scanning TikTok with browser cookies.");
      const result = await acquireSocialMedia(engine, {
        provider: "tiktok",
        url,
        browser: tiktokBrowser,
        limit: scanLimit,
        cursor,
        date_from: tiktokDateFrom || undefined,
        date_to: tiktokDateTo || undefined,
      }, updateAcquisitionProgress);
      applyScanResult(result.candidates, { append: false });
      setTikTokNextCursor(resultNextCursor(result));
      setTikTokBatchNumber((current) => nextBatch ? current + 1 : 1);
      setActiveSocialSource("tiktok");
      const batch = nextBatch ? tiktokBatchNumber + 1 : 1;
      setStatus(`TikTok batch ${batch}: ${result.candidates.length} candidate(s).`);
      setActiveAcquisitionJob(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "TikTok scan failed.");
      setActiveAcquisitionJob(null);
    }
  }

  function updateAcquisitionProgress(job: SocialAcquisitionJob) {
    setActiveAcquisitionJob(job);
    setStatus(job.progress_message);
  }

  async function cancelActiveAcquisition() {
    if (!activeAcquisitionJob || !engine.cancelSocialAcquisitionJob) return;
    try {
      const job = await engine.cancelSocialAcquisitionJob(activeAcquisitionJob.id);
      setActiveAcquisitionJob(job);
      setStatus(job.progress_message);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not cancel retrieval.");
    }
  }

  async function loadNextSocialBatch() {
    if (!activeBatchConfirmed) {
      setStatus("Confirm the current batch before loading the next batch.");
      return;
    }
    if (activeSocialSource === "x") {
      if (!xNextCursor) {
        setStatus("No next X batch is available.");
        return;
      }
      await scanXBrowserUrl(xNextCursor);
      return;
    }
    if (activeSocialSource === "tiktok") {
      if (!tiktokNextCursor) {
        setStatus("No next TikTok batch is available.");
        return;
      }
      await scanTikTokBrowserUrl(tiktokNextCursor);
      return;
    }
    await loadNextInstagramBatch();
  }

  async function loadInstagramHelperCandidates() {
    try {
      setStatus("Loading Instagram helper candidates.");
      const result = await engine.listIngressCandidates("instagram");
      applyScanResult(result.candidates);
      clearInstagramBatchState();
      setStatus(`Loaded ${result.candidates.length} Instagram helper candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Candidate load failed.");
    }
  }

  function applyScanResult(
    nextCandidates: IngressCandidate[],
    { append = false }: { append?: boolean } = {},
  ) {
    setCandidates((currentCandidates) =>
      append ? mergeCandidates(currentCandidates, nextCandidates) : nextCandidates,
    );
    setSelectedIds((currentIds) => {
      const nextIds = append ? new Set(currentIds) : new Set<string>();
      for (const candidate of nextCandidates) {
        if (candidate.status === "ready" && candidate.selected) {
          nextIds.add(candidate.id);
        }
      }
      return nextIds;
    });
    setActiveBatchCandidateIds((currentIds) => {
      const nextIds = append && currentIds ? new Set(currentIds) : new Set<string>();
      for (const candidate of nextCandidates) {
        nextIds.add(candidate.id);
      }
      return nextIds;
    });
    setActiveBatchConfirmed(nextCandidates.length === 0);
    setGalleryIndex(0);
  }

  function applyInstagramBatchMetadata(
    result: IngressScanResult,
    { append }: { append: boolean },
  ) {
    setInstagramNextCursor(resultNextCursor(result));
    setInstagramBatchNumber((currentBatchNumber) => (append ? currentBatchNumber + 1 : 1));
  }

  function applyRecoveredAcquisition(job: SocialAcquisitionJob) {
    const result = job.result;
    if (!result) return;
    applyScanResult(result.candidates, { append: false });
    const nextCursor = resultNextCursor(result);
    if (job.request.provider === "instagram") {
      setActiveSocialSource("instagram");
      setInstagramNextCursor(nextCursor);
      setInstagramBatchNumber((current) => job.request.cursor ? Math.max(1, current + 1) : 1);
    } else if (job.request.provider === "x") {
      setActiveSocialSource("x");
      setXNextCursor(nextCursor);
      setXBatchNumber((current) => job.request.cursor ? Math.max(1, current + 1) : 1);
    } else {
      setActiveSocialSource("tiktok");
      setTikTokNextCursor(nextCursor);
      setTikTokBatchNumber((current) => job.request.cursor ? Math.max(1, current + 1) : 1);
    }
    setStatus(`Recovered ${result.candidates.length} ${job.request.provider} candidate record(s) after restart.`);
  }

  function clearInstagramBatchState() {
    setInstagramNextCursor(undefined);
    setInstagramBatchNumber(0);
  }

  async function confirmIngest() {
    const batchCandidateIds = activeCandidates.map((candidate) => candidate.id);
    if (batchCandidateIds.length === 0) {
      setStatus("No candidates to confirm.");
      return;
    }

    const selectedCandidates = activeCandidates.filter(
      (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
    );
    const candidateIds = selectedCandidates.map((candidate) => candidate.id);
    const batchDeferredCount = batchCandidateIds.length - candidateIds.length;

    if (candidateIds.length === 0) {
      removeCandidates(batchCandidateIds);
      setActiveBatchConfirmed(true);
      setStatus(`Batch confirmed: 0 selected, ${batchDeferredCount} deferred.`);
      return;
    }

    const sourceKinds = new Set(selectedCandidates.map((candidate) => candidate.source_kind));
    if (sourceKinds.size !== 1) {
      setStatus("Confirm one source type at a time.");
      return;
    }
    const sourceKind = selectedCandidates[0]?.source_kind;
    if (!sourceKind) {
      setStatus("Select at least one ready candidate.");
      return;
    }

    setStatus("Creating ingress job.");
    try {
      const destinationRoot = mediaDestination.trim();
      const job = await engine.createIngressJob({
        ...(activeProjectId || (destinationRoot && !browserDestinationHandle) ? { options: { ...(activeProjectId ? { project_id: activeProjectId, target } : {}), ...(destinationRoot && !browserDestinationHandle ? { destination_root: destinationRoot } : {}) } } : {}),
        source_kind: sourceKind,
        candidate_ids: candidateIds,
        reviewed_candidate_ids: batchCandidateIds,

      });
      setJobs((currentJobs) => upsertJob(currentJobs, job));
      const completedJob = await waitForJob(job.id);
      setJobs((currentJobs) => upsertJob(currentJobs, completedJob));
      if (completedJob.imported_media_items.length > 0) {
        onMediaItemsImported(completedJob.imported_media_items);
      }
      const browserMirrorCount = browserDestinationHandle
        ? await mirrorImportedItemsToBrowserDestination(
            completedJob.imported_media_items,
            browserDestinationHandle,
            engine.assetUrl,
          )
        : 0;
      removeCandidates(batchCandidateIds);
      setActiveBatchConfirmed(true);
      const deferredCount = completedJob.deferred_count ?? 0;
      const progressSummary =
        `${completedJob.progress_message}: ${completedJob.imported_count} imported, ` +
        `${deferredCount} deferred, ${completedJob.failed_count} failed.`;
      const browserMirrorSuffix =
        browserMirrorCount > 0
          ? ` Browser destination mirrored ${browserMirrorCount} file(s).`
          : "";
      setStatus(
        `${progressSummary}${browserMirrorSuffix}`,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Ingress job failed.");
    }
  }

  async function waitForJob(jobId: string): Promise<IngressJob> {
    let currentJob = await engine.getIngressJob(jobId);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (
        currentJob.status === "complete" ||
        currentJob.status === "failed" ||
        currentJob.status === "canceled"
      ) {
        return currentJob;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
      currentJob = await engine.getIngressJob(jobId);
    }
    return currentJob;
  }

  function toggleCandidate(candidateId: string) {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      if (nextIds.has(candidateId)) {
        nextIds.delete(candidateId);
      } else {
        nextIds.add(candidateId);
      }
      return nextIds;
    });
  }

  function selectVisibleReadyCandidates() {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidate of candidatesForReviewItems(visibleReviewItems)) {
        if (candidate.status === "ready") {
          nextIds.add(candidate.id);
        }
      }
      return nextIds;
    });
  }

  function selectVisibleRoleCandidates(role: CandidateRole) {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const item of visibleReviewItems) {
        const candidate = candidateForRole(item, role);
        if (candidate?.status === "ready") {
          nextIds.add(candidate.id);
        }
      }
      return nextIds;
    });
  }

  function deselectVisibleCandidates() {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidate of candidatesForReviewItems(visibleReviewItems)) {
        nextIds.delete(candidate.id);
      }
      return nextIds;
    });
  }

  function invertVisibleReadyCandidates() {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidate of candidatesForReviewItems(visibleReviewItems)) {
        if (candidate.status !== "ready") continue;
        if (nextIds.has(candidate.id)) {
          nextIds.delete(candidate.id);
        } else {
          nextIds.add(candidate.id);
        }
      }
      return nextIds;
    });
  }

  function removeCandidates(candidateIds: string[]) {
    const removedIds = new Set(candidateIds);
    setCandidates((currentCandidates) =>
      currentCandidates.filter((candidate) => !removedIds.has(candidate.id)),
    );
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidateId of removedIds) {
        nextIds.delete(candidateId);
      }
      return nextIds;
    });
    setActiveBatchCandidateIds((currentBatchIds) => {
      if (currentBatchIds === null) return null;
      const nextBatchIds = new Set(currentBatchIds);
      for (const candidateId of removedIds) {
        nextBatchIds.delete(candidateId);
      }
      return nextBatchIds;
    });
    setGalleryIndex(0);
  }

  function clearCandidateQueue() {
    if (clearingAllMedia) return;
    setCandidates([]);
    setSelectedIds(new Set());
    setActiveBatchCandidateIds(null);
    setActiveBatchConfirmed(true);
    setGalleryIndex(0);
    setVideoPreviewItem(null);
    setInstagramNextCursor(undefined);
    setInstagramBatchNumber(0);
    setXNextCursor(undefined);
    setXBatchNumber(0);
    setTikTokNextCursor(undefined);
    setTikTokBatchNumber(0);
    setActiveSocialSource(undefined);
    setStatus("Candidate queue cleared. Confirmed vault media was not changed.");
  }

  async function clearAllMedia() {
    if (clearingAllMedia) return;
    if (!confirmingClearAll) {
      setConfirmingClearAll(true);
      return;
    }
    setClearingAllMedia(true);
    setStatus("Clearing imported media and dependent workspace data.");
    try {
      await engine.clearAllMedia("CLEAR ALL MEDIA");
      setCandidates([]);
      setSelectedIds(new Set());
      setActiveBatchCandidateIds(null);
      setActiveBatchConfirmed(true);
      setGalleryIndex(0);
      setVideoPreviewItem(null);
      setJobs([]);
      setInstagramNextCursor(undefined);
      setInstagramBatchNumber(0);
      setXNextCursor(undefined);
      setXBatchNumber(0);
      setTikTokNextCursor(undefined);
      setTikTokBatchNumber(0);
      setActiveSocialSource(undefined);
      setConfirmingClearAll(false);
      onAllMediaCleared?.();
      setStatus("All imported media and dependent workspace data were cleared.");
    } catch (error) {
      setConfirmingClearAll(false);
      setStatus(error instanceof Error ? error.message : "Could not clear all media.");
    } finally {
      setClearingAllMedia(false);
    }
  }

  return (
    <section className="workspace-section ingress-workspace">
      {activeProjectId ? <ProjectMediaLibrary items={projectMedia.items} assetUrl={engine.assetUrl} loading={projectMedia.loading} error={projectMedia.error} /> : null}
      <div className="section-header ingress-header">
        <div>
          <h2>Data Ingress</h2>
          <p>Scan local media, review candidates, then confirm only what should enter the vault.</p>
        </div>
        <dl className="metric-grid" aria-label="Ingress summary">
          <div>
            <dt>Imported</dt>
            <dd>{activeProjectId ? projectMedia.items.length : mediaItems.length}</dd>
          </div>
          <div>
            <dt>Candidates</dt>
            <dd>{candidates.length}</dd>
          </div>
          <div>
            <dt>Selected</dt>
            <dd>{selectedReadyCount}</dd>
          </div>
          <div>
            <dt>Skipped</dt>
            <dd>{skippedCount}</dd>
          </div>
        </dl>
      </div>

      <div className="ingress-topbar" aria-label="Ingress source actions">
        <div className="ingress-actions">
          <button className="primary-action ingress-source-action" type="button" onClick={chooseLocalMedia}>
            <FolderInput size={16} aria-hidden="true" /> Import Media
          </button>
          <button
            type="button"
            className="ingress-source-action"
            aria-label="Instagram Source"
            onClick={() => {
              setShowInstagramHelper((visible) => !visible);
              setShowXHelper(false);
              setShowTikTokHelper(false);
            }}
          >
            <Instagram size={16} aria-hidden="true" /> Instagram
          </button>
          {engine.scanXBrowserUrl ? <button
            type="button"
            className="ingress-source-action"
            aria-label="X Source"
            onClick={() => {
              setShowXHelper((visible) => !visible);
              setShowInstagramHelper(false);
              setShowTikTokHelper(false);
            }}
          >
            <AtSign size={16} aria-hidden="true" /> X
          </button> : null}
          {engine.scanTikTokBrowserUrl ? <button
            type="button"
            className="ingress-source-action"
            aria-label="TikTok Source"
            onClick={() => {
              setShowTikTokHelper((visible) => !visible);
              setShowInstagramHelper(false);
              setShowXHelper(false);
            }}
          >
            <Music2 size={16} aria-hidden="true" /> TikTok
          </button> : null}
        </div>
        <div className="ingress-storage-actions">
          <div className="destination-picker" role="group" aria-label="Destination controls">
            <button
              type="button"
              onClick={
                canChooseMediaDestination
                  ? chooseMediaDestination
                  : () => {
                      setShowAdvancedFallbacks(true);
                      setStatus("Enter a media destination path in Advanced Fallbacks.");
                    }
              }
            >
              <Folder size={15} aria-hidden="true" />
              {canChooseMediaDestination ? "Choose Destination" : "Destination Path"}
            </button>
            {mediaDestination ? (
              <span className="destination-summary" title={mediaDestination}>
                {mediaDestination}
              </span>
            ) : null}
          </div>
          <button
            type="button"
            className="ingress-clear-action"
            disabled={!candidates.length || clearingAllMedia}
            onClick={clearCandidateQueue}
          >
            <Trash2 size={15} aria-hidden="true" /> Clear queue
          </button>
          <button
            type="button"
            className={`ingress-clear-action clear-all ${confirmingClearAll ? "confirming" : ""}`}
            disabled={clearingAllMedia}
            title="Deletes imported media and dependent workspace data. Installed models, settings, and completed training artifacts are preserved."
            onClick={() => void clearAllMedia()}
          >
            <Trash2 size={15} aria-hidden="true" /> {confirmingClearAll ? "Confirm clear all" : "Clear all media"}
          </button>
        </div>
      </div>

      {showBrowserLocalImport && !runtimeCapabilities.pickLocalMedia && (
        <div className="form-stack helper-payload-panel instagram-panel browser-local-panel">
          <h3>Browser Local Import</h3>
          <div className="source-actions-row">
            <button type="button" onClick={openBrowserFilePicker}>
              <Plus size={15} aria-hidden="true" /> Choose Files
            </button>
            <button type="button" onClick={openBrowserFolderPicker}>
              <FolderOpen size={15} aria-hidden="true" /> Choose Folder
            </button>
          </div>
          <input
            ref={browserFileInputRef}
            className="visually-hidden"
            data-testid="browser-file-input"
            type="file"
            multiple
            onChange={handleBrowserLocalFileChange}
          />
          <input
            ref={browserFolderInputRef}
            className="visually-hidden"
            data-testid="browser-folder-input"
            type="file"
            multiple
            onChange={handleBrowserLocalFileChange}
          />
        </div>
      )}

      {showInstagramHelper && (
        <div className="form-stack helper-payload-panel instagram-panel ingress-instagram-panel">
          <div className="instagram-primary-row">
            <label className="instagram-url-field" htmlFor="instagram-url">
              Instagram URL
              <input
                id="instagram-url"
                value={instagramUrl}
                onChange={(event) => setInstagramUrl(event.target.value)}
                placeholder="https://www.instagram.com/reel/..."
              />
            </label>
            <label className="instagram-limit-field" htmlFor="instagram-scan-limit">
              Scan limit
              <input
                id="instagram-scan-limit"
                min="1"
                max="100"
                step="1"
                type="number"
                value={instagramScanLimit}
                onChange={(event) => setInstagramScanLimit(event.target.value)}
              />
            </label>
            <label className="instagram-cookie-field" htmlFor="instagram-browser">
              Browser cookies
              <select
                id="instagram-browser"
                value={instagramBrowser}
                onChange={(event) => setInstagramBrowser(event.target.value)}
              >
                {browserCookieSources.map((browser) => (
                  <option key={browser} value={browser}>
                    {browserLabel(browser)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="instagram-scan-options">
            <div className="scan-target-field">
              <span id="instagram-scan-mode-label">Scan target</span>
              <div
                className="segmented-control"
                role="group"
                aria-labelledby="instagram-scan-mode-label"
              >
                {instagramScanModes.map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={instagramScanMode === mode}
                    onClick={() => setInstagramScanMode(mode)}
                  >
                    {instagramScanModeLabel(mode)}
                  </button>
                ))}
              </div>
            </div>
            <div className="instagram-scan-actions">
              <button type="button" onClick={scanInstagramBrowserUrl}>
                Scan Instagram
              </button>
              <button
                type="button"
                aria-label="Advanced Fallbacks"
                onClick={() => setShowAdvancedFallbacks((visible) => !visible)}
              >
                Advanced
              </button>
            </div>
            <div className="instagram-date-controls" aria-label="Post date">
              <span className="instagram-date-title">
                <CalendarRange size={14} aria-hidden="true" />
                Post date
              </span>
              <label htmlFor="instagram-date-from">
                From
                <input
                  id="instagram-date-from"
                  type="date"
                  value={instagramDateFrom}
                  max={instagramDateTo || undefined}
                  onChange={(event) => {
                    setInstagramDateFrom(event.target.value);
                    clearInstagramBatchState();
                  }}
                />
              </label>
              <label htmlFor="instagram-date-to">
                To
                <input
                  id="instagram-date-to"
                  type="date"
                  value={instagramDateTo}
                  min={instagramDateFrom || undefined}
                  onChange={(event) => {
                    setInstagramDateTo(event.target.value);
                    clearInstagramBatchState();
                  }}
                />
              </label>
              <button
                type="button"
                disabled={!instagramDateFrom && !instagramDateTo}
                onClick={() => {
                  setInstagramDateFrom("");
                  setInstagramDateTo("");
                  clearInstagramBatchState();
                }}
              >
                Clear
              </button>
            </div>
          </div>
        </div>
      )}

      {showXHelper && engine.scanXBrowserUrl ? (
        <div className="form-stack helper-payload-panel instagram-panel ingress-instagram-panel" aria-label="X browser scan">
          <div className="instagram-primary-row">
            <label className="instagram-url-field" htmlFor="x-url">
              X URL
              <input id="x-url" value={xUrl} onChange={(event) => setXUrl(event.target.value)} placeholder="https://x.com/account" />
            </label>
            <label className="instagram-limit-field" htmlFor="x-scan-limit">
              Scan limit
              <input id="x-scan-limit" min="1" max="100" step="1" type="number" value={xScanLimit} onChange={(event) => setXScanLimit(event.target.value)} />
            </label>
            <label className="instagram-cookie-field" htmlFor="x-browser">
              Browser cookies
              <select id="x-browser" value={xBrowser} onChange={(event) => setXBrowser(event.target.value)}>
                {browserCookieSources.map((browser) => <option key={browser} value={browser}>{browserLabel(browser)}</option>)}
              </select>
            </label>
          </div>
          <div className="instagram-scan-options">
            <div className="instagram-scan-actions">
              <button type="button" onClick={() => void scanXBrowserUrl()}>Scan X</button>
            </div>
            <div className="instagram-date-controls" aria-label="X post date">
              <span className="instagram-date-title"><CalendarRange size={14} aria-hidden="true" />Post date</span>
              <label htmlFor="x-date-from">From<input id="x-date-from" type="date" value={xDateFrom} max={xDateTo || undefined} onChange={(event) => { setXDateFrom(event.target.value); setXNextCursor(undefined); setXBatchNumber(0); }} /></label>
              <label htmlFor="x-date-to">To<input id="x-date-to" type="date" value={xDateTo} min={xDateFrom || undefined} onChange={(event) => { setXDateTo(event.target.value); setXNextCursor(undefined); setXBatchNumber(0); }} /></label>
              <button type="button" disabled={!xDateFrom && !xDateTo} onClick={() => { setXDateFrom(""); setXDateTo(""); setXNextCursor(undefined); setXBatchNumber(0); }}>Clear</button>
            </div>
          </div>
        </div>
      ) : null}

      {showTikTokHelper && engine.scanTikTokBrowserUrl ? (
        <div className="form-stack helper-payload-panel instagram-panel ingress-instagram-panel" aria-label="TikTok browser scan">
          <div className="instagram-primary-row">
            <label className="instagram-url-field" htmlFor="tiktok-url">
              TikTok URL
              <input id="tiktok-url" value={tiktokUrl} onChange={(event) => setTikTokUrl(event.target.value)} placeholder="https://www.tiktok.com/@account" />
            </label>
            <label className="instagram-limit-field" htmlFor="tiktok-scan-limit">
              Scan limit
              <input id="tiktok-scan-limit" min="1" max="100" step="1" type="number" value={tiktokScanLimit} onChange={(event) => setTikTokScanLimit(event.target.value)} />
            </label>
            <label className="instagram-cookie-field" htmlFor="tiktok-browser">
              Browser cookies
              <select id="tiktok-browser" value={tiktokBrowser} onChange={(event) => setTikTokBrowser(event.target.value)}>
                {browserCookieSources.map((browser) => <option key={browser} value={browser}>{browserLabel(browser)}</option>)}
              </select>
            </label>
          </div>
          <div className="instagram-scan-options">
            <div className="instagram-scan-actions">
              <button type="button" onClick={() => void scanTikTokBrowserUrl()}>Scan TikTok</button>
            </div>
            <div className="instagram-date-controls" aria-label="TikTok post date">
              <span className="instagram-date-title"><CalendarRange size={14} aria-hidden="true" />Post date</span>
              <label htmlFor="tiktok-date-from">From<input id="tiktok-date-from" type="date" value={tiktokDateFrom} max={tiktokDateTo || undefined} onChange={(event) => { setTikTokDateFrom(event.target.value); setTikTokNextCursor(undefined); setTikTokBatchNumber(0); }} /></label>
              <label htmlFor="tiktok-date-to">To<input id="tiktok-date-to" type="date" value={tiktokDateTo} min={tiktokDateFrom || undefined} onChange={(event) => { setTikTokDateTo(event.target.value); setTikTokNextCursor(undefined); setTikTokBatchNumber(0); }} /></label>
              <button type="button" disabled={!tiktokDateFrom && !tiktokDateTo} onClick={() => { setTikTokDateFrom(""); setTikTokDateTo(""); setTikTokNextCursor(undefined); setTikTokBatchNumber(0); }}>Clear</button>
            </div>
          </div>
        </div>
      ) : null}

      {showAdvancedFallbacks && (
        <div className="form-stack helper-payload-panel instagram-panel">
          <label htmlFor="media-destination-path">Media destination path</label>
          <input
            id="media-destination-path"
            value={mediaDestination}
            onChange={(event) => {
              setBrowserDestinationHandle(null);
              setMediaDestination(event.target.value);
            }}
            placeholder="/optional/output/folder"
          />
          <label htmlFor="instagram-helper-payload">Instagram helper payload</label>
          <textarea
            id="instagram-helper-payload"
            value={instagramPayloadText}
            onChange={(event) => setInstagramPayloadText(event.target.value)}
            rows={8}
          />
          <button type="button" onClick={scanInstagramHelperPayload}>
            Scan Instagram Helper Payload
          </button>
          <button type="button" onClick={loadInstagramHelperCandidates}>
            Load Helper Candidates
          </button>
          <label htmlFor="manual-paths">Local media paths</label>
          <textarea
            id="manual-paths"
            value={manualPaths}
            onChange={(event) => setManualPaths(event.target.value)}
            rows={3}
            placeholder="/absolute/path/to/file-or-folder"
          />
          <button type="button" onClick={scanManualPaths}>
            Scan Paths
          </button>
        </div>
      )}

      <div className="ingress-status-strip">
        <p aria-live="polite" className="status-line">
          {status}
        </p>
        {activeAcquisitionJob && !["complete", "failed", "canceled"].includes(activeAcquisitionJob.status) ? (
          <button type="button" onClick={() => void cancelActiveAcquisition()}>
            <Trash2 size={14} aria-hidden="true" /> Cancel Retrieval
          </button>
        ) : null}
      </div>

      <div className="ingress-layout">
        <section className="review-panel" aria-label="Candidate review">
          <div className="panel-header review-header">
            <div className="review-title-line">
              <h3>Review</h3>
              <span className="review-visible-count">{visibleReviewItems.length} visible</span>
            </div>
            <div className="review-header-actions">
              <button
                className="primary-action"
                type="button"
                onClick={confirmIngest}
                disabled={!hasActiveBatchCandidates}
              >
                <Check size={14} aria-hidden="true" />
                Confirm Ingest
              </button>
              {activeSocialBatchNumber > 0 && (
                <button
                  type="button"
                  onClick={() => void loadNextSocialBatch()}
                  disabled={!canLoadNextSocialBatch}
                >
                  <ArrowRight size={14} aria-hidden="true" />
                  Next Batch
                </button>
              )}
            </div>
          </div>
          <div className="review-toolbar" aria-label="Candidate review controls">
            <div className="segmented-control" aria-label="Review view mode">
              {viewModes.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={viewMode === mode}
                  onClick={() => setViewMode(mode)}
                >
                  {modeLabel(mode)}
                </button>
              ))}
            </div>

            <label className="compact-field" htmlFor="media-filter">
              Filter
              <select
                id="media-filter"
                value={mediaFilter}
                onChange={(event) => setMediaFilter(event.target.value as MediaFilter)}
              >
                <option value="all">All</option>
                <option value="image">Images</option>
                <option value="video">Videos</option>
                <option value="audio">Voice</option>
              </select>
            </label>
            <label className="compact-field" htmlFor="surface-filter">
              Surface
              <select
                id="surface-filter"
                value={surfaceFilter}
                onChange={(event) => setSurfaceFilter(event.target.value as SurfaceFilter)}
              >
                {surfaceFilterOptions.map((option) => (
                  <option key={option} value={option}>
                    {surfaceFilterLabel(option)}
                  </option>
                ))}
              </select>
            </label>
            {hasUploaderMetadata ? (
              <label className="compact-field" htmlFor="uploader-filter">
                Posted by
                <select
                  id="uploader-filter"
                  aria-label="Uploader"
                  value={uploaderFilter}
                  onChange={(event) => setUploaderFilter(event.target.value as UploaderFilter)}
                >
                  {uploaderFilterOptions.map((option) => (
                    <option key={option} value={option}>
                      {uploaderFilterLabel(option)}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <button type="button" onClick={selectVisibleReadyCandidates} disabled={!hasVisibleItems}>
              Select All
            </button>
            <button
              type="button"
              aria-label="Select All Images"
              onClick={() => selectVisibleRoleCandidates("image")}
              disabled={!hasVisibleImageCandidates}
            >
              All Images
            </button>
            <button
              type="button"
              aria-label="Select All Videos"
              onClick={() => selectVisibleRoleCandidates("video")}
              disabled={!hasVisibleVideoCandidates}
            >
              All Videos
            </button>
            <button
              type="button"
              aria-label="Select All Voice"
              onClick={() => selectVisibleRoleCandidates("audio")}
              disabled={!hasVisibleAudioCandidates}
            >
              All Voice
            </button>
            <button
              type="button"
              aria-label="Deselect All"
              onClick={deselectVisibleCandidates}
              disabled={!hasVisibleItems}
            >
              Deselect
            </button>
            <button type="button" onClick={invertVisibleReadyCandidates} disabled={!hasVisibleItems}>
              Invert
            </button>
          </div>

          <div className="candidate-review">
            {visibleReviewItems.length === 0 ? (
              <p className="empty-state">No candidates scanned yet.</p>
            ) : (
              <>
                {viewMode === "tile" && (
                  <TileView
                    items={visibleReviewItems}
                    selectedIds={selectedIds}
                    engine={engine}
                    onToggleCandidate={toggleCandidate}
                    onPreviewVideo={setVideoPreviewItem}
                  />
                )}
                {viewMode === "list" && (
                  <ListView
                    items={visibleReviewItems}
                    selectedIds={selectedIds}
                    engine={engine}
                    onToggleCandidate={toggleCandidate}
                    onPreviewVideo={setVideoPreviewItem}
                  />
                )}
                {viewMode === "gallery" && galleryItem && (
                  <GalleryView
                    item={galleryItem}
                    currentIndex={safeGalleryIndex}
                    total={visibleReviewItems.length}
                    selectedIds={selectedIds}
                    engine={engine}
                    onToggleCandidate={toggleCandidate}
                    onPreviewVideo={setVideoPreviewItem}
                    onPrevious={() => setGalleryIndex(Math.max(0, safeGalleryIndex - 1))}
                    onNext={() =>
                      setGalleryIndex(Math.min(visibleReviewItems.length - 1, safeGalleryIndex + 1))
                    }
                  />
                )}
              </>
            )}
          </div>
        </section>
      </div>

      {videoPreviewItem && (
        <VideoPreviewDialog
          item={videoPreviewItem}
          engine={engine}
          onClose={() => setVideoPreviewItem(null)}
        />
      )}

      <div className="jobs-panel">
        <h3>Ingress Jobs</h3>
        {jobs.length === 0 ? (
          <p className="empty-state">No ingress jobs yet.</p>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Source</th>
                <th>Selected</th>
                <th>Imported</th>
                <th>Deferred</th>
                <th>Failed</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.status}</td>
                  <td>{job.source_kind}</td>
                  <td>{job.selected_count}</td>
                  <td>{job.imported_count}</td>
                  <td>{job.deferred_count ?? 0}</td>
                  <td>{job.failed_count}</td>
                  <td>{job.progress_message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

interface CandidateViewProps {
  items: CandidateReviewItem[];
  selectedIds: Set<string>;
  engine: EngineClient;
  onToggleCandidate(candidateId: string): void;
  onPreviewVideo(item: CandidateReviewItem): void;
}

function TileView({
  items,
  selectedIds,
  engine,
  onToggleCandidate,
  onPreviewVideo,
}: CandidateViewProps) {
  return (
    <div className="candidate-grid">
      {items.map((item) => (
        <article
          className="candidate-tile"
          key={item.id}
          aria-label={item.displayName}
        >
          <div className="candidate-media">
            <CandidateThumbnail candidate={item.thumbnailCandidate} engine={engine} />
            <RoleSelectors
              item={item}
              selectedIds={selectedIds}
              onToggleCandidate={onToggleCandidate}
            />
            <VideoPreviewButton item={item} onPreviewVideo={onPreviewVideo} />
          </div>
          <div className="candidate-body">
            <strong>{item.displayName}</strong>
          </div>
        </article>
      ))}
    </div>
  );
}

function ListView({
  items,
  selectedIds,
  engine,
  onToggleCandidate,
  onPreviewVideo,
}: CandidateViewProps) {
  return (
    <table className="candidate-list" aria-label="Candidate list">
      <thead>
        <tr>
          <th>Preview</th>
          <th>File</th>
          <th>Roles</th>
          <th>Path</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>
              <CandidateThumbnail candidate={item.thumbnailCandidate} engine={engine} />
            </td>
            <td className="list-title-cell">{item.displayName}</td>
            <td>
              <RoleSelectors
                item={item}
                selectedIds={selectedIds}
                onToggleCandidate={onToggleCandidate}
              />
              <VideoPreviewButton item={item} onPreviewVideo={onPreviewVideo} />
            </td>
            <td className="path-cell">{item.sourceLocator}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface GalleryViewProps {
  item: CandidateReviewItem;
  currentIndex: number;
  total: number;
  selectedIds: Set<string>;
  engine: EngineClient;
  onToggleCandidate(candidateId: string): void;
  onPreviewVideo(item: CandidateReviewItem): void;
  onPrevious(): void;
  onNext(): void;
}

function GalleryView({
  item,
  currentIndex,
  total,
  selectedIds,
  engine,
  onToggleCandidate,
  onPreviewVideo,
  onPrevious,
  onNext,
}: GalleryViewProps) {
  return (
    <div className="gallery-review">
      <CandidateThumbnail candidate={item.thumbnailCandidate} engine={engine} large />
      <div className="gallery-details">
        <p className="muted">
          {currentIndex + 1} of {total}
        </p>
        <h3>{item.displayName}</h3>
        <p>{item.sourceLocator}</p>
        <p>{reviewItemSummary(item)}</p>
        <RoleSelectors
          item={item}
          selectedIds={selectedIds}
          onToggleCandidate={onToggleCandidate}
        />
        <VideoPreviewButton item={item} onPreviewVideo={onPreviewVideo} />
        <div className="gallery-controls">
          <button type="button" onClick={onPrevious} disabled={currentIndex === 0}>
            Previous
          </button>
          <button type="button" onClick={onNext} disabled={currentIndex >= total - 1}>
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function RoleSelectors({
  item,
  selectedIds,
  onToggleCandidate,
}: {
  item: CandidateReviewItem;
  selectedIds: Set<string>;
  onToggleCandidate(candidateId: string): void;
}) {
  const roles: CandidateRole[] = ["image", "video", "audio"];
  return (
    <div className="role-selectors">
      {roles.map((role) => {
        const candidate = candidateForRole(item, role);
        if (!candidate) return null;
        const displayRole = roleLabel(role);
        const label = `Select as ${displayRole}: ${item.displayName}`;
        return (
          <label
            className={roleChipClassName(item, role, selectedIds.has(candidate.id))}
            key={role}
          >
            <input
              aria-label={label}
              type="checkbox"
              checked={selectedIds.has(candidate.id)}
              disabled={candidate.status !== "ready"}
              onChange={() => onToggleCandidate(candidate.id)}
            />
            <span className="role-chip-label" aria-hidden="true">
              {compactRoleLabel(role)}
            </span>
          </label>
        );
      })}
    </div>
  );
}

function CandidateThumbnail({
  candidate,
  engine,
  large = false,
}: {
  candidate: IngressCandidate;
  engine: EngineClient;
  large?: boolean;
}) {
  const thumbnailPath = candidate.thumbnail_path ?? candidate.poster_asset_path;
  const sourceVideoId = sourceVideoCandidateId(candidate);
  const thumbnail = thumbnailPath
    ? engine.assetUrl(thumbnailPath)
    : candidate.source_kind === "x_twitter" && sourceVideoId
      ? engine.ingressCandidateThumbnailUrl(sourceVideoId)
      : candidate.source_kind === "x_twitter" && candidate.media_type === "video"
        ? engine.ingressCandidateThumbnailUrl(candidate.id)
        : undefined;
  return (
    <div className={large ? "candidate-thumb large" : "candidate-thumb"}>
      {thumbnail ? (
        <>
          <img className="thumbnail-image" src={thumbnail} alt="" />
          <span className="thumb-overlay" aria-hidden="true">
            <span className="thumb-meta">{mediaSummary(candidate)}</span>
            <span className={`thumb-status ${candidate.status}`}>{candidate.status}</span>
          </span>
          <img
            className="hover-preview"
            src={thumbnail}
            alt={`Enlarged preview for ${candidate.display_name}`}
          />
        </>
      ) : (
        <span>{candidate.media_type ?? "file"}</span>
      )}
    </div>
  );
}

function VideoPreviewButton({
  item,
  onPreviewVideo,
}: {
  item: CandidateReviewItem;
  onPreviewVideo(item: CandidateReviewItem): void;
}) {
  if (!item.videoCandidate) {
    return null;
  }
  return (
    <button
      className="preview-action"
      type="button"
      aria-label={`Preview video: ${item.displayName}`}
      onClick={() => onPreviewVideo(item)}
    >
      Play
    </button>
  );
}

function VideoPreviewDialog({
  item,
  engine,
  onClose,
}: {
  item: CandidateReviewItem;
  engine: EngineClient;
  onClose(): void;
}) {
  const previewUrl = videoPreviewUrl(item, engine);
  const sourceUrl = item.videoCandidate?.source_locator ?? item.sourceLocator;
  return (
    <div className="video-preview-backdrop">
      <div
        className="video-preview-dialog compact"
        role="dialog"
        aria-modal="true"
        aria-label={`Video preview: ${item.displayName}`}
      >
        <div className="video-preview-header">
          <h3>{item.displayName}</h3>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <video
          title={`Video preview: ${item.displayName}`}
          controls
          autoPlay
          playsInline
          preload="metadata"
          src={previewUrl}
        />
        <a href={sourceUrl} target="_blank" rel="noreferrer">
          Open source in browser
        </a>
      </div>
    </div>
  );
}

function modeLabel(mode: ViewMode): string {
  return mode[0].toUpperCase() + mode.slice(1);
}

function instagramScanModeLabel(mode: InstagramScanMode): string {
  return mode[0].toUpperCase() + mode.slice(1);
}

function browserLabel(browser: string): string {
  return browser[0].toUpperCase() + browser.slice(1);
}

function surfaceFilterLabel(filter: SurfaceFilter): string {
  if (filter === "all") return "All";
  if (filter === "direct") return "Direct URL";
  if (filter === "unknown") return "Unknown";
  return instagramScanModeLabel(filter);
}

function uploaderFilterLabel(filter: UploaderFilter): string {
  if (filter === "all") return "All";
  if (filter === "owner") return "Profile account";
  if (filter === "other") return "Other accounts";
  return "Unknown";
}

function resultNextCursor(result: IngressScanResult): string | undefined {
  const rawCursor = result.metadata_json?.next_cursor;
  return typeof rawCursor === "string" && rawCursor ? rawCursor : undefined;
}

function instagramScanStatus(result: IngressScanResult, batchNumber: number): string {
  const suffix = resultNextCursor(result) ? " More batches available." : " No more batches.";
  return `Loaded Instagram batch ${batchNumber}: ${result.candidates.length} candidate(s).${suffix}${instagramWarningStatus(result)}`;
}

function instagramWarningStatus(result: IngressScanResult): string {
  const failedSurfaces = instagramFailedSurfaces(result);
  if (failedSurfaces.length > 0) {
    return ` Warning: ${failedSurfaces.join(", ")} skipped.`;
  }
  if (result.errors.length > 0) {
    return ` Warning: ${result.errors.length} issue(s).`;
  }
  return "";
}

function instagramFailedSurfaces(result: IngressScanResult): string[] {
  const metadataSurfaces = result.metadata_json?.failed_scan_surfaces;
  if (Array.isArray(metadataSurfaces)) {
    return uniqueStrings(metadataSurfaces);
  }

  const errorSurfaces = result.errors.map((error) => error.surface);
  return uniqueStrings(errorSurfaces);
}

function uniqueStrings(values: unknown[]): string[] {
  return [
    ...new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
}

function mergeCandidates(
  currentCandidates: IngressCandidate[],
  nextCandidates: IngressCandidate[],
): IngressCandidate[] {
  const candidatesById = new Map<string, IngressCandidate>();
  for (const candidate of currentCandidates) {
    candidatesById.set(candidate.id, candidate);
  }
  for (const candidate of nextCandidates) {
    candidatesById.set(candidate.id, candidate);
  }
  return [...candidatesById.values()];
}

function parseScanLimit(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 100) {
    return null;
  }
  return parsed;
}

function buildReviewItems(candidates: IngressCandidate[]): CandidateReviewItem[] {
  const candidatesById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
  const posterByVideoCandidateId = new Map<string, IngressCandidate>();
  const audioByVideoCandidateId = new Map<string, IngressCandidate>();
  for (const candidate of candidates) {
    const videoCandidateId = sourceVideoCandidateId(candidate);
    if (
      candidate.media_type === "image" &&
      videoCandidateId &&
      candidatesById.has(videoCandidateId)
    ) {
      posterByVideoCandidateId.set(videoCandidateId, candidate);
    }
    if (
      candidate.media_type === "audio" &&
      videoCandidateId &&
      candidatesById.has(videoCandidateId)
    ) {
      audioByVideoCandidateId.set(videoCandidateId, candidate);
    }
  }

  const consumedIds = new Set<string>();
  const items: CandidateReviewItem[] = [];
  for (const candidate of candidates) {
    if (consumedIds.has(candidate.id)) continue;

    const pairedVideoId = sourceVideoCandidateId(candidate);
    if (pairedVideoId && candidatesById.has(pairedVideoId)) {
      continue;
    }

    const posterCandidate = posterByVideoCandidateId.get(candidate.id)
      ?? (candidate.source_kind === "x_twitter" ? xVideoPosterCandidate(candidate) : undefined);
    const audioCandidate = audioByVideoCandidateId.get(candidate.id);
    if (candidate.media_type === "video") {
      const itemCandidates = [
        ...(posterCandidate ? [posterCandidate] : []),
        candidate,
        ...(audioCandidate ? [audioCandidate] : []),
      ];
      consumedIds.add(candidate.id);
      if (posterCandidate) consumedIds.add(posterCandidate.id);
      if (audioCandidate) consumedIds.add(audioCandidate.id);
      items.push({
        id: candidate.id,
        displayName: candidate.display_name,
        sourceLocator: candidate.source_locator,
        imageCandidate: posterCandidate,
        videoCandidate: candidate,
        audioCandidate,
        thumbnailCandidate: posterCandidate ?? candidate,
        candidates: itemCandidates,
      });
      continue;
    }

    consumedIds.add(candidate.id);
    items.push({
      id: candidate.id,
      displayName: candidate.display_name,
      sourceLocator: candidate.source_locator,
      imageCandidate: candidate.media_type === "image" ? candidate : undefined,
      audioCandidate: candidate.media_type === "audio" ? candidate : undefined,
      thumbnailCandidate: candidate,
      candidates: [candidate],
    });
  }

  return items;
}

function sourceVideoCandidateId(candidate: IngressCandidate): string | undefined {
  const rawValue = candidate.metadata_json?.source_video_candidate_id;
  return typeof rawValue === "string" && rawValue ? rawValue : undefined;
}

function xVideoPosterCandidate(videoCandidate: IngressCandidate): IngressCandidate {
  return {
    id: `${videoCandidate.id}_poster`,
    source_kind: videoCandidate.source_kind,
    source_locator: `${videoCandidate.source_locator}#poster`,
    display_name: `${videoCandidate.display_name} poster`,
    media_type: "image",
    width: videoCandidate.width,
    height: videoCandidate.height,
    status: "ready",
    selected: true,
    metadata_json: {
      ...(videoCandidate.metadata_json ?? {}),
      source_video_candidate_id: videoCandidate.id,
      asset_role: "video_poster",
      materialize_from_video: true,
    },
  };
}

function itemMatchesReviewFilters(
  item: CandidateReviewItem,
  mediaFilter: MediaFilter,
  surfaceFilter: SurfaceFilter,
  uploaderFilter: UploaderFilter,
): boolean {
  return (
    itemMatchesMediaFilter(item, mediaFilter) &&
    itemMatchesSurfaceFilter(item, surfaceFilter) &&
    itemMatchesUploaderFilter(item, uploaderFilter)
  );
}

function itemMatchesMediaFilter(item: CandidateReviewItem, mediaFilter: MediaFilter): boolean {
  return mediaFilter === "all" || candidateForRole(item, mediaFilter) !== undefined;
}

function itemMatchesSurfaceFilter(
  item: CandidateReviewItem,
  surfaceFilter: SurfaceFilter,
): boolean {
  if (surfaceFilter === "all") return true;
  return item.candidates.some((candidate) => candidateScanSurface(candidate) === surfaceFilter);
}

function itemMatchesUploaderFilter(
  item: CandidateReviewItem,
  uploaderFilter: UploaderFilter,
): boolean {
  if (uploaderFilter === "all") return true;
  return itemUploaderRelation(item) === uploaderFilter;
}

function itemUploaderRelation(item: CandidateReviewItem): Exclude<UploaderFilter, "all"> {
  for (const candidate of item.candidates) {
    const ownerUsername = normalizedMetadataString(candidate, "owner_username");
    const uploaderUsername = normalizedMetadataString(candidate, "uploader_username");
    if (!ownerUsername || !uploaderUsername) continue;
    return ownerUsername === uploaderUsername ? "owner" : "other";
  }
  return "unknown";
}

function candidateScanSurface(candidate: IngressCandidate): SurfaceFilter {
  const rawSurface = normalizedMetadataString(candidate, "scan_surface");
  if (
    rawSurface === "feed" ||
    rawSurface === "reels" ||
    rawSurface === "tagged" ||
    rawSurface === "direct"
  ) {
    return rawSurface;
  }
  return "unknown";
}

function normalizedMetadataString(
  candidate: IngressCandidate,
  key: string,
): string | undefined {
  const rawValue = candidate.metadata_json?.[key];
  if (typeof rawValue !== "string") return undefined;
  const normalized = rawValue.trim().toLowerCase();
  return normalized || undefined;
}

function candidateForRole(
  item: CandidateReviewItem,
  role: CandidateRole,
): IngressCandidate | undefined {
  if (role === "image") return item.imageCandidate;
  if (role === "video") return item.videoCandidate;
  return item.audioCandidate;
}

function candidatesForReviewItems(items: CandidateReviewItem[]): IngressCandidate[] {
  const candidatesById = new Map<string, IngressCandidate>();
  for (const item of items) {
    for (const candidate of item.candidates) {
      candidatesById.set(candidate.id, candidate);
    }
  }
  return [...candidatesById.values()];
}

function roleChipClassName(
  item: CandidateReviewItem,
  role: CandidateRole,
  selected: boolean,
): string {
  return [
    "role-chip",
    selected ? "selected" : "",
    role === "audio" && hasNonOriginalAudio(item) ? "audio-ineligible" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function hasNonOriginalAudio(item: CandidateReviewItem): boolean {
  return candidateAudioOriginal(item.audioCandidate ?? item.videoCandidate) === false;
}

function candidateAudioOriginal(candidate: IngressCandidate | undefined): boolean | undefined {
  const rawOriginal = candidate?.metadata_json?.audio_original;
  if (typeof rawOriginal === "boolean") return rawOriginal;
  if (typeof rawOriginal === "string") {
    const normalized = rawOriginal.toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }

  const audioKind = candidate?.metadata_json?.audio_kind;
  if (audioKind === "original") return true;
  if (audioKind === "reused_or_music" || audioKind === "music") return false;
  return undefined;
}

function videoPreviewUrl(item: CandidateReviewItem, engine: EngineClient): string {
  const videoCandidate = item.videoCandidate;
  if (videoCandidate?.source_kind === "x_twitter" || videoCandidate?.source_kind === "tiktok") {
    return engine.ingressCandidateVideoPreviewUrl(videoCandidate.id);
  }
  const downloadUrl = videoCandidate?.metadata_json?.download_url;
  if (typeof downloadUrl === "string" && downloadUrl.trim()) {
    return downloadUrl;
  }

  const sourceLocator = videoCandidate?.source_locator ?? item.sourceLocator;
  if (sourceLocator.startsWith("/")) {
    return engine.assetUrl(sourceLocator);
  }
  return sourceLocator;
}

function roleLabel(role: CandidateRole): string {
  return role === "audio" ? "voice" : role;
}

function compactRoleLabel(role: CandidateRole): string {
  return roleLabel(role);
}

function reviewItemSummary(item: CandidateReviewItem): string {
  const baseSummary = mediaSummary(item.thumbnailCandidate);
  const videoDuration = item.videoCandidate?.duration;
  if (item.imageCandidate && item.videoCandidate && videoDuration) {
    return `${baseSummary} - video ${videoDuration.toFixed(1)}s`;
  }
  return baseSummary;
}

function mediaSummary(candidate: IngressCandidate): string {
  if (candidate.width && candidate.height) {
    return `${candidate.width}x${candidate.height}`;
  }
  if (candidate.duration) {
    return `${candidate.duration.toFixed(1)}s`;
  }
  return candidate.media_type ?? "unknown";
}

function upsertJob(jobs: IngressJob[], job: IngressJob): IngressJob[] {
  const existingIndex = jobs.findIndex((existingJob) => existingJob.id === job.id);
  if (existingIndex === -1) {
    return [job, ...jobs];
  }

  const nextJobs = [...jobs];
  nextJobs[existingIndex] = job;
  return nextJobs;
}

async function mirrorImportedItemsToBrowserDestination(
  items: MediaItem[],
  destination: BrowserDirectoryHandle,
  assetUrl: (path: string) => string,
): Promise<number> {
  let copiedCount = 0;
  for (const item of items) {
    if (!item.raw_path) continue;
    const response = await fetch(assetUrl(item.raw_path));
    if (!response.ok) {
      throw new Error(`Browser destination copy failed for ${item.raw_path}.`);
    }
    const fileHandle = await destination.getFileHandle(fileNameFromPath(item.raw_path), {
      create: true,
    });
    const writable = await fileHandle.createWritable();
    await writable.write(await response.blob());
    await writable.close();
    copiedCount += 1;
  }
  return copiedCount;
}

function fileNameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || "media";
}

function dialogErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return `Native file picker unavailable: ${error.message}. Use Advanced Fallbacks to scan paths manually.`;
  }
  return "Native file picker unavailable. Use Advanced Fallbacks to scan paths manually.";
}

function isPickerAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function loadDataIngressDraft(key = dataIngressDraftStorageKey): DataIngressDraft {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const rawDraft = window.localStorage.getItem(key);
    if (!rawDraft) return {};
    const parsed = JSON.parse(rawDraft) as unknown;
    if (!isRecord(parsed)) return {};

    return {
      manualPaths: draftString(parsed.manualPaths),
      candidates: draftCandidates(parsed.candidates),
      activeBatchCandidateIds: draftStringArrayOrNull(parsed.activeBatchCandidateIds),
      activeBatchConfirmed: draftBoolean(parsed.activeBatchConfirmed),
      selectedIds: draftStringArray(parsed.selectedIds),
      viewMode: draftEnumValue(parsed.viewMode, viewModes),
      mediaFilter: draftEnumValue(parsed.mediaFilter, ["all", "image", "video", "audio"]),
      surfaceFilter: draftEnumValue(parsed.surfaceFilter, surfaceFilterOptions),
      uploaderFilter: draftEnumValue(parsed.uploaderFilter, uploaderFilterOptions),
      showBrowserLocalImport: draftBoolean(parsed.showBrowserLocalImport),
      showInstagramHelper: draftBoolean(parsed.showInstagramHelper),
      showXHelper: draftBoolean(parsed.showXHelper),
      showTikTokHelper: draftBoolean(parsed.showTikTokHelper),
      showAdvancedFallbacks: draftBoolean(parsed.showAdvancedFallbacks),
      mediaDestination: draftString(parsed.mediaDestination),
      instagramUrl: draftString(parsed.instagramUrl),
      instagramBrowser: draftEnumValue(parsed.instagramBrowser, browserCookieSources),
      instagramScanLimit: draftString(parsed.instagramScanLimit),
      instagramScanMode: draftEnumValue(parsed.instagramScanMode, instagramScanModes),
      instagramDateFrom: draftString(parsed.instagramDateFrom),
      instagramDateTo: draftString(parsed.instagramDateTo),
      instagramNextCursor: draftString(parsed.instagramNextCursor),
      instagramBatchNumber: draftNonNegativeInteger(parsed.instagramBatchNumber),
      instagramPayloadText: draftString(parsed.instagramPayloadText),
      xUrl: draftString(parsed.xUrl),
      xBrowser: draftEnumValue(parsed.xBrowser, browserCookieSources),
      xScanLimit: draftString(parsed.xScanLimit),
      xDateFrom: draftString(parsed.xDateFrom),
      xDateTo: draftString(parsed.xDateTo),
      xNextCursor: draftString(parsed.xNextCursor),
      xBatchNumber: draftNonNegativeInteger(parsed.xBatchNumber),
      tiktokUrl: draftString(parsed.tiktokUrl),
      tiktokBrowser: draftEnumValue(parsed.tiktokBrowser, browserCookieSources),
      tiktokScanLimit: draftString(parsed.tiktokScanLimit),
      tiktokDateFrom: draftString(parsed.tiktokDateFrom),
      tiktokDateTo: draftString(parsed.tiktokDateTo),
      tiktokNextCursor: draftString(parsed.tiktokNextCursor),
      tiktokBatchNumber: draftNonNegativeInteger(parsed.tiktokBatchNumber),
      activeSocialSource: draftEnumValue(parsed.activeSocialSource, ["instagram", "x", "tiktok"]),
      activeAcquisitionJobId: draftString(parsed.activeAcquisitionJobId),
    };
  } catch {
    return {};
  }
}

function saveDataIngressDraft(draft: DataIngressDraft, key = dataIngressDraftStorageKey): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Local persistence is best-effort; browser quota/security should not block ingress.
  }
}

function draftString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function draftBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function draftStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((item): item is string => typeof item === "string");
}

function draftStringArrayOrNull(value: unknown): string[] | null | undefined {
  if (value === null) return null;
  return draftStringArray(value);
}

function draftEnumValue<T extends string>(
  value: unknown,
  allowedValues: readonly T[],
): T | undefined {
  if (typeof value !== "string") return undefined;
  return allowedValues.includes(value as T) ? (value as T) : undefined;
}

function draftNonNegativeInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : undefined;
}

function draftCandidates(value: unknown): IngressCandidate[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter(isDraftCandidate);
}

function isDraftCandidate(value: unknown): value is IngressCandidate {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.source_kind === "string" &&
    typeof value.source_locator === "string" &&
    typeof value.display_name === "string" &&
    typeof value.status === "string" &&
    typeof value.selected === "boolean"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function detectRuntimeCapabilities(): RuntimeCapabilities {
  const hostBridge = hostPathBridge();
  if (hostBridge?.pickMediaPaths || hostBridge?.pickDestinationPath) {
    return {
      pickLocalMedia: hostBridge.pickMediaPaths,
      pickMediaDestination: hostBridge.pickDestinationPath,
    };
  }

  if (isTauriRuntime()) {
    return {
      pickLocalMedia: () =>
        open({
          multiple: true,
          recursive: true,
          title: "Choose files or folders",
        }),
      pickMediaDestination: () =>
        open({
          directory: true,
          multiple: false,
          title: "Choose media destination",
          canCreateDirectories: true,
        }),
    };
  }

  return {
    pickBrowserDestination: browserDirectoryPicker(),
  };
}

function hostPathBridge(): HostPathBridge | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const hostWindow = window as Window & { loraSuiteHost?: HostPathBridge };
  return hostWindow.loraSuiteHost;
}

function browserDirectoryPicker(): (() => Promise<BrowserDirectoryHandle>) | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const browserWindow = window as Window & {
    showDirectoryPicker?: () => Promise<BrowserDirectoryHandle>;
  };
  if (!browserWindow.showDirectoryPicker) {
    return undefined;
  }
  return () => browserWindow.showDirectoryPicker?.() ?? Promise.reject(new Error("No picker"));
}

function isTauriRuntime(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}
