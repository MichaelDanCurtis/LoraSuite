import type { EngineClient } from "../lib/api";
import type { MediaItem } from "../lib/types";

interface DataIngressTabProps {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

export function DataIngressTab({ mediaItems }: DataIngressTabProps) {
  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Data Ingress</h2>
        <p>Import local images and videos before social acquisition connectors are added.</p>
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
