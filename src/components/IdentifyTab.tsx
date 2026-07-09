import { useState } from "react";

import type { MediaItem } from "../lib/types";

type IdentityIntent = "unassigned" | "face" | "body" | "full" | "reject";

interface IdentifyTabProps {
  mediaItems: MediaItem[];
  assetUrl(path: string): string;
}

export function IdentifyTab({ mediaItems, assetUrl }: IdentifyTabProps) {
  const [intents, setIntents] = useState<Record<string, IdentityIntent>>({});
  const intentCounts = mediaItems.reduce(
    (counts, item) => {
      const intent = intents[item.id] ?? "unassigned";
      counts[intent] += 1;
      return counts;
    },
    {
      unassigned: 0,
      face: 0,
      body: 0,
      full: 0,
      reject: 0,
    } satisfies Record<IdentityIntent, number>,
  );

  function setIntent(itemId: string, intent: IdentityIntent) {
    setIntents((currentIntents) => ({
      ...currentIntents,
      [itemId]: intent,
    }));
  }

  return (
    <section className="workspace-section identify-workspace">
      <div className="section-header">
        <h2>Identify</h2>
        <p>Choose which imported images become identity, face, and body candidates.</p>
      </div>

      <dl className="metric-grid" aria-label="Identify summary">
        <div>
          <dt>Targets</dt>
          <dd>
            {mediaItems.length} target candidate{mediaItems.length === 1 ? "" : "s"}
          </dd>
        </div>
        <div>
          <dt>Face crops</dt>
          <dd>{intentCounts.face}</dd>
        </div>
        <div>
          <dt>Body shots</dt>
          <dd>{intentCounts.body}</dd>
        </div>
        <div>
          <dt>Full body</dt>
          <dd>{intentCounts.full}</dd>
        </div>
      </dl>

      {mediaItems.length === 0 ? (
        <p className="empty-state">Send image candidates from Curate to begin identity review.</p>
      ) : (
        <div className="media-grid">
          {mediaItems.map((item) => {
            const name = displayName(item);
            return (
              <article className="media-card" key={item.id} aria-label={name}>
                <div className="media-preview">
                  {item.raw_path ? (
                    <img src={assetUrl(item.raw_path)} alt="" />
                  ) : (
                    <span>image</span>
                  )}
                  <span className="thumb-overlay" aria-hidden="true">
                    <span className="thumb-meta">{mediaSummary(item)}</span>
                    <span className="thumb-status ready">
                      {intents[item.id] ?? "unassigned"}
                    </span>
                  </span>
                </div>
                <div className="media-card-body">
                  <strong>{name}</strong>
                  <span>{mediaSummary(item)}</span>
                  <label htmlFor={`identity-intent-${item.id}`}>
                    Identity intent for {name}
                  </label>
                  <select
                    id={`identity-intent-${item.id}`}
                    value={intents[item.id] ?? "unassigned"}
                    onChange={(event) =>
                      setIntent(item.id, event.target.value as IdentityIntent)
                    }
                  >
                    <option value="unassigned">Unassigned</option>
                    <option value="face">Face</option>
                    <option value="body">Body</option>
                    <option value="full">Full body</option>
                    <option value="reject">Reject</option>
                  </select>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
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
  return item.media_type;
}
