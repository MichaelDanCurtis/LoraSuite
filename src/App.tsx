import { useProjectMedia } from "./lib/useProjectMedia";
import { isRelevantMedia } from "./lib/projectMedia";
import {
  Boxes,
  FolderInput,
  GalleryHorizontalEnd,
  LayoutGrid,
  PackageCheck,
  ScanFace,
  Settings2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { AppUpdateControl } from "./components/AppUpdateControl";
import { CredentialVault } from "./components/CredentialVault";
import { DataIngressTab } from "./components/DataIngressTab";
import { GuidedExperience, type GuidedStage } from "./components/GuidedExperience";
import { GuidedErrorBoundary } from "./components/GuidedErrorBoundary";
import { JobCenter } from "./components/JobCenter";
import { ModelLibrary } from "./components/ModelLibrary";
import { ProjectHome } from "./components/ProjectHome";
import { SupportDiagnostics } from "./components/SupportDiagnostics";
import {
  ThemePicker,
} from "./components/ThemePicker";
import { WorkflowWizard } from "./components/WorkflowWizard";
import type { WizardTarget, WorkspaceTab } from "./components/WorkflowWizard";
import { useSharedWorkspace } from "./lib/useSharedWorkspace";
import { useSharedTheme } from "./lib/useSharedTheme";
import { createEngineClient } from "./lib/api";
import type { MediaItem, TrainingIntent, TrainingWorkflowLane } from "./lib/types";

type TabId = WorkspaceTab;

const wizardTargetStorageKey = "lorasuite:workflow-target:v1";
const activeProjectStorageKey = "lorasuite:active-project:v1";
const experienceStorageKey = "lorasuite:experience:v1";
const guidedStageStorageKey = "lorasuite:guided-stage:v2";
const VAULT_MEDIA_PAGE_SIZE = 250;
const LazyCurateSearchTab = lazy(() =>
  import("./components/CurateSearchTab").then((module) => ({ default: module.CurateSearchTab })),
);
const LazyIdentifyTab = lazy(() =>
  import("./components/IdentifyTab").then((module) => ({ default: module.IdentifyTab })),
);
const LazyTrainTab = lazy(() =>
  import("./components/TrainTab").then((module) => ({ default: module.TrainTab })),
);

const tabs: Array<{ id: TabId; label: string; icon: LucideIcon }> = [
  { id: "ingest", label: "Data Ingest", icon: FolderInput },
  { id: "curate", label: "Prepare", icon: GalleryHorizontalEnd },
  { id: "identify", label: "Verify Identity", icon: ScanFace },
  { id: "train", label: "Build & Train", icon: PackageCheck },
];

function App() {
  const engine = useMemo(() => createEngineClient(), []);
  const { workspace, updateWorkspace, workspaceSyncError, workspaceLoaded } = useSharedWorkspace(engine);
  const experience = workspace.experience;
  const wizardTarget = workspace.target;
  const activeProjectId = workspace.active_project_id;
  const setExperience = useCallback((experience: "guided" | "studio") => updateWorkspace({ experience }), [updateWorkspace]);
  const setWizardTarget = useCallback((target: WizardTarget) => updateWorkspace({ target }), [updateWorkspace]);
  const setActiveProjectId = useCallback((active_project_id: string) => updateWorkspace({ active_project_id, stage: "create" }), [updateWorkspace]);
  const [activeTab, setActiveTab] = useState<TabId>("ingest");
  const [loadedStudioTabs, setLoadedStudioTabs] = useState<Set<TabId>>(
    () => new Set(["ingest"]),
  );
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const projectMedia = useProjectMedia(engine, mediaItems, activeProjectId);
  const preparationItems = useMemo(() => (activeProjectId ? projectMedia.items : mediaItems).filter((item) => isRelevantMedia(item, wizardTarget)), [activeProjectId, projectMedia.items, mediaItems, wizardTarget]);
  const [identifyItems, setIdentifyItems] = useState<MediaItem[]>([]);
  const [guidedNavigation, setGuidedNavigation] = useState<{ stage: GuidedStage; target?: WizardTarget; token: number } | null>(null);
  const { theme, selectTheme: setTheme, themeSyncError } = useSharedTheme(engine);

  const goHome = useCallback(() => {
    setGuidedNavigation((previous) => ({ stage: "create", token: (previous?.token ?? 0) + 1 }));
    updateWorkspace({ experience: "guided", stage: "create" });
  }, [updateWorkspace]);

  const continueProjectLane = useCallback((lane: TrainingWorkflowLane) => {
    if (["image", "video", "voice", "id_lora"].includes(lane.target_mode)) {
      setWizardTarget(lane.target_mode as WizardTarget);
    }
    const nextStage: GuidedStage = lane.id === "evaluate"
      ? "evaluate"
      : lane.target_workspace === "ingest"
        ? "sources"
        : lane.target_workspace === "curate"
          ? "prepare"
          : lane.target_workspace === "identify"
            ? "verify"
            : "build";
    window.localStorage.setItem(guidedStageStorageKey, nextStage);
    setGuidedNavigation({
      stage: nextStage,
      target: ["image", "video", "voice", "id_lora"].includes(lane.target_mode)
        ? lane.target_mode as WizardTarget
        : undefined,
      token: Date.now(),
    });
    setExperience("guided");
  }, [setWizardTarget, setExperience]);

  const addMediaItems = useCallback((items: MediaItem[]) => {
    setMediaItems((existingItems) =>
      mergeMediaItems(existingItems, items.filter((item) => item.status !== "ignored")),
    );
  }, []);

  const removeMediaItems = useCallback((itemIds: string[]) => {
    const rejectedIds = new Set(itemIds);
    setMediaItems((items) => items.filter((item) => !rejectedIds.has(item.id)));
    setIdentifyItems((items) => items.filter((item) => !rejectedIds.has(item.id)));
  }, []);

  const clearAllMediaState = useCallback(() => {
    setMediaItems([]);
    setIdentifyItems([]);
    setActiveProjectId("");
  }, [setActiveProjectId]);

  const sendToIdentify = useCallback((items: MediaItem[]) => {
    setIdentifyItems((existingItems) => mergeMediaItems(existingItems, items));
    setActiveTab("identify");
  }, []);

  const persistCreationBrief = useCallback(async (
    nextTarget: WizardTarget,
    subjectLabel: string,
    requestedOutputs: WizardTarget[] = [nextTarget],
    mode: "new" | "resume" = "resume",
    trainingTargetProfileIds: Partial<Record<WizardTarget, string>> = {},
  ) => {
    const projects = await engine.listCharacterProjects();
    let project = mode === "resume"
      ? projects.find((candidate) => candidate.id === activeProjectId)
      : undefined;
    const normalizedSubject = subjectLabel.trim()
      || project?.intent.subject_name.trim()
      || (project?.name && project.name !== "Character Dataset" ? project.name : "the subject");
    const normalizedOutputs = Array.from(new Set([nextTarget, ...requestedOutputs]));
    if (!project) {
      const intent: TrainingIntent = {
        target_type: "character",
        subject_name: normalizedSubject,
        requested_outputs: normalizedOutputs,
        training_target_profile_ids: trainingTargetProfileIds,
        trigger_token: "",
        description: "",
        learned_attributes: ["identity", "face", "body"],
        controllable_attributes: ["expression", "pose", "clothing", "environment"],
        excluded_attributes: ["background", "other people", "watermark"],
      };
      const created = await engine.createCharacterProject(
        normalizedSubject === "the subject" ? "Character Dataset" : normalizedSubject,
        intent,
      );
      setActiveProjectId(created.id);
      setWizardTarget(nextTarget);
      return;
    }
    const intent: TrainingIntent = {
      ...project.intent,
      subject_name: normalizedSubject,
      requested_outputs: normalizedOutputs,
      training_target_profile_ids: {
        ...project.intent.training_target_profile_ids,
        ...trainingTargetProfileIds,
      },
    };
    const updated = await engine.updateCharacterProject(project.id, {
      name: normalizedSubject === "the subject" ? project.name : normalizedSubject,
      intent,
    });
    setActiveProjectId(updated.id);
    setWizardTarget(nextTarget);
  }, [activeProjectId, engine, setActiveProjectId, setWizardTarget]);

  useEffect(() => {
    window.localStorage.setItem(wizardTargetStorageKey, wizardTarget);
  }, [wizardTarget]);

  useEffect(() => {
    window.localStorage.setItem(experienceStorageKey, experience);
  }, [experience]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (activeProjectId) window.localStorage.setItem(activeProjectStorageKey, activeProjectId);
    else window.localStorage.removeItem(activeProjectStorageKey);
  }, [activeProjectId]);

  useEffect(() => {
    setLoadedStudioTabs((loadedTabs) => {
      if (loadedTabs.has(activeTab)) return loadedTabs;
      return new Set([...loadedTabs, activeTab]);
    });
  }, [activeTab]);

  useEffect(() => {
    if (!workspaceLoaded) return;
    let ignore = false;
    void engine.listCharacterProjects().then((projects) => {
      if (ignore || !Array.isArray(projects)) return;
      const restored = projects.some((project) => project.id === activeProjectId) ? activeProjectId : projects[0]?.id ?? "";
      if (restored !== activeProjectId) setActiveProjectId(restored);
      const project = projects.find((candidate) => candidate.id === restored);
      const requestedOutput = project?.intent.requested_outputs?.[0];
      if (restored !== activeProjectId && requestedOutput) setWizardTarget(requestedOutput);
    }).catch(() => undefined);
    return () => { ignore = true; };
  }, [engine, activeProjectId, setActiveProjectId, setWizardTarget, workspaceLoaded]);

  useEffect(() => {
    let ignore = false;
    void (async () => {
      try {
        try {
          await engine.listCurationBundles();
        } catch {
          // Bundle discovery is additive; media loading still works with older sidecars.
        }
        await loadVaultMediaProgressively(engine, {
          canceled: () => ignore,
          onFirstPage: (items) => setMediaItems(items),
          onNextPage: addMediaItems,
        });
      } catch {
        return;
      }
    })();
    return () => {
      ignore = true;
    };
  }, [addMediaItems, engine]);

  useEffect(() => {
    let ignore = false;
    setIdentifyItems([]);
    if (!activeProjectId) {
      return () => { ignore = true; };
    }
    void engine.getCurationHandoff(activeProjectId, wizardTarget).then((handoff) => {
      if (ignore || !Array.isArray(handoff.items)) return;
      const handoffIds = new Set(handoff.items.map((item) => item.media_item_id));
      setIdentifyItems(mediaItems.filter((item) => handoffIds.has(item.id)));
    }).catch(() => {
      // Older sidecars may not expose scoped handoff queries yet.
    });
    return () => { ignore = true; };
  }, [activeProjectId, engine, mediaItems, wizardTarget]);

  if (experience === "guided") {
    return (
      <main className="guided-app-shell">
        <header className="guided-app-header">
          <AppBrand onHome={goHome} />
          <div className="guided-header-actions">
            <ModelLibrary engine={engine} />
            <ProjectHome engine={engine} activeProjectId={activeProjectId} onProjectChange={setActiveProjectId} onContinue={continueProjectLane} />
            <JobCenter engine={engine} />
            <details className="workspace-tools">
              <summary><Settings2 size={16} aria-hidden="true" /> Settings & tools</summary>
              <div className="workspace-tools-panel">
                <CredentialVault />
                <SupportDiagnostics engine={engine} activeProjectId={activeProjectId} />
                <AppUpdateControl />
                <ThemePicker theme={theme} onChange={setTheme} syncError={themeSyncError} />
              </div>
            </details>
          </div>
        </header>
        {workspaceSyncError ? <p className="workspace-sync-notice" role="status">{workspaceSyncError}</p> : null}
        <GuidedErrorBoundary
          resetKey={`${activeProjectId}:${workspace.stage}:${guidedNavigation?.token ?? 0}`}
          onBack={goHome}
          onReload={() => window.location.reload()}
          onOpenStudio={() => { setActiveTab("ingest"); setExperience("studio"); }}
        >
          <GuidedExperience
            controlledStage={workspace.stage}
            onStageChange={(stage) => updateWorkspace({ stage })}
            engine={engine}
            mediaItems={mediaItems}
            identifyItems={identifyItems}
            target={wizardTarget}
            theme={theme}
            activeProjectId={activeProjectId}
            navigationRequest={guidedNavigation}
            onTargetChange={setWizardTarget}
            onPersistCreationBrief={persistCreationBrief}
            onMediaItemsImported={addMediaItems}
            onMediaItemsRejected={removeMediaItems}
            onSendToIdentify={sendToIdentify}
            onProjectChange={setActiveProjectId}
            onAllMediaCleared={clearAllMediaState}
            onOpenStudio={(tab) => {
              setActiveTab(tab);
              setExperience("studio");
            }}
          />
        </GuidedErrorBoundary>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <AppBrand onHome={goHome} />
        <WorkflowWizard engine={engine} target={wizardTarget} activeTab={activeTab} mediaItems={mediaItems} activeProjectId={activeProjectId} onProjectChange={setActiveProjectId} onTargetChange={(nextTarget) => void persistCreationBrief(nextTarget, "")} onNavigate={setActiveTab} />
        <div className="studio-mode-actions">
          <ModelLibrary engine={engine} />
          <button type="button" onClick={() => setExperience("guided")}><LayoutGrid size={15} aria-hidden="true" /> Guided Mode</button>
          <ProjectHome engine={engine} activeProjectId={activeProjectId} onProjectChange={setActiveProjectId} onContinue={continueProjectLane} />
          <JobCenter engine={engine} />
          <CredentialVault />
          <SupportDiagnostics engine={engine} activeProjectId={activeProjectId} />
          <AppUpdateControl />
          <ThemePicker theme={theme} onChange={setTheme} syncError={themeSyncError} />
        </div>
        <nav className="workspace-tabs" role="tablist" aria-label="LoraSuite workspace">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const label = workspaceTabLabel(tab, wizardTarget);
            return (
              <button
                key={tab.id}
                role="tab"
                type="button"
                aria-label={label}
                aria-selected={activeTab === tab.id}
                className={activeTab === tab.id ? "tab active" : "tab"}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={17} aria-hidden="true" />
                <strong>{label}</strong>
              </button>
            );
          })}
        </nav>
      </header>

      <section className="workspace-panel" role="tabpanel">
        <div hidden={activeTab !== "ingest"}>
          <DataIngressTab
            key={`${activeProjectId}:${wizardTarget}`}
            activeProjectId={activeProjectId}
            target={wizardTarget}
            engine={engine}
            mediaItems={mediaItems}
            onMediaItemsImported={addMediaItems}
            onAllMediaCleared={clearAllMediaState}
          />
        </div>
        {loadedStudioTabs.has("curate") ? (
          <Suspense fallback={<WorkspaceLoading />}>
            <LazyCurateSearchTab
              key={`${activeProjectId}:${wizardTarget}`}
              mediaItems={preparationItems}
              engine={engine}
              isActive={activeTab === "curate"}
              workflowTarget={wizardTarget}
              activeProjectId={activeProjectId}
              onSendToIdentify={sendToIdentify}
              onMediaItemsGenerated={addMediaItems}
              onMediaItemsRejected={removeMediaItems}
            />
          </Suspense>
        ) : null}
        {activeTab === "identify" ? (
          <Suspense fallback={<WorkspaceLoading />}>
            <LazyIdentifyTab
              mediaItems={identifyItems}
              engine={engine}
              activeProjectId={activeProjectId}
              guidedTarget={wizardTarget}
              onProjectChange={setActiveProjectId}
              onBuildDatasets={() => setActiveTab("train")}
            />
          </Suspense>
        ) : null}
        {activeTab === "train" ? (
          <Suspense fallback={<WorkspaceLoading />}>
            <LazyTrainTab engine={engine} targetItems={identifyItems} initialMode={wizardTarget} activeProjectId={activeProjectId} onProjectChange={setActiveProjectId} />
          </Suspense>
        ) : null}
      </section>
    </main>
  );
}

