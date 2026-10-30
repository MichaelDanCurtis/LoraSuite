import { ArrowRight, AudioLines, Check, Clapperboard, Copy, Images, Library, Maximize2, RotateCcw, RotateCw, ScanFace, Scissors, Search, Sparkles, Video, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type WheelEvent as ReactWheelEvent } from "react";

import type { EngineClient } from "../lib/api";
import type {
  CurationSourceBundle,
  CurationAnalysisEvidence,
  AudioSeparationRuntimeStatus,
  ExactDuplicateCluster,
  MediaItem,
  MediaType,
  ProcessingJob,
  ProcessingJobStatus,
  VideoBreakdownOptions,
} from "../lib/types";
import { AudioReviewTab } from "./AudioReviewTab";
import { VideoReviewTab } from "./VideoReviewTab";

interface CurateSearchTabProps {
  mediaItems: MediaItem[];
  engine: Pick<
    EngineClient,
    | "assetUrl"
    | "rotateVaultImage"
    | "createProcessingJob"
    | "getProcessingJob"
    | "listProcessingJobs"
    | "processProcessingJob"
    | "updateVideoKeepers"
    | "commitVideoBreakdown"
    | "addCurationHandoff"
    | "rejectCurationMedia"
    | "restoreCurationAudio"
    | "createCurationAnalysisJob"
    | "getAudioCleaningRecipe"
    | "previewAudioCleaning"
    | "renderAudioCleaning"
    | "getAudioSeparationStatus"
    | "installAudioSeparationModel"
    | "createAudioCleaningJob"
  > & Partial<Pick<EngineClient, "listExactDuplicateClusters">>;
  isActive?: boolean;
  workflowTarget?: "image" | "video" | "voice" | "id_lora";
  activeProjectId?: string;
  initialView?: CurationView;
  onSendToIdentify(items: MediaItem[]): void;
  onMediaItemsGenerated(items: MediaItem[]): void;
  onMediaItemsRejected?(itemIds: string[]): void;
}

type CurationView = "sources" | MediaType;
type StagedAiDecision = "keep" | "reject";
interface VideoPreparationOutputs {
  framesAndClips: boolean;
  audioTracks: boolean;
}
const PROCESSING_JOB_POLL_DELAY_MS = 1000;
const PROCESSING_JOB_MAX_DETAIL_ATTEMPTS = 600;
const CURATION_RENDER_PAGE_SIZE = 84;
const terminalProcessingStatuses = new Set<ProcessingJobStatus>(["complete", "failed", "canceled"]);

