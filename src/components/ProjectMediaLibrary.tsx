import { useState } from "react";
import type { MediaItem } from "../lib/types";

export function ProjectMediaLibrary({ items, assetUrl, loading = false, error = "" }: {
  items: MediaItem[]; assetUrl(path: string): string; loading?: boolean; error?: string;
}) {
  const [type, setType] = useState("all");
  const [page, setPage] = useState(0);
  const visible = items.filter((item) => type === "all" || item.media_type === type);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(visible.length / 24) - 1));
  return <section className="project-media-library" aria-label="Saved project media">
    <header><div><h3>Already in this project</h3><p>{loading ? "Loading saved media…" : `${items.length} saved items. New imports are reviewed separately below.`}</p></div>
      <label>Show <select aria-label="Saved media type" value={type} onChange={(event) => { setType(event.target.value); setPage(0); }}>
        <option value="all">All media</option><option value="image">Images</option><option value="video">Videos</option><option value="audio">Audio</option>
      </select></label>
    </header>
    {error ? <p role="alert">{error}</p> : null}
    {!loading && !visible.length ? <p>No saved {type === "all" ? "media" : type} items in this project yet.</p> : null}
    <div className="project-media-grid">{visible.slice(currentPage * 24, currentPage * 24 + 24).map((item) => {
      const name = item.raw_path?.split(/[\\/]/).pop() || item.id;
      return <figure key={item.id}>
        {item.media_type === "image" && item.raw_path ? <img loading="lazy" src={assetUrl(item.raw_path)} alt={name} />
          : item.media_type === "video" && item.raw_path ? <video src={assetUrl(item.raw_path)} preload="none" controls />
            : item.media_type === "audio" && item.raw_path ? <audio src={assetUrl(item.raw_path)} preload="none" controls /> : null}
        <figcaption title={name}>{name}</figcaption>
      </figure>;
    })}</div>
    {visible.length > 24 ? <footer><button type="button" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous saved media</button><span>{currentPage + 1} / {Math.ceil(visible.length / 24)}</span><button type="button" disabled={(currentPage + 1) * 24 >= visible.length} onClick={() => setPage(currentPage + 1)}>Next saved media</button></footer> : null}
  </section>;
}
