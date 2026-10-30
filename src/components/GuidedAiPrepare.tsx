import {
  AudioLines,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Eye,
  Image as ImageIcon,
  LoaderCircle,
  Sparkles,
  Video,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { EngineClient } from "../lib/api";
import type {
  CurationAnalysisEvidence,
  MediaItem,
  ProcessingJob,
  ProcessingJobStatus,
  PreparationCheckpoint,
  VideoBreakdownOptions,
} from "../lib/types";
import type { WizardTarget } from "./WorkflowWizard";
import { WarpedSphereSurface } from "./WarpedSphereSurface";

interface GuidedAiPrepareProps {
  engine: EngineClient;
  mediaItems: MediaItem[];
  target: WizardTarget;
  activeProjectId?: string;
  onComplete(items: MediaItem[]): void;
  onMediaItemsGenerated(items: MediaItem[]): void;
}

type PreparePhase = "idle" | "running" | "ready" | "finishing" | "error";
type ReviewFilter = "review" | "reject" | null;

const terminalStatuses = new Set<ProcessingJobStatus>(["complete", "failed", "canceled"]);
const pollDelayMs = 800;
const maxPollAttempts = 750;
const prepareSphereColors: ReadonlyArray<readonly [number, number, number]> = [
  [91, 201, 232],
  [98, 230, 174],
  [181, 139, 242],
];


function readCheckpoint(key: string): PreparationCheckpoint | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "null");
    return value && Array.isArray(value.sourceItems) ? value : null;
  } catch { return null; }
}

export function GuidedAiPrepare(props: GuidedAiPrepareProps) {
  return <PreparationSession key={`${props.activeProjectId}:${props.target}`} {...props} />;
}

