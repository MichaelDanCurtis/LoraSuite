import { useMemo, useState } from "react";

import type { MediaItem, MediaType } from "../lib/types";

interface CurateSearchTabProps {
  mediaItems: MediaItem[];
  assetUrl(path: string): string;
}

type MediaTypeFilter = "all" | MediaType;

export function CurateSearchTab({ mediaItems, assetUrl }: CurateSearchTabProps) {
  const [searchText, setSearchText] = useState("");
  const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
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

  return (
    <section className="workspace-section curate-workspace">
      <div className="section-header">
        <h2>Curate / Search</h2>
        <p>PhotoMapAI-derived curation workspace</p>
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
                  <MediaPreview item={item} assetUrl={assetUrl} />
                  <div className="media-card-body">
                    <label className="media-select">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.id)}
                        aria-label={`Select for dataset: ${displayName(item)}`}
                        onChange={() => toggleSelected(item.id)}
                      />
                      Select
                    </label>
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
