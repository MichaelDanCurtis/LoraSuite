import { useCallback, useMemo, useState } from "react";

import { CurateSearchTab } from "./components/CurateSearchTab";
import { DataIngressTab } from "./components/DataIngressTab";
import { IdentifyTab } from "./components/IdentifyTab";
import { TrainTab } from "./components/TrainTab";
import { createEngineClient } from "./lib/api";
import type { MediaItem } from "./lib/types";

type TabId = "ingest" | "curate" | "identify" | "train";

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "ingest", label: "Data Ingest" },
  { id: "curate", label: "Curate" },
  { id: "identify", label: "Identify" },
  { id: "train", label: "Train" },
];

function App() {
  const [activeTab, setActiveTab] = useState<TabId>("ingest");
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const [identifyItems, setIdentifyItems] = useState<MediaItem[]>([]);
  const engine = useMemo(() => createEngineClient(), []);

  const addMediaItems = useCallback((items: MediaItem[]) => {
    setMediaItems((existingItems) => mergeMediaItems(existingItems, items));
  }, []);

  const sendToIdentify = useCallback((items: MediaItem[]) => {
    setIdentifyItems((existingItems) => mergeMediaItems(existingItems, items));
    setActiveTab("identify");
  }, []);

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
        <div hidden={activeTab !== "ingest"}>
          <DataIngressTab
            engine={engine}
            mediaItems={mediaItems}
            onMediaItemsImported={addMediaItems}
          />
        </div>
        <CurateSearchTab
          mediaItems={mediaItems}
          engine={engine}
          isActive={activeTab === "curate"}
          onSendToIdentify={sendToIdentify}
          onMediaItemsGenerated={addMediaItems}
        />
        {activeTab === "identify" ? (
          <IdentifyTab mediaItems={identifyItems} assetUrl={engine.assetUrl} />
        ) : null}
        {activeTab === "train" ? (
          <TrainTab engine={engine} targetItems={identifyItems} />
        ) : null}
      </section>
    </main>
  );
}

function mergeMediaItems(existingItems: MediaItem[], nextItems: MediaItem[]): MediaItem[] {
  if (nextItems.length === 0) {
    return existingItems;
  }

  const existingKeys = new Set(existingItems.map(mediaItemKey));
  const uniqueItems = nextItems.filter((item) => {
    const key = mediaItemKey(item);
    if (existingKeys.has(key)) {
      return false;
    }
    existingKeys.add(key);
    return true;
  });
  return uniqueItems.length === 0 ? existingItems : [...existingItems, ...uniqueItems];
}

function mediaItemKey(item: MediaItem): string {
  return item.raw_path ?? item.id;
}

export default App;