function PreparationSession({
  engine,
  mediaItems,
  target,
  activeProjectId = "",
  onComplete,
  onMediaItemsGenerated,
}: GuidedAiPrepareProps) {
  const checkpointKey = `lorasuite:preparation:v1:${activeProjectId}:${target}`;
  const checkpoint = useRef<PreparationCheckpoint | null>(null);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [loadingCheckpoint, setLoadingCheckpoint] = useState(Boolean(engine.getPreparationCheckpoint && activeProjectId));
  const runVersion = useRef(0);
  const [saveWarning, setSaveWarning] = useState("");
  const sourceItems = useMemo(
    () => prepareSourceItems(mediaItems, target),
    [mediaItems, target],
  );
  const [phase, setPhase] = useState<PreparePhase>("idle");
  const [status, setStatus] = useState("Ready when you are.");
  const [preparedItems, setPreparedItems] = useState<MediaItem[]>([]);
  const [evidence, setEvidence] = useState<CurationAnalysisEvidence[]>([]);
  const [includedIds, setIncludedIds] = useState<Set<string>>(() => new Set());
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>(null);
  const [reviewIndex, setReviewIndex] = useState(0);

  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.media_item_id, item])),
    [evidence],
  );
  function recommendation(item: MediaItem) {
    return decisions[item.id] === true ? "keep" : decisions[item.id] === false ? "reject" : evidenceById.get(item.id)?.recommendation;
  }
  const keepItems = preparedItems.filter(
    (item) => recommendation(item) === "keep",
  );
  const reviewItems = preparedItems.filter(
    (item) => recommendation(item) === "review",
  );
  const rejectedItems = preparedItems.filter(
    (item) => recommendation(item) === "reject",
  );
  const selectedItems = preparedItems.filter((item) => includedIds.has(item.id))
    .map((item) => mediaItems.find((source) => source.id === item.id) ?? item);
  const activeReviewItems = reviewFilter === "review" ? reviewItems : reviewFilter === "reject" ? rejectedItems : [];
  const activeReviewItem = activeReviewItems[reviewIndex];

  function saveCheckpoint(patch: Partial<PreparationCheckpoint>) {
    checkpoint.current = { sourceItems, ...checkpoint.current, ...patch };
    const compact = (item: MediaItem): MediaItem => ({
      id: item.id, raw_path: item.raw_path, media_type: item.media_type, status: item.status,
      metadata_json: Object.fromEntries(Object.entries(item.metadata_json ?? {}).filter(([key]) =>
        ["source_media_item_id", "derivative_type", "analysis_frame_id", "clip_proposal_id"].includes(key))),
    });
    const value = { ...checkpoint.current, sourceItems: checkpoint.current.sourceItems.map(compact),
      preparedItems: checkpoint.current.preparedItems?.map(compact) };
    if (engine.savePreparationCheckpoint && activeProjectId) {
      saveQueue.current = saveQueue.current.then(() => engine.savePreparationCheckpoint!(activeProjectId, target, value))
        .catch(() => { setSaveWarning("Saved on this device. Reconnect to share preparation with the desktop."); });
    }
    try { window.localStorage.setItem(checkpointKey, JSON.stringify(value)); }
    catch { setSaveWarning("Preparation is available now, but this browser could not save it for your next visit."); }
  }

  useEffect(() => {
    let ignore = false;
    function restore(saved: PreparationCheckpoint | null) {
      if (ignore) return;
      checkpoint.current = saved;
      if (saved?.evidence && saved.preparedItems) {
        setPreparedItems(saved.preparedItems);
        setEvidence(saved.evidence);
        setIncludedIds(new Set(saved.includedIds ?? []));
        setDecisions(saved.decisions ?? Object.fromEntries((saved.includedIds ?? []).map((id) => [id, true])));
        setPhase("ready");
        setStatus("Your saved preparation and review choices are restored.");
      } else if (saved?.analysisJobId || saved?.breakdownJobId) {
        void runAiPreparation(saved);
      }
      setLoadingCheckpoint(false);
    }
    const local = readCheckpoint(checkpointKey);
    if (engine.getPreparationCheckpoint && activeProjectId) {
      void engine.getPreparationCheckpoint(activeProjectId, target).then(async ({ checkpoint: shared }) => {
        if (ignore) return;
        if (!shared && local && engine.savePreparationCheckpoint) {
          const migrated = await engine.savePreparationCheckpoint(activeProjectId, target, local, true);
          restore(migrated.checkpoint);
        } else restore(shared);
      }).catch(() => {
        if (ignore) return;
        setSaveWarning("Using this device's preparation. Reconnect to load changes from the desktop.");
        restore(local);
      });
    } else restore(local);
    return () => { ignore = true; runVersion.current += 1; };
  }, []);

  useEffect(() => {
    if (phase === "ready") saveCheckpoint({ preparedItems, evidence, includedIds: [...includedIds], decisions });
  }, [phase, preparedItems, evidence, includedIds, decisions]);

  async function runAiPreparation(resume?: PreparationCheckpoint) {
    if ((!resume && (phase === "running" || loadingCheckpoint)) || (!resume && sourceItems.length === 0)) return;
    const version = ++runVersion.current;
    const ensureCurrent = () => {
      if (version !== runVersion.current) throw new Error("Preparation view changed");
    };
    const inputs = resume?.sourceItems ?? sourceItems;
    if (!resume) {
      checkpoint.current = { sourceItems: inputs };
      saveCheckpoint({});
    }
    setPhase("running");
    setEvidence([]);
    setDecisions({});
    setIncludedIds(new Set());
    setReviewFilter(null);
    try {
      let workingItems = resume?.preparedItems ?? [...inputs];
      const sourceVideos = inputs.filter((item) => item.media_type === "video");
      const breakdownOptions = targetBreakdownOptions(target);

      if (!resume?.analysisJobId && sourceVideos.length > 0 && breakdownOptions) {
        setStatus(breakdownStatus(target, sourceVideos.length));
        const queuedJob = resume?.breakdownJobId
          ? { id: resume.breakdownJobId }
          : await engine.createProcessingJob({
          job_type: "video_breakdown",
          source_media_item_ids: sourceVideos.map((item) => item.id),
          options: breakdownOptions,
        });
        saveCheckpoint({ breakdownJobId: queuedJob.id });
        ensureCurrent();
        let breakdown = await pollJob(engine, queuedJob.id, (job) => {
          ensureCurrent();
          setStatus(job.progress_message || breakdownStatus(target, sourceVideos.length));
        });
        ensureCurrent();
        if (breakdown.status !== "complete") throw new Error(jobErrorMessage(breakdown));
        let selectedFrameIds: string[] = [];
        let selectedClipIds: string[] = [];
        if (target !== "voice" && breakdown.video_analyses?.length) {
          selectedFrameIds = breakdown.video_analyses.flatMap((analysis) =>
            analysis.frames
              .filter((frame) => frame.decision === "keeper")
              .map((frame) => frame.id),
          );
          const clips = target === "video" || target === "id_lora"
            ? breakdown.video_analyses.flatMap((analysis) =>
                (analysis.clip_proposals ?? [])
                  .filter((clip) => clip.decision !== "reject")
                  .map((clip) => ({
                    clip_id: clip.id,
                    start_seconds: clip.start_seconds,
                    end_seconds: clip.end_seconds,
                    decision: clip.decision,
                  })),
              )
            : [];
          selectedClipIds = clips
            .filter((clip) => clip.decision === "keep")
            .map((clip) => clip.clip_id);
          setStatus(
            `Saving ${selectedFrameIds.length} strongest keyframe${selectedFrameIds.length === 1 ? "" : "s"}`
            + `${selectedClipIds.length ? ` and ${selectedClipIds.length} video clip${selectedClipIds.length === 1 ? "" : "s"}` : ""}.`,
          );
          breakdown = await engine.commitVideoBreakdown(breakdown.id, {
            frame_ids: selectedFrameIds,
            clips,
          });
        }
        ensureCurrent();
        const selectedBreakdownItems = filterSelectedBreakdownItems(
          breakdown.derived_media_items,
          selectedFrameIds,
          selectedClipIds,
        );
        if (selectedBreakdownItems.length > 0) {
          onMediaItemsGenerated(selectedBreakdownItems);
          workingItems = deduplicateMediaItems([...workingItems, ...selectedBreakdownItems]);
        }
      }

      const analysisItems = analysisInputs(workingItems, target);
      if (analysisItems.length === 0) {
        throw new Error(noUsableMediaMessage(target));
      }
      setPreparedItems(analysisItems);
      setStatus(`AI is evaluating ${analysisItems.length} item${analysisItems.length === 1 ? "" : "s"}.`);
      const queuedAnalysis = resume?.analysisJobId
        ? { id: resume.analysisJobId }
        : await engine.createCurationAnalysisJob(analysisItems.map((item) => item.id));
      saveCheckpoint({ analysisJobId: queuedAnalysis.id, preparedItems: analysisItems });
      ensureCurrent();
      const completedAnalysis = await pollJob(engine, queuedAnalysis.id, (job) => {
        ensureCurrent();
        setStatus(job.progress_message || "AI is evaluating the collection.");
      });
      ensureCurrent();
      if (completedAnalysis.status !== "complete" || !completedAnalysis.curation_analyses?.length) {
        throw new Error(jobErrorMessage(completedAnalysis));
      }

      const normalizedEvidence = normalizeEvidence(
        analysisItems,
        completedAnalysis.curation_analyses,
      );
      setEvidence(normalizedEvidence);
      setIncludedIds(new Set(
        normalizedEvidence
          .filter((item) => item.recommendation === "keep")
          .map((item) => item.media_item_id),
      ));
      setStatus("AI preparation is complete. Nothing has been discarded.");
      setPhase("ready");
    } catch (error) {
      if (version !== runVersion.current) return;
      setStatus(errorMessage(error));
      setPhase("error");
    }
  }

  function openReview(filter: Exclude<ReviewFilter, null>) {
    setReviewFilter(filter);
    setReviewIndex(0);
  }

  function decideReview(itemId: string, include: boolean) {
    setDecisions((current) => ({ ...current, [itemId]: include }));
    setIncludedIds((current) => {
      const next = new Set(current);
      if (include) next.add(itemId);
      else next.delete(itemId);
      return next;
    });
    if (activeReviewItems.length > 1) setReviewIndex(Math.min(reviewIndex, activeReviewItems.length - 2));
    else setReviewFilter(null);
  }

  function decideAllActive(include: boolean) {
    const activeIds = new Set(activeReviewItems.map((item) => item.id));
    setDecisions((current) => ({ ...current, ...Object.fromEntries([...activeIds].map((id) => [id, include])) }));
    setIncludedIds((current) => {
      const next = new Set(current);
      for (const itemId of activeIds) {
        if (include) next.add(itemId);
        else next.delete(itemId);
      }
      return next;
    });
    setReviewFilter(null);
    setReviewIndex(0);
  }

  async function continueWithSelection() {
    if (selectedItems.length === 0 || phase === "finishing") return;
    const version = ++runVersion.current;
    setPhase("finishing");
    try {
      let handoffItems = [...selectedItems];
      const selectedAudio = selectedItems.filter((item) => item.media_type === "audio");
      if ((target === "voice" || target === "id_lora") && selectedAudio.length > 0) {
        setStatus(`AI is cleaning ${selectedAudio.length} selected voice track${selectedAudio.length === 1 ? "" : "s"}.`);
        const queuedCleaning = await engine.createAudioCleaningJob(
          selectedAudio.map((item) => item.id),
          false,
        );
        const cleaning = await pollJob(engine, queuedCleaning.id, (job) => {
          setStatus(job.progress_message || "AI is cleaning the selected voice tracks.");
        });
        if (version !== runVersion.current) return;
        if (cleaning.status !== "complete") throw new Error(jobErrorMessage(cleaning));
        if (cleaning.derived_media_items.length > 0) {
          onMediaItemsGenerated(cleaning.derived_media_items);
          handoffItems = replacePreparedAudio(handoffItems, cleaning.derived_media_items);
        }
      }

      setStatus("Saving the prepared collection.");
      if (!activeProjectId) throw new Error("Choose or create a project before preparing media.");
      await engine.addCurationHandoff(
        handoffItems.map((item) => item.id),
        activeProjectId,
        target,
      );
      if (version !== runVersion.current) return;
      await saveQueue.current;
      if (version !== runVersion.current) return;
      onComplete(handoffItems);
    } catch (error) {
      if (version !== runVersion.current) return;
      setStatus(errorMessage(error));
      setPhase("ready");
    }
  }

  const copy = prepareCopy(target, sourceItems.length);
  return (
    <section className="guided-ai-prepare" aria-label="AI guided preparation">
      {saveWarning ? <p role="status">{saveWarning}</p> : null}
      <div className="guided-ai-dialogue">
        <div className={`guided-ai-mark ${phase === "running" || phase === "finishing" ? "working" : ""}`}>
          <WarpedSphereSurface color={prepareSphereColors[1]} phase={1.7} />
          {phase === "running" || phase === "finishing"
            ? <LoaderCircle className="spin" size={24} aria-hidden="true" />
            : <Sparkles size={24} aria-hidden="true" />}
        </div>
        <div>
          <small>LoraSuite AI</small>
          <h3>
            {loadingCheckpoint ? "Restoring your preparation" : phase === "ready"
              ? "Your first pass is ready"
              : phase === "running"
                ? "Preparing your collection"
                : phase === "finishing"
                  ? "Saving your prepared collection"
                  : copy.title}
          </h3>
          <p>{loadingCheckpoint ? "Checking the saved project before starting anything new." : phase === "idle" ? copy.description : status}</p>
        </div>
      </div>

      {!loadingCheckpoint && (phase === "idle" || phase === "error") ? (
        <>
          <button className="guided-ai-primary" type="button" disabled={sourceItems.length === 0} onClick={() => void runAiPreparation()}>
            <Sparkles size={17} aria-hidden="true" />
            {sourceItems.length === 0 ? "Add media first" : `Let AI prepare ${sourceItems.length} item${sourceItems.length === 1 ? "" : "s"}`}
          </button>
          <div className="guided-ai-path" aria-label="Automatic preparation plan">
            {copy.steps.map(({ label, icon: Icon }, index) => (
              <div className="guided-ai-path-step" key={label}>
                <WarpedSphereSurface color={prepareSphereColors[index % prepareSphereColors.length]} phase={index * 0.9 + 0.3} />
                <span><Icon size={18} aria-hidden="true" /></span>
                <strong>{label}</strong>
              </div>
            ))}
          </div>
          <p className="guided-ai-plan-help">One preparation pass runs these steps together. Start with the preparation button above.</p>
          {phase === "error" ? <p className="guided-ai-error"><CircleAlert size={15} aria-hidden="true" /> {status}</p> : null}

        </>
      ) : null}

      {phase === "running" || phase === "finishing" ? (
        <div className="guided-ai-running" role="status">
          <div><i /><i /><i /><i /></div>
          <strong>{status}</strong>
          <span>
            {phase === "running"
              ? "No action needed yet. Review controls will appear here automatically."
              : "No action needed. The next guided step will open when saving is complete."}
          </span>
        </div>
      ) : null}

      {phase === "ready" ? (
        <div className="guided-ai-results">
          <button type="button" onClick={() => void runAiPreparation()} disabled={!sourceItems.length}>Prepare again</button>
          <div className="guided-ai-result-counts">
            <button type="button" onClick={() => setReviewFilter(null)}>
              <Check size={16} aria-hidden="true" /><span><strong>{keepItems.length}</strong> ready</span>
            </button>
            <button type="button" disabled={reviewItems.length === 0} onClick={() => openReview("review")}>
              <Eye size={16} aria-hidden="true" /><span><strong>{reviewItems.length}</strong> need you</span>
            </button>
            <button type="button" disabled={rejectedItems.length === 0} onClick={() => openReview("reject")}>
              <X size={16} aria-hidden="true" /><span><strong>{rejectedItems.length}</strong> excluded</span>
            </button>
          </div>

          {reviewFilter && activeReviewItem ? (
            <div className="guided-ai-review-overlay" role="dialog" aria-modal="true" aria-label={`${activeReviewItems.length} ${reviewFilter === "review" ? "uncertain" : "excluded"} items`}>
              <button type="button" className="guided-ai-review-backdrop" aria-label="Close review" onClick={() => setReviewFilter(null)} />
              <div className="guided-ai-review-dialog">
                <header>
                  <div>
                    <small>{reviewFilter === "review" ? "Needs your judgment" : "AI exclusion check"}</small>
                    <strong>{activeReviewItems.length} item{activeReviewItems.length === 1 ? "" : "s"} to review</strong>
                  </div>
                  <div>
                    <button type="button" onClick={() => decideAllActive(false)}><X size={15} aria-hidden="true" /> Skip all</button>
                    <button type="button" className="primary-action" onClick={() => decideAllActive(true)}><Check size={15} aria-hidden="true" /> Use all</button>
                  </div>
                </header>
                <GuidedDecisionCard
                  item={activeReviewItem}
                  evidence={evidenceById.get(activeReviewItem.id)}
                  assetUrl={engine.assetUrl}
                  included={includedIds.has(activeReviewItem.id)}
                  index={reviewIndex}
                  total={activeReviewItems.length}
                  onPrevious={() => setReviewIndex((current) => Math.max(0, current - 1))}
                  onNext={() => setReviewIndex((current) => Math.min(activeReviewItems.length - 1, current + 1))}
                  onUse={() => decideReview(activeReviewItem.id, true)}
                  onSkip={() => decideReview(activeReviewItem.id, false)}
                  onClose={() => setReviewFilter(null)}
                />
              </div>
            </div>
          ) : (
            <div className="guided-ai-selection">
              <div className="guided-ai-preview-strip" aria-label="AI selected media">
                {selectedItems.slice(0, 12).map((item) => (
                  <GuidedMediaPreview key={item.id} item={item} assetUrl={engine.assetUrl} compact />
                ))}
                {selectedItems.length > 12 ? <span>+{selectedItems.length - 12}</span> : null}
              </div>
              <p>
                AI selected {selectedItems.length} item{selectedItems.length === 1 ? "" : "s"}.
                {reviewItems.length ? ` ${reviewItems.length} uncertain item${reviewItems.length === 1 ? " is" : "s are"} waiting for you.` : " No decisions need your attention."}
              </p>
            </div>
          )}

          <footer>
            {reviewItems.length > 0 ? (
              <button type="button" className="secondary-action" onClick={() => openReview("review")}>
                <Eye size={15} aria-hidden="true" /> Review {reviewItems.length} uncertain
              </button>
            ) : <span />}
            <button className="guided-ai-primary" type="button" disabled={selectedItems.length === 0} onClick={() => void continueWithSelection()}>
              Continue with {selectedItems.length} selected <ChevronRight size={16} aria-hidden="true" />
            </button>
          </footer>
        </div>
      ) : null}
    </section>
  );
}

