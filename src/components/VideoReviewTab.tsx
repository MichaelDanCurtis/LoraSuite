import { Check, Eye, EyeOff, RotateCcw, Scissors, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { EngineClient } from "../lib/api";
import type {
  MediaItem,
  ProcessingJob,
  VideoAnalysisFrame,
  VideoBreakdownAnalysis,
  VideoClipDecision,
} from "../lib/types";

interface VideoReviewTabProps {
  analysis: VideoBreakdownAnalysis;
  job: ProcessingJob;
  sourceItem: MediaItem;
  engine: Pick<EngineClient, "assetUrl" | "commitVideoBreakdown">;
  onBack(): void;
  onMediaItemsGenerated(items: MediaItem[]): void;
}

type PlaybackPhase = "scanning" | "collapsing" | "settled";
interface ClipDraft {
  id: string;
  startSeconds: number;
  endSeconds: number;
  decision: VideoClipDecision;
}
const MAX_AUTOPLAY_FRAMES = 48;

export function VideoReviewTab({
  analysis,
  job,
  sourceItem,
  engine,
  onBack,
  onMediaItemsGenerated,
}: VideoReviewTabProps) {
  const [selectedFrameIds, setSelectedFrameIds] = useState<Set<string>>(
    () => initialKeeperIds(analysis),
  );
  const [revealCount, setRevealCount] = useState(0);
  const [phase, setPhase] = useState<PlaybackPhase>("scanning");
  const [showRejected, setShowRejected] = useState(false);
  const [discardedLimit, setDiscardedLimit] = useState(48);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("Analyzing source frames");
  const [clipDrafts, setClipDrafts] = useState<ClipDraft[]>(
    () => initialClipDrafts(analysis),
  );
  const playerRef = useRef<HTMLVideoElement>(null);
  const framesById = useMemo(
    () => new Map(analysis.frames.map((frame) => [frame.id, frame])),
    [analysis.frames],
  );
  const frameIndexById = useMemo(
    () => new Map(analysis.frames.map((frame, index) => [frame.id, index])),
    [analysis.frames],
  );
  const playbackFrames = useMemo(
    () => selectPlaybackFrames(analysis.frames, MAX_AUTOPLAY_FRAMES),
    [analysis.frames],
  );
  const timelineProgress =
    revealCount === 0
      ? 0
      : (frameIndexById.get(
          playbackFrames[Math.min(revealCount, playbackFrames.length) - 1]?.id ?? "",
        ) ?? -1) + 1;
  const selectedFrames = analysis.frames.filter((frame) => selectedFrameIds.has(frame.id));
  const displayedSelectedFrames = selectedFrames.filter(
    (frame) => phase !== "scanning" || (frameIndexById.get(frame.id) ?? 0) < timelineProgress,
  );
  const keeperCount = analysis.frames.filter((frame) => frame.decision === "keeper").length;
  const duplicateCount = analysis.frames.filter((frame) => frame.decision === "duplicate").length;
  const rejectedCount = analysis.frames.filter((frame) => frame.decision === "rejected").length;
  const discardedCount = duplicateCount + rejectedCount;
  const keptClipCount = clipDrafts.filter((clip) => clip.decision === "keep").length;
  const audioItemCount = job.derived_media_items.filter(
    (item) => item.media_type === "audio",
  ).length;
  const visibleFrameIds = useMemo(() => {
    const visibleIds = new Set<string>();
    const revealedFrames = playbackFrames.slice(0, revealCount);
    if (showRejected) {
      let includedDiscarded = 0;
      for (const frame of analysis.frames) {
        if (frame.decision === "keeper") {
          visibleIds.add(frame.id);
        } else if (includedDiscarded < discardedLimit) {
          visibleIds.add(frame.id);
          includedDiscarded += 1;
        }
      }
      return visibleIds;
    }
    if (phase === "settled") {
      for (const frame of analysis.frames) {
        if (frame.decision === "keeper") {
          visibleIds.add(frame.id);
        }
      }
      return visibleIds;
    }
    const recentStart = Math.max(0, revealedFrames.length - 30);
    for (let index = recentStart; index < revealedFrames.length; index += 1) {
      visibleIds.add(revealedFrames[index].id);
    }
    for (const frame of revealedFrames) {
      if (frame.decision === "keeper") {
        visibleIds.add(frame.id);
      }
    }
    return visibleIds;
  }, [analysis.frames, discardedLimit, phase, playbackFrames, revealCount, showRejected]);

  useEffect(() => {
    setSelectedFrameIds(initialKeeperIds(analysis));
    setRevealCount(0);
    setPhase("scanning");
    setShowRejected(false);
    setDiscardedLimit(48);
    setStatus("Analyzing source frames");
    setClipDrafts(initialClipDrafts(analysis));
  }, [analysis]);

  useEffect(() => {
    if (phase !== "scanning") {
      return;
    }
    if (revealCount >= playbackFrames.length) {
      const collapseTimer = window.setTimeout(() => {
        setPhase("collapsing");
        setStatus("Collapsing near-duplicates");
      }, 280);
      return () => window.clearTimeout(collapseTimer);
    }
    const revealStep = Math.max(1, Math.ceil(playbackFrames.length / 90));
    const revealTickCount = Math.ceil(playbackFrames.length / revealStep);
    const revealTimer = window.setTimeout(
      () => setRevealCount((current) => Math.min(current + revealStep, playbackFrames.length)),
      Math.max(32, Math.min(70, 4500 / Math.max(revealTickCount, 1))),
    );
    return () => window.clearTimeout(revealTimer);
  }, [phase, playbackFrames.length, revealCount]);

  useEffect(() => {
    if (phase !== "collapsing") {
      return;
    }
    const settleTimer = window.setTimeout(() => {
      setPhase("settled");
      setStatus(`${keeperCount} strongest frames ready for review`);
    }, 850);
    return () => window.clearTimeout(settleTimer);
  }, [keeperCount, phase]);

  function replayAnalysis() {
    setRevealCount(0);
    setPhase("scanning");
    setStatus("Analyzing source frames");
    setShowRejected(false);
    setDiscardedLimit(48);
  }

  function toggleFrame(frameId: string) {
    setSelectedFrameIds((current) => {
      const next = new Set(current);
      if (next.has(frameId)) {
        next.delete(frameId);
      } else {
        next.add(frameId);
      }
      return next;
    });
  }

  function updateClipDraft(clipId: string, update: Partial<ClipDraft>) {
    setClipDrafts((current) =>
      current.map((clip) => (clip.id === clipId ? { ...clip, ...update } : clip)),
    );
  }

  function seekToClip(startSeconds: number) {
    if (playerRef.current) {
      playerRef.current.currentTime = startSeconds;
      void playerRef.current.play().catch(() => undefined);
    }
  }

  async function commitBreakdown() {
    if ((selectedFrameIds.size === 0 && keptClipCount === 0) || saving) {
      return;
    }
    setSaving(true);
    setStatus("Materializing approved frames and video clips");
    try {
      const updatedJob = await engine.commitVideoBreakdown(job.id, {
        frame_ids: [...selectedFrameIds],
        clips: clipDrafts.map((clip) => ({
          clip_id: clip.id,
          start_seconds: clip.startSeconds,
          end_seconds: clip.endSeconds,
          decision: clip.decision,
        })),
      });
      onMediaItemsGenerated(updatedJob.derived_media_items);
      const reviewedAnalysis = updatedJob.video_analyses?.find(
        (item) => item.source_media_item_id === analysis.source_media_item_id,
      );
      const frameOutputIds = new Set(
        reviewedAnalysis?.frames
          .filter((frame) => selectedFrameIds.has(frame.id))
          .map((frame) => frame.output_media_item_id)
          .filter((id): id is string => Boolean(id)) ?? [],
      );
      const clipOutputIds = new Set(
        reviewedAnalysis?.clip_proposals
          ?.filter((clip) => clip.decision === "keep")
          .map((clip) => clip.output_media_item_id)
          .filter((id): id is string => Boolean(id)) ?? [],
      );
      if (frameOutputIds.size !== selectedFrameIds.size || clipOutputIds.size !== keptClipCount) {
        throw new Error("One or more approved outputs were not produced.");
      }
      setStatus(
        `Committed ${frameOutputIds.size} frames and ${clipOutputIds.size} clips to Curate`,
      );
    } catch (error) {
      setStatus(`Could not commit breakdown: ${errorMessage(error)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="video-review-workspace" aria-label="Intelligent video review">
      <header className="video-review-header">
        <div>
          <button className="quiet-action" type="button" onClick={onBack}>
            <X size={16} aria-hidden="true" />
            Close review
          </button>
          <h2>{displayName(sourceItem)}</h2>
          <p>{formatDuration(analysis.duration_seconds)} · imported video</p>
        </div>
        <div className="video-review-actions">
          <button className="quiet-action" type="button" onClick={replayAnalysis}>
            <RotateCcw size={16} aria-hidden="true" />
            Replay analysis
          </button>
          <button
            className="quiet-action"
            type="button"
            aria-pressed={showRejected}
            onClick={() => {
              setShowRejected((current) => !current);
              setDiscardedLimit(48);
            }}
          >
            {showRejected ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
            {showRejected ? "Hide discarded" : "Show discarded"}
          </button>
        </div>
      </header>

      <div className="video-review-overview">
        <div className="review-player-shell">
          <video
            ref={playerRef}
            controls
            preload="metadata"
            src={assetPath(sourceItem, engine.assetUrl)}
          />
          <div className="player-readout">
            <span className={`analysis-pulse ${phase}`} aria-hidden="true" />
            <span aria-live="polite">{status}</span>
            <strong>{analysis.analyzer.replaceAll("-", " ")}</strong>
          </div>
        </div>
        <dl className="review-metrics" aria-label="Video analysis summary">
          <div>
            <dt>Analyzed</dt>
            <dd>{analysis.frames.length}</dd>
          </div>
          <div>
            <dt>Stable ranges</dt>
            <dd>{analysis.stable_ranges.length}</dd>
          </div>
          <div>
            <dt>Frame keepers</dt>
            <dd>{selectedFrameIds.size}</dd>
          </div>
          <div>
            <dt>Clip keepers</dt>
            <dd>{keptClipCount}</dd>
          </div>
        </dl>
      </div>

      {analysis.clip_proposals?.length ? (
        <section className="clip-review-stage">
          <div className="analysis-stage-header">
            <div>
              <span className="eyebrow">Video training lane</span>
              <h3>Stable clip proposals</h3>
            </div>
            <span>{keptClipCount} kept · {audioItemCount ? "audio linked" : "no audio derivative"}</span>
          </div>
          <div className="clip-timeline" aria-label="Video clip proposal timeline">
            {analysis.clip_proposals.map((proposal, index) => {
              const draft = clipDrafts.find((clip) => clip.id === proposal.id);
              if (!draft) {
                return null;
              }
              const representativeFrame = representativeClipFrame(proposal.stable_range_ids, analysis);
              return (
                <article className={`clip-proposal decision-${draft.decision}`} key={proposal.id}>
                  <button
                    className="clip-preview"
                    type="button"
                    onClick={() => seekToClip(draft.startSeconds)}
                    aria-label={`Preview clip ${index + 1}`}
                  >
                    {representativeFrame ? (
                      <img src={engine.assetUrl(representativeFrame.thumbnail_path)} alt="" />
                    ) : null}
                    <span><Scissors size={14} aria-hidden="true" /> Clip {index + 1}</span>
                  </button>
                  <div className="clip-evidence">
                    <strong>{formatTimestamp(draft.startSeconds)} - {formatTimestamp(draft.endSeconds)}</strong>
                    <span>Quality {percent(proposal.scores.quality)}</span>
                    <span>Identity {percent(proposal.scores.identity_coverage)}</span>
                    <span>Motion {percent(proposal.scores.motion)}</span>
                    <span>Stable {percent(proposal.scores.stability)}</span>
                  </div>
                  <div className="clip-trim-controls">
                    <label>
                      In
                      <input
                        type="number"
                        min={0}
                        max={draft.endSeconds - 0.5}
                        step={0.1}
                        value={draft.startSeconds}
                        onChange={(event) => updateClipDraft(proposal.id, {
                          startSeconds: Number(event.target.value),
                        })}
                      />
                    </label>
                    <label>
                      Out
                      <input
                        type="number"
                        min={draft.startSeconds + 0.5}
                        max={analysis.duration_seconds}
                        step={0.1}
                        value={draft.endSeconds}
                        onChange={(event) => updateClipDraft(proposal.id, {
                          endSeconds: Number(event.target.value),
                        })}
                      />
                    </label>
                  </div>
                  <div className="clip-decision-controls" aria-label={`Clip ${index + 1} decision`}>
                    {(["keep", "review", "reject"] as const).map((decision) => (
                      <button
                        key={decision}
                        type="button"
                        aria-pressed={draft.decision === decision}
                        onClick={() => updateClipDraft(proposal.id, { decision })}
                      >
                        {decision}
                      </button>
                    ))}
                  </div>
                  <small>{proposal.reasons.join(" · ")}</small>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className={`analysis-stage phase-${phase}`}>
        <div className="analysis-stage-header">
          <div>
            <span className="eyebrow">Source timeline</span>
            <h3>Frame analysis</h3>
          </div>
          <span>{timelineProgress} / {analysis.frames.length}</span>
        </div>
        <div
          className="analysis-progress"
          aria-hidden="true"
          style={{ "--analysis-progress": `${analysis.frames.length ? timelineProgress / analysis.frames.length : 0}` } as CSSProperties}
        />
        <div className="stable-range-track">
          {analysis.stable_ranges.map((range, rangeIndex) => {
            const rangeFrames = range.frame_ids
              .map((frameId) => framesById.get(frameId))
              .filter((frame): frame is VideoAnalysisFrame => Boolean(frame))
              .filter((frame) => visibleFrameIds.has(frame.id));
            const hiddenFrameCount = range.frame_ids.filter(
              (frameId) => !visibleFrameIds.has(frameId),
            ).length;
            if (rangeFrames.length === 0) {
              return null;
            }
            return (
              <div className="stable-range" key={range.id}>
                <span className="range-label">Range {rangeIndex + 1}</span>
                <div className="analysis-frame-strip">
                  {rangeFrames.map((frame) => (
                    <AnalysisFrame
                      key={frame.id}
                      frame={frame}
                      selected={selectedFrameIds.has(frame.id)}
                      phase={phase}
                      showDiscarded={showRejected}
                      assetUrl={engine.assetUrl}
                      onToggle={() => toggleFrame(frame.id)}
                    />
                  ))}
                  {hiddenFrameCount > 0 && phase !== "scanning" && !showRejected ? (
                    <button
                      className="collapsed-stack-summary"
                      type="button"
                      onClick={() => setShowRejected(true)}
                      aria-label={`Show ${hiddenFrameCount} collapsed frames from range ${rangeIndex + 1}`}
                    >
                      <span>+{hiddenFrameCount}</span>
                      <small>stacked</small>
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
        {showRejected && discardedLimit < discardedCount ? (
          <button
            className="quiet-action load-discarded"
            type="button"
            onClick={() => setDiscardedLimit((current) => current + 48)}
          >
            Load more discarded frames
          </button>
        ) : null}
      </section>

      <section className="keepers-stage">
        <div className="analysis-stage-header">
          <div>
            <span className="eyebrow">Training candidates</span>
            <h3>Keepers</h3>
          </div>
          <span>{displayedSelectedFrames.length} selected</span>
        </div>
        {displayedSelectedFrames.length === 0 ? (
          <p className="empty-state">
            {phase === "scanning"
              ? "Strong frames will rise here as the playhead advances."
              : "Select at least one frame from the timeline."}
          </p>
        ) : (
          <div className="keepers-rail">
            {displayedSelectedFrames.map((frame) => (
              <button
                className="keeper-card"
                type="button"
                key={frame.id}
                onClick={() => toggleFrame(frame.id)}
                aria-label={`Remove frame at ${formatTimestamp(frame.timestamp_seconds)}`}
              >
                <img
                  src={engine.assetUrl(frame.thumbnail_path)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
                <span>{formatTimestamp(frame.timestamp_seconds)}</span>
                <small>{frame.reasons[0] ?? "User selected"}</small>
                <Check size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        )}
        <footer className="keepers-footer">
          <span>{rejectedCount} lower-ranked frames remain recoverable.</span>
          <button
            className="primary-action"
            type="button"
            disabled={(selectedFrameIds.size === 0 && keptClipCount === 0) || saving}
            onClick={commitBreakdown}
          >
            {saving ? "Preparing approved outputs" : "Commit Breakdown"}
          </button>
        </footer>
      </section>
    </section>
  );
}

function AnalysisFrame({
  frame,
  selected,
  phase,
  showDiscarded,
  assetUrl,
  onToggle,
}: {
  frame: VideoAnalysisFrame;
  selected: boolean;
  phase: PlaybackPhase;
  showDiscarded: boolean;
  assetUrl(path: string): string;
  onToggle(): void;
}) {
  const discarded = frame.decision === "duplicate" || frame.decision === "rejected";
  return (
    <button
      type="button"
      className={`analysis-frame decision-${frame.decision}${selected ? " selected" : ""}${
        discarded && phase === "settled" && !showDiscarded ? " compressed" : ""
      }`}
      onClick={onToggle}
      aria-pressed={selected}
      title={`${formatTimestamp(frame.timestamp_seconds)} · ${frame.reasons.join(", ")}`}
    >
      <img src={assetUrl(frame.thumbnail_path)} alt="" loading="lazy" decoding="async" />
      <span className="frame-time">{formatTimestamp(frame.timestamp_seconds)}</span>
      <span className="frame-score">{Math.round(frame.scores.overall * 100)}</span>
      {phase !== "scanning" ? (
        <span className="frame-decision">{decisionLabel(frame)}</span>
      ) : null}
    </button>
  );
}

function decisionLabel(frame: VideoAnalysisFrame): string {
  if (frame.decision === "duplicate") {
    return "Stack";
  }
  if (frame.decision === "keeper") {
    return "Keep";
  }
  if (frame.decision === "rejected") {
    return "Pass";
  }
  return "Scan";
}

function initialKeeperIds(analysis: VideoBreakdownAnalysis): Set<string> {
  return new Set(
    analysis.frames.filter((frame) => frame.decision === "keeper").map((frame) => frame.id),
  );
}

function initialClipDrafts(analysis: VideoBreakdownAnalysis): ClipDraft[] {
  return (analysis.clip_proposals ?? []).map((proposal) => ({
    id: proposal.id,
    startSeconds: proposal.start_seconds,
    endSeconds: proposal.end_seconds,
    decision: proposal.decision,
  }));
}

function representativeClipFrame(
  stableRangeIds: string[],
  analysis: VideoBreakdownAnalysis,
): VideoAnalysisFrame | undefined {
  const stableRange = analysis.stable_ranges.find((range) => stableRangeIds.includes(range.id));
  if (!stableRange?.frame_ids.length) {
    return undefined;
  }
  const frameId = stableRange.frame_ids[Math.floor(stableRange.frame_ids.length / 2)];
  return analysis.frames.find((frame) => frame.id === frameId);
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function selectPlaybackFrames(
  frames: VideoAnalysisFrame[],
  maximumFrameCount: number,
): VideoAnalysisFrame[] {
  if (frames.length <= maximumFrameCount) {
    return frames;
  }

  const selectedIds = new Set(
    frames.filter((frame) => frame.decision === "keeper").map((frame) => frame.id),
  );
  const sampleBudget = Math.max(0, maximumFrameCount - selectedIds.size);
  for (let sampleIndex = 0; sampleIndex < sampleBudget; sampleIndex += 1) {
    const frameIndex =
      sampleBudget === 1
        ? Math.floor(frames.length / 2)
        : Math.round((sampleIndex * (frames.length - 1)) / (sampleBudget - 1));
    selectedIds.add(frames[frameIndex].id);
  }

  return frames.filter((frame) => selectedIds.has(frame.id));
}

function assetPath(item: MediaItem, assetUrl: (path: string) => string): string | undefined {
  return item.raw_path ? assetUrl(item.raw_path) : undefined;
}

function displayName(item: MediaItem): string {
  const metadata = item.metadata_json ?? {};
  for (const key of ["display_name", "title", "caption"]) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim().slice(0, 90);
    }
  }
  const normalized = item.raw_path?.replace(/\\/g, "/");
  const filename = normalized?.split("/").filter(Boolean).at(-1);
  if (filename && !/^[a-f0-9]{48,}\.[a-z0-9]+$/i.test(filename)) {
    return filename;
  }
  return "Video review";
}

function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds.toFixed(1)} seconds`;
  }
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected failure";
}
