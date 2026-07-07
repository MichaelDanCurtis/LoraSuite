import type { MediaItem } from "../lib/types";
import { useMemo, useState } from "react";

interface VideoReviewTabProps {
  mediaItems: MediaItem[];
}

export function VideoReviewTab({ mediaItems }: VideoReviewTabProps) {
  const [startSeconds, setStartSeconds] = useState("0");
  const [endSeconds, setEndSeconds] = useState("10");
  const [useForImage, setUseForImage] = useState(false);
  const [useForVideo, setUseForVideo] = useState(false);
  const [useForVoice, setUseForVoice] = useState(false);
  const videoCount = mediaItems.filter((item) => item.media_type === "video").length;
  const guidance = useMemo(() => {
    const lines: string[] = [];
    if (useForImage) {
      lines.push("Extract sparse keyframes from stable visual ranges.");
    }
    if (useForVideo) {
      lines.push("Keep the clip coherent; there is no hard duration limit.");
    }
    if (useForVoice) {
      lines.push("Prefer clean speech with one speaker and low noise.");
    }
    if (lines.length === 0) {
      lines.push("Select at least one training intent for this segment.");
    }
    return lines;
  }, [useForImage, useForVideo, useForVoice]);

  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Video Review</h2>
        <p>Select segment ranges and intent flags for video, image, and voice handoffs.</p>
      </div>
      <p className="muted">{videoCount} videos ready for segment review.</p>

      <div className="field-grid">
        <label>
          Start seconds
          <input
            value={startSeconds}
            onChange={(event) => setStartSeconds(event.target.value)}
            inputMode="decimal"
          />
        </label>
        <label>
          End seconds
          <input
            value={endSeconds}
            onChange={(event) => setEndSeconds(event.target.value)}
            inputMode="decimal"
          />
        </label>
      </div>

      <fieldset>
        <legend>Training intent</legend>
        <label>
          <input
            type="checkbox"
            checked={useForImage}
            onChange={(event) => setUseForImage(event.target.checked)}
          />
          Use for image training
        </label>
        <label>
          <input
            type="checkbox"
            checked={useForVideo}
            onChange={(event) => setUseForVideo(event.target.checked)}
          />
          Use for video training
        </label>
        <label>
          <input
            type="checkbox"
            checked={useForVoice}
            onChange={(event) => setUseForVoice(event.target.checked)}
          />
          Use for voice training / cloning
        </label>
      </fieldset>

      <div className="guidance-block">
        <h3>Guidance</h3>
        {guidance.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
    </section>
  );
}