function GuidedDecisionCard({
  item,
  evidence,
  assetUrl,
  included,
  index,
  total,
  onPrevious,
  onNext,
  onUse,
  onSkip,
  onClose,
}: {
  item: MediaItem;
  evidence?: CurationAnalysisEvidence;
  assetUrl(path: string): string;
  included: boolean;
  index: number;
  total: number;
  onPrevious(): void;
  onNext(): void;
  onUse(): void;
  onSkip(): void;
  onClose(): void;
}) {
  return (
    <article className="guided-ai-decision">
      <GuidedMediaPreview item={item} assetUrl={assetUrl} />
      <div className="guided-ai-decision-copy">
        <header>
          <span>{index + 1} / {total}</span>
          <button type="button" title="Close review" aria-label="Close review" onClick={onClose}><X size={15} /></button>
        </header>
        <small>{evidence?.recommendation === "reject" ? "AI would exclude this" : "AI wants your judgment"}</small>
        <h4>{displayName(item)}</h4>
        <p>{evidence?.reasons[0] ?? "The automatic checks did not produce a decisive result."}</p>
        {evidence?.warnings[0] ? <em>{evidence.warnings[0]}</em> : null}
        <div className="guided-ai-confidence">
          <i style={{ width: `${Math.round((evidence?.confidence ?? 0) * 100)}%` }} />
          <span>{Math.round((evidence?.confidence ?? 0) * 100)}% confidence</span>
        </div>
        <div className="guided-ai-decision-actions">
          <button type="button" className={!included ? "active" : ""} onClick={onSkip}><X size={16} /> Skip</button>
          <button type="button" className={included ? "active" : ""} onClick={onUse}><Check size={16} /> Use it</button>
        </div>
        <nav aria-label="Review navigation">
          <button type="button" title="Previous item" disabled={index === 0} onClick={onPrevious}><ChevronLeft size={16} /></button>
          <button type="button" title="Next item" disabled={index >= total - 1} onClick={onNext}><ChevronRight size={16} /></button>
        </nav>
      </div>
    </article>
  );
}

