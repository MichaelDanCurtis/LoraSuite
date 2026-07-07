import { useState } from "react";

import type { EngineClient } from "../lib/api";
import type { MediaItem } from "../lib/types";

interface DataIngressTabProps {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

export function DataIngressTab({
  engine,
  mediaItems,
  onMediaItemsImported,
}: DataIngressTabProps) {
  const [pathsText, setPathsText] = useState("");
  const [status, setStatus] = useState("Idle");

  async function importPaths() {
    const paths = pathsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

    if (paths.length === 0) {
      setStatus("Enter at least one local file path.");
      return;
    }

    setStatus("Importing");
    try {
      const response = await engine.importLocal(paths);
      onMediaItemsImported(response.media_items);
      const errorText =
        response.errors.length > 0 ? ` ${response.errors.length} item(s) skipped.` : "";
      setStatus(`Imported ${response.media_items.length} media item(s).${errorText}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Import failed.");
    }
  }

  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Data Ingress</h2>
        <p>Import local images and videos before social acquisition connectors are added.</p>
      </div>

      <div className="form-stack">
        <label htmlFor="local-paths">Local image/video paths</label>
        <textarea
          id="local-paths"
          value={pathsText}
          onChange={(event) => setPathsText(event.target.value)}
          rows={6}
          placeholder="/absolute/path/to/file.png"
        />
        <button className="primary-action" type="button" onClick={importPaths}>
          Import Local Media
        </button>
        <p aria-live="polite" className="status-line">
          {status}
        </p>
      </div>

      <dl className="metric-grid" aria-label="Ingress summary">
        <div>
          <dt>Imported</dt>
          <dd>{mediaItems.length}</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>Local</dd>
        </div>
      </dl>
    </section>
  );
}