export function CurateSearchTab({
  mediaItems,
  engine,
  isActive = true,
  workflowTarget,
  activeProjectId = "",
  initialView,
  onSendToIdentify,
  onMediaItemsGenerated,
  onMediaItemsRejected,
}: CurateSearchTabProps) {
  const [searchText, setSearchText] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [view, setView] = useState<CurationView>(() => initialView ?? "sources");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [breakdownSourceIds, setBreakdownSourceIds] = useState<Set<string>>(() => new Set());
  const [videoOutputs, setVideoOutputs] = useState<VideoPreparationOutputs>(() =>
    defaultVideoPreparationOutputs(workflowTarget),
  );
  const [breakdownInFlight, setBreakdownInFlight] = useState(false);
  const [reviewJob, setReviewJob] = useState<ProcessingJob | null>(null);
  const [processingJobs, setProcessingJobs] = useState<ProcessingJob[]>([]);
  const [status, setStatus] = useState("Idle");
  const [rejectingIds, setRejectingIds] = useState<Set<string>>(() => new Set());
  const [rotatingIds, setRotatingIds] = useState<Set<string>>(() => new Set());
  const [showRejectedAudio, setShowRejectedAudio] = useState(false);
  const [analysisInFlight, setAnalysisInFlight] = useState(false);
  const [audioCleaningInFlight, setAudioCleaningInFlight] = useState(false);
  const [audioSeparationStatus, setAudioSeparationStatus] = useState<AudioSeparationRuntimeStatus | null>(null);
  const [aiStagingActive, setAiStagingActive] = useState(false);
  const [stagedAiDecisions, setStagedAiDecisions] = useState<Map<string, StagedAiDecision>>(
    () => new Map(),
  );
  const [expandedItem, setExpandedItem] = useState<MediaItem | null>(null);
  const [audioReviewItem, setAudioReviewItem] = useState<MediaItem | null>(null);
  const [handoffReviewOpen, setHandoffReviewOpen] = useState(false);
  const [duplicateClusters, setDuplicateClusters] = useState<ExactDuplicateCluster[]>([]);
  const [duplicateReviewOpen, setDuplicateReviewOpen] = useState(false);
  const [renderLimit, setRenderLimit] = useState(CURATION_RENDER_PAGE_SIZE);
  const canonicalMediaItems = useMemo(() => deduplicateMediaItems(mediaItems), [mediaItems]);

  useEffect(() => {
    if (!isActive || !engine.listExactDuplicateClusters) return;
    let canceled = false;
    void engine.listExactDuplicateClusters()
      .then((clusters) => {
        if (!canceled) {
          const ids = new Set(mediaItems.map((item) => item.id));
          setDuplicateClusters(activeProjectId ? clusters.filter((cluster) => ids.has(cluster.canonical_media_item_id) || cluster.media_item_ids.some((id) => ids.has(id))) : clusters);
        }
      })
      .catch(() => {
        if (!canceled) setDuplicateClusters([]);
      });
    return () => {
      canceled = true;
    };
  }, [engine, isActive, mediaItems, activeProjectId]);
  const mediaById = useMemo(
    () => new Map(canonicalMediaItems.map((item) => [item.id, item])),
    [canonicalMediaItems],
  );
  const sourceBundles = useMemo(
    () =>
      buildSourceBundles(canonicalMediaItems).filter((bundle) =>
        bundle.items.some((bundleItem) => {
          const item = mediaById.get(bundleItem.media_item_id);
          return item !== undefined && (item.media_type !== "audio" || isUsefulAudio(item, mediaById));
        }),
      ),
    [canonicalMediaItems, mediaById],
  );
  const visibleItems = useMemo(
    () =>
      canonicalMediaItems.filter((item) => {
        if (view === "sources" || item.media_type !== view) {
          return false;
        }
        if (item.media_type === "audio") {
          const usefulAudio = isUsefulAudio(item, mediaById);
          if (showRejectedAudio ? usefulAudio : !usefulAudio) {
            return false;
          }
        }
        const query = searchText.trim().toLowerCase();
        if (!query) {
          return true;
        }
        return searchableText(item).includes(query);
      }),
    [canonicalMediaItems, mediaById, searchText, showRejectedAudio, view],
  );
  const visibleBundles = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    if (!query) {
      return sourceBundles;
    }
    const mediaById = new Map(canonicalMediaItems.map((item) => [item.id, item]));
    return sourceBundles.filter((bundle) =>
      [
        bundle.title,
        bundle.source_locator,
        bundle.source_kind,
        bundle.id,
        ...bundle.items.map((item) => mediaById.get(item.media_item_id)).filter(Boolean).map((item) => searchableText(item as MediaItem)),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [canonicalMediaItems, searchText, sourceBundles]);
  const displayedItems = useMemo(
    () => visibleItems.slice(0, renderLimit),
    [renderLimit, visibleItems],
  );
  const displayedBundles = useMemo(
    () => visibleBundles.slice(0, renderLimit),
    [renderLimit, visibleBundles],
  );
  const visibleResultCount = view === "sources" ? visibleBundles.length : visibleItems.length;
  const displayedResultCount = view === "sources" ? displayedBundles.length : displayedItems.length;

  useEffect(() => {
    setRenderLimit(CURATION_RENDER_PAGE_SIZE);
  }, [searchText, showRejectedAudio, view]);
  const selectedBreakdownVideoIds = useMemo(
    () =>
      canonicalMediaItems
        .filter((item) => item.media_type === "video" && breakdownSourceIds.has(item.id))
        .map((item) => item.id),
    [breakdownSourceIds, canonicalMediaItems],
  );
  const imageCount = canonicalMediaItems.filter((item) => item.media_type === "image").length;
  const videoCount = canonicalMediaItems.filter((item) => item.media_type === "video").length;
  const voiceCount = canonicalMediaItems.filter(
    (item) => item.media_type === "audio" && isUsefulAudio(item, mediaById),
  ).length;
  const extractedTrackCount = canonicalMediaItems.filter(
    (item) => item.media_type === "audio" && metadataString(item, "derivative_type") === "audio_clip",
  ).length;
  const cleanedTrackCount = canonicalMediaItems.filter(
    (item) => item.media_type === "audio" && metadataString(item, "derivative_type") === "audio_clean",
  ).length;
  const rejectedVoiceCount = canonicalMediaItems.filter(
    (item) => item.media_type === "audio" && !isUsefulAudio(item, mediaById),
  ).length;
  const selectedCount = canonicalMediaItems.filter((item) => selectedIds.has(item.id)).length;
  const selectedItems = useMemo(
    () => canonicalMediaItems.filter((item) => selectedIds.has(item.id)),
    [canonicalMediaItems, selectedIds],
  );
  const selectedAudioIds = useMemo(
    () => selectedItems.filter((item) => item.media_type === "audio").map((item) => item.id),
    [selectedItems],
  );
  const handoffItems = workflowTarget === "voice"
    ? selectedItems.filter((item) => item.media_type === "audio")
    : selectedItems;
  const handoffLaneCounts = {
    image: handoffItems.filter((item) => item.media_type === "image").length,
    video: handoffItems.filter((item) => item.media_type === "video").length,
    audio: handoffItems.filter((item) => item.media_type === "audio").length,
  };
  const voiceWorkflow = workflowTarget === "voice" || workflowTarget === "id_lora";
  const selectedVideoOutputCount = Number(videoOutputs.framesAndClips) + Number(videoOutputs.audioTracks);
  const workflowCopy = curateWorkflowCopy(workflowTarget);

  useEffect(() => {
    setVideoOutputs(defaultVideoPreparationOutputs(workflowTarget));
  }, [workflowTarget]);
  const stagedKeepCount = [...stagedAiDecisions.values()].filter(
    (decision) => decision === "keep",
  ).length;
  const stagedRejectCount = stagedAiDecisions.size - stagedKeepCount;
  const latestAnalysisBySource = useMemo(() => {
    const jobsBySource = new Map<string, ProcessingJob>();
    for (const job of processingJobs) {
      if (job.status !== "complete" || !job.video_analyses?.length) {
        continue;
      }
      for (const analysis of job.video_analyses) {
        if (!jobsBySource.has(analysis.source_media_item_id)) {
          jobsBySource.set(analysis.source_media_item_id, job);
        }
      }
    }
    return jobsBySource;
  }, [processingJobs]);
  const latestCurationEvidence = useMemo(() => {
    const evidenceByMedia = new Map<string, CurationAnalysisEvidence>();
    for (const job of processingJobs) {
      if (job.job_type !== "curation_analysis" || job.status !== "complete") {
        continue;
      }
      for (const evidence of job.curation_analyses ?? []) {
        if (!evidenceByMedia.has(evidence.media_item_id)) {
          evidenceByMedia.set(evidence.media_item_id, evidence);
        }
      }
    }
    return evidenceByMedia;
  }, [processingJobs]);

  useEffect(() => {
    if (!isActive) {
      return;
    }
    let ignore = false;
    void engine
      .listProcessingJobs()
      .then((jobs) => {
        if (!ignore) {
          setProcessingJobs(Array.isArray(jobs) ? jobs : []);
        }
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, [engine, isActive]);

  useEffect(() => {
    if (!isActive) {
      return;
    }
    let ignore = false;
    void engine.getAudioSeparationStatus()
      .then((nextStatus) => {
        if (!ignore) setAudioSeparationStatus(nextStatus);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, [engine, isActive]);

  useEffect(() => {
    if (!expandedItem) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setExpandedItem(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [expandedItem]);

  function toggleSelected(itemId: string) {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      if (nextIds.has(itemId)) {
        nextIds.delete(itemId);
      } else {
        nextIds.add(itemId);
      }
      return nextIds;
    });
  }

  function toggleBreakdownSelected(itemId: string) {
    setBreakdownSourceIds((currentIds) => {
      const nextIds = new Set(currentIds);
      if (nextIds.has(itemId)) {
        nextIds.delete(itemId);
      } else {
        nextIds.add(itemId);
      }
      return nextIds;
    });
  }

  function reviewCurationHandoff() {
    if (aiStagingActive) {
      setStatus("Commit or clear the staged AI picks before finishing curation.");
      return;
    }
    if (handoffItems.length === 0) {
      setStatus(
        workflowTarget === "voice"
          ? "Select at least one cleaned voice track before speaker verification."
          : "Select at least one prepared candidate before finishing curation.",
      );
      return;
    }
    setHandoffReviewOpen(true);
  }

  async function confirmCurationHandoff() {
    try {
      if (!activeProjectId || !workflowTarget) {
        throw new Error("Choose a project and creation type before finishing curation.");
      }
      await engine.addCurationHandoff(
        handoffItems.map((item) => item.id),
        activeProjectId,
        workflowTarget,
      );
      setHandoffReviewOpen(false);
      onSendToIdentify(handoffItems);
      setStatus(
        `${workflowTarget === "voice" ? "Started speaker verification" : "Started identity verification"} for ${handoffItems.length} prepared candidate${handoffItems.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      setStatus(`Curate handoff error: ${errorMessage(error)}`);
    }
  }

  async function rejectItems(itemIds: string[], label: string): Promise<boolean> {
    const uniqueIds = [...new Set(itemIds)].filter((itemId) => !rejectingIds.has(itemId));
    if (uniqueIds.length === 0) {
      return true;
    }
    setRejectingIds((current) => new Set([...current, ...uniqueIds]));
    try {
      await engine.rejectCurationMedia(uniqueIds);
      onMediaItemsRejected?.(uniqueIds);
      setSelectedIds((current) => new Set([...current].filter((itemId) => !uniqueIds.includes(itemId))));
      setBreakdownSourceIds((current) => new Set([...current].filter((itemId) => !uniqueIds.includes(itemId))));
      setStagedAiDecisions((current) =>
        new Map([...current].filter(([itemId]) => !uniqueIds.includes(itemId))),
      );
      const displayLabel = uniqueIds.length === 1 ? label.replace(/s$/, "") : label;
      setStatus(`Rejected ${uniqueIds.length} ${displayLabel} candidate${uniqueIds.length === 1 ? "" : "s"}.`);
      return true;
    } catch (error) {
      setStatus(`Could not reject ${label}: ${errorMessage(error)}`);
      return false;
    } finally {
      setRejectingIds((current) => new Set([...current].filter((itemId) => !uniqueIds.includes(itemId))));
    }
  }

  function selectVisibleVideosForBreakdown() {
    const visibleVideoIds = visibleItems
      .filter((item) => item.media_type === "video")
      .map((item) => item.id);
    setBreakdownSourceIds((current) => new Set([...current, ...visibleVideoIds]));
    setStatus(`Selected ${visibleVideoIds.length} visible video${visibleVideoIds.length === 1 ? "" : "s"} to prepare.`);
  }

  function deselectVisibleVideosForBreakdown() {
    const visibleVideoIds = new Set(
      visibleItems.filter((item) => item.media_type === "video").map((item) => item.id),
    );
    setBreakdownSourceIds(
      (current) => new Set([...current].filter((itemId) => !visibleVideoIds.has(itemId))),
    );
    setStatus("Cleared visible video selections.");
  }

  function selectVisibleAudio() {
    const visibleAudioIds = visibleItems
      .filter((item) => item.media_type === "audio")
      .map((item) => item.id);
    setSelectedIds((current) => new Set([...current, ...visibleAudioIds]));
    setStatus(`Selected ${visibleAudioIds.length} visible audio track${visibleAudioIds.length === 1 ? "" : "s"}.`);
  }

  function deselectVisibleAudio() {
    const visibleAudioIds = new Set(
      visibleItems.filter((item) => item.media_type === "audio").map((item) => item.id),
    );
    setSelectedIds(
      (current) => new Set([...current].filter((itemId) => !visibleAudioIds.has(itemId))),
    );
    setStatus("Cleared visible audio selections.");
  }

  async function prepareSelectedAudio(forceVoiceIsolation: boolean) {
    if (audioCleaningInFlight || selectedAudioIds.length === 0) {
      return;
    }
    if (forceVoiceIsolation && !audioSeparationStatus?.ready) {
      setStatus(audioSeparationStatus?.message ?? "Vocal isolation is not ready.");
      return;
    }
    setAudioCleaningInFlight(true);
    try {
      setStatus(
        `${forceVoiceIsolation ? "Isolating and cleaning" : "Cleaning"} ${selectedAudioIds.length} voice track${selectedAudioIds.length === 1 ? "" : "s"}.`,
      );
      const job = await engine.createAudioCleaningJob(
        selectedAudioIds,
        forceVoiceIsolation,
      );
      const detail = await pollProcessingJob(job.id, engine.getProcessingJob, (nextDetail) => {
        setStatus(nextDetail.progress_message || "Preparing voice tracks");
      });
      setProcessingJobs((jobs) => [detail, ...jobs.filter((item) => item.id !== detail.id)]);
      if (detail.derived_media_items.length > 0) {
        onMediaItemsGenerated(detail.derived_media_items);
        const preparedSourceIds = new Set(
          detail.derived_media_items
            .map((item) => item.metadata_json?.source_media_item_id)
            .filter((itemId): itemId is string => typeof itemId === "string"),
        );
        setSelectedIds((current) => new Set([
          ...[...current].filter((itemId) => !preparedSourceIds.has(itemId)),
          ...detail.derived_media_items.map((item) => item.id),
        ]));
      }
      setStatus(processingJobStatusMessage(detail));
    } catch (error) {
      setStatus(`Voice preparation error: ${errorMessage(error)}`);
    } finally {
      setAudioCleaningInFlight(false);
    }
  }

  function selectAiBreakdownPicks() {
    const recommendedIds = visibleItems
      .filter(
        (item) =>
          item.media_type === "video"
          && latestCurationEvidence.get(item.id)?.recommendation !== "reject"
          && latestCurationEvidence.has(item.id),
      )
      .map((item) => item.id);
    setBreakdownSourceIds(new Set(recommendedIds));
    setStatus(
      `Selected ${recommendedIds.length} AI-recommended video${recommendedIds.length === 1 ? "" : "s"} to prepare.`,
    );
  }

  function stageAiRecommendations() {
    const nextDecisions = new Map<string, StagedAiDecision>();
    for (const item of canonicalMediaItems) {
      const recommendation = latestCurationEvidence.get(item.id)?.recommendation;
      if (recommendation === "keep" || recommendation === "reject") {
        nextDecisions.set(item.id, recommendation);
      }
    }
    setStagedAiDecisions(nextDecisions);
    setAiStagingActive(true);
    const counts = countStagedDecisions(nextDecisions);
    setStatus(
      `Staged AI picks: ${counts.keep} keep, ${counts.reject} reject; review recommendations remain undecided. Nothing has been committed.`,
    );
  }

  function toggleStagedDecision(itemId: string, decision: StagedAiDecision) {
    setStagedAiDecisions((current) => {
      const next = new Map(current);
      if (next.get(itemId) === decision) {
        next.delete(itemId);
      } else {
        next.set(itemId, decision);
      }
      return next;
    });
  }

  function clearStagedAiDecisions() {
    setStagedAiDecisions(new Map());
    setAiStagingActive(false);
    setStatus("Cleared staged AI picks. No media decisions were changed.");
  }

  async function commitStagedAiDecisions() {
    const keepIds = [...stagedAiDecisions]
      .filter(([, decision]) => decision === "keep")
      .map(([itemId]) => itemId);
    const rejectIds = [...stagedAiDecisions]
      .filter(([, decision]) => decision === "reject")
      .map(([itemId]) => itemId);
    if (rejectIds.length > 0 && !(await rejectItems(rejectIds, "AI-staged"))) {
      return;
    }
    setSelectedIds((current) => new Set([...current, ...keepIds]));
    setStagedAiDecisions(new Map());
    setAiStagingActive(false);
    setStatus(
      `Committed AI picks: ${keepIds.length} selected for Identify, ${rejectIds.length} rejected.`,
    );
  }

  async function restoreAudio(itemId: string) {
    try {
      const restoredItems = await engine.restoreCurationAudio([itemId]);
      onMediaItemsGenerated(restoredItems);
      setStatus("Restored audio after user review.");
    } catch (error) {
      setStatus(`Could not restore audio: ${errorMessage(error)}`);
    }
  }

  async function rotateImage(item: MediaItem) {
    if (item.media_type !== "image" || rotatingIds.has(item.id)) {
      return;
    }
    setRotatingIds((current) => new Set([...current, item.id]));
    try {
      const rotated = await engine.rotateVaultImage(item.id, 90);
      onMediaItemsGenerated([rotated]);
      setExpandedItem((current) => current?.id === item.id ? rotated : current);
      setStatus(`Rotated ${displayName(item)} clockwise.`);
    } catch (error) {
      setStatus(`Could not rotate image: ${errorMessage(error)}`);
    } finally {
      setRotatingIds((current) =>
        new Set([...current].filter((itemId) => itemId !== item.id)),
      );
    }
  }

  async function analyzeAllMedia() {
    if (analysisInFlight || canonicalMediaItems.length === 0) {
      return;
    }
    setAnalysisInFlight(true);
    try {
      setStatus(`Starting local AI review for ${canonicalMediaItems.length} candidates.`);
      const job = await engine.createCurationAnalysisJob(canonicalMediaItems.map((item) => item.id));
      const detail = await pollProcessingJob(job.id, engine.getProcessingJob, (nextDetail) => {
        setStatus(nextDetail.progress_message || "Analyzing curation candidates");
      });
      setProcessingJobs((jobs) => [detail, ...jobs.filter((item) => item.id !== detail.id)]);
      const recommendationCounts = countRecommendations(detail.curation_analyses ?? []);
      setStatus(
        `AI review complete: ${recommendationCounts.keep} keep, ${recommendationCounts.review} review, ${recommendationCounts.reject} reject.`,
      );
    } catch (error) {
      setStatus(`AI review error: ${errorMessage(error)}`);
    } finally {
      setAnalysisInFlight(false);
    }
  }

  async function analyzeAudioItem(item: MediaItem) {
    if (analysisInFlight) {
      return;
    }
    setAnalysisInFlight(true);
    try {
      setStatus(`Analyzing ${displayName(item)}.`);
      const job = await engine.createCurationAnalysisJob([item.id]);
      const detail = await pollProcessingJob(job.id, engine.getProcessingJob, (nextDetail) => {
        setStatus(nextDetail.progress_message || "Analyzing audio candidate");
      });
      setProcessingJobs((jobs) => [detail, ...jobs.filter((jobItem) => jobItem.id !== detail.id)]);
      setStatus(`Audio analysis complete for ${displayName(item)}.`);
    } catch (error) {
      setStatus(`Audio analysis error: ${errorMessage(error)}`);
    } finally {
      setAnalysisInFlight(false);
    }
  }

  async function prepareSelectedVideos() {
    if (breakdownInFlight) {
      return;
    }
    if (selectedBreakdownVideoIds.length === 0) {
      setStatus("Select at least one video to prepare.");
      return;
    }
    if (selectedVideoOutputCount === 0) {
      setStatus("Choose Frames & clips, Audio tracks, or both.");
      return;
    }

    const options: VideoBreakdownOptions = {
      generate_frames: videoOutputs.framesAndClips,
      extract_audio: videoOutputs.audioTracks,
      intelligent_selection: videoOutputs.framesAndClips,
      frames_per_second: 4,
      max_frame_count: 24,
    };
    const activityLabel = videoPreparationActivityLabel(videoOutputs);
    setBreakdownInFlight(true);
    try {
      setStatus(
        `${activityLabel} for ${selectedBreakdownVideoIds.length} video${
          selectedBreakdownVideoIds.length === 1 ? "" : "s"
        }.`,
      );
      const existingJob = await findReusableProcessingJob(
        selectedBreakdownVideoIds,
        options,
        engine.listProcessingJobs,
      );
      const job =
        existingJob === undefined
          ? await engine.createProcessingJob({
              job_type: "video_breakdown",
              source_media_item_ids: selectedBreakdownVideoIds,
              options,
            })
          : await engine.processProcessingJob(existingJob.id);
      setStatus(processingJobStatusMessage(job));

      const detail = await pollProcessingJob(job.id, engine.getProcessingJob, (nextDetail) => {
        setStatus(processingJobStatusMessage(nextDetail));
      });
      if (detail.derived_media_items.length > 0) {
        onMediaItemsGenerated(detail.derived_media_items);
      }
      if (detail.video_analyses?.length) {
        setReviewJob(detail);
        setProcessingJobs((jobs) => [detail, ...jobs.filter((jobItem) => jobItem.id !== detail.id)]);
      }
      if (detail.status === "complete" && videoOutputs.audioTracks) {
        const audioCount = detail.derived_media_items.filter((item) => item.media_type === "audio").length;
        if (audioCount > 0) {
          setStatus(
            `${audioCount} audio track${audioCount === 1 ? "" : "s"} ready. Open Audio to analyze, isolate, and clean the voice.`,
          );
        } else {
          setStatus(
            `${processingJobStatusMessage(detail)} No audio track was extracted; check that the source video contains audio.`,
          );
        }
        if (audioCount > 0 && (!videoOutputs.framesAndClips || voiceWorkflow)) {
          setView("audio");
          setBreakdownSourceIds(new Set());
        }
      } else {
        setStatus(processingJobStatusMessage(detail));
      }
    } catch (error) {
      setStatus(`Video preparation error: ${errorMessage(error)}`);
    } finally {
      setBreakdownInFlight(false);
    }
  }

  if (!isActive) {
    return null;
  }

  const reviewAnalysis = reviewJob?.video_analyses?.[0];
  const reviewSource = reviewAnalysis
    ? canonicalMediaItems.find((item) => item.id === reviewAnalysis.source_media_item_id)
    : undefined;
  if (reviewJob && reviewAnalysis && reviewSource) {
    return (
      <VideoReviewTab
        analysis={reviewAnalysis}
        job={reviewJob}
        sourceItem={reviewSource}
        engine={engine}
        onBack={() => setReviewJob(null)}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />
    );
  }


  if (audioReviewItem) {
    return (
      <AudioReviewTab
        item={audioReviewItem}
        artworkItem={audioArtworkItem(audioReviewItem, canonicalMediaItems)}
        evidence={latestCurationEvidence.get(audioReviewItem.id)}
        selected={selectedIds.has(audioReviewItem.id)}
        analyzing={analysisInFlight}
        assetUrl={engine.assetUrl}
        onAnalyze={() => void analyzeAudioItem(audioReviewItem)}
        onBack={() => setAudioReviewItem(null)}
        onKeep={() => {
          setSelectedIds((current) => new Set([...current, audioReviewItem.id]));
          setStatus(`Selected ${displayName(audioReviewItem)} for Identify.`);
        }}
        onReject={() => {
          void rejectItems([audioReviewItem.id], "audio").then((rejected) => {
            if (rejected) setAudioReviewItem(null);
          });
        }}
        loadCleaningRecipe={() => engine.getAudioCleaningRecipe(audioReviewItem.id)}
        previewCleaning={(recipe) => engine.previewAudioCleaning(audioReviewItem.id, recipe)}
        renderCleaning={(recipe) => engine.renderAudioCleaning(audioReviewItem.id, recipe)}
        loadSeparationStatus={() => engine.getAudioSeparationStatus()}
        installSeparationModel={() => engine.installAudioSeparationModel()}
        onDerivativeRendered={(item) => onMediaItemsGenerated([item])}
      />
    );
  }

  return (
    <section className="workspace-section curate-workspace">
      <div className="section-header curate-header">
        <div>
          <h2>{workflowCopy.title}</h2>
          <p>{workflowCopy.description}</p>
        </div>
        <dl className="metric-grid curate-header-metrics" aria-label="Curate summary">
          <div>
            <dt>Sources</dt>
            <dd>{sourceBundles.length}</dd>
          </div>
          <div>
            <dt>Visible</dt>
            <dd>{view === "sources" ? visibleBundles.length : visibleItems.length}</dd>
          </div>
          <div>
            <dt>Images</dt>
            <dd>{imageCount}</dd>
          </div>
          <div>
            <dt>Video</dt>
            <dd>{videoCount}</dd>
          </div>
          <div>
            <dt>Audio</dt>
            <dd>{voiceCount}</dd>
          </div>
          <div>
            <dt>Selected</dt>
            <dd>{selectedCount}</dd>
          </div>
        </dl>
        <button
          className="primary-action"
          type="button"
          onClick={reviewCurationHandoff}
          disabled={handoffItems.length === 0 || aiStagingActive}
          title={aiStagingActive ? "Commit or clear staged AI picks first" : undefined}
        >
          {workflowCopy.handoffLabel} <ArrowRight size={14} aria-hidden="true" />
        </button>
      </div>

      {voiceWorkflow ? (
        <nav className="voice-sample-path" aria-label="Voice sample workflow">
          <button type="button" className={view === "video" ? "active" : ""} onClick={() => setView("video")}>
            <span>1</span><Video size={16} aria-hidden="true" />
            <strong>Extract tracks</strong><small>{videoCount} video{videoCount === 1 ? "" : "s"} ready</small>
          </button>
          <ArrowRight size={15} aria-hidden="true" />
          <button type="button" className={view === "audio" ? "active" : ""} onClick={() => setView("audio")}>
            <span>2</span><AudioLines size={16} aria-hidden="true" />
            <strong>Clean voice</strong><small>{extractedTrackCount || voiceCount} track{(extractedTrackCount || voiceCount) === 1 ? "" : "s"} available</small>
          </button>
          <ArrowRight size={15} aria-hidden="true" />
          <button
            type="button"
            onClick={reviewCurationHandoff}
            disabled={selectedAudioIds.length === 0 || aiStagingActive}
          >
            <span>3</span><ScanFace size={16} aria-hidden="true" />
            <strong>Verify speaker</strong><small>{selectedAudioIds.length} selected</small>
          </button>
          <ArrowRight size={15} aria-hidden="true" />
          <div>
            <span>4</span><Scissors size={16} aria-hidden="true" />
            <strong>Create samples</strong><small>{cleanedTrackCount} cleaned; continues in Build</small>
          </div>
        </nav>
      ) : null}

      <div className="curate-layout">
        <aside className="curate-panel" aria-label="Curate search controls">
          <div className="curate-command-row">
            <button
              className={searchText ? "curate-search-toggle active" : "curate-search-toggle"}
              type="button"
              aria-label={searchOpen ? "Close media search" : "Open media search"}
              aria-expanded={searchOpen}
              title={searchText ? "Search filter is active" : "Search media"}
              onClick={() => setSearchOpen((current) => !current)}
            >
              <Search size={15} aria-hidden="true" />
            </button>
            <div className="curate-toolbar-actions">
            {duplicateClusters.length > 0 ? (
              <button
                type="button"
                className="duplicate-review-action"
                onClick={() => setDuplicateReviewOpen(true)}
                title="Review consolidated exact duplicates and their retained sources"
              >
                <Copy size={14} aria-hidden="true" /> Duplicates ({duplicateClusters.reduce((total, cluster) => total + cluster.duplicate_count, 0)})
              </button>
            ) : null}
            <button
              type="button"
              className="ai-analyze-action"
              onClick={() => void analyzeAllMedia()}
              disabled={analysisInFlight || canonicalMediaItems.length === 0}
            >
              <Sparkles size={14} aria-hidden="true" />
              {analysisInFlight ? "Analyzing" : "AI Analyze All"}
            </button>
            {latestCurationEvidence.size > 0 && !aiStagingActive ? (
              <button
                type="button"
                className="ai-stage-action"
                onClick={stageAiRecommendations}
                title="Mark AI keep and reject recommendations for review without committing them"
              >
                <Sparkles size={14} aria-hidden="true" /> Stage AI Picks
              </button>
            ) : null}
            {aiStagingActive ? (
              <>
                <button
                  type="button"
                  className="ai-commit-action"
                  onClick={() => void commitStagedAiDecisions()}
                  disabled={stagedAiDecisions.size === 0}
                >
                  <Check size={14} aria-hidden="true" /> Commit AI Picks ({stagedKeepCount}/{stagedRejectCount})
                </button>
                <button type="button" onClick={clearStagedAiDecisions}>
                  <RotateCcw size={14} aria-hidden="true" /> Clear AI Picks
                </button>
              </>
            ) : null}
            {view === "video" ? (
              <>
                <button
                  type="button"
                  aria-label="Select All Videos to Prepare"
                  onClick={selectVisibleVideosForBreakdown}
                  disabled={visibleItems.length === 0}
                >
                  <Check size={14} aria-hidden="true" /> Select All
                </button>
                <button
                  type="button"
                  aria-label="Deselect All Videos"
                  onClick={deselectVisibleVideosForBreakdown}
                  disabled={selectedBreakdownVideoIds.length === 0}
                >
                  <X size={14} aria-hidden="true" /> Deselect All
                </button>
                <button
                  type="button"
                  aria-label="Select AI Video Picks"
                  onClick={selectAiBreakdownPicks}
                  disabled={!visibleItems.some((item) => latestCurationEvidence.has(item.id))}
                  title="Select analyzed videos unless AI marked them reject"
                >
                  <Sparkles size={14} aria-hidden="true" /> Select AI Picks
                </button>
                <div className="video-output-choices" role="group" aria-label="Video preparation outputs">
                  <label className={videoOutputs.framesAndClips ? "selected" : ""}>
                    <input
                      type="checkbox"
                      checked={videoOutputs.framesAndClips}
                      onChange={(event) =>
                        setVideoOutputs((current) => ({ ...current, framesAndClips: event.target.checked }))
                      }
                    />
                    <Images size={13} aria-hidden="true" /> Frames &amp; clips
                  </label>
                  <label className={videoOutputs.audioTracks ? "selected" : ""}>
                    <input
                      type="checkbox"
                      checked={videoOutputs.audioTracks}
                      onChange={(event) =>
                        setVideoOutputs((current) => ({ ...current, audioTracks: event.target.checked }))
                      }
                    />
                    <AudioLines size={13} aria-hidden="true" /> Audio tracks
                  </label>
                </div>
                <button
                  type="button"
                  className="primary-action"
                  aria-label="Prepare Selected Videos"
                  onClick={prepareSelectedVideos}
                  disabled={breakdownInFlight || selectedBreakdownVideoIds.length === 0 || selectedVideoOutputCount === 0}
                >
                  {videoOutputs.audioTracks && !videoOutputs.framesAndClips
                    ? <AudioLines size={14} aria-hidden="true" />
                    : <Clapperboard size={14} aria-hidden="true" />}
                  {videoPreparationButtonLabel(videoOutputs)} ({selectedBreakdownVideoIds.length})
                </button>
              </>
            ) : null}
            {view === "audio" && rejectedVoiceCount > 0 ? (
              <button
                type="button"
                className={showRejectedAudio ? "audio-filter active" : "audio-filter"}
                aria-pressed={showRejectedAudio}
                onClick={() => setShowRejectedAudio((current) => !current)}
              >
                <RotateCcw size={14} aria-hidden="true" />
                {showRejectedAudio
                  ? `Show usable audio (${voiceCount})`
                  : `Show rejected audio (${rejectedVoiceCount})`}
              </button>
            ) : null}
            {view === "audio" ? (
              <>
                <button type="button" onClick={selectVisibleAudio} disabled={visibleItems.length === 0}>
                  <Check size={14} aria-hidden="true" /> Select All
                </button>
                <button type="button" onClick={deselectVisibleAudio} disabled={selectedAudioIds.length === 0}>
                  <X size={14} aria-hidden="true" /> Deselect All
                </button>
                <button
                  type="button"
                  onClick={() => void prepareSelectedAudio(false)}
                  disabled={audioCleaningInFlight || selectedAudioIds.length === 0}
                  title="Apply each track's saved cleaning recipe and create training derivatives"
                >
                  <AudioLines size={14} aria-hidden="true" /> Clean ({selectedAudioIds.length})
                </button>
                <button
                  type="button"
                  className="primary-action"
                  onClick={() => void prepareSelectedAudio(true)}
                  disabled={audioCleaningInFlight || selectedAudioIds.length === 0 || !audioSeparationStatus?.ready}
                  title={audioSeparationStatus?.message ?? "Checking vocal-isolation runtime"}
                >
                  <Sparkles size={14} aria-hidden="true" /> Isolate &amp; Clean ({selectedAudioIds.length})
                </button>
              </>
            ) : null}
            </div>
          </div>
          {searchOpen ? (
            <div className="curate-search-panel">
              <Search size={15} aria-hidden="true" />
              <input
                id="curate-search"
                aria-label="Search media"
                autoFocus
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder={view === "sources" ? "Search media by source, title, or account" : "Search media by name, path, or metadata"}
              />
              {searchText ? (
                <button
                  type="button"
                  aria-label="Clear media search"
                  title="Clear search"
                  onClick={() => setSearchText("")}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="curate-lane-tabs" role="tablist" aria-label="Curate workspace lanes">
            <LaneButton icon={Library} label="Sources" value="sources" current={view} onSelect={setView} />
            <LaneButton icon={Images} label="Images" value="image" current={view} onSelect={setView} count={imageCount} />
            <LaneButton icon={Video} label="Video" value="video" current={view} onSelect={setView} count={videoCount} />
            <LaneButton icon={AudioLines} label="Audio" value="audio" current={view} onSelect={setView} count={voiceCount} />
          </div>
        </aside>

        {status !== "Idle" ? (
          <p aria-live="polite" className="status-line curate-status-line">
            {status}
          </p>
        ) : null}

        <section className="curate-results" aria-label="Curate search results">
          <div className="panel-header">
            <h3>
              {view === "sources"
                ? "Source bundles"
                : view === "audio" && showRejectedAudio
                  ? "Rejected audio candidates"
                  : `${laneLabel(view)} candidates`}
            </h3>
            <p className="muted">
              <span>{view === "sources" ? visibleBundles.length : visibleItems.length} visible</span>
              <span> / </span>
              <span>{selectedCount} selected</span>
            </p>
          </div>
          {view === "sources" ? (
            visibleBundles.length === 0 ? (
              <p className="empty-state">No source bundles match the current search.</p>
            ) : (
              <div className="source-bundle-grid">
                {displayedBundles.map((bundle) => (
                  <SourceBundleCard
                    key={bundle.id}
                    bundle={bundle}
                    mediaItems={canonicalMediaItems}
                    assetUrl={engine.assetUrl}
                    onOpenLane={setView}
                    onRejectItems={rejectItems}
                    rejectingIds={rejectingIds}
                    onExpand={setExpandedItem}
                  />
                ))}
              </div>
            )
          ) : visibleItems.length === 0 ? (
            <p className="empty-state">No {laneLabel(view).toLowerCase()} candidates match the current search.</p>
          ) : (
            <div className="media-grid">
              {displayedItems.map((item) => (
                <article
                  className={mediaCardClass(
                    selectedIds.has(item.id),
                    latestCurationEvidence.get(item.id),
                    stagedAiDecisions.get(item.id),
                  )}
                  key={item.id}
                  aria-label={displayName(item)}
                >
                  <div className="media-preview-shell">
                    <MediaPreview
                      item={item}
                      assetUrl={engine.assetUrl}
                      hoverPlayback
                      artworkItem={audioArtworkItem(item, canonicalMediaItems)}
                      onExpand={item.media_type === "audio" ? setAudioReviewItem : setExpandedItem}
                    />
                    <div className="media-action-dock" aria-label="Quick media actions">
                      {item.media_type === "image" ? (
                        <button
                          className="media-rotate-action"
                          type="button"
                          aria-label={`Rotate Clockwise: ${displayName(item)}`}
                          title="Rotate clockwise"
                          disabled={rotatingIds.has(item.id)}
                          onClick={() => void rotateImage(item)}
                        >
                          <RotateCw size={15} aria-hidden="true" />
                        </button>
                      ) : null}
                      <button
                        className={
                          (aiStagingActive
                            ? stagedAiDecisions.get(item.id) === "keep"
                            : selectedIds.has(item.id))
                            ? "media-select-action selected"
                            : "media-select-action"
                        }
                        type="button"
                        aria-pressed={
                          aiStagingActive
                            ? stagedAiDecisions.get(item.id) === "keep"
                            : selectedIds.has(item.id)
                        }
                        aria-label={
                          aiStagingActive
                            ? `Stage Keep: ${displayName(item)}`
                            : `Select for Identify: ${displayName(item)}`
                        }
                        title={aiStagingActive ? "Stage keep" : selectedIds.has(item.id) ? "Remove selection" : "Select for Identify"}
                        onClick={() =>
                          aiStagingActive
                            ? toggleStagedDecision(item.id, "keep")
                            : toggleSelected(item.id)
                        }
                      >
                        <Check size={15} aria-hidden="true" />
                      </button>
                      {item.media_type === "audio" && showRejectedAudio ? (
                        <button
                          className="media-restore-action"
                          type="button"
                          aria-label={`Restore Audio: ${displayName(item)}`}
                          title="Keep this audio"
                          onClick={() => void restoreAudio(item.id)}
                        >
                          <RotateCcw size={15} aria-hidden="true" />
                        </button>
                      ) : (
                        <button
                          className="media-reject-action"
                          type="button"
                          aria-label={
                            aiStagingActive
                              ? `Stage Reject: ${displayName(item)}`
                              : `Reject ${laneLabel(item.media_type)}: ${displayName(item)}`
                          }
                          title={aiStagingActive ? "Stage reject" : `Reject ${laneLabel(item.media_type).toLowerCase()}`}
                          disabled={rejectingIds.has(item.id)}
                          onClick={() =>
                            aiStagingActive
                              ? toggleStagedDecision(item.id, "reject")
                              : void rejectItems([item.id], laneLabel(item.media_type).toLowerCase())
                          }
                        >
                          <X size={15} aria-hidden="true" />
                        </button>
                      )}
                      {aiStagingActive && stagedAiDecisions.has(item.id) ? (
                        <button
                          className="media-clear-stage-action"
                          type="button"
                          aria-label={`Clear Staged Decision: ${displayName(item)}`}
                          title="Leave undecided"
                          onClick={() =>
                            setStagedAiDecisions((current) => {
                              const next = new Map(current);
                              next.delete(item.id);
                              return next;
                            })
                          }
                        >
                          <RotateCcw size={14} aria-hidden="true" />
                        </button>
                      ) : null}
                    </div>
                  </div>
                  {latestCurationEvidence.has(item.id) ? (
                    <CurationEvidenceBadge
                      evidence={latestCurationEvidence.get(item.id)!}
                      stagedDecision={stagedAiDecisions.get(item.id)}
                    />
                  ) : null}
                  <div className="media-card-body">
                    {item.media_type === "video" ? (
                      <>
                        <label className="media-select">
                          <input
                            type="checkbox"
                            checked={breakdownSourceIds.has(item.id)}
                            aria-label={`Select to Prepare: ${displayName(item)}`}
                            onChange={() => toggleBreakdownSelected(item.id)}
                          />
                          Prepare
                        </label>
                        {latestAnalysisBySource.has(item.id) ? (
                          <button
                            className="inline-action"
                            type="button"
                            onClick={() => setReviewJob(latestAnalysisBySource.get(item.id) ?? null)}
                            aria-label={`Open Analysis: ${displayName(item)}`}
                          >
                            Open analysis
                          </button>
                        ) : null}
                      </>
                    ) : null}
                    <strong>{displayName(item)}</strong>
                    <span>{mediaSummary(item)}</span>
                    <p>{item.raw_path ?? item.id}</p>
                    {latestCurationEvidence.get(item.id)?.reasons[0] ? (
                      <small className="ai-evidence-reason">
                        {latestCurationEvidence.get(item.id)?.reasons[0]}
                      </small>
                    ) : null}
                    {latestCurationEvidence.has(item.id) ? (
                      <CurationEvidenceFacts evidence={latestCurationEvidence.get(item.id)!} />
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
          {displayedResultCount < visibleResultCount ? (
            <div className="curate-load-more">
              <span>{displayedResultCount} of {visibleResultCount} loaded</span>
              <button
                type="button"
                onClick={() => setRenderLimit((current) => current + CURATION_RENDER_PAGE_SIZE)}
              >
                Load {Math.min(CURATION_RENDER_PAGE_SIZE, visibleResultCount - displayedResultCount)} more
              </button>
            </div>
          ) : null}
        </section>
      </div>
      {handoffReviewOpen ? (
        <div className="curation-handoff-backdrop" role="presentation" onMouseDown={() => setHandoffReviewOpen(false)}>
          <section className="curation-handoff" role="dialog" aria-modal="true" aria-labelledby="curation-handoff-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <ScanFace size={20} aria-hidden="true" />
                <span><h3 id="curation-handoff-title">{workflowTarget === "voice" ? "Speaker Verification" : "Identity Verification"}</h3><p>{handoffItems.length} prepared candidates</p></span>
              </div>
              <button type="button" aria-label="Close curation handoff" onClick={() => setHandoffReviewOpen(false)}><X size={16} /></button>
            </header>
            <div className="curation-handoff-lanes">
              <div><Images size={19} aria-hidden="true" /><span><strong>Face</strong><small>Image identity and crops</small></span><b>{handoffLaneCounts.image}</b></div>
              <div><Video size={19} aria-hidden="true" /><span><strong>Video Subject</strong><small>Identity across each clip</small></span><b>{handoffLaneCounts.video}</b></div>
              <div><AudioLines size={19} aria-hidden="true" /><span><strong>Speaker</strong><small>Voice ownership and quality</small></span><b>{handoffLaneCounts.audio}</b></div>
            </div>
            <footer>
              <button type="button" onClick={() => setHandoffReviewOpen(false)}>Back</button>
              <button className="primary-action" type="button" onClick={() => void confirmCurationHandoff()}>
                {workflowTarget === "voice" ? "Start Speaker Verification" : "Start Identity Verification"} <ArrowRight size={14} />
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {duplicateReviewOpen ? (
        <div className="duplicate-review-backdrop" role="presentation" onMouseDown={() => setDuplicateReviewOpen(false)}>
          <section className="duplicate-review-dialog" role="dialog" aria-modal="true" aria-labelledby="duplicate-review-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <Copy size={19} aria-hidden="true" />
                <span><h3 id="duplicate-review-title">Exact Duplicates</h3><p>One canonical file is kept; every alternate source remains recorded.</p></span>
              </div>
              <button type="button" aria-label="Close duplicate review" title="Close" onClick={() => setDuplicateReviewOpen(false)}><X size={16} /></button>
            </header>
            <div className="duplicate-cluster-list">
              {duplicateClusters.map((cluster) => (
                <article key={cluster.id}>
                  <div><strong>{cluster.media_type}</strong><span>{cluster.duplicate_count + 1} copies</span></div>
                  <code>{cluster.canonical_raw_path}</code>
                  {cluster.original_paths.length > 1 ? (
                    <ul>{cluster.original_paths.map((path) => <li key={path}>{path}</li>)}</ul>
                  ) : null}
                  <small>{cluster.source_bundle_keys.length} source bundle{cluster.source_bundle_keys.length === 1 ? "" : "s"} retained</small>
                </article>
              ))}
            </div>
            <footer><button type="button" className="primary-action" onClick={() => setDuplicateReviewOpen(false)}>Done</button></footer>
          </section>
        </div>
      ) : null}
      {expandedItem ? (
        <MediaLightbox
          item={expandedItem}
          assetUrl={engine.assetUrl}
          onClose={() => setExpandedItem(null)}
        />
      ) : null}
    </section>
  );
}

function LaneButton({
  icon: Icon,
  label,
  value,
  current,
  count,
  onSelect,
}: {
  icon: LucideIcon;
  label: string;
  value: CurationView;
  current: CurationView;
  count?: number;
  onSelect(value: CurationView): void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={current === value}
      onClick={() => onSelect(value)}
    >
      <Icon size={14} aria-hidden="true" />
      <span>{label}</span>
      {count !== undefined ? <small>{count}</small> : null}
    </button>
  );
}

function CurationEvidenceBadge({
  evidence,
  stagedDecision,
}: {
  evidence: CurationAnalysisEvidence;
  stagedDecision?: StagedAiDecision;
}) {
  return (
    <span
      className={`ai-evidence-badge ${stagedDecision ? `staged-${stagedDecision}` : evidence.recommendation}`}
      title={curationEvidenceTitle(evidence)}
    >
      <Sparkles size={11} aria-hidden="true" />
      {stagedDecision ? `staged ${stagedDecision}` : evidence.recommendation}
    </span>
  );
}

function CurationEvidenceFacts({ evidence }: { evidence: CurationAnalysisEvidence }) {
  const facts = evidenceFacts(evidence);
  if (facts.length === 0) {
    return null;
  }
  return (
    <span className="ai-evidence-facts" title={`Analyzer: ${evidence.analyzer}`}>
      {facts.map((fact) => <small key={fact}>{fact}</small>)}
    </span>
  );
}

function mediaCardClass(
  selected: boolean,
  evidence?: CurationAnalysisEvidence,
  stagedDecision?: StagedAiDecision,
): string {
  return [
    "media-card",
    selected ? "selected" : "",
    evidence ? `ai-${evidence.recommendation}` : "",
    stagedDecision ? `staged-${stagedDecision}` : "",
  ].filter(Boolean).join(" ");
}

function countRecommendations(evidence: CurationAnalysisEvidence[]) {
  return evidence.reduce(
    (counts, item) => ({ ...counts, [item.recommendation]: counts[item.recommendation] + 1 }),
    { keep: 0, review: 0, reject: 0 },
  );
}

function countStagedDecisions(decisions: Map<string, StagedAiDecision>) {
  return [...decisions.values()].reduce(
    (counts, decision) => ({ ...counts, [decision]: counts[decision] + 1 }),
    { keep: 0, reject: 0 },
  );
}

function evidenceFacts(evidence: CurationAnalysisEvidence): string[] {
  if (evidence.media_type === "image") {
    return [
      evidence.quality_score == null ? null : `Q ${formatEvidencePercent(evidence.quality_score)}`,
      evidence.face_count == null ? null : `Faces ${evidence.face_count}`,
      evidence.face_area == null ? null : `Face ${formatEvidencePercent(evidence.face_area)}`,
      evidence.body_coverage == null ? null : `Body ${formatEvidencePercent(evidence.body_coverage)}`,
      evidence.pose_coverage == null ? null : `Pose ${formatEvidencePercent(evidence.pose_coverage)}`,
      evidence.aesthetic_score == null ? null : `Aesthetic ${formatEvidencePercent(evidence.aesthetic_score)}`,
    ].filter((fact): fact is string => fact !== null);
  }
  if (evidence.media_type === "audio") {
    return [
      evidence.active_audio_ratio == null ? null : `Active ${formatEvidencePercent(evidence.active_audio_ratio)}`,
      evidence.speech_duration_ratio == null ? null : `Speech ${formatEvidencePercent(evidence.speech_duration_ratio)}`,
      evidence.word_count == null ? null : `Words ${evidence.word_count}`,
      evidence.speaker_count == null ? null : `Speakers ${evidence.speaker_count}`,
      evidence.clipping_ratio == null ? null : `Clip ${formatEvidencePercent(evidence.clipping_ratio)}`,
    ].filter((fact): fact is string => fact !== null);
  }
  return [
    `Confidence ${formatEvidencePercent(evidence.confidence)}`,
    evidence.sample_count == null ? null : `Samples ${evidence.sample_count}`,
    evidence.quality_score == null ? null : `Q ${formatEvidencePercent(evidence.quality_score)}`,
    evidence.face_count == null ? null : `Faces ${evidence.face_count}`,
    evidence.body_coverage == null ? null : `Body ${formatEvidencePercent(evidence.body_coverage)}`,
    evidence.pose_coverage == null ? null : `Pose ${formatEvidencePercent(evidence.pose_coverage)}`,
  ].filter((fact): fact is string => fact !== null);
}

function curationEvidenceTitle(evidence: CurationAnalysisEvidence): string {
  return [
    `${formatEvidencePercent(evidence.confidence)} confidence`,
    ...evidenceFacts(evidence),
    ...evidence.reasons,
    ...evidence.warnings.map((warning) => `Warning: ${warning}`),
    `Analyzer: ${evidence.analyzer}`,
  ].join("; ");
}

function formatEvidencePercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function SourceBundleCard({
  bundle,
  mediaItems,
  assetUrl,
  onOpenLane,
  onRejectItems,
  rejectingIds,
  onExpand,
}: {
  bundle: CurationSourceBundle;
  mediaItems: MediaItem[];
  assetUrl(path: string): string;
  onOpenLane(lane: CurationView): void;
  onRejectItems(itemIds: string[], label: string): void;
  rejectingIds: Set<string>;
  onExpand(item: MediaItem): void;
}) {
  const [hovered, setHovered] = useState(false);
  const [previewLane, setPreviewLane] = useState<MediaType | null>(null);
  const itemById = new Map(mediaItems.map((item) => [item.id, item]));
  const items = bundle.items
    .map((bundleItem) => itemById.get(bundleItem.media_item_id))
    .filter((item): item is MediaItem => item !== undefined);
  const representative =
    items.find((item) => item.media_type === "image") ??
    items.find((item) => item.media_type === "video") ??
    items[0];
  const laneItems = {
    image: items.filter((item) => item.media_type === "image"),
    video: items.filter((item) => item.media_type === "video"),
    audio: items.filter(
      (item) => item.media_type === "audio" && isUsefulAudio(item, itemById),
    ),
  };
  const previewItem = previewLane ? laneItems[previewLane][0] ?? representative : representative;
  const counts = {
    image: laneItems.image.length,
    video: laneItems.video.length,
    audio: laneItems.audio.length,
  };
  return (
    <article
      className="source-bundle-card"
      aria-label={bundle.title}
      title={bundle.title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => {
        setHovered(false);
        setPreviewLane(null);
      }}
    >
      {previewItem ? (
        <MediaPreview
          key={previewItem.id}
          item={previewItem}
          assetUrl={assetUrl}
          compact
          autoPlay={hovered && previewItem.media_type !== "image"}
          artworkItem={audioArtworkItem(previewItem, items)}
          onExpand={previewItem.media_type === "audio" ? undefined : onExpand}
        />
      ) : null}
      <div className="bundle-lane-overlays" aria-label="Bundle outputs">
        <BundleLaneButton icon={Images} label="Images" lane="image" count={counts.image} onOpen={onOpenLane} onPreview={setPreviewLane} />
        <BundleLaneButton icon={Video} label="Video" lane="video" count={counts.video} onOpen={onOpenLane} onPreview={setPreviewLane} />
        <BundleLaneButton icon={AudioLines} label="Audio" lane="audio" count={counts.audio} onOpen={onOpenLane} onPreview={setPreviewLane} />
      </div>
      <div className="bundle-reject-actions" aria-label="Quick reject bundle outputs">
        <BundleRejectButton icon={Images} label="images" itemIds={laneItems.image.map((item) => item.id)} rejectingIds={rejectingIds} onReject={onRejectItems} />
        <BundleRejectButton icon={Video} label="video" itemIds={laneItems.video.map((item) => item.id)} rejectingIds={rejectingIds} onReject={onRejectItems} />
        <BundleRejectButton icon={AudioLines} label="audio" itemIds={laneItems.audio.map((item) => item.id)} rejectingIds={rejectingIds} onReject={onRejectItems} />
      </div>
    </article>
  );
}

function BundleLaneButton({
  icon: Icon,
  label,
  lane,
  count,
  onOpen,
  onPreview,
}: {
  icon: LucideIcon;
  label: string;
  lane: MediaType;
  count: number;
  onOpen(lane: CurationView): void;
  onPreview(lane: MediaType): void;
}) {
  return (
    <button
      type="button"
      aria-label={`${label} ${count}`}
      title={`${count} ${label.toLowerCase()} candidate${count === 1 ? "" : "s"}`}
      disabled={count === 0}
      onClick={() => onOpen(lane)}
      onMouseEnter={() => onPreview(lane)}
      onFocus={() => onPreview(lane)}
    >
      <Icon size={12} aria-hidden="true" />
      <strong>{count}</strong>
    </button>
  );
}

function BundleRejectButton({
  icon: Icon,
  label,
  itemIds,
  rejectingIds,
  onReject,
}: {
  icon: LucideIcon;
  label: string;
  itemIds: string[];
  rejectingIds: Set<string>;
  onReject(itemIds: string[], label: string): void;
}) {
  if (itemIds.length === 0) {
    return null;
  }
  return (
    <button
      type="button"
      aria-label={`Reject ${label}`}
      title={`Reject ${label}`}
      disabled={itemIds.some((itemId) => rejectingIds.has(itemId))}
      onClick={() => onReject(itemIds, label)}
    >
      <Icon size={13} aria-hidden="true" />
      <X size={10} aria-hidden="true" />
    </button>
  );
}

function MediaPreview({
  item,
  assetUrl,
  compact = false,
  autoPlay = false,
  hoverPlayback = false,
  artworkItem,
  onExpand,
}: {
  item: MediaItem;
  assetUrl(path: string): string;
  compact?: boolean;
  autoPlay?: boolean;
  hoverPlayback?: boolean;
  artworkItem?: MediaItem;
  onExpand?(item: MediaItem): void;
}) {
  const [previewHovered, setPreviewHovered] = useState(false);
  const [scrubFeedback, setScrubFeedback] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const scrubFeedbackTimeoutRef = useRef<number | null>(null);
  const assetPath = item.raw_path ? assetUrl(item.raw_path) : undefined;
  const artworkPath = artworkItem?.raw_path ? assetUrl(artworkItem.raw_path) : undefined;
  const shouldPlay = autoPlay || (hoverPlayback && previewHovered);
  useEffect(() => {
    const media = item.media_type === "video" ? videoRef.current : audioRef.current;
    if (!media) {
      return;
    }
    if (shouldPlay) {
      media.muted = false;
      try {
        const playback = media.play();
        if (playback) {
          void playback.catch(() => undefined);
        }
      } catch {
        // Browsers can require one click before allowing audible hover playback.
      }
      return;
    }
    if (!media.paused) {
      media.pause();
    }
    if (media.currentTime > 0) {
      media.currentTime = 0;
    }
  }, [assetPath, item.media_type, shouldPlay]);
  useEffect(
    () => () => {
      if (scrubFeedbackTimeoutRef.current !== null) {
        window.clearTimeout(scrubFeedbackTimeoutRef.current);
      }
    },
    [],
  );

  function handleWheelScrub(
    event: ReactWheelEvent,
    media: HTMLMediaElement,
  ) {
    const nextTime = scrubMediaWithWheel(event, media, item.duration);
    if (nextTime === null) {
      return;
    }
    setScrubFeedback(formatMediaTime(nextTime));
    if (scrubFeedbackTimeoutRef.current !== null) {
      window.clearTimeout(scrubFeedbackTimeoutRef.current);
    }
    scrubFeedbackTimeoutRef.current = window.setTimeout(() => {
      setScrubFeedback(null);
      scrubFeedbackTimeoutRef.current = null;
    }, 700);
  }
  return (
    <div
      className={compact ? "media-preview compact" : "media-preview"}
      onMouseEnter={() => setPreviewHovered(true)}
      onMouseLeave={() => setPreviewHovered(false)}
    >
      {item.media_type === "image" && assetPath ? (
        onExpand ? (
          <button
            className="media-expand-hit"
            type="button"
            aria-label={`Expand preview: ${displayName(item)}`}
            onClick={() => onExpand(item)}
          >
            <img src={assetPath} alt="" />
          </button>
        ) : (
          <img src={assetPath} alt="" />
        )
      ) : item.media_type === "video" && assetPath ? (
        <>
          <video
            ref={videoRef}
            src={assetPath}
            controls={!compact || shouldPlay}
            playsInline
            preload="metadata"
            onWheel={(event) => handleWheelScrub(event, event.currentTarget)}
          />
          {onExpand ? (
            <button
              className="preview-expand-action"
              type="button"
              aria-label={`Expand preview: ${displayName(item)}`}
              onClick={() => onExpand(item)}
            >
              <Maximize2 size={14} aria-hidden="true" />
            </button>
          ) : null}
        </>
      ) : item.media_type === "audio" && assetPath ? (
        <div
          className={artworkPath ? "audio-preview has-artwork" : "audio-preview"}
          onWheel={(event) => {
            if (audioRef.current) {
              handleWheelScrub(event, audioRef.current);
            }
          }}
        >
          {artworkPath ? <img className="audio-preview-artwork" src={artworkPath} alt="" /> : null}
          {artworkPath ? <span className="audio-preview-shade" aria-hidden="true" /> : null}
          <AudioLines size={compact ? 22 : 32} aria-hidden="true" />
          {!compact || shouldPlay ? (
            <audio
              ref={audioRef}
              src={assetPath}
              controls
              preload="metadata"
            />
          ) : (
            <audio
              ref={audioRef}
              src={assetPath}
              preload="metadata"
            />
          )}
          {onExpand ? (
            <button
              className="preview-expand-action"
              type="button"
              aria-label={`Open audio review: ${displayName(item)}`}
              title="Open audio review"
              onClick={() => onExpand(item)}
            >
              <Maximize2 size={14} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      ) : (
        <span>{mediaTypeLabel(item.media_type)}</span>
      )}
      <span className="thumb-overlay" aria-hidden="true">
        <span className="thumb-meta">{mediaTypeLabel(item.media_type)}</span>
        <span className="thumb-status ready">{item.status ?? "new"}</span>
      </span>
      {scrubFeedback ? (
        <span className="media-scrub-feedback" aria-live="polite">
          {scrubFeedback}
        </span>
      ) : null}
    </div>
  );
}

function MediaLightbox({
  item,
  assetUrl,
  onClose,
}: {
  item: MediaItem;
  assetUrl(path: string): string;
  onClose(): void;
}) {
  const assetPath = item.raw_path ? assetUrl(item.raw_path) : undefined;
  return (
    <div
      className="media-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Expanded preview: ${displayName(item)}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="media-lightbox-content">
        <button
          className="media-lightbox-close"
          type="button"
          aria-label="Close expanded preview"
          onClick={onClose}
        >
          <X size={19} aria-hidden="true" />
        </button>
        {item.media_type === "image" && assetPath ? (
          <img src={assetPath} alt="" />
        ) : item.media_type === "video" && assetPath ? (
          <video
            src={assetPath}
            controls
            autoPlay
            playsInline
            onWheel={(event) => scrubMediaWithWheel(event, event.currentTarget, item.duration)}
          />
        ) : null}
      </div>
    </div>
  );
}

function displayName(item: MediaItem): string {
  const rawPath = item.raw_path;
  if (!rawPath) {
    return item.id;
  }
  const normalized = rawPath.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).at(-1) ?? item.id;
}

function scrubMediaWithWheel(
  event: ReactWheelEvent,
  media: HTMLMediaElement,
  manifestDuration?: number | null,
): number | null {
  const wheelDelta = event.deltaY !== 0 ? event.deltaY : event.deltaX;
  const duration = Number.isFinite(media.duration) && media.duration > 0
    ? media.duration
    : manifestDuration;
  if (!wheelDelta || typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) {
    return null;
  }
  event.preventDefault();
  event.stopPropagation();
  const secondsPerUnit = event.deltaMode === 1 ? 1 : event.deltaMode === 2 ? 10 : 1 / 45;
  const rawDeltaSeconds = wheelDelta * secondsPerUnit;
  const deltaSeconds = Math.sign(rawDeltaSeconds)
    * Math.min(10, Math.max(0.1, Math.abs(rawDeltaSeconds)));
  const nextTime = Math.min(duration, Math.max(0, media.currentTime + deltaSeconds));
  media.currentTime = nextTime;
  return nextTime;
}

function formatMediaTime(seconds: number): string {
  const wholeSeconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(wholeSeconds / 60);
  return `${minutes}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function mediaSummary(item: MediaItem): string {
  if (item.width && item.height) {
    return `${item.width}x${item.height}`;
  }
  if (typeof item.duration === "number") {
    return `${item.duration.toFixed(1)}s`;
  }
  return mediaTypeLabel(item.media_type);
}

function mediaTypeLabel(mediaType: MediaType): string {
  return mediaType === "audio" ? "audio" : mediaType;
}

function laneLabel(view: Exclude<CurationView, "sources">): string {
  if (view === "image") return "Image";
  if (view === "video") return "Video";
  return "Audio";
}

function deduplicateMediaItems(mediaItems: MediaItem[]): MediaItem[] {
  const canonicalByContent = new Map<string, MediaItem>();
  const canonicalIdByItemId = new Map<string, string>();
  for (const item of mediaItems) {
    const contentKey = mediaContentKey(item);
    const canonical = canonicalByContent.get(contentKey);
    if (canonical) {
      canonicalIdByItemId.set(item.id, canonical.id);
      continue;
    }
    canonicalByContent.set(contentKey, item);
    canonicalIdByItemId.set(item.id, item.id);
  }
  return [...canonicalByContent.values()].map((item) => {
    const parentId = metadataString(item, "source_media_item_id");
    const canonicalParentId = parentId ? canonicalIdByItemId.get(parentId) : undefined;
    if (!parentId || !canonicalParentId || canonicalParentId === parentId) {
      return item;
    }
    return {
      ...item,
      metadata_json: {
        ...item.metadata_json,
        source_media_item_id: canonicalParentId,
      },
    };
  });
}

function mediaContentKey(item: MediaItem): string {
  if (item.sha256?.trim()) {
    return `${item.media_type}:sha256:${item.sha256.trim().toLowerCase()}`;
  }
  if (item.raw_path?.trim()) {
    return `${item.media_type}:path:${item.raw_path.trim()}`;
  }
  return `${item.media_type}:id:${item.id}`;
}

function buildSourceBundles(mediaItems: MediaItem[]): CurationSourceBundle[] {
  const mediaById = new Map(mediaItems.map((item) => [item.id, item]));
  const grouped = new Map<string, MediaItem[]>();
  for (const item of mediaItems) {
    const root = rootMediaItem(item, mediaById);
    const bundleKey = metadataString(item, "source_bundle_key")
      ?? metadataString(root, "source_bundle_key")
      ?? `media:${root.id}`;
    grouped.set(bundleKey, [...(grouped.get(bundleKey) ?? []), item]);
  }
  return [...grouped.entries()]
    .map(([id, items]) => {
      const roots = [...new Set(items.map((item) => rootMediaItem(item, mediaById).id))];
      const representative = items.find((item) => roots.includes(item.id)) ?? items[0];
      const sourceKind = metadataString(representative, "source_kind");
      return {
        id,
        title: metadataString(representative, "display_name") ?? displayName(representative),
        source_kind: isSourceKind(sourceKind) ? sourceKind : null,
        source_locator: metadataString(representative, "source_locator"),
        root_media_item_ids: roots,
        intent_lanes: [...new Set(items.map((item) => item.media_type))],
        items: items.map((item) => ({
          media_item_id: item.id,
          lane: item.media_type,
          role: metadataString(item, "asset_role") ?? "source",
          source_media_item_id: metadataString(item, "source_media_item_id"),
          derivative_type: metadataString(item, "derivative_type"),
        })),
      } satisfies CurationSourceBundle;
    })
    .sort((left, right) => left.title.localeCompare(right.title));
}

function rootMediaItem(item: MediaItem, mediaById: Map<string, MediaItem>): MediaItem {
  let current = item;
  const visited = new Set<string>();
  while (!visited.has(current.id)) {
    visited.add(current.id);
    const parentId = metadataString(current, "source_media_item_id");
    const parent = parentId ? mediaById.get(parentId) : undefined;
    if (!parent) return current;
    current = parent;
  }
  return current;
}

function metadataString(item: MediaItem, key: string): string | undefined {
  const value = item.metadata_json?.[key];
  return typeof value === "string" && value ? value : undefined;
}

function isUsefulAudio(item: MediaItem, mediaById: Map<string, MediaItem>): boolean {
  const root = rootMediaItem(item, mediaById);
  if (
    [item, root].some(
      (candidate) => metadataString(candidate, "audio_review_override") === "keep",
    )
  ) {
    return true;
  }
  for (const candidate of [item, root]) {
    const original = candidate.metadata_json?.audio_original;
    if (original === false || original === "false") {
      return false;
    }
    const kind = metadataString(candidate, "audio_kind")?.toLowerCase();
    const type = metadataString(candidate, "audio_type")?.toLowerCase();
    if (
      kind === "music" ||
      kind === "reused_or_music" ||
      type?.includes("music") ||
      type?.includes("licensed")
    ) {
      return false;
    }
  }
  return true;
}

function audioArtworkItem(item: MediaItem, mediaItems: MediaItem[]): MediaItem | undefined {
  if (item.media_type !== "audio") {
    return undefined;
  }
  const mediaById = new Map(mediaItems.map((candidate) => [candidate.id, candidate]));
  const root = rootMediaItem(item, mediaById);
  const bundleKey = metadataString(item, "source_bundle_key")
    ?? metadataString(root, "source_bundle_key")
    ?? `media:${root.id}`;
  const candidates = mediaItems.filter((candidate) => {
    if (candidate.media_type !== "image") {
      return false;
    }
    const candidateRoot = rootMediaItem(candidate, mediaById);
    const candidateBundleKey = metadataString(candidate, "source_bundle_key")
      ?? metadataString(candidateRoot, "source_bundle_key")
      ?? `media:${candidateRoot.id}`;
    return candidateBundleKey === bundleKey;
  });
  return candidates.find((candidate) => metadataString(candidate, "asset_role") === "video_poster")
    ?? candidates.find((candidate) => metadataString(candidate, "derivative_type") === "video_frame")
    ?? candidates[0];
}

function isSourceKind(
  value: string | undefined,
): value is NonNullable<CurationSourceBundle["source_kind"]> {
  return value === "local" || value === "instagram" || value === "x_twitter" || value === "tiktok";
}

function searchableText(item: MediaItem): string {
  return [
    item.id,
    item.raw_path,
    item.media_type,
    item.status,
    item.width,
    item.height,
    item.duration,
    JSON.stringify(item.metadata_json ?? {}),
  ]
    .filter((value) => value !== undefined && value !== null)
    .join(" ")
    .toLowerCase();
}

async function pollProcessingJob(
  jobId: string,
  getProcessingJob: EngineClient["getProcessingJob"],
  onDetail: (job: ProcessingJob) => void,
): Promise<ProcessingJob> {
  let latestDetail: ProcessingJob | undefined;
  for (let attempt = 0; attempt < PROCESSING_JOB_MAX_DETAIL_ATTEMPTS; attempt += 1) {
    latestDetail = await getProcessingJob(jobId);
    onDetail(latestDetail);
    if (terminalProcessingStatuses.has(latestDetail.status)) {
      return latestDetail;
    }
    if (attempt < PROCESSING_JOB_MAX_DETAIL_ATTEMPTS - 1) {
      await delay(PROCESSING_JOB_POLL_DELAY_MS);
    }
  }

  throw new Error(
    `Video breakdown job ${jobId} did not finish after ${PROCESSING_JOB_MAX_DETAIL_ATTEMPTS} checks.`,
  );
}

async function findReusableProcessingJob(
  sourceMediaItemIds: string[],
  requestedOptions: VideoBreakdownOptions,
  listProcessingJobs: EngineClient["listProcessingJobs"],
): Promise<ProcessingJob | undefined> {
  const selectedKey = sourceSetKey(sourceMediaItemIds);
  const jobs = await listProcessingJobs();
  return jobs.find(
    (job) =>
      job.job_type === "video_breakdown" &&
      !terminalProcessingStatuses.has(job.status) &&
      sourceSetKey(job.source_media_item_ids) === selectedKey &&
      Boolean((job.options as VideoBreakdownOptions | undefined)?.generate_frames) === Boolean(requestedOptions.generate_frames) &&
      Boolean((job.options as VideoBreakdownOptions | undefined)?.extract_audio) === Boolean(requestedOptions.extract_audio),
  );
}

function sourceSetKey(sourceMediaItemIds: string[]): string {
  return [...sourceMediaItemIds].sort().join("\u0000");
}

function defaultVideoPreparationOutputs(
  workflowTarget: CurateSearchTabProps["workflowTarget"],
): VideoPreparationOutputs {
  if (workflowTarget === "voice") {
    return { framesAndClips: false, audioTracks: true };
  }
  if (workflowTarget === "image") {
    return { framesAndClips: true, audioTracks: false };
  }
  return { framesAndClips: true, audioTracks: true };
}

function videoPreparationActivityLabel(outputs: VideoPreparationOutputs): string {
  if (outputs.audioTracks && !outputs.framesAndClips) return "Extracting audio";
  if (outputs.framesAndClips && !outputs.audioTracks) return "Creating frames and clips";
  return "Creating frames, clips, and audio";
}

function videoPreparationButtonLabel(outputs: VideoPreparationOutputs): string {
  if (outputs.audioTracks && !outputs.framesAndClips) return "Extract Audio";
  if (outputs.framesAndClips && !outputs.audioTracks) return "Create Frames & Clips";
  return "Prepare All Outputs";
}

function curateWorkflowCopy(workflowTarget: CurateSearchTabProps["workflowTarget"]): {
  title: string;
  description: string;
  handoffLabel: string;
} {
  if (workflowTarget === "voice") {
    return {
      title: "Prepare Voice Samples",
      description: "Extract audio from video, isolate clean speech, and choose tracks for speaker verification",
      handoffLabel: "Verify Speaker",
    };
  }
  if (workflowTarget === "id_lora") {
    return {
      title: "Prepare Identity Media",
      description: "Align images, motion, and cleaned voice tracks before identity verification",
      handoffLabel: "Verify Identity",
    };
  }
  return {
    title: "Prepare Media",
    description: "Images, video clips, frames, and voice tracks",
    handoffLabel: "Finish Curation",
  };
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function processingJobStatusMessage(job: ProcessingJob): string {
  const label = job.job_type === "audio_cleaning" ? "Voice preparation" : "Video breakdown";
  if (job.status === "complete") {
    if (job.derived_media_items.length > 0) {
      return `Generated ${job.derived_media_items.length} derivative media item${
        job.derived_media_items.length === 1 ? "" : "s"
      }.`;
    }
    return `${label} complete with no derivative media items.`;
  }
  if (job.status === "queued") {
    return `${label} job ${job.id} queued.`;
  }
  if (job.status === "running") {
    return `${label} job ${job.id} running: ${job.progress_message || "Processing media."}`;
  }
  if (job.status === "failed") {
    return `${label} job ${job.id} failed: ${jobErrorMessage(job)}.`;
  }
  if (job.status === "canceled") {
    return `${label} job ${job.id} canceled.`;
  }
  return `${label} job ${job.id} status: ${job.status}.`;
}

function jobErrorMessage(job: ProcessingJob): string {
  const firstError = job.errors[0];
  if (firstError) {
    const message = firstError.message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return job.progress_message || "Processing failed";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected failure";
}