function GuidedMediaPreview({
  item,
  assetUrl,
  compact = false,
}: {
  item: MediaItem;
  assetUrl(path: string): string;
  compact?: boolean;
}) {
  const path = item.raw_path ? assetUrl(item.raw_path) : undefined;
  const className = compact ? "guided-ai-media compact" : "guided-ai-media";
  if (item.media_type === "image" && path) return <img className={className} src={path} alt="" />;
  if (item.media_type === "video" && path) return <video className={className} src={path} controls={!compact} muted={compact} playsInline />;
  if (item.media_type === "audio") {
    return (
      <div className={`${className} audio`}>
        <AudioLines size={compact ? 18 : 36} aria-hidden="true" />
        {!compact && path ? <audio src={path} controls /> : null}
      </div>
    );
  }
  return <div className={`${className} missing`}><ImageIcon size={compact ? 18 : 36} aria-hidden="true" /></div>;
}

function prepareCopy(target: WizardTarget, count: number) {
  const countLabel = `${count} item${count === 1 ? "" : "s"}`;
  if (target === "voice") {
    return {
      title: "Want me to prepare the voice?",
      description: `I will extract speech from ${countLabel}, check what is usable, and clean the tracks you approve.`,
      steps: [
        { label: "Extract speech", icon: Video },
        { label: "Check voice", icon: Sparkles },
        { label: "Clean samples", icon: AudioLines },
      ],
    };
  }
  if (target === "video") {
    return {
      title: "Want me to prepare the motion?",
      description: `I will map ${countLabel}, find stable visual ranges, and surface only uncertain decisions.`,
      steps: [
        { label: "Map motion", icon: Video },
        { label: "Find keyframes", icon: ImageIcon },
        { label: "Flag for review", icon: Sparkles },
      ],
    };
  }
  if (target === "id_lora") {
    return {
      title: "Want me to assemble the identity?",
      description: `I will separate visual, motion, and voice evidence across ${countLabel}, then ask only where confidence is low.`,
      steps: [
        { label: "Separate media", icon: Video },
        { label: "Match evidence", icon: Sparkles },
        { label: "Prepare identity", icon: AudioLines },
      ],
    };
  }
  return {
    title: "Want me to choose the strongest images?",
    description: `I will check image quality and face or body visibility across ${countLabel}, then flag uncertain items for you.`,
    steps: [
      { label: "Check quality", icon: ImageIcon },
      { label: "Check visibility", icon: Eye },
      { label: "Flag for review", icon: Sparkles },
    ],
  };
}

