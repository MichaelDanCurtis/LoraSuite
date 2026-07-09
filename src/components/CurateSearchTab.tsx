import { useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { MediaItem, MediaType } from "../lib/types";

interface CurateSearchTabProps {
  mediaItems: MediaItem[];
  engine: Pick<EngineClient, "assetUrl" | "createProcessingJob" | "getProcessingJob">;
  onSendToIdentify(items: MediaItem[]): void;
  onMediaItemsGenerated(items: MediaItem[]): void;
}

type MediaTypeFilter = "all" | MediaType;

export function CurateSearchTab({
  mediaItems,
  engine,
  onSendToIdentify,
  onMediaItemsGenerated,
}: CurateSearchTabProps) {
  const [searchText, setSearchText] = useState("");
  const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [breakdownSourceIds, setBreakdownSourceIds] = useState<Set<string>>(() => new Set());
  const [status, setStatus] = useState("Idle");
  const visibleItems = useMemo(
    () =>
      mediaItems.filter((item) => {
        if (mediaTypeFilter !== "all" && item.media_type !== mediaTypeFilter) {
          return false;
        }
        const query = searchText.trim().toLowerCase();
        if (!query) {
          return true;
        }
        return searchableText(item).includes(query);
      }),
    [mediaItems, mediaTypeFilter, searchText],
  );
  const selectedBreakdownVideoIds = useMemo(
    () =>
      mediaItems
        .filter((item) => item.media_type === "video" && breakdownSourceIds.has(item.id))
        .map((item) => item.id),
    [breakdownSourceIds, mediaItems],
  );
  const imageCount = mediaItems.filter((item) => item.media_type === "image").length;
  const videoCount = mediaItems.filter((item) => item.media_type === "video").length;
  const voiceCount = mediaItems.filter((item) => item.media_type === "audio").length;

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

  function sendSelectedToIdentify() {
    const selectedItems = mediaItems.filter((item) => selectedIds.has(item.id));
    const imageItems = selectedItems.filter((item) => item.media_type === "image");
    if (imageItems.length === 0) {
      setStatus("Select at least one image candidate for Identify.");
      return;
    }

    onSendToIdentify(imageItems);
    setStatus(
      `Sent ${imageItems.length} image candidate${imageItems.length === 1 ? "" : "s"} to Identify.`,
    );
  }

  async function breakDownSelectedVideos() {
    if (selectedBreakdownVideoIds.length === 0) {
      setStatus("Select at least one video for Breakdown.");
      return;
    }

    try {
      setStatus(
        `Launching video breakdown for ${selectedBreakdownVideoIds.length} video${
          selectedBreakdownVideoIds.length === 1 ? "" : "s"
        }.`,
      );
      const job = await engine.createProcessingJob({
        job_type: "video_breakdown",
        source_media_item_ids: selectedBreakdownVideoIds,
        options: {
          generate_frames: true,
          extract_audio: true,
        },
      });
      setStatus(processingJobStatusMessage(job));

      const detail = await engine.getProcessingJob(job.id);
      if (detail.derived_media_items.length > 0) {
        onMediaItemsGenerated(detail.derived_media_items);
      }
      setStatus(processingJobStatusMessage(detail));
    } catch (error) {
      setStatus(`Video breakdown error: ${errorMessage(error)}`);
    }
  }

  return (
    <section className="workspace-section curate-workspace">
      <div className="section-header">
        <h2>Curate</h2>
        <p>PhotoMapAI-derived media triage workspace</p>
      </div>

      <div className="curate-layout">
        <aside className="curate-panel" aria-label="Curate search controls">
          <label htmlFor="curate-search">
            Search media
            <input
              id="curate-search"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="Path, filename, status, metadata"
            />
          </label>
          <label htmlFor="curate-media-type">
            Media type
            <select
              id="curate-media-type"
              value={mediaTypeFilter}
              onChange={(event) => setMediaTypeFilter(event.target.value as MediaTypeFilter)}
            >
              <option value="all">All</option>
              <option value="image">Images</option>
              <option value="video">Videos</option>
              <option value="audio">Voice</option>
            </select>
          </label>
          <dl className="metric-grid" aria-label="Curate summary">
            <div>
              <dt>Total</dt>
              <dd>{mediaItems.length}</dd>
            </div>
            <div>
              <dt>Visible</dt>
              <dd>{visibleItems.length}</dd>
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
              <dt>Voice</dt>
              <dd>{voiceCount}</dd>
            </div>
            <div>
              <dt>Selected</dt>
              <dd>{selectedIds.size}</dd>
            </div>
          </dl>
          <button
            className="primary-action"
            type="button"
            onClick={sendSelectedToIdentify}
            disabled={selectedIds.size === 0}
          >
            Send to Identify
          </button>
          <button
            className="primary-action"
            type="button"
            onClick={breakDownSelectedVideos}
            disabled={selectedBreakdownVideoIds.length === 0}
          >
            Break Down Selected Videos
          </button>
          <p aria-live="polite" className="status-line">
            {status}
          </p>
        </aside>

        <section className="curate-results" aria-label="Curate search results">
          <div className="panel-header">
            <h3>Media</h3>
            <p className="muted">
              <span>{visibleItems.length} visible</span>
              <span> / </span>
              <span>{selectedIds.size} selected</span>
            </p>
          </div>
          {visibleItems.length === 0 ? (
            <p className="empty-state">No media matches the current search.</p>
          ) : (
            <div className="media-grid">
              {visibleItems.map((item) => (
                <article
                  className={selectedIds.has(item.id) ? "media-card selected" : "media-card"}
                  key={item.id}
                  aria-label={displayName(item)}
                >
                  <MediaPreview item={item} assetUrl={engine.assetUrl} />
                  <div className="media-card-body">
                    <label className="media-select">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.id)}
                        aria-label={`Select for Identify: ${displayName(item)}`}
                        onChange={() => toggleSelected(item.id)}
                      />
                      Select
                    </label>
                    {item.media_type === "video" ? (
                      <label className="media-select">
                        <input
                          type="checkbox"
                          checked={breakdownSourceIds.has(item.id)}
                          aria-label={`Select for Breakdown: ${displayName(item)}`}
                          onChange={() => toggleBreakdownSelected(item.id)}
                        />
                        Breakdown
                      </label>
                    ) : null}
                    <strong>{displayName(item)}</strong>
                    <span>{mediaSummary(item)}</span>
                    <p>{item.raw_path ?? item.id}</p>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function MediaPreview({
  item,
  assetUrl,
}: {
  item: MediaItem;
  assetUrl(path: string): string;
}) {
  const imagePath = item.media_type === "image" ? item.raw_path : undefined;
  return (
    <div className="media-preview">
      {imagePath ? (
        <img src={assetUrl(imagePath)} alt="" />
      ) : (
        <span>{mediaTypeLabel(item.media_type)}</span>
      )}
      <span className="thumb-overlay" aria-hidden="true">
        <span className="thumb-meta">{mediaTypeLabel(item.media_type)}</span>
        <span className="thumb-status ready">{item.status ?? "new"}</span>
      </span>
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
  return mediaType === "audio" ? "voice" : mediaType;
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

function processingJobStatusMessage(
  job: Awaited<ReturnType<EngineClient["getProcessingJob"]>>,
): string {
  if (job.status === "complete") {
    if (job.derived_media_items.length > 0) {
      return `Generated ${job.derived_media_items.length} derivative media item${
        job.derived_media_items.length === 1 ? "" : "s"
      }.`;
    }
    return "Video breakdown complete with no derivative media items.";
  }
  if (job.status === "queued") {
    return `Video breakdown job ${job.id} queued.`;
  }
  if (job.status === "running") {
    return `Video breakdown job ${job.id} running: ${job.progress_message || "Processing videos."}`;
  }
  if (job.status === "failed") {
    return `Video breakdown job ${job.id} failed: ${jobErrorMessage(job)}.`;
  }
  if (job.status === "canceled") {
    return `Video breakdown job ${job.id} canceled.`;
  }
  return `Video breakdown job ${job.id} status: ${job.status}.`;
}

function jobErrorMessage(job: Awaited<ReturnType<EngineClient["getProcessingJob"]>>): string {
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
