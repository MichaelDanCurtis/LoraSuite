import type { MediaItem } from "../lib/types";

interface VideoReviewTabProps {
  mediaItems: MediaItem[];
}

export function VideoReviewTab({ mediaItems }: VideoReviewTabProps) {
  const videoCount = mediaItems.filter((item) => item.media_type === "video").length;

  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Video Review</h2>
        <p>Select segment ranges and intent flags for video, image, and voice handoffs.</p>
      </div>
      <p className="muted">{videoCount} videos ready for segment review.</p>
    </section>
  );
}