function targetBreakdownOptions(target: WizardTarget): VideoBreakdownOptions | null {
  if (target === "voice") {
    return {
      generate_frames: false,
      extract_audio: true,
      intelligent_selection: false,
      frames_per_second: 4,
      max_frame_count: 24,
    };
  }
  if (target === "video" || target === "id_lora") {
    return {
      generate_frames: true,
      extract_audio: target === "id_lora",
      intelligent_selection: true,
      frames_per_second: 4,
      max_frame_count: 24,
    };
  }
  return {
    generate_frames: true,
    extract_audio: false,
    intelligent_selection: true,
    frames_per_second: 4,
    max_frame_count: 24,
  };
}

function analysisInputs(items: MediaItem[], target: WizardTarget): MediaItem[] {
  if (target === "voice") return items.filter((item) => item.media_type === "audio");
  if (target === "image") return items.filter((item) => item.media_type === "image");
  if (target === "video") return items.filter((item) => item.media_type !== "audio");
  return items;
}

function filterSelectedBreakdownItems(
  items: MediaItem[],
  selectedFrameIds: string[],
  selectedClipIds: string[],
): MediaItem[] {
  const frameIds = new Set(selectedFrameIds);
  const clipIds = new Set(selectedClipIds);
  return items.filter((item) => {
    const derivativeType = metadataString(item, "derivative_type");
    if (derivativeType === "video_frame") {
      const frameId = metadataString(item, "analysis_frame_id");
      return !frameId || frameIds.has(frameId);
    }
    if (derivativeType === "video_clip") {
      const clipId = metadataString(item, "clip_proposal_id");
      return !clipId || clipIds.has(clipId);
    }
    return true;
  });
}

