import { convertFileSrc } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useState } from "react";

import type { EngineClient } from "../lib/api";
import type { IngressCandidate, IngressJob, MediaItem } from "../lib/types";

type ViewMode = "tile" | "list" | "gallery";
type MediaFilter = "all" | "image" | "video";

interface DataIngressTabProps {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

const viewModes: ViewMode[] = ["tile", "list", "gallery"];

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
  const [instagramPayloadText, setInstagramPayloadText] = useState(
    '{\n  "helper_version": "fixture",\n  "media": []\n}',
  );

  const visibleCandidates = candidates.filter((candidate) => {
    return mediaFilter === "all" || candidate.media_type === mediaFilter;
  });
  const selectedReadyCount = candidates.filter(
    (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
  ).length;
  const skippedCount = candidates.filter((candidate) => candidate.status !== "ready").length;
  const safeGalleryIndex =
    visibleCandidates.length === 0
      ? 0
      : Math.min(galleryIndex, visibleCandidates.length - 1);
  const galleryCandidate = visibleCandidates[safeGalleryIndex];

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
      setCandidates(result.candidates);
      setSelectedIds(
        new Set(
          result.candidates
            .filter((candidate) => candidate.status === "ready" && candidate.selected)
            .map((candidate) => candidate.id),
        ),
      );
      setGalleryIndex(0);
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
      setCandidates(result.candidates);
      setSelectedIds(
        new Set(
          result.candidates
            .filter((candidate) => candidate.status === "ready" && candidate.selected)
            .map((candidate) => candidate.id),
        ),
      );
      setGalleryIndex(0);
      setStatus(`Scanned ${result.candidates.length} Instagram candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram helper scan failed.");
    }
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
      setStatus(
        `${completedJob.progress_message}: ${completedJob.imported_count} imported, ${completedJob.failed_count} failed.`,
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
      for (const candidate of visibleCandidates) {
        if (candidate.status === "ready") {
          nextIds.add(candidate.id);
        }
      }
      return nextIds;
    });
  }

  function deselectVisibleCandidates() {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidate of visibleCandidates) {
        nextIds.delete(candidate.id);
      }
      return nextIds;
    });
  }

  function invertVisibleReadyCandidates() {
    setSelectedIds((currentIds) => {
      const nextIds = new Set(currentIds);
      for (const candidate of visibleCandidates) {
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
        </div>
      )}

      <div className="form-stack manual-ingress">
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

        <button type="button" onClick={selectVisibleReadyCandidates} disabled={visibleCandidates.length === 0}>
          Select All
        </button>
        <button type="button" onClick={deselectVisibleCandidates} disabled={visibleCandidates.length === 0}>
          Deselect All
        </button>
        <button type="button" onClick={invertVisibleReadyCandidates} disabled={visibleCandidates.length === 0}>
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
        {visibleCandidates.length === 0 ? (
          <p className="empty-state">No candidates scanned yet.</p>
        ) : (
          <>
            {viewMode === "tile" && (
              <TileView
                candidates={visibleCandidates}
                selectedIds={selectedIds}
                onToggleCandidate={toggleCandidate}
              />
            )}
            {viewMode === "list" && (
              <ListView
                candidates={visibleCandidates}
                selectedIds={selectedIds}
                onToggleCandidate={toggleCandidate}
              />
            )}
            {viewMode === "gallery" && galleryCandidate && (
              <GalleryView
                candidate={galleryCandidate}
                currentIndex={safeGalleryIndex}
                total={visibleCandidates.length}
                selected={selectedIds.has(galleryCandidate.id)}
                onToggleCandidate={() => toggleCandidate(galleryCandidate.id)}
                onPrevious={() => setGalleryIndex(Math.max(0, safeGalleryIndex - 1))}
                onNext={() =>
                  setGalleryIndex(Math.min(visibleCandidates.length - 1, safeGalleryIndex + 1))
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
  candidates: IngressCandidate[];
  selectedIds: Set<string>;
  onToggleCandidate(candidateId: string): void;
}

function TileView({ candidates, selectedIds, onToggleCandidate }: CandidateViewProps) {
  return (
    <div className="candidate-grid">
      {candidates.map((candidate) => (
        <article className="candidate-tile" key={candidate.id}>
          <CandidateThumbnail candidate={candidate} />
          <div className="candidate-body">
            <label>
              <input
                type="checkbox"
                checked={selectedIds.has(candidate.id)}
                disabled={candidate.status !== "ready"}
                onChange={() => onToggleCandidate(candidate.id)}
              />
              Select
            </label>
            <strong>{candidate.display_name}</strong>
            <span>{mediaSummary(candidate)}</span>
            <StatusBadge candidate={candidate} />
          </div>
        </article>
      ))}
    </div>
  );
}

function ListView({ candidates, selectedIds, onToggleCandidate }: CandidateViewProps) {
  return (
    <table className="candidate-list">
      <thead>
        <tr>
          <th>Use</th>
          <th>File</th>
          <th>Type</th>
          <th>Size</th>
          <th>Status</th>
          <th>Path</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((candidate) => (
          <tr key={candidate.id}>
            <td>
              <input
                aria-label={`Select ${candidate.display_name}`}
                type="checkbox"
                checked={selectedIds.has(candidate.id)}
                disabled={candidate.status !== "ready"}
                onChange={() => onToggleCandidate(candidate.id)}
              />
            </td>
            <td>{candidate.display_name}</td>
            <td>{candidate.media_type ?? "unknown"}</td>
            <td>{formatBytes(candidate.size_bytes)}</td>
            <td>
              <StatusBadge candidate={candidate} />
            </td>
            <td className="path-cell">{candidate.source_locator}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface GalleryViewProps {
  candidate: IngressCandidate;
  currentIndex: number;
  total: number;
  selected: boolean;
  onToggleCandidate(): void;
  onPrevious(): void;
  onNext(): void;
}

function GalleryView({
  candidate,
  currentIndex,
  total,
  selected,
  onToggleCandidate,
  onPrevious,
  onNext,
}: GalleryViewProps) {
  return (
    <div className="gallery-review">
      <CandidateThumbnail candidate={candidate} large />
      <div className="gallery-details">
        <p className="muted">
          {currentIndex + 1} of {total}
        </p>
        <h3>{candidate.display_name}</h3>
        <p>{candidate.source_locator}</p>
        <p>{mediaSummary(candidate)}</p>
        <StatusBadge candidate={candidate} />
        <label>
          <input
            type="checkbox"
            checked={selected}
            disabled={candidate.status !== "ready"}
            onChange={onToggleCandidate}
          />
          Select for ingest
        </label>
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

function CandidateThumbnail({
  candidate,
  large = false,
}: {
  candidate: IngressCandidate;
  large?: boolean;
}) {
  const thumbnail = fileUrl(candidate.thumbnail_path ?? candidate.poster_asset_path);
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

function fileUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  try {
    return convertFileSrc(path);
  } catch {
    return `file://${path}`;
  }
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
    return `Native file picker unavailable: ${error.message}`;
  }
  return "Native file picker unavailable. Use the manual path fallback.";
}
