import type { MediaItem } from "../lib/types";

interface CurateSearchTabProps {
  mediaItems: MediaItem[];
}

export function CurateSearchTab({ mediaItems }: CurateSearchTabProps) {
  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Curate / Search</h2>
        <p>PhotoMapAI-derived curation workspace</p>
      </div>
      <p className="muted">{mediaItems.length} items available for curation.</p>
    </section>
  );
}