function breakdownStatus(target: WizardTarget, count: number): string {
  if (target === "voice") return `Extracting audio from ${count} video${count === 1 ? "" : "s"}.`;
  if (target === "id_lora") return `Separating image, motion, and audio evidence from ${count} video${count === 1 ? "" : "s"}.`;
  return `Finding stable ranges and keyframes in ${count} video${count === 1 ? "" : "s"}.`;
}

function replacePreparedAudio(items: MediaItem[], cleanedItems: MediaItem[]): MediaItem[] {
  const cleanedSourceIds = new Set(
    cleanedItems
      .map((item) => metadataString(item, "source_media_item_id"))
      .filter((item): item is string => Boolean(item)),
  );
  return deduplicateMediaItems([
    ...items.filter((item) => item.media_type !== "audio" || !cleanedSourceIds.has(item.id)),
    ...cleanedItems,
  ]);
}

function isRelevantMedia(item: MediaItem, target: WizardTarget): boolean {
  if (item.status === "ignored") return false;
  if (target === "image") return item.media_type === "image" || item.media_type === "video";
  if (target === "video") return item.media_type === "video" || item.media_type === "image";
  if (target === "voice") return item.media_type === "audio" || item.media_type === "video";
  return true;
}

function prepareSourceItems(items: MediaItem[], target: WizardTarget): MediaItem[] {
  const relevantItems = items.filter((item) => isRelevantMedia(item, target));
  const sourceVideoIds = new Set(
    relevantItems
      .filter((item) => item.media_type === "video" && !metadataString(item, "derivative_type"))
      .map((item) => item.id),
  );
  return deduplicateMediaItems(relevantItems.filter((item) => {
    const derivativeType = metadataString(item, "derivative_type");
    const sourceMediaItemId = metadataString(item, "source_media_item_id");
    const isRegeneratedBreakdownDerivative = (
      derivativeType === "video_frame"
      || derivativeType === "video_clip"
      || derivativeType === "audio_clip"
    );
    return !(
      isRegeneratedBreakdownDerivative
      && sourceMediaItemId
      && sourceVideoIds.has(sourceMediaItemId)
    );
  }));
}