function AppBrand({ onHome }: { onHome(): void }) {
  return <div className="app-brand"><h1>
    <button className="app-brand-home" type="button" onClick={onHome} aria-label="LoraSuite home" title="Back to project home">
      <span className="app-brand-mark"><Boxes size={20} aria-hidden="true" /></span>
      <span>LoraSuite</span>
    </button>
  </h1></div>;
}

function workspaceTabLabel(
  tab: (typeof tabs)[number],
  target: WizardTarget,
): string {
  if (tab.id === "identify" && target === "voice") return "Verify Speaker";
  return tab.label;
}

function WorkspaceLoading() {
  return <div className="empty-state" role="status">Loading workspace...</div>;
}

export async function loadVaultMediaProgressively(
  engine: ReturnType<typeof createEngineClient>,
  callbacks: {
    canceled(): boolean;
    onFirstPage(items: MediaItem[]): void;
    onNextPage(items: MediaItem[]): void;
  },
): Promise<MediaItem[]> {
  if (!engine.listVaultMediaPage) {
    const items = (await engine.listVaultMedia())
      .filter(isMediaItem)
      .filter((item) => item.status !== "ignored");
    if (!callbacks.canceled()) callbacks.onFirstPage(items);
    return callbacks.canceled() ? [] : items;
  }
  let restarted = false;
  while (!callbacks.canceled()) {
    let snapshot: string | undefined;
    let offset = 0;
    const loaded: MediaItem[] = [];
    try {
      while (!callbacks.canceled()) {
        const page = await engine.listVaultMediaPage({
          offset,
          limit: VAULT_MEDIA_PAGE_SIZE,
          snapshot,
        });
        if (callbacks.canceled()) return [];
        const validItems = page.items.filter(isMediaItem).filter((item) => item.status !== "ignored");
        if (offset === 0) callbacks.onFirstPage(validItems);
        else callbacks.onNextPage(validItems);
        loaded.push(...validItems);
        snapshot = page.snapshot;
        if (!page.has_more || page.next_offset === null) return loaded;
        offset = page.next_offset;
      }
    } catch (error) {
      if (restarted || !isVaultSnapshotConflict(error)) throw error;
      restarted = true;
    }
  }
  return [];
}

