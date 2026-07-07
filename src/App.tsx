import { useMemo, useState } from "react";

import { CurateSearchTab } from "./components/CurateSearchTab";
import { DataIngressTab } from "./components/DataIngressTab";
import { ExportsTab } from "./components/ExportsTab";
import { VideoReviewTab } from "./components/VideoReviewTab";
import { createEngineClient } from "./lib/api";
import type { MediaItem } from "./lib/types";

type TabId = "ingress" | "curate" | "video" | "exports";

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "ingress", label: "Data Ingress" },
  { id: "curate", label: "Curate / Search" },
  { id: "video", label: "Video Review" },
  { id: "exports", label: "Exports" },
];

function App() {
  const [activeTab, setActiveTab] = useState<TabId>("ingress");
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const engine = useMemo(() => createEngineClient(), []);

  function addMediaItems(items: MediaItem[]) {
    setMediaItems((existingItems) => [...existingItems, ...items]);
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <h1>LoraSuite</h1>
          <p>Local media to training-ready LoRA dataset handoffs.</p>
        </div>
      </header>

      <nav className="workspace-tabs" role="tablist" aria-label="LoraSuite workspace">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <section className="workspace-panel" role="tabpanel">
        {activeTab === "ingress" && (
          <DataIngressTab
            engine={engine}
            mediaItems={mediaItems}
            onMediaItemsImported={addMediaItems}
          />
        )}
        {activeTab === "curate" && <CurateSearchTab mediaItems={mediaItems} />}
        {activeTab === "video" && <VideoReviewTab mediaItems={mediaItems} />}
        {activeTab === "exports" && <ExportsTab engine={engine} />}
      </section>
    </main>
  );
}

export default App;