function deduplicateMediaItems(items: MediaItem[]): MediaItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.sha256?.trim()
      ? `${item.media_type}:sha:${item.sha256.trim().toLowerCase()}`
      : item.raw_path?.trim()
        ? `${item.media_type}:path:${item.raw_path.trim()}`
        : `${item.media_type}:id:${item.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function metadataString(item: MediaItem, key: string): string | undefined {
  const value = item.metadata_json?.[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

function displayName(item: MediaItem): string {
  const metadataName = metadataString(item, "display_name");
  if (metadataName) return metadataName;
  const normalized = item.raw_path?.replace(/\\/g, "/");
  return normalized?.split("/").filter(Boolean).at(-1) ?? item.id;
}

function noUsableMediaMessage(target: WizardTarget): string {
  if (target === "voice") return "No audio tracks could be extracted. Open Advanced Consoles to inspect the source videos.";
  return "No usable media was available for this preparation pass.";
}

function normalizeEvidence(
  items: MediaItem[],
  analyses: CurationAnalysisEvidence[],
): CurationAnalysisEvidence[] {
  const evidenceById = new Map(analyses.map((analysis) => [analysis.media_item_id, analysis]));
  return items.map((item) => evidenceById.get(item.id) ?? {
    media_item_id: item.id,
    media_type: item.media_type,
    recommendation: "review",
    confidence: 0,
    reasons: ["AI could not complete this check, so it needs a human decision."],
    warnings: ["No automatic evidence was returned."],
    analyzer: "guided-fallback",
    analyzed_at: new Date().toISOString(),
  });
}

function jobErrorMessage(job: ProcessingJob): string {
  const firstError = job.errors[0];
  const message = firstError?.message;
  return typeof message === "string" && message ? message : job.progress_message || "The preparation job failed.";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function pollJob(
  engine: Pick<EngineClient, "getProcessingJob">,
  jobId: string,
  onProgress: (job: ProcessingJob) => void,
): Promise<ProcessingJob> {
  let latest: ProcessingJob | undefined;
  for (let attempt = 0; attempt < maxPollAttempts; attempt += 1) {
    latest = await engine.getProcessingJob(jobId);
    onProgress(latest);
    if (terminalStatuses.has(latest.status)) return latest;
    if (attempt < maxPollAttempts - 1) await delay(pollDelayMs);
  }
  throw new Error(`${latest?.job_type ?? "Preparation"} did not finish in time.`);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
