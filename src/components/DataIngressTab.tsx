import { open } from "@tauri-apps/plugin-dialog";
import { useState } from "react";

import type { EngineClient } from "../lib/api";
import type { IngressCandidate, IngressJob, MediaItem } from "../lib/types";

type ViewMode = "tile" | "list" | "gallery";
type MediaFilter = "all" | "image" | "video";
type CandidateRole = "image" | "video";

interface CandidateReviewItem {
  id: string;
  displayName: string;
  sourceLocator: string;
  imageCandidate?: IngressCandidate;
  videoCandidate?: IngressCandidate;
  thumbnailCandidate: IngressCandidate;
  candidates: IngressCandidate[];
}

interface DataIngressTabProps {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

const viewModes: ViewMode[] = ["tile", "list", "gallery"];
const browserCookieSources = ["chrome", "brave", "chromium", "edge", "firefox", "safari"] as const;

export function DataIngressTab({
  engine,
  mediaItems,
  onMediaItemsImported,
}: DataIngressTabProps) {
  const [manualPaths, setManualPaths] = useState("");
  const [status, setStatus] = useState("Idle");
  const [candidates, setCandidates] = useState<IngressCandidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [viewMode, setViewMode] = useState<ViewMode>("tile");
  const [mediaFilter, setMediaFilter] = useState<MediaFilter>("all");
  const [galleryIndex, setGalleryIndex] = useState(0);
  const [jobs, setJobs] = useState<IngressJob[]>([]);
  const [showInstagramHelper, setShowInstagramHelper] = useState(false);
  const [showAdvancedFallbacks, setShowAdvancedFallbacks] = useState(false);
  const [instagramUrl, setInstagramUrl] = useState("");
  const [instagramBrowser, setInstagramBrowser] = useState("chrome");
  const [instagramPayloadText, setInstagramPayloadText] = useState(
    '{\n  "helper_version": "fixture",\n  "media": []\n}',
  );

  const reviewItems = buildReviewItems(candidates);
  const visibleReviewItems = reviewItems.filter((item) => itemMatchesFilter(item, mediaFilter));
  const selectedReadyCount = candidates.filter(
    (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
  ).length;
  const skippedCount = candidates.filter((candidate) => candidate.status !== "ready").length;
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

  async function chooseFiles() {
    try {
      const selected = await open({ multiple: true });
      await scanDialogSelection(selected);
    } catch (error) {
      setStatus(dialogErrorMessage(error));
    }
  }

  async function chooseFolder() {
    try {
      const selected = await open({ directory: true, multiple: true });
      await scanDialogSelection(selected);
    } catch (error) {
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
      applyScanResult(result.candidates);
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

    try {
      setStatus("Scanning Instagram URL with browser cookies.");
      const result = await engine.scanInstagramBrowserUrl(url, instagramBrowser);
      applyScanResult(result.candidates);
      setStatus(`Scanned ${result.candidates.length} Instagram candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram URL scan failed.");
    }
  }

  async function loadInstagramHelperCandidates() {
    try {
      setStatus("Loading Instagram helper candidates.");
      const result = await engine.listIngressCandidates("instagram");
      applyScanResult(result.candidates);
      setStatus(`Loaded ${result.candidates.length} Instagram helper candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Candidate load failed.");
    }
  }

  function applyScanResult(nextCandidates: IngressCandidate[]) {
    setCandidates(nextCandidates);
    setSelectedIds(
      new Set(
        nextCandidates
          .filter((candidate) => candidate.status === "ready" && candidate.selected)
          .map((candidate) => candidate.id),
      ),
    );
    setGalleryIndex(0);
  }

  async function confirmIngest() {
    const selectedCandidates = candidates.filter(
      (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
    );
    const candidateIds = selectedCandidates.map((candidate) => candidate.id);

    if (candidateIds.length === 0) {
      setStatus("Select at least one ready candidate.");
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
      const job = await engine.createIngressJob({
        source_kind: sourceKind,
        candidate_ids: candidateIds,
      });
      setJobs((currentJobs) => upsertJob(currentJobs, job));
      const completedJob = await waitForJob(job.id);
      setJobs((currentJobs) => upsertJob(currentJobs, completedJob));
      if (completedJob.imported_media_items.length > 0) {
        onMediaItemsImported(completedJob.imported_media_items);
      }
      const deferredCount = completedJob.deferred_count ?? 0;
      setStatus(
        `${completedJob.progress_message}: ${completedJob.imported_count} imported, ${deferredCount} deferred, ${completedJob.failed_count} failed.`,
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

  return (
    <section className="workspace-section ingress-workspace">
      <div className="section-header">
        <h2>Data Ingress</h2>
        <p>Scan local media, review candidates, then confirm only what should enter the vault.</p>
      </div>

      <div className="ingress-actions" aria-label="Ingress source actions">
        <button className="primary-action" type="button" onClick={chooseFiles}>
          Choose Files
        </button>
        <button type="button" onClick={chooseFolder}>
          Choose Folder
        </button>
        <button type="button" onClick={() => setShowInstagramHelper((visible) => !visible)}>
          Instagram Source
        </button>
        <button type="button" disabled>
          X Source
        </button>
      </div>

      {showInstagramHelper && (
        <div className="form-stack helper-payload-panel">
          <label htmlFor="instagram-url">Instagram URL</label>
          <input
            id="instagram-url"
            value={instagramUrl}
            onChange={(event) => setInstagramUrl(event.target.value)}
            placeholder="https://www.instagram.com/reel/..."
          />
          <label htmlFor="instagram-browser">Browser cookies</label>
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
          <button type="button" onClick={scanInstagramBrowserUrl}>
            Scan Instagram URL
          </button>
          <button type="button" onClick={() => setShowAdvancedFallbacks((visible) => !visible)}>
            Advanced Fallbacks
          </button>
          {showAdvancedFallbacks && (
            <div className="advanced-fallbacks">
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
              <label htmlFor="manual-paths">Manual path fallback</label>
              <textarea
                id="manual-paths"
                value={manualPaths}
                onChange={(event) => setManualPaths(event.target.value)}
                rows={3}
                placeholder="/absolute/path/to/file-or-folder"
              />
              <button type="button" onClick={scanManualPaths}>
                Scan Manual Paths
              </button>
            </div>
          )}
        </div>
      )}

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
          </select>
        </label>

        <button type="button" onClick={selectVisibleReadyCandidates} disabled={!hasVisibleItems}>
          Select All
        </button>
        <button
          type="button"
          onClick={() => selectVisibleRoleCandidates("image")}
          disabled={!hasVisibleImageCandidates}
        >
          Select All Images
        </button>
        <button
          type="button"
          onClick={() => selectVisibleRoleCandidates("video")}
          disabled={!hasVisibleVideoCandidates}
        >
          Select All Videos
        </button>
        <button type="button" onClick={deselectVisibleCandidates} disabled={!hasVisibleItems}>
          Deselect All
        </button>
        <button type="button" onClick={invertVisibleReadyCandidates} disabled={!hasVisibleItems}>
          Invert
        </button>
        <button
          className="primary-action"
          type="button"
          onClick={confirmIngest}
          disabled={selectedReadyCount === 0}
        >
          Confirm Ingest
        </button>
      </div>

      <p aria-live="polite" className="status-line">
        {status}
      </p>

      <dl className="metric-grid" aria-label="Ingress summary">
        <div>
          <dt>Imported</dt>
          <dd>{mediaItems.length}</dd>
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

      <div className="candidate-review">
        {visibleReviewItems.length === 0 ? (
          <p className="empty-state">No candidates scanned yet.</p>
        ) : (
          <>
            {viewMode === "tile" && (
              <TileView
                items={visibleReviewItems}
                selectedIds={selectedIds}
                assetUrl={engine.assetUrl}
                onToggleCandidate={toggleCandidate}
              />
            )}
            {viewMode === "list" && (
              <ListView
                items={visibleReviewItems}
                selectedIds={selectedIds}
                assetUrl={engine.assetUrl}
                onToggleCandidate={toggleCandidate}
              />
            )}
            {viewMode === "gallery" && galleryItem && (
              <GalleryView
                item={galleryItem}
                currentIndex={safeGalleryIndex}
                total={visibleReviewItems.length}
                selectedIds={selectedIds}
                assetUrl={engine.assetUrl}
                onToggleCandidate={toggleCandidate}
                onPrevious={() => setGalleryIndex(Math.max(0, safeGalleryIndex - 1))}
                onNext={() =>
                  setGalleryIndex(Math.min(visibleReviewItems.length - 1, safeGalleryIndex + 1))
                }
              />
            )}
          </>
        )}
      </div>

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
  assetUrl(path: string): string;
  onToggleCandidate(candidateId: string): void;
}

function TileView({ items, selectedIds, assetUrl, onToggleCandidate }: CandidateViewProps) {
  return (
    <div className="candidate-grid">
      {items.map((item) => (
        <article className="candidate-tile" key={item.id}>
          <CandidateThumbnail candidate={item.thumbnailCandidate} assetUrl={assetUrl} />
          <div className="candidate-body">
            <RoleSelectors
              item={item}
              selectedIds={selectedIds}
              onToggleCandidate={onToggleCandidate}
            />
            <strong>{item.displayName}</strong>
            <span>{reviewItemSummary(item)}</span>
            <RoleStatusBadges item={item} />
          </div>
        </article>
      ))}
    </div>
  );
}

function ListView({ items, selectedIds, assetUrl, onToggleCandidate }: CandidateViewProps) {
  return (
    <table className="candidate-list" aria-label="Candidate list">
      <thead>
        <tr>
          <th>Preview</th>
          <th>Use</th>
          <th>File</th>
          <th>Roles</th>
          <th>Size</th>
          <th>Status</th>
          <th>Path</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>
              <CandidateThumbnail candidate={item.thumbnailCandidate} assetUrl={assetUrl} />
            </td>
            <td>
              <RoleSelectors
                item={item}
                selectedIds={selectedIds}
                onToggleCandidate={onToggleCandidate}
              />
            </td>
            <td>{item.displayName}</td>
            <td>{roleSummary(item)}</td>
            <td>{formatBytes(item.thumbnailCandidate.size_bytes)}</td>
            <td>
              <RoleStatusBadges item={item} />
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
  assetUrl(path: string): string;
  onToggleCandidate(candidateId: string): void;
  onPrevious(): void;
  onNext(): void;
}

function GalleryView({
  item,
  currentIndex,
  total,
  selectedIds,
  assetUrl,
  onToggleCandidate,
  onPrevious,
  onNext,
}: GalleryViewProps) {
  return (
    <div className="gallery-review">
      <CandidateThumbnail candidate={item.thumbnailCandidate} assetUrl={assetUrl} large />
      <div className="gallery-details">
        <p className="muted">
          {currentIndex + 1} of {total}
        </p>
        <h3>{item.displayName}</h3>
        <p>{item.sourceLocator}</p>
        <p>{reviewItemSummary(item)}</p>
        <RoleStatusBadges item={item} />
        <RoleSelectors
          item={item}
          selectedIds={selectedIds}
          onToggleCandidate={onToggleCandidate}
        />
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
  const roles: CandidateRole[] = ["image", "video"];
  return (
    <div className="role-selectors">
      {roles.map((role) => {
        const candidate = candidateForRole(item, role);
        if (!candidate) return null;
        const label = `Select as ${role}: ${item.displayName}`;
        return (
          <label key={role}>
            <input
              aria-label={label}
              type="checkbox"
              checked={selectedIds.has(candidate.id)}
              disabled={candidate.status !== "ready"}
              onChange={() => onToggleCandidate(candidate.id)}
            />
            Select as {role}
          </label>
        );
      })}
    </div>
  );
}

function RoleStatusBadges({ item }: { item: CandidateReviewItem }) {
  const roles: CandidateRole[] = ["image", "video"];
  return (
    <div className="role-statuses">
      {roles.map((role) => {
        const candidate = candidateForRole(item, role);
        if (!candidate) return null;
        return (
          <span className="role-status" key={role}>
            <span className="role-name">{role}</span>
            <StatusBadge candidate={candidate} />
          </span>
        );
      })}
    </div>
  );
}

function CandidateThumbnail({
  candidate,
  assetUrl,
  large = false,
}: {
  candidate: IngressCandidate;
  assetUrl(path: string): string;
  large?: boolean;
}) {
  const thumbnailPath = candidate.thumbnail_path ?? candidate.poster_asset_path;
  const thumbnail = thumbnailPath ? assetUrl(thumbnailPath) : undefined;
  return (
    <div className={large ? "candidate-thumb large" : "candidate-thumb"}>
      {thumbnail ? (
        <img src={thumbnail} alt="" />
      ) : (
        <span>{candidate.media_type ?? "file"}</span>
      )}
    </div>
  );
}

function StatusBadge({ candidate }: { candidate: IngressCandidate }) {
  return (
    <span className={`status-badge ${candidate.status}`}>
      {candidate.status}
      {candidate.error_message ? `: ${candidate.error_message}` : ""}
    </span>
  );
}

function modeLabel(mode: ViewMode): string {
  return mode[0].toUpperCase() + mode.slice(1);
}

function browserLabel(browser: string): string {
  return browser[0].toUpperCase() + browser.slice(1);
}

function buildReviewItems(candidates: IngressCandidate[]): CandidateReviewItem[] {
  const candidatesById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
  const posterByVideoCandidateId = new Map<string, IngressCandidate>();
  for (const candidate of candidates) {
    const videoCandidateId = sourceVideoCandidateId(candidate);
    if (
      candidate.media_type === "image" &&
      videoCandidateId &&
      candidatesById.has(videoCandidateId)
    ) {
      posterByVideoCandidateId.set(videoCandidateId, candidate);
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

    const posterCandidate = posterByVideoCandidateId.get(candidate.id);
    if (candidate.media_type === "video") {
      const itemCandidates = posterCandidate ? [posterCandidate, candidate] : [candidate];
      consumedIds.add(candidate.id);
      if (posterCandidate) consumedIds.add(posterCandidate.id);
      items.push({
        id: candidate.id,
        displayName: candidate.display_name,
        sourceLocator: candidate.source_locator,
        imageCandidate: posterCandidate,
        videoCandidate: candidate,
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

function itemMatchesFilter(item: CandidateReviewItem, mediaFilter: MediaFilter): boolean {
  return mediaFilter === "all" || candidateForRole(item, mediaFilter) !== undefined;
}

function candidateForRole(
  item: CandidateReviewItem,
  role: CandidateRole,
): IngressCandidate | undefined {
  return role === "image" ? item.imageCandidate : item.videoCandidate;
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

function roleSummary(item: CandidateReviewItem): string {
  const roles: CandidateRole[] = ["image", "video"];
  const labels = roles.filter((role) => candidateForRole(item, role));
  return labels.length > 0 ? labels.join(", ") : "unknown";
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

function formatBytes(bytes?: number | null): string {
  if (!bytes) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

function dialogErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return `Native file picker unavailable: ${error.message}. Use Advanced Fallbacks to scan paths manually.`;
  }
  return "Native file picker unavailable. Use Advanced Fallbacks to scan paths manually.";
}