function isVaultSnapshotConflict(error: unknown): boolean {
  return error instanceof Error && error.message.includes("Vault media changed");
}

function mergeMediaItems(existingItems: MediaItem[], nextItems: MediaItem[]): MediaItem[] {
  if (nextItems.length === 0) {
    return existingItems;
  }

  const itemsByKey = new Map(existingItems.map((item) => [mediaItemKey(item), item]));
  const keysById = new Map(existingItems.map((item) => [item.id, mediaItemKey(item)]));
  for (const item of nextItems) {
    const key = mediaItemKey(item);
    const previousKey = keysById.get(item.id);
    const existing = previousKey ? itemsByKey.get(previousKey) : itemsByKey.get(key);
    if (previousKey && previousKey !== key) {
      itemsByKey.delete(previousKey);
    }
    itemsByKey.set(
      key,
      existing
        ? {
            ...existing,
            ...item,
            metadata_json: {
              ...existing.metadata_json,
              ...item.metadata_json,
            },
          }
        : item,
    );
    keysById.set(item.id, key);
  }
  return Array.from(itemsByKey.values());
}

function mediaItemKey(item: MediaItem): string {
  return item.raw_path ?? item.id;
}

function isMediaItem(value: unknown): value is MediaItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "media_type" in value &&
    ["image", "video", "audio"].includes(String(value.media_type))
  );
}

export default App;
