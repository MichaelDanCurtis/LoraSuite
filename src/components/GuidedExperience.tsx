import { isRelevantMedia } from "../lib/projectMedia";
import { ProjectMediaLibrary } from "./ProjectMediaLibrary";
import { useProjectMedia } from "../lib/useProjectMedia";
import { DataIngressTab } from "./DataIngressTab";
import { TrainingTargetSelect } from "./TrainingTargetSelect";
import { defaultTrainingTargetProfileIds, targetsForOutput } from "../lib/trainingCatalog";
import {
  PencilLine,
  ScanFace,
  PackageCheck,
  ChartNoAxesCombined,
  ArrowLeft,
  ArrowRight,
  AtSign,
  AudioLines,
  CalendarRange,
  Check,
  CircleAlert,
  CloudCog,
  Combine,
  Download,
  FolderOpen,
  Image,
  Instagram,
  LoaderCircle,
  Music2,
  ScanSearch,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  Video,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import type { WizardTarget, WorkspaceTab } from "./WorkflowWizard";
import { GuidedCopilot } from "./GuidedCopilot";
import type { AppTheme } from "./ThemePicker";
import { WarpedSphereSurface } from "./WarpedSphereSurface";
import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import { acquireSocialMedia } from "../lib/socialAcquisition";
import type {
  IngressCandidate,
  IngressCandidateAnalysis,
  IngressJob,
  InstagramScanMode,
  CharacterProject,
  MediaItem,
  PartnerQualificationReport,
  ProviderReadinessMatrix,
  SourceKind,
  SocialAcquisitionJob,
  TrainingWorkflowStatus,
  TrainingTargetProfile,
} from "../lib/types";

export type GuidedStage = "create" | "sources" | "prepare" | "verify" | "build" | "evaluate";
type GuidedSource = "local" | "instagram" | "x" | "tiktok";
type CreationMode = "new" | "resume";

interface GuidedExperienceProps {
  controlledStage?: GuidedStage;
  onStageChange?(stage: GuidedStage): void;
  engine: EngineClient;
  mediaItems: MediaItem[];
  identifyItems?: MediaItem[];
  target: WizardTarget;
  theme?: AppTheme;
  activeProjectId?: string;
  navigationRequest?: { stage: GuidedStage; target?: WizardTarget; token: number } | null;
  onTargetChange(target: WizardTarget): void;
  onPersistCreationBrief?(
    target: WizardTarget,
    subjectLabel: string,
    requestedOutputs?: WizardTarget[],
    mode?: CreationMode,
    trainingTargetProfileIds?: Partial<Record<WizardTarget, string>>,
  ): Promise<void>;
  onMediaItemsImported(items: MediaItem[]): void;
  onMediaItemsRejected?(itemIds: string[]): void;
  onSendToIdentify?(items: MediaItem[]): void;
  onProjectChange?(projectId: string): void;
  onAllMediaCleared?(): void;
  onOpenStudio(tab: WorkspaceTab): void;
}

interface SourceProgress {
  batches: number;
  imported: number;
}

interface GuidedSourceScope {
  progress: Record<GuidedSource, SourceProgress>;
  drafts: Record<GuidedSource, IntakeDraft>;
  mediaItemIds: string[];
}

interface IntakeDraft {
  url: string;
  browser: string;
  allDates: boolean;
  fromYear: number;
  toYear: number;
  surfaceFilter: InstagramScanMode;
  candidates: IngressCandidate[];
  selectedIds: string[];
  rejectedItemIds: string[];
  confirmedItemIds: string[];
  analysisByCandidateId: Record<string, IngressCandidateAnalysis>;
  analysisComplete: boolean;
  batchNumber: number;
  confirmed: boolean;
  status: string;
  activeAcquisitionJobId?: string;
  retrievalCursor?: string;
  retrievalExhausted: boolean;
  retrievalQueryKey?: string;
}

interface CandidateReviewItem {
  id: string;
  displayName: string;
  candidates: IngressCandidate[];
  imageCandidate?: IngressCandidate;
  videoCandidate?: IngressCandidate;
  audioCandidate?: IngressCandidate;
  thumbnailCandidate: IngressCandidate;
}

const currentYear = new Date().getFullYear();
const earliestYear = 2005;
const guidedRetrievalWindowSize = 100;
const guidedRetrievalPageSize = 100;
const guidedReviewPageSize = 24;
const LazyCurateSearchTab = lazy(() => import("./CurateSearchTab").then((module) => ({ default: module.CurateSearchTab })));
const LazyGuidedAiPrepare = lazy(() =>
  import("./GuidedAiPrepare").then((module) => ({ default: module.GuidedAiPrepare })),
);
const LazyEvaluationWorkspace = lazy(() =>
  import("./EvaluationWorkspace").then((module) => ({ default: module.EvaluationWorkspace })),
);
const LazyIdentifyTab = lazy(() =>
  import("./IdentifyTab").then((module) => ({ default: module.IdentifyTab })),
);
const LazyIdLoraAcceptance = lazy(() =>
  import("./IdLoraAcceptance").then((module) => ({ default: module.IdLoraAcceptance })),
);
const LazyTrainTab = lazy(() =>
  import("./TrainTab").then((module) => ({ default: module.TrainTab })),
);
const LazyVoiceArtifactEvaluator = lazy(() =>
  import("./VoiceArtifactEvaluator").then((module) => ({ default: module.VoiceArtifactEvaluator })),
);

const targetOptions: Array<{
  id: WizardTarget;
  label: string;
  description: string;
  icon: LucideIcon;
  nodeClass: string;
}> = [
  { id: "image", label: "Image LoRA", description: "Place a recognizable subject in new images", icon: Image, nodeClass: "image" },
  { id: "video", label: "Video LoRA", description: "Preserve a subject through motion and time", icon: Video, nodeClass: "video" },
  { id: "voice", label: "Voice", description: "Build a clean, reusable speaking identity", icon: AudioLines, nodeClass: "voice" },
  { id: "id_lora", label: "Living Identity", description: "Connect visual, motion, and voice references", icon: Combine, nodeClass: "identity" },
];

const sourceOptions: Array<{ id: GuidedSource; label: string; detail: string; icon: LucideIcon }> = [
  { id: "local", label: "Local Media", detail: "Files and folders", icon: FolderOpen },
  { id: "instagram", label: "Instagram", detail: "Feed, reels, and tagged", icon: Instagram },
  { id: "x", label: "X / Twitter", detail: "Posts and media", icon: AtSign },
  { id: "tiktok", label: "TikTok", detail: "Videos and posts", icon: Music2 },
];

const targetSphereColors: Record<WizardTarget, readonly [number, number, number]> = {
  image: [91, 201, 232],
  video: [120, 217, 147],
  voice: [228, 184, 95],
  id_lora: [98, 230, 174],
};
const targetSphereColorVariables: Record<WizardTarget, string> = {
  image: "--guided-secondary-rgb",
  video: "--guided-accent-rgb",
  voice: "--guided-warm-rgb",
  id_lora: "--guided-accent-rgb",
};
const sourceSphereColors: Record<GuidedSource, readonly [number, number, number]> = {
  local: [98, 230, 174],
  instagram: [104, 224, 180],
  x: [91, 201, 232],
  tiktok: [125, 224, 197],
};
const sourceSphereColorVariables: Record<GuidedSource, string> = {
  local: "--guided-accent-rgb",
  instagram: "--guided-accent-rgb",
  x: "--guided-secondary-rgb",
  tiktok: "--guided-secondary-rgb",
};

const stageStorageKey = "lorasuite:guided-stage:v2";
const progressStorageKey = "lorasuite:guided-source-progress:v1";
const draftStorageKey = "lorasuite:guided-source-drafts:v1";
const sourceScopesStorageKey = "lorasuite:guided-source-scopes:v2";
const legacyScopeMigrationKey = "lorasuite:guided-source-scope-migration:v2";
const guidedStages: Array<{ id: GuidedStage; label: string; icon: LucideIcon }> = [
  { id: "create", label: "Create", icon: PencilLine },
  { id: "sources", label: "Sources", icon: FolderOpen },
  { id: "prepare", label: "Prepare", icon: Sparkles },
  { id: "verify", label: "Verify", icon: ScanFace },
  { id: "build", label: "Build & Train", icon: PackageCheck },
  { id: "evaluate", label: "Evaluate & Release", icon: ChartNoAxesCombined },
];

export function GuidedExperience({
  controlledStage,
  onStageChange,
  engine,
  mediaItems,
  identifyItems = [],
  target,
  theme = "aurora",
  activeProjectId = "",
  navigationRequest = null,
  onTargetChange,
  onPersistCreationBrief,
  onMediaItemsImported,
  onSendToIdentify,
  onProjectChange,
  onAllMediaCleared,
  onMediaItemsRejected,
  onOpenStudio,
}: GuidedExperienceProps) {
  const [localStage, setLocalStage] = useState<GuidedStage>(() => storedStage());
  const stage = controlledStage ?? localStage;
  function setStage(next: GuidedStage) {
    setLocalStage(next);
    onStageChange?.(next);
  }
  const [activeSource, setActiveSource] = useState<GuidedSource | null>(null);
  const [transitionTarget, setTransitionTarget] = useState<WizardTarget | null>(null);
  const [subjectLabel, setSubjectLabel] = useState("");
  const [creationMode, setCreationMode] = useState<CreationMode>(() => activeProjectId ? "resume" : "new");
  const [resumeProjectId, setResumeProjectId] = useState(activeProjectId);
  const [requestedOutputs, setRequestedOutputs] = useState<WizardTarget[]>(activeProjectId ? [target] : []);
  const [trainingTargetProfileIds, setTrainingTargetProfileIds] = useState<Record<WizardTarget, string>>(
    defaultTrainingTargetProfileIds,
  );
  const [trainingTargets, setTrainingTargets] = useState<TrainingTargetProfile[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [briefStatus, setBriefStatus] = useState("");
  const [sourceScopes, setSourceScopes] = useState<Record<string, GuidedSourceScope>>(
    () => storedSourceScopes(activeProjectId, target),
  );
  const sourceScopeKey = guidedSourceScopeKey(activeProjectId, target);
  const sourceScope = sourceScopes[sourceScopeKey] ?? emptySourceScope();
  const progress = sourceScope.progress;
  const drafts = sourceScope.drafts;
  const [providerReadiness, setProviderReadiness] = useState<ProviderReadinessMatrix | null>(null);
  const [partnerQualification, setPartnerQualification] = useState<PartnerQualificationReport | null>(null);
  const [trainingWorkflow, setTrainingWorkflow] = useState<TrainingWorkflowStatus | null>(null);
  const [workflowError, setWorkflowError] = useState<{ projectId: string; message: string } | null>(null);
  const [providerReadinessStatus, setProviderReadinessStatus] = useState("");
  const [providerReadinessLoading, setProviderReadinessLoading] = useState(false);
  const transitionTimer = useRef<number | null>(null);
  const consumedNavigation = useRef<number | null>(null);
  const explicitCreationMode = useRef(false);

  const projectMedia = useProjectMedia(engine, mediaItems, activeProjectId);
  const [advancedImportOpen, setAdvancedImportOpen] = useState(false);
  const [advancedPrepareOpen, setAdvancedPrepareOpen] = useState(false);
  const relevantMediaItems = useMemo(() => {
    if (!activeProjectId) return mediaItems.filter((item) => isRelevantMedia(item, target));
    const scopedIds = new Set([
      ...sourceScope.mediaItemIds,
      ...projectMedia.items.map((item) => item.id),
      ...identifyItems.map((item) => item.id),
    ]);
    return mediaItems.filter((item) => scopedIds.has(item.id) && isRelevantMedia(item, target));
  }, [activeProjectId, identifyItems, mediaItems, projectMedia.items, sourceScope.mediaItemIds, target]);
  const relevantMediaCount = relevantMediaItems.length;
  const savedPreparationCount = identifyItems.filter((item) => isRelevantMedia(item, target)).length;

  useEffect(() => {
    window.localStorage.setItem(stageStorageKey, stage);
  }, [stage]);

  useEffect(() => {
    if (!navigationRequest || consumedNavigation.current === navigationRequest.token) return;
    consumedNavigation.current = navigationRequest.token;
    if (navigationRequest.target && navigationRequest.target !== target) {
      onTargetChange(navigationRequest.target);
    }
    setStage(navigationRequest.stage);
  }, [navigationRequest, onTargetChange, target]);

  useEffect(() => {
    if (activeProjectId) {
      setResumeProjectId(activeProjectId);
      if (!explicitCreationMode.current) setCreationMode("resume");
    }
    setActiveSource(null);
  }, [activeProjectId]);

  useEffect(() => {
    let ignore = false;
    if (!engine.listTrainingTargets) return;
    void engine.listTrainingTargets().then((targets) => {
      if (!ignore) { setTrainingTargets(targets); setCatalogError(""); }
    }).catch(() => { if (!ignore) setCatalogError("Model recipes could not load. Retry when the engine is available."); });
    return () => { ignore = true; };
  }, [engine, catalogRevision]);

  useEffect(() => {
    if (typeof engine.listCharacterProjects !== "function") return undefined;
    let ignore = false;
    void engine.listCharacterProjects().then((projects) => {
      if (ignore) return;
      setProjects(projects);
      const current = projects.find((project) => project.id === activeProjectId);
      if (current) {
        if (creationMode === "resume" && current.intent.subject_name) {
          setSubjectLabel(current.intent.subject_name);
        }
        if (creationMode === "resume" && current.intent.requested_outputs?.length) {
          setRequestedOutputs(current.intent.requested_outputs);
        }
        if (creationMode === "resume" && current.intent.training_target_profile_ids) {
          setTrainingTargetProfileIds({
            ...defaultTrainingTargetProfileIds,
            ...current.intent.training_target_profile_ids,
          });
        }
      }
    }).catch(() => undefined);
    return () => { ignore = true; };
  }, [activeProjectId, creationMode, engine]);

  useEffect(() => {
    if (!activeProjectId || typeof engine.listIngressJobs !== "function") return;
    let ignore = false;
    void engine.listIngressJobs().then((jobs) => {
      if (ignore) return;
      const importedIds = jobs.filter((job) => job.status === "complete"
        && job.options?.project_id === activeProjectId && job.options?.target === target)
        .flatMap((job) => job.imported_media_items.map((item) => item.id));
      if (!importedIds.length) return;
      setSourceScopes((scopes) => {
        const current = scopes[sourceScopeKey] ?? emptySourceScope();
        return { ...scopes, [sourceScopeKey]: { ...current,
          mediaItemIds: Array.from(new Set([...current.mediaItemIds, ...importedIds])),
        } };
      });
    }).catch(() => undefined);
    return () => { ignore = true; };
  }, [activeProjectId, engine, sourceScopeKey, target]);

  useEffect(() => {
    window.localStorage.setItem(sourceScopesStorageKey, JSON.stringify(sourceScopes));
  }, [sourceScopes]);

  useEffect(() => () => {
    if (transitionTimer.current !== null) window.clearTimeout(transitionTimer.current);
  }, []);

  useEffect(() => {
    if ((stage !== "build" && stage !== "evaluate") || !activeProjectId) {
      setProviderReadiness(null);
      setPartnerQualification(null);
      setProviderReadinessStatus("");
      return;
    }
    void loadProviderReadiness();
  }, [activeProjectId, stage]);

  useEffect(() => {
    if (!activeProjectId) {
      setTrainingWorkflow(null);
      return undefined;
    }
    setWorkflowError(null);
    if (typeof engine.getTrainingWorkflow !== "function") {
      setWorkflowError({ projectId: activeProjectId, message: "Project requirements are unavailable in this engine." });
      return undefined;
    }
    let ignore = false;
    const refresh = () => {
      void engine.getTrainingWorkflow(activeProjectId)
        .then((workflow) => {
          if (!ignore) { setTrainingWorkflow(workflow); setWorkflowError(null); }
        })
        .catch(() => {
          if (!ignore) {
            setTrainingWorkflow(null);
            setWorkflowError({ projectId: activeProjectId, message: "Could not load project requirements. Open Project to check the connection and retry." });
          }
        });
    };
    refresh();
    const interval = window.setInterval(refresh, 10000);
    return () => {
      ignore = true;
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [activeProjectId, engine, stage]);

  async function loadProviderReadiness() {
    if (!activeProjectId || providerReadinessLoading) return;
    setProviderReadinessLoading(true);
    setProviderReadinessStatus("Checking provider readiness...");
    try {
      const matrix = await engine.getProviderReadiness(activeProjectId);
      setProviderReadiness(matrix);
      if (engine.getPartnerQualificationReport) {
        try {
          setPartnerQualification(await engine.getPartnerQualificationReport(activeProjectId));
          setProviderReadinessStatus("");
        } catch (error) {
          setPartnerQualification(null);
          setProviderReadinessStatus(`Qualification report unavailable: ${errorMessage(error)}`);
        }
      } else {
        setPartnerQualification(null);
        setProviderReadinessStatus("");
      }
    } catch (error) {
      setProviderReadiness(null);
      setProviderReadinessStatus(`Provider readiness unavailable: ${errorMessage(error)}`);
    } finally {
      setProviderReadinessLoading(false);
    }
  }

  async function chooseTarget(nextTarget: WizardTarget) {
    if (!targetsForOutput(trainingTargets, nextTarget).some((recipe) => recipe.profile_id === trainingTargetProfileIds[nextTarget])) {
      setBriefStatus("Choose a compatible model recipe before continuing.");
      return;
    }
    if (transitionTimer.current !== null) window.clearTimeout(transitionTimer.current);
    setBriefStatus("Saving creation brief...");
    setTransitionTarget(nextTarget);
    const outputs = Array.from(new Set([nextTarget, ...requestedOutputs]));
    try {
      if (onPersistCreationBrief) {
        await onPersistCreationBrief(
          nextTarget,
          subjectLabel,
          outputs,
          creationMode,
          trainingTargetProfileIds,
        );
      }
      else onTargetChange(nextTarget);
      explicitCreationMode.current = false;
      setCreationMode("resume");
      setBriefStatus("");
      transitionTimer.current = window.setTimeout(() => {
        setStage("sources");
        setTransitionTarget(null);
        transitionTimer.current = null;
      }, 640);
    } catch (error) {
      setBriefStatus(`Could not save the creation brief: ${errorMessage(error)}`);
      setTransitionTarget(null);
    }
  }

  function updateDraft(source: GuidedSource, update: (draft: IntakeDraft) => IntakeDraft) {
    updateSourceScope((current) => ({
      ...current,
      drafts: { ...current.drafts, [source]: update(current.drafts[source]) },
    }));
  }

  function recordImported(source: GuidedSource, items: MediaItem[]) {
    onMediaItemsImported(items);
    updateSourceScope((current) => ({
      ...current,
      mediaItemIds: Array.from(new Set([
        ...current.mediaItemIds,
        ...items.map((item) => item.id),
      ])),
      progress: {
        ...current.progress,
        [source]: {
          batches: current.progress[source].batches + 1,
          imported: current.progress[source].imported + items.length,
        },
      },
    }));
  }

  function resetAllMediaState() {
    const nextDrafts = emptyDrafts();
    if (activeSource) {
      nextDrafts[activeSource] = {
        ...nextDrafts[activeSource],
        status: "All imported media and dependent workspace data were cleared.",
      };
    }
    updateSourceScope(() => ({
      progress: emptyProgress(),
      drafts: nextDrafts,
      mediaItemIds: [],
    }));
    onAllMediaCleared?.();
  }

  function updateSourceScope(update: (current: GuidedSourceScope) => GuidedSourceScope) {
    setSourceScopes((current) => ({
      ...current,
      [sourceScopeKey]: update(current[sourceScopeKey] ?? emptySourceScope()),
    }));
  }

  function chooseCreationMode(mode: CreationMode) {
    explicitCreationMode.current = true;
    setCreationMode(mode);
    if (mode === "new") {
      setSubjectLabel("");
      setRequestedOutputs([target]);
      setTrainingTargetProfileIds(defaultTrainingTargetProfileIds);
      return;
    }
    const project = projects.find((candidate) => candidate.id === resumeProjectId)
      ?? projects.find((candidate) => candidate.id === activeProjectId)
      ?? projects[0];
    if (!project) return;
    applyResumeProject(project);
  }

  function applyResumeProject(project: CharacterProject) {
    setResumeProjectId(project.id);
    if (project.id !== activeProjectId) onProjectChange?.(project.id);
    setSubjectLabel(project.intent.subject_name || project.name);
    setRequestedOutputs(project.intent.requested_outputs?.length ? project.intent.requested_outputs : [target]);
    setTrainingTargetProfileIds({
      ...defaultTrainingTargetProfileIds,
      ...project.intent.training_target_profile_ids,
    });
    const requestedTarget = project.intent.requested_outputs?.[0];
    if (requestedTarget) onTargetChange(requestedTarget);
  }

  function chooseResumeProject(projectId: string) {
    const project = projects.find((candidate) => candidate.id === projectId);
    if (!project) return;
    setCreationMode("resume");
    applyResumeProject(project);
  }

  function toggleRequestedOutput(output: WizardTarget) {
    setRequestedOutputs((current) => current.includes(output)
      ? current.filter((candidate) => candidate !== output)
      : [...current, output]);
  }

  function chooseTrainingTarget(output: WizardTarget, profileId: string) {
    setTrainingTargetProfileIds((current) => ({ ...current, [output]: profileId }));
  }

  function finishPreparation(items: MediaItem[]) {
    onSendToIdentify?.(items);
    setStage("verify");
  }

  function studioTabForStage(): WorkspaceTab {
    if (stage === "prepare") return "curate";
    if (stage === "verify") return "identify";
    if (stage === "build" || stage === "evaluate") return "train";
    return "ingest";
  }

  function canOpenStage(nextStage: GuidedStage): boolean {
    if (nextStage === "prepare") {
      return relevantMediaCount > 0
        || Boolean(workflowLane && workflowLane.target_workspace !== "ingest");
    }
    if (nextStage === "verify") {
      return identifyItems.length > 0
        || Boolean(workflowLane && ["identify", "train"].includes(workflowLane.target_workspace))
        || stage === "verify"
        || stage === "build"
        || stage === "evaluate";
    }
    if (nextStage === "build") {
      return Boolean(
        workflowLane
        && workflowLane.target_workspace === "train"
        && !["curate", "identity"].includes(workflowLane.phase),
      ) || stage === "build" || stage === "evaluate";
    }
    if (nextStage === "evaluate") return evaluationReady || stage === "evaluate";
    return true;
  }

  function stageBlocker(nextStage: GuidedStage): string | undefined {
    if (canOpenStage(nextStage)) return undefined;
    if (nextStage === "prepare") return "Add source media to this project and output lane first.";
    if (nextStage === "verify") return workflowLane?.blockers[0] ?? "Prepare this project's media first.";
    if (nextStage === "build") return workflowLane?.blockers[0] ?? "Complete identity verification first.";
    if (nextStage === "evaluate") return "A trained or generated output is required before evaluation.";
    return undefined;
  }

  const currentWorkflow = trainingWorkflow?.project_id === activeProjectId ? trainingWorkflow : null;
  const workflowLane = currentWorkflow?.lanes.find((lane) => lane.id === target) ?? null;
  const evaluationLane = currentWorkflow?.lanes.find((lane) => lane.id === "evaluate") ?? null;
  const currentReadiness = providerReadiness?.project_id === activeProjectId ? providerReadiness : null;
  const buildItems = currentReadiness?.items.filter((item) => item.lane === guidedReadinessLane(target)) ?? [];
  const evaluationReady = (
    target === "voice"
      ? Boolean(workflowLane && ["evaluate", "select", "selected"].includes(workflowLane.phase))
      : target === "id_lora"
        ? Boolean(workflowLane && ["evaluate", "certification", "certified", "review"].includes(workflowLane.phase))
        : Boolean(evaluationLane && evaluationLane.phase !== "artifact")
  ) || buildItems.some(
    (item) => item.state === "outputs_ready" || item.state === "complete" || item.release_selected,
  );
  const guidedBuildMode = target === "id_lora" && workflowLane?.target_mode === "video"
    ? "video"
    : target;
  const targetLabel = targetOptions.find((option) => option.id === target)?.label ?? "LoRA";
  const selectedTargetProfileId = trainingTargetProfileIds[target];
  const copilotAction = stage === "create"
    ? null
    : stage === "sources"
      ? relevantMediaCount > 0
        ? { label: `Prepare ${relevantMediaCount}`, onClick: () => setStage("prepare" as GuidedStage) }
        : { label: "Add local media", onClick: () => setActiveSource("local" as GuidedSource) }
      : stage === "verify" && identifyItems.length === 0
        ? { label: "Return to Prepare", onClick: () => setStage("prepare" as GuidedStage) }
        : stage === "build" && !activeProjectId
          ? { label: "Return to Verify", onClick: () => setStage("verify" as GuidedStage) }
          : stage === "evaluate" && !evaluationReady
            ? { label: "Open Build & Train", onClick: () => setStage("build" as GuidedStage) }
            : null;

  const currentProject = projects.find((project) => project.id === activeProjectId);
  const workflowDestination: GuidedStage = workflowLane?.target_workspace === "ingest" ? "sources"
    : workflowLane?.target_workspace === "curate" ? "prepare"
    : workflowLane?.target_workspace === "identify" ? "verify" : "build";
  const nextAction = stage === "create" && creationMode === "new" ? null
    : workflowLane && workflowDestination !== stage && canOpenStage(workflowDestination)
      ? { label: workflowLane.action_label, onClick: () => setStage(workflowDestination) }
      : copilotAction;
  const currentStep = guidedStages.find((step) => step.id === stage)!;
  const nextRequirement = workflowLane?.blockers[0]
    ?? (activeProjectId && !currentWorkflow
      ? workflowError?.projectId === activeProjectId ? workflowError.message : "Checking project requirements…"
      : null)
    ?? (stage === "sources" && !relevantMediaCount ? "Add files or choose a source to begin."
      : stage === "build" && !evaluationReady ? "A trained or generated output is required before evaluation."
        : stage === "create" ? "Choose your outputs and a starting workflow below."
          : "Complete the review in this step to continue.");

  return (
    <section className="guided-experience guided-focused">
      <section className="guided-work-context" aria-label="Current project and next step">
        <div className="guided-context-project">
          <small>{creationMode === "new" && stage === "create" ? "NEW PROJECT" : "YOUR PROJECT"}</small>
          <strong>{creationMode === "new" && stage === "create" ? "A new creation" : currentProject?.intent.subject_name || currentProject?.name || currentWorkflow?.project_name || (activeProjectId ? "Selected project" : "New project")}</strong>
          <span>{stage === "create" ? "Choose an output and model recipe" : targetsForOutput(trainingTargets, target).find((recipe) => recipe.profile_id === selectedTargetProfileId)?.label ?? "Choose a compatible model recipe"}</span>
        </div>
        <div className="guided-context-next">
          <small>STEP {guidedStages.findIndex((step) => step.id === stage) + 1} OF {guidedStages.length} · {guidedStageLabel(currentStep, target, selectedTargetProfileId)}</small>
          <p>{nextRequirement}</p>
        </div>
        {nextAction ? <button type="button" className="primary-action" onClick={nextAction.onClick}>{nextAction.label}<ArrowRight size={15} aria-hidden="true" /></button> : null}
      </section>
      <nav className="guided-journey" aria-label="Guided creation steps">
        {guidedStages.map((journeyStage, index) => {
          const StageIcon = journeyStage.icon;
          return (
          <div className="guided-journey-step" key={journeyStage.id}>
            {index > 0 ? <i aria-hidden="true" /> : null}
            <button
              type="button"
              aria-label={guidedStageLabel(journeyStage, target, selectedTargetProfileId)}
              aria-current={stage === journeyStage.id ? "step" : undefined}
              className={stage === journeyStage.id ? "active" : ""}
              disabled={!canOpenStage(journeyStage.id)}
              title={stageBlocker(journeyStage.id)}
              onClick={() => setStage(journeyStage.id)}
            >
              <span className="guided-step-icon"><StageIcon size={20} aria-hidden="true" /></span>
              <span className="guided-step-copy"><small>STEP {String(index + 1).padStart(2, "0")}</small><strong>{guidedStageLabel(journeyStage, target, selectedTargetProfileId)}</strong></span>
            </button>
          </div>
        ); })}
      </nav>

      <div className={`guided-stage guided-stage-${stage}`} key={stage}>
        <Suspense fallback={<div className="empty-state" role="status">Loading workspace...</div>}>
        {stage === "create" ? (
          <CreationGraph
            target={target}
            trainingTargets={trainingTargets}
            catalogError={catalogError}
            onRetryCatalog={() => setCatalogRevision((value) => value + 1)}
            transitionTarget={transitionTarget}
            subjectLabel={subjectLabel}
            creationMode={creationMode}
            requestedOutputs={requestedOutputs}
            trainingTargetProfileIds={trainingTargetProfileIds}
            projects={projects}
            resumeProjectId={resumeProjectId}
            canResume={projects.length > 0}
            status={briefStatus}
            onSubjectLabelChange={setSubjectLabel}
            onCreationModeChange={chooseCreationMode}
            onResumeProjectChange={chooseResumeProject}
            onToggleOutput={toggleRequestedOutput}
            onTrainingTargetChange={chooseTrainingTarget}
            onChoose={(nextTarget) => void chooseTarget(nextTarget)}
          />
        ) : stage === "sources" ? (
          <>
          <SourceGraph
            target={target}
            progress={progress}
            relevantMediaCount={relevantMediaCount}
            onBack={() => setStage("create")}
            onOpenSource={setActiveSource}
            onPrepare={() => setStage("prepare")}
          />
          <ProjectMediaLibrary items={projectMedia.items} assetUrl={engine.assetUrl} loading={projectMedia.loading} error={projectMedia.error} />
          <details className="guided-advanced-options" onToggle={(event) => setAdvancedImportOpen(event.currentTarget.open)}>
            <summary>Advanced import options</summary>
            {advancedImportOpen ? <DataIngressTab key={`${activeProjectId}:${target}`} engine={engine} activeProjectId={activeProjectId} target={target} mediaItems={mediaItems} onMediaItemsImported={onMediaItemsImported} onAllMediaCleared={onAllMediaCleared} /> : null}
          </details>
          </>
        ) : stage === "prepare" ? (
          <GuidedWorkspaceStage step="3 of 6" title={guidedPrepareCopy(target).title} description={guidedPrepareCopy(target).description} onBack={() => setStage("sources")} atmosphere>
            {savedPreparationCount > 0 ? (
              <aside className="guided-saved-preparation" aria-label="Saved preparation">
                <div><strong>Your saved collection is available</strong><p>Continue reviewing {savedPreparationCount} saved items, or run a new preparation pass below.</p></div>
                <button type="button" onClick={() => setStage("verify")}>Continue to Verify</button>
              </aside>
            ) : null}
            {!advancedPrepareOpen ? <LazyGuidedAiPrepare
              mediaItems={relevantMediaItems}
              engine={engine}
              target={target}
              activeProjectId={activeProjectId}
              onComplete={finishPreparation}
              onMediaItemsGenerated={onMediaItemsImported}
            /> : null}
            <details className="guided-advanced-options" onToggle={(event) => setAdvancedPrepareOpen(event.currentTarget.open)}>
              <summary>Advanced preparation options</summary>
              {advancedPrepareOpen ? <LazyCurateSearchTab key={`${activeProjectId}:${target}`} engine={engine} mediaItems={relevantMediaItems} workflowTarget={target} activeProjectId={activeProjectId} onSendToIdentify={finishPreparation} onMediaItemsGenerated={onMediaItemsImported} onMediaItemsRejected={onMediaItemsRejected} /> : null}
            </details>
          </GuidedWorkspaceStage>
        ) : stage === "verify" ? (
          <GuidedWorkspaceStage step="4 of 6" title={guidedVerifyCopy(target).title} description={guidedVerifyCopy(target).description} onBack={() => setStage("prepare")} atmosphere>
            <LazyIdentifyTab
              mediaItems={identifyItems}
              engine={engine}
              activeProjectId={activeProjectId}
              guided
              guidedTarget={target}
              onProjectChange={onProjectChange}
              onBuildDatasets={() => setStage("build")}
            />
          </GuidedWorkspaceStage>
        ) : stage === "build" ? (
          <GuidedWorkspaceStage
            step="5 of 6"
            title={guidedBuildCopy(target, selectedTargetProfileId).title}
            description={guidedBuildCopy(target, selectedTargetProfileId).description}
            onBack={() => setStage("verify")}
            nextAction={{
              label: evaluationReady ? "Evaluate result" : "Waiting for trained result",
              onClick: () => setStage("evaluate"),
              disabled: !evaluationReady,
              title: evaluationReady ? "Open the evaluation stage" : "A provider output is required before evaluation",
            }}
            atmosphere
          >
            {workflowLane ? (
              <GuidedWorkflowEvidence workflow={currentWorkflow} target={target} />
            ) : null}
            <GuidedProviderReadiness
              matrix={currentReadiness}
              report={partnerQualification?.project_id === activeProjectId ? partnerQualification : null}
              target={target}
              loading={providerReadinessLoading}
              status={providerReadinessStatus}
              onRefresh={() => void loadProviderReadiness()}
            />
            <LazyTrainTab
              engine={engine}
              targetItems={identifyItems}
              initialMode={guidedBuildMode}
              activeProjectId={activeProjectId}
              guided
              onProjectChange={onProjectChange}
              onReturnToPrepare={() => setStage("prepare")}
              onReturnToVerify={() => setStage("verify")}
            />
          </GuidedWorkspaceStage>
        ) : (
          <GuidedWorkspaceStage
            step="6 of 6"
            title={guidedEvaluationCopy(target).title}
            description={guidedEvaluationCopy(target).description}
            onBack={() => setStage("build")}
            atmosphere
          >
            <GuidedEvaluationStage
              engine={engine}
              target={target}
              activeProjectId={activeProjectId}
              onProjectChange={onProjectChange}
              onOpenRevision={() => setStage("build")}
            />
          </GuidedWorkspaceStage>
        )}
        </Suspense>
      </div>

      {activeSource ? (
        <SourceIntakeWindow
          key={sourceScopeKey}
          source={activeSource}
          savedItems={projectMedia.items}
          activeProjectId={activeProjectId}
          target={target}
          engine={engine}
          draft={drafts[activeSource]}
          progress={progress[activeSource]}
          onChange={(update) => updateDraft(activeSource, update)}
          onClose={() => setActiveSource(null)}
          onImported={(items) => recordImported(activeSource, items)}
          onAllMediaCleared={resetAllMediaState}
        />
      ) : null}

      <footer className="guided-utility-bar" aria-label="Workspace tools">
      <button
        className="guided-studio-shortcut"
        type="button"
        onClick={() => onOpenStudio(studioTabForStage())}
        title="Open the advanced workspace consoles"
      >
        <SlidersHorizontal size={17} aria-hidden="true" /> Advanced Consoles
      </button>
      {!activeSource ? (
        <GuidedCopilot
          stage={stage}
          target={target}
          relevantMediaCount={relevantMediaCount}
          identifyItemCount={identifyItems.length}
          hasProject={Boolean(activeProjectId)}
          evaluationReady={evaluationReady}
          action={copilotAction}
        />
      ) : null}
      </footer>
    </section>
  );
}

function GuidedWorkflowEvidence({
  workflow,
  target,
}: {
  workflow: TrainingWorkflowStatus | null;
  target: WizardTarget;
}) {
  const lane = workflow?.lanes.find((candidate) => candidate.id === target);
  if (!lane) return null;
  return (
    <section className={`guided-workflow-evidence ${lane.state}`} aria-label="Guided workflow readiness">
      <span>
        {lane.state === "blocked"
          ? <CircleAlert size={16} aria-hidden="true" />
          : <Check size={16} aria-hidden="true" />}
        <span>
          <small>{lane.label} · {lane.phase.replaceAll("_", " ")}</small>
          <strong>{lane.action_label}</strong>
        </span>
      </span>
      <p>{lane.summary}</p>
      {lane.blockers[0] ? <em>{lane.blockers[0]}</em> : lane.warnings[0] ? <em>{lane.warnings[0]}</em> : null}
    </section>
  );
}

export function GuidedProviderReadiness({
  matrix,
  report,
  target,
  loading,
  status,
  onRefresh,
}: {
  matrix: ProviderReadinessMatrix | null;
  report?: PartnerQualificationReport | null;
  target: WizardTarget;
  loading: boolean;
  status: string;
  onRefresh(): void;
}) {
  const lane = guidedReadinessLane(target);
  const items = matrix?.items.filter((item) => item.lane === lane) ?? [];
  const qualificationLanes = report?.lanes.filter((item) => item.lane === lane) ?? [];
  const qualificationByPartner = new Map(
    qualificationLanes.map((item) => [item.partner, item]),
  );
  const comfyQualification = qualificationByPartner.get("comfyui");
  return (
    <section className="guided-provider-readiness" aria-label="Guided provider readiness">
      <header>
        <span><CloudCog size={16} aria-hidden="true" /><strong>Provider path</strong></span>
        <em>{report ? `${report.passed_count} / ${report.total_count} qualification gates` : items.some((item) => item.state === "outputs_ready" || item.state === "complete" || item.release_selected) ? "Output ready" : items.length ? "Next action required" : "Checking"}</em>
        <button type="button" title="Refresh provider readiness" onClick={onRefresh} disabled={loading}>
          <LoaderCircle className={loading ? "spin" : ""} size={14} aria-hidden="true" />
        </button>
      </header>
      {items.length || comfyQualification ? (
        <div>
          {items.map((item) => {
            const qualification = qualificationByPartner.get(item.provider);
            return (
              <article className={item.state} key={`${item.provider}:${item.profile_id}`}>
                <span>
                  <strong>{item.provider === "runcomfy" ? "RunComfy" : "RunPod"}</strong>
                  <small>{item.summary}</small>
                </span>
                <span>
                  <strong>{item.action_label}</strong>
                  <small>{qualification ? `${qualification.passed_count} / ${qualification.total_count} qualification gates` : item.blockers[0] ?? item.warnings[0] ?? item.state.replaceAll("_", " ")}</small>
                </span>
                {item.blockers.length ? <CircleAlert size={14} aria-label="Blocked" /> : <Check size={14} aria-label="Ready" />}
              </article>
            );
          })}
          {comfyQualification ? (
            <article className={comfyQualification.status} key={`comfyui:${lane}`}>
              <span>
                <strong>ComfyUI</strong>
                <small>{comfyQualification.checks.find((check) => check.status !== "passed")?.detail ?? "ComfyUI delivery and evaluation are qualified."}</small>
              </span>
              <span>
                <strong>{comfyQualification.checks.find((check) => check.status !== "passed")?.action ?? "Qualification complete"}</strong>
                <small>{comfyQualification.passed_count} / {comfyQualification.total_count} qualification gates</small>
              </span>
              {comfyQualification.status === "blocked" ? <CircleAlert size={14} aria-label="Blocked" /> : <Check size={14} aria-label="Ready" />}
            </article>
          ) : null}
        </div>
      ) : (
        <p>{status || "Choose or create a verified identity project to inspect its provider path."}</p>
      )}
    </section>
  );
}

function GuidedEvaluationStage({
  engine,
  target,
  activeProjectId,
  onProjectChange,
  onOpenRevision,
}: {
  engine: EngineClient;
  target: WizardTarget;
  activeProjectId: string;
  onProjectChange?(projectId: string): void;
  onOpenRevision(): void;
}) {
  if (target === "voice") {
    return <LazyVoiceArtifactEvaluator engine={engine} projectId={activeProjectId} />;
  }
  if (target === "id_lora") {
    return <LazyIdLoraAcceptance engine={engine} projectId={activeProjectId} />;
  }
  return (
    <LazyEvaluationWorkspace
      engine={engine}
      activeProjectId={activeProjectId}
      initialMode={target === "image" ? "image" : "audio_visual"}
      onProjectChange={onProjectChange}
      onOpenRevision={onOpenRevision}
    />
  );
}

function guidedEvaluationCopy(target: WizardTarget): { title: string; description: string } {
  if (target === "voice") {
    return {
      title: "Evaluate the trained voice",
      description: "Compare speaker identity, transcript accuracy, and signal quality, then select the release checkpoint.",
    };
  }
  if (target === "id_lora") {
    return {
      title: "Evaluate the living identity",
      description: "Check face, voice, transcript, motion, and synchronization before accepting the audio-visual result.",
    };
  }
  if (target === "video") {
    return {
      title: "Evaluate and improve the video LoRA",
      description: "Run matched clips, verify identity and temporal stability, then turn measured weaknesses into the next revision.",
    };
  }
  return {
    title: "Evaluate and improve the image LoRA",
    description: "Run matched images, select a release, and turn measured weaknesses into the next revision.",
  };
}

function guidedPrepareCopy(target: WizardTarget): { title: string; description: string } {
  return {
    title: "Prepare with AI",
    description: `Run one automatic ${target === "id_lora" ? "identity" : target} pass, then review only the decisions that need you.`,
  };
}

function guidedVerifyCopy(target: WizardTarget): { title: string; description: string } {
  if (target === "voice") {
    return {
      title: "Check the voice",
      description: "LoraSuite compares the clips for you. Confirm the speaker, then continue.",
    };
  }
  if (target === "id_lora") {
    return {
      title: "Check the identity",
      description: "Confirm that the photos, motion, and voice all belong to the same person.",
    };
  }
  return {
    title: "Check the identity",
    description: target === "video"
      ? "Confirm the person and motion clips, then continue."
      : "LoraSuite matched the photos for you. Check its references, then continue.",
  };
}

function guidedBuildCopy(target: WizardTarget, targetProfileId?: string): { title: string; description: string } {
  if (target === "video" && targetProfileId === "comfyui_minimax_h3_ref2va") {
    return {
      title: "Package MiniMax H3 references",
      description: "Review your ordered image, motion, and voice references, then export the package for use in ComfyUI. This reference workflow does not train an H3 LoRA.",
    };
  }
  if (target === "voice") {
    return {
      title: "Create samples and train the voice",
      description: "Transcribe verified tracks, create timestamped speech samples, review the quality gate, then submit the frozen voice dataset.",
    };
  }
  if (target === "id_lora") {
    return {
      title: "Package and run the synchronized identity",
      description: "Compile visual, motion, voice, and transcript references, then run the pre-trained zero-shot identity adapter.",
    };
  }
  return {
    title: "Build your LoRA",
    description: "Choose where it should work. LoraSuite will prepare the package and lead you through training.",
  };
}

function guidedReadinessLane(target: WizardTarget): "image" | "video" | "voice" | "id_lora" {
  return target;
}

function guidedStageLabel(stage: { id: GuidedStage; label: string }, target: WizardTarget, targetProfileId?: string): string {
  return stage.id === "build" && (
    target === "id_lora" || targetProfileId === "comfyui_minimax_h3_ref2va"
  ) ? "Package & Run" : stage.label;
}

function guidedUpdatedLabel(value: string): string {
  const updatedAt = new Date(value);
  if (Number.isNaN(updatedAt.getTime())) return "Update date unavailable";
  return `Updated ${updatedAt.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;
}

function CreationGraph({
  trainingTargets, catalogError, onRetryCatalog,
  target,
  transitionTarget,
  subjectLabel,
  creationMode,
  requestedOutputs,
  trainingTargetProfileIds,
  projects,
  resumeProjectId,
  canResume,
  status,
  onSubjectLabelChange,
  onCreationModeChange,
  onResumeProjectChange,
  onToggleOutput,
  onTrainingTargetChange,
  onChoose,
}: {
  trainingTargets: TrainingTargetProfile[];
  catalogError: string;
  onRetryCatalog(): void;
  target: WizardTarget;
  transitionTarget: WizardTarget | null;
  subjectLabel: string;
  creationMode: CreationMode;
  requestedOutputs: WizardTarget[];
  trainingTargetProfileIds: Record<WizardTarget, string>;
  projects: CharacterProject[];
  resumeProjectId: string;
  canResume: boolean;
  status: string;
  onSubjectLabelChange(value: string): void;
  onCreationModeChange(mode: CreationMode): void;
  onResumeProjectChange(projectId: string): void;
  onToggleOutput(target: WizardTarget): void;
  onTrainingTargetChange(target: WizardTarget, profileId: string): void;
  onChoose(target: WizardTarget): void;
}) {
  const [startTarget, setStartTarget] = useState(target);
  useEffect(() => setStartTarget(target), [target]);
  const resumeProject = projects.find((project) => project.id === resumeProjectId) ?? projects[0];
  const resumeOutputs = resumeProject?.intent.requested_outputs?.length
    ? resumeProject.intent.requested_outputs
    : [];

  return (
    <div className="guided-create-screen">
      <header className="guided-heading">
        <small><Sparkles size={13} aria-hidden="true" /> {creationMode === "new" ? "New creation" : "Resume creation"}</small>
        <h2>What do you want to create?</h2>
        <p>Prepare a dataset, train a LoRA, and evaluate it in ComfyUI.</p>
        <div className="guided-creation-mode" role="group" aria-label="Creation project">
          <button
            type="button"
            aria-pressed={creationMode === "new"}
            className={creationMode === "new" ? "active" : ""}
            onClick={() => onCreationModeChange("new")}
          >
            New project
          </button>
          <button
            type="button"
            aria-pressed={creationMode === "resume"}
            className={creationMode === "resume" ? "active" : ""}
            disabled={!canResume}
            onClick={() => onCreationModeChange("resume")}
          >
            Resume project
          </button>
        </div>
        {creationMode === "resume" && resumeProject ? (
          <div className="guided-resume-picker">
            <label>
              <span>Project to resume</span>
              <select
                aria-label="Project to resume"
                value={resumeProject.id}
                onChange={(event) => onResumeProjectChange(event.target.value)}
              >
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{projectOptionLabel(project)}</option>
                ))}
              </select>
            </label>
            <div className="guided-resume-summary" aria-live="polite">
              <strong>{resumeProject.intent.subject_name || resumeProject.name}</strong>
              <span>
                {resumeOutputs.length
                  ? resumeOutputs.map((output) => targetOptions.find((option) => option.id === output)?.label ?? output).join(" · ")
                  : "Output not selected yet"}
              </span>
              <small>
                {resumeProject.health.accepted_count} accepted source{resumeProject.health.accepted_count === 1 ? "" : "s"}
                {" · "}
                {guidedUpdatedLabel(resumeProject.updated_at)}
              </small>
            </div>
          </div>
        ) : null}
        <label className="guided-subject-label">
          <span>Who or what is this identity for?</span>
          <input
            value={subjectLabel}
            onChange={(event) => onSubjectLabelChange(event.target.value)}
            placeholder="Subject name or label"
          />
        </label>
        <label className="guided-start-target">
          <span>Start with</span>
          <select aria-label="Start with" value={startTarget} onChange={(event) => setStartTarget(event.target.value as WizardTarget)}>
            {targetOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label>
        <label className="guided-start-target">
          <span>Model recipe</span>
          <TrainingTargetSelect targets={trainingTargets} output={startTarget} value={trainingTargetProfileIds[startTarget]} onChange={(value) => onTrainingTargetChange(startTarget, value)} />
        </label>
        <details className="guided-extra-outputs">
          <summary>Additional outputs and recipes</summary>
        <fieldset className="guided-output-brief">
          <legend>Requested outputs</legend>
          {targetOptions.map((option) => (
            <div className={requestedOutputs.includes(option.id) ? "selected" : ""} key={option.id}>
              <label>
                <input
                  type="checkbox"
                  checked={option.id === startTarget || requestedOutputs.includes(option.id)}
                  disabled={option.id === startTarget}
                  onChange={() => onToggleOutput(option.id)}
                />
                <span>{option.label}</span>
              </label>
              <TrainingTargetSelect targets={trainingTargets} output={option.id} label={`${option.label} training recipe`}
                value={trainingTargetProfileIds[option.id]} disabled={option.id !== startTarget && !requestedOutputs.includes(option.id)}
                onChange={(value) => onTrainingTargetChange(option.id, value)} />
            </div>
          ))}
        </fieldset>
        </details>
        {catalogError ? <p role="alert">{catalogError} <button type="button" onClick={onRetryCatalog}>Retry model recipes</button></p> : null}
        {status ? <small role="status">{status}</small> : null}
      </header>
      <div className="guided-start-action">
        <p>{targetOptions.find((option) => option.id === startTarget)?.description}</p>
        <button type="button" className="primary-action" disabled={transitionTarget !== null} onClick={() => onChoose(startTarget)}>
          {transitionTarget ? "Saving project…" : "Continue to sources"}<ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function SourceGraph({ target, progress, relevantMediaCount, onBack, onOpenSource, onPrepare }: {
  target: WizardTarget;
  progress: Record<GuidedSource, SourceProgress>;
  relevantMediaCount: number;
  onBack(): void;
  onOpenSource(source: GuidedSource): void;
  onPrepare(): void;
}) {
  const targetOption = targetOptions.find((option) => option.id === target) ?? targetOptions[0];
  const TargetIcon = targetOption.icon;
  const connectedSources = sourceOptions.filter((source) => progress[source.id].batches > 0).length;
  return (
    <div className="guided-source-screen">
      <header className="guided-heading">
        <button className="guided-back" type="button" title="Back to creation type" onClick={onBack}><ArrowLeft size={16} /></button>
        <small>Step 2 · {targetOption.label}</small>
        <h2>Give me everything you have</h2>
        <p>{relevantMediaCount ? `${relevantMediaCount} items are already available. Browse your saved media below, add more sources, or continue to Prepare.` : "Open a source, approve each batch, then prepare the finished collection."}</p>
      </header>
      <div className="source-constellation">
        <GraphFilaments variant="sources" />
        <GraphParticles />
        {sourceOptions.map((source, index) => {
          const Icon = source.icon;
          const sourceProgress = progress[source.id];
          const connected = sourceProgress.batches > 0;
          return (
            <button
              key={source.id}
              type="button"
              className={`guided-node source-node source-${index + 1} ${connected ? "selected" : ""}`}
              aria-label={`Open ${source.label} intake`}
              onClick={() => onOpenSource(source.id)}
            >
              <WarpedSphereSurface color={sourceSphereColors[source.id]} colorVariable={sourceSphereColorVariables[source.id]} phase={index * 0.71 + 0.4} />
              <span className="node-icon"><Icon size={26} aria-hidden="true" /></span>
              <strong>{source.label}</strong>
              <small>{connected ? `${sourceProgress.imported} approved · ${sourceProgress.batches} batch${sourceProgress.batches === 1 ? "" : "es"}` : source.detail}</small>
              {connected ? <i className="source-check"><Check size={13} /></i> : null}
              <i className="source-open"><ArrowRight size={13} /></i>
            </button>
          );
        })}
        <button
          type="button"
          className="guided-node source-target"
          aria-label={`Prepare ${targetOption.label}`}
          disabled={relevantMediaCount === 0}
          onClick={onPrepare}
        >
          <WarpedSphereSurface color={targetSphereColors[target]} colorVariable={targetSphereColorVariables[target]} phase={2.3} />
          <TargetIcon size={30} aria-hidden="true" />
          <strong>{targetOption.label}</strong>
          <span>{relevantMediaCount ? `${relevantMediaCount} ready to curate` : connectedSources ? "Finishing imports" : "Add a source"}</span>
          {relevantMediaCount ? <i className="node-action"><ArrowRight size={14} /></i> : null}
        </button>
      </div>
    </div>
  );
}

function GuidedWorkspaceStage({ step, title, description, onBack, nextAction, children, atmosphere = false }: {
  step: string;
  title: string;
  description: string;
  onBack(): void;
  nextAction?: { label: string; onClick(): void; disabled?: boolean; title?: string };
  children: ReactNode;
  atmosphere?: boolean;
}) {
  return (
    <div className={atmosphere ? "guided-workspace-stage atmospheric" : "guided-workspace-stage"}>
      {atmosphere ? <div className="guided-workspace-atmosphere"><GraphFilaments variant="sources" /><GraphParticles /></div> : null}
      <header className="guided-workspace-heading">
        <button className="guided-back" type="button" title="Previous guided step" onClick={onBack}><ArrowLeft size={16} /></button>
        <span><small>{step}</small><h2>{title}</h2><p>{description}</p></span>
        {nextAction ? <button className="guided-stage-forward" type="button" onClick={nextAction.onClick} disabled={nextAction.disabled} title={nextAction.title}>{nextAction.label}<ArrowRight size={15} /></button> : null}
      </header>
      <div className="guided-workspace-canvas">{children}</div>
    </div>
  );
}

function SourceIntakeWindow({ source, target, activeProjectId, savedItems, engine, draft, progress, onChange, onClose, onImported, onAllMediaCleared }: {
  source: GuidedSource;
  target: WizardTarget;
  savedItems: MediaItem[];
  activeProjectId: string;
  engine: EngineClient;
  draft: IntakeDraft;
  progress: SourceProgress;
  onChange(update: (draft: IntakeDraft) => IntakeDraft): void;
  onClose(): void;
  onImported(items: MediaItem[]): void;
  onAllMediaCleared(): void;
}) {
  const [busy, setBusy] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  const [activeAcquisitionJob, setActiveAcquisitionJob] = useState<SocialAcquisitionJob | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [confirmingClearAll, setConfirmingClearAll] = useState(false);
  const [reviewPage, setReviewPage] = useState(0);
  const retrievalRunRef = useRef<symbol | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const sourceOption = sourceOptions.find((option) => option.id === source) ?? sourceOptions[0];
  const SourceIcon = sourceOption.icon;
  const reviewItems = useMemo(() => buildReviewItems(draft.candidates), [draft.candidates]);
  const confirmedItemIds = useMemo(() => new Set(draft.confirmedItemIds ?? []), [draft.confirmedItemIds]);
  const pendingReviewItems = useMemo(
    () => reviewItems.filter((item) => !confirmedItemIds.has(item.id)),
    [confirmedItemIds, reviewItems],
  );
  const aiCandidateCount = useMemo(
    () => pendingReviewItems.reduce(
      (count, item) => count + item.candidates.filter((candidate) => candidateFitsTarget(candidate, target)).length,
      0,
    ),
    [pendingReviewItems, target],
  );
  const retrievalComplete = draft.retrievalExhausted;
  const retrieveLabel = retrievalComplete
    ? "Retrieval complete"
    : reviewItems.length
      ? "Retrieve next 100"
      : "Retrieve first 100";
  const filteredReviewItems = useMemo(
    () => reviewItems
      .filter((item) => (
        !confirmedItemIds.has(item.id) &&
        !draft.rejectedItemIds.includes(item.id) &&
        (source !== "instagram" || draft.surfaceFilter === "all" || reviewItemScanSurfaces(item).has(draft.surfaceFilter))
      ))
      .sort((left, right) => {
        if (!draft.analysisComplete) return 0;
        const leftAnalysis = reviewItemAiSummary(left, draft.analysisByCandidateId, target);
        const rightAnalysis = reviewItemAiSummary(right, draft.analysisByCandidateId, target);
        const recommendationDifference = recommendationPriority(rightAnalysis) - recommendationPriority(leftAnalysis);
        if (recommendationDifference) return recommendationDifference;
        return (rightAnalysis?.confidence ?? -1) - (leftAnalysis?.confidence ?? -1);
      }),
    [confirmedItemIds, draft.analysisByCandidateId, draft.analysisComplete, draft.rejectedItemIds, draft.surfaceFilter, reviewItems, source, target],
  );
  const reviewPageCount = Math.max(1, Math.ceil(filteredReviewItems.length / guidedReviewPageSize));
  const visibleReviewItems = useMemo(
    () => filteredReviewItems.slice(reviewPage * guidedReviewPageSize, (reviewPage + 1) * guidedReviewPageSize),
    [filteredReviewItems, reviewPage],
  );
  const surfaceCounts = useMemo(() => instagramSurfaceCounts(pendingReviewItems), [pendingReviewItems]);
  const selectedIds = useMemo(() => new Set(draft.selectedIds), [draft.selectedIds]);
  const [poppingItemIds, setPoppingItemIds] = useState<Set<string>>(new Set());
  const reviewLocked = (busy && !retrieving) || draft.confirmed;
  const selectedCount = draft.selectedIds.length;
  const selectedVisibleItems = useMemo(
    () => visibleReviewItems.filter((item) => item.candidates.some((candidate) => selectedIds.has(candidate.id))),
    [selectedIds, visibleReviewItems],
  );
  const unselectedVisibleItems = useMemo(
    () => visibleReviewItems.filter((item) => !item.candidates.some((candidate) => selectedIds.has(candidate.id))),
    [selectedIds, visibleReviewItems],
  );

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onClose]);

  useEffect(() => {
    if (reviewPage >= reviewPageCount) setReviewPage(reviewPageCount - 1);
  }, [reviewPage, reviewPageCount]);

  useEffect(() => {
    if (!confirmingClearAll) return undefined;
    const timer = window.setTimeout(() => setConfirmingClearAll(false), 5000);
    return () => window.clearTimeout(timer);
  }, [confirmingClearAll]);

  useEffect(() => {
    if (!draft.confirmed) return;
    setReviewPage(0);
    patch({
      confirmed: false,
      confirmedItemIds: Array.from(new Set([
        ...(draft.confirmedItemIds ?? []),
        ...reviewItems.map((item) => item.id),
      ])),
      selectedIds: [],
      rejectedItemIds: [],
      analysisByCandidateId: {},
      analysisComplete: false,
      status: source === "local"
        ? "Previous batch is saved. Choose more files when ready."
        : draft.retrievalExhausted
          ? "Previous batch is saved. Retrieval is complete."
          : "Previous batch is saved. Retrieve the next 100 when ready.",
    });
  }, [draft.confirmed]);

  useEffect(() => {
    const jobId = draft.activeAcquisitionJobId;
    const getJob = engine.getSocialAcquisitionJob;
    if (!jobId || !getJob || retrievalRunRef.current) return undefined;
    const restoredJobId = jobId;
    const loadJob = getJob;
    const retrievalRun = Symbol("restored-social-retrieval");
    retrievalRunRef.current = retrievalRun;
    let canceled = false;

    async function restoreRetrieval() {
      setRetrieving(true);
      setBusy(true);
      try {
        let job = await loadJob(restoredJobId);
        if (!job || canceled) return;
        setActiveAcquisitionJob(job);
        if (job.status === "queued" && engine.resumeSocialAcquisitionJob) {
          job = await engine.resumeSocialAcquisitionJob(job.id);
        }
        const result = job.status === "complete" && job.result
          ? job.result
          : await acquireSocialMedia(engine, job.request, (nextJob) => {
              setActiveAcquisitionJob(nextJob);
              patch({
                activeAcquisitionJobId: nextJob.id,
                status: nextJob.progress_message,
              });
            });
        if (canceled) return;
        const startingCount = buildReviewItems(draft.candidates).length;
        const recoveryTarget = startingCount + guidedRetrievalWindowSize;
        const legacyLargeRequest = (job.request.limit ?? guidedRetrievalPageSize) > guidedRetrievalPageSize;
        const candidates = limitCandidatesToReviewItems(
          mergeCandidates(draft.candidates, result.candidates),
          recoveryTarget,
        );
        // A cursor returned by an older large job points past the candidates
        // we intentionally withheld. Restart that query and let merge/dedupe
        // advance through the pool without skipping items.
        const nextCursor = legacyLargeRequest ? undefined : resultNextCursor(result.metadata_json);
        const recoveredCount = buildReviewItems(candidates).length;
        patch({
          candidates,
          activeAcquisitionJobId: undefined,
          retrievalCursor: nextCursor,
          retrievalExhausted: legacyLargeRequest ? false : !nextCursor,
          status: legacyLargeRequest
            ? `Recovered ${recoveredCount} unique previews from the previous large retrieval. Retrieve the next 100 when ready.`
            : `Recovered ${recoveredCount} unique previews after restart${nextCursor ? ". The next 100 are ready to retrieve." : ". Source exhausted."}`,
        });
      } catch (error) {
        if (!canceled) {
          patch({
            activeAcquisitionJobId: undefined,
            status: error instanceof Error ? error.message : "Could not restore retrieval.",
          });
        }
      } finally {
        if (!canceled && retrievalRunRef.current === retrievalRun) {
          retrievalRunRef.current = null;
          setRetrieving(false);
          setBusy(false);
          setActiveAcquisitionJob(null);
        }
      }
    }

    void restoreRetrieval();
    return () => {
      canceled = true;
      if (retrievalRunRef.current === retrievalRun) retrievalRunRef.current = null;
    };
  }, [draft.activeAcquisitionJobId, engine]);

  function patch(values: Partial<IntakeDraft>) {
    onChange((current) => ({ ...current, ...values }));
  }

  async function retrieve() {
    if (source !== "local" && !draft.url.trim()) {
      patch({ status: `Enter a ${sourceOption.label} profile or post URL.` });
      return;
    }
    const dateFrom = draft.allDates ? undefined : `${draft.fromYear}-01-01`;
    const dateTo = draft.allDates ? undefined : `${draft.toYear}-12-31`;
    const retrievalQueryKey = JSON.stringify([
      source,
      draft.url.trim(),
      draft.browser,
      dateFrom ?? "",
      dateTo ?? "",
    ]);
    const continuingQuery = draft.retrievalQueryKey === undefined || draft.retrievalQueryKey === retrievalQueryKey;
    if (continuingQuery && draft.retrievalExhausted) return;
    let candidates = continuingQuery ? [...draft.candidates] : [];
    const confirmedItemIds = continuingQuery ? (draft.confirmedItemIds ?? []) : [];
    const startingCount = buildReviewItems(candidates).length;
    const startingPendingCount = buildReviewItems(candidates)
      .filter((item) => !confirmedItemIds.includes(item.id))
      .length;
    const targetCount = startingCount + guidedRetrievalWindowSize;

    const retrievalRun = Symbol("social-retrieval");
    retrievalRunRef.current = retrievalRun;
    setRetrieving(true);
    setBusy(true);
    setReviewPage(Math.floor(startingPendingCount / guidedReviewPageSize));
    patch({
      ...(continuingQuery ? {} : {
        candidates: [],
        selectedIds: [],
        rejectedItemIds: [],
        confirmedItemIds: [],
        analysisByCandidateId: {},
        analysisComplete: false,
      }),
      status: `Retrieving previews ${startingCount + 1}–${targetCount} from ${sourceOption.label}…`,
      retrievalQueryKey,
    });
    try {
      const seenCursors = new Set<string>();
      const failedSurfaces = new Set<string>();
      let cursor = continuingQuery ? draft.retrievalCursor : undefined;
      let sourceExhausted = false;
      if (cursor) seenCursors.add(cursor);

      while (!sourceExhausted && buildReviewItems(candidates).length < targetCount) {
        let result;
        if (source === "local") {
          throw new Error(`${sourceOption.label} retrieval is not available in this engine.`);
        }
        result = await acquireSocialMedia(engine, {
          provider: source,
          url: draft.url.trim(),
          browser: draft.browser,
          limit: guidedRetrievalPageSize,
          cursor,
          scan_mode: "all",
          date_from: dateFrom,
          date_to: dateTo,
        }, (job) => {
          setActiveAcquisitionJob(job);
          patch({
            activeAcquisitionJobId: job.id,
            status: job.progress_message,
          });
        });
        result.errors.forEach((error) => {
          if (typeof error.surface === "string" && error.surface) failedSurfaces.add(error.surface);
        });
        candidates = limitCandidatesToReviewItems(
          mergeCandidates(candidates, result.candidates),
          targetCount,
        );
        const retrievedCount = buildReviewItems(candidates).length;
        patch({
          candidates,
          analysisComplete: false,
          confirmed: false,
          retrievalCursor: resultNextCursor(result.metadata_json),
          retrievalExhausted: false,
          retrievalQueryKey,
          status: `Retrieved ${Math.max(0, retrievedCount - startingCount)} of this 100 · ${retrievedCount} total…`,
        });
        const nextCursor = resultNextCursor(result.metadata_json);
        sourceExhausted = !nextCursor || seenCursors.has(nextCursor);
        if (nextCursor && !sourceExhausted) {
          seenCursors.add(nextCursor);
          cursor = nextCursor;
        }
      }
      const retrievedItems = buildReviewItems(candidates);
      const retrievedCount = retrievedItems.length;
      const addedCount = Math.max(0, retrievedCount - startingCount);
      const retrievalExhausted = sourceExhausted;
      const retrievedSurfaceCounts = instagramSurfaceCounts(retrievedItems);
      const surfaceSummary = source === "instagram"
        ? `Feed ${retrievedSurfaceCounts.feed} · Reels ${retrievedSurfaceCounts.reels} · Tagged ${retrievedSurfaceCounts.tagged}`
        : "";
      const failureSummary = failedSurfaces.size
        ? ` ${Array.from(failedSurfaces).map(capitalize).join(" and ")} could not be retrieved.`
        : "";
      patch({
        candidates,
        analysisComplete: false,
        surfaceFilter: "all",
        batchNumber: draft.batchNumber || 1,
        confirmed: false,
        retrievalCursor: cursor,
        retrievalExhausted,
        retrievalQueryKey,
        status: `${addedCount} new previews · ${retrievedCount} total${surfaceSummary ? ` · ${surfaceSummary}` : ""}${retrievalExhausted ? ". Source exhausted." : ". Retrieve the next 100 when ready."}${failureSummary}`,
      });
    } catch (error) {
      patch({
        candidates,
        retrievalQueryKey,
        status: candidates.length
          ? `Retrieval stopped with ${buildReviewItems(candidates).length} unique previews. ${error instanceof Error ? error.message : "The source request failed."}`
          : error instanceof Error ? error.message : "Source retrieval failed.",
      });
    } finally {
      if (retrievalRunRef.current === retrievalRun) retrievalRunRef.current = null;
      setRetrieving(false);
      setBusy(false);
      setActiveAcquisitionJob(null);
      patch({ activeAcquisitionJobId: undefined });
    }
  }

  async function cancelRetrieval() {
    if (!activeAcquisitionJob || !engine.cancelSocialAcquisitionJob) return;
    try {
      const job = await engine.cancelSocialAcquisitionJob(activeAcquisitionJob.id);
      setActiveAcquisitionJob(job);
      patch({ status: job.progress_message });
    } catch (error) {
      patch({ status: error instanceof Error ? error.message : "Could not cancel retrieval." });
    }
  }

  async function scanLocal(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    patch({ status: `Reading ${files.length} local file${files.length === 1 ? "" : "s"}…` });
    try {
      const result = await engine.uploadLocalIngress(Array.from(files));
      const candidates = mergeCandidates(draft.confirmed ? [] : draft.candidates, result.candidates);
      patch({
        candidates,
        selectedIds: [],
        analysisByCandidateId: {},
        analysisComplete: false,
        batchNumber: draft.batchNumber || 1,
        confirmed: false,
        status: `${candidates.length} local media candidates ready for review. Add more files or approve this batch.`,
      });
    } catch (error) {
      patch({ status: error instanceof Error ? error.message : "Local media scan failed." });
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  }

  async function scanWithAi() {
    const pendingCandidates = pendingReviewItems
      .flatMap((item) => item.candidates)
      .filter((candidate) => candidateFitsTarget(candidate, target));
    if (!pendingCandidates.length || busy || draft.confirmed) return;
    setBusy(true);
    setAnalyzing(true);
    patch({ status: `AI is evaluating ${pendingCandidates.length} retrieved media candidates…` });
    try {
      const result = await engine.analyzeIngressCandidates(
        pendingCandidates.map((candidate) => candidate.id),
        target,
      );
      const analysisByCandidateId = Object.fromEntries(
        result.analyses.map((analysis) => [analysis.candidate_id, analysis]),
      );
      const counts = result.analyses.reduce(
        (current, analysis) => ({ ...current, [analysis.recommendation]: current[analysis.recommendation] + 1 }),
        { keep: 0, review: 0, reject: 0 },
      );
      setReviewPage(0);
      patch({
        analysisByCandidateId,
        analysisComplete: true,
        status: `AI scan complete: ${counts.keep} keep, ${counts.review} review, ${counts.reject} reject. Recommendations are labeled; your selections and visible media were preserved.`,
      });
    } catch (error) {
      patch({ status: error instanceof Error ? error.message : "AI scan failed. Retrieved media was preserved." });
    } finally {
      setAnalyzing(false);
      setBusy(false);
    }
  }

  function toggleItem(item: CandidateReviewItem) {
    const itemIds = item.candidates
      .filter((candidate) => candidate.status === "ready" && candidateFitsTarget(candidate, target))
      .map((candidate) => candidate.id);
    const allSelected = itemIds.every((id) => selectedIds.has(id));
    onChange((current) => {
      const next = new Set(current.selectedIds);
      for (const id of itemIds) allSelected ? next.delete(id) : next.add(id);
      return { ...current, selectedIds: Array.from(next) };
    });
  }

  function toggleCandidate(candidate: IngressCandidate) {
    if (candidate.status !== "ready") return;
    onChange((current) => {
      const next = new Set(current.selectedIds);
      next.has(candidate.id) ? next.delete(candidate.id) : next.add(candidate.id);
      return { ...current, selectedIds: Array.from(next) };
    });
  }

  function rejectItem(item: CandidateReviewItem) {
    if (reviewLocked || poppingItemIds.has(item.id)) return;
    setPoppingItemIds((current) => new Set(current).add(item.id));
    window.setTimeout(() => {
      onChange((current) => {
        const itemCandidateIds = new Set(item.candidates.map((candidate) => candidate.id));
        return {
          ...current,
          selectedIds: current.selectedIds.filter((id) => !itemCandidateIds.has(id)),
          rejectedItemIds: Array.from(new Set([...current.rejectedItemIds, item.id])),
        };
      });
      setPoppingItemIds((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
    }, 360);
  }

  function restoreRejected() {
    patch({ rejectedItemIds: [] });
  }

  function clearQueue() {
    if (busy) return;
    setReviewPage(0);
    setPoppingItemIds(new Set());
    patch({
      candidates: [],
      selectedIds: [],
      rejectedItemIds: [],
      confirmedItemIds: [],
      analysisByCandidateId: {},
      analysisComplete: false,
      surfaceFilter: "all",
      batchNumber: 0,
      confirmed: false,
      retrievalCursor: undefined,
      retrievalExhausted: false,
      retrievalQueryKey: undefined,
      status: "Retrieval queue cleared. Confirmed vault media was not changed.",
    });
  }

  async function clearAllMedia() {
    if (busy) return;
    if (!confirmingClearAll) {
      setConfirmingClearAll(true);
      return;
    }
    setBusy(true);
    patch({ status: "Clearing imported media and dependent workspace data…" });
    try {
      await engine.clearAllMedia("CLEAR ALL MEDIA");
      setReviewPage(0);
      setPoppingItemIds(new Set());
      setConfirmingClearAll(false);
      onAllMediaCleared();
    } catch (error) {
      patch({ status: error instanceof Error ? error.message : "Could not clear all media." });
      setConfirmingClearAll(false);
    } finally {
      setBusy(false);
    }
  }

  function selectVisible() {
    onChange((current) => {
      const next = new Set(current.selectedIds);
      for (const item of visibleReviewItems) {
        for (const candidate of item.candidates) {
          if (candidate.status === "ready") next.add(candidate.id);
        }
      }
      return { ...current, selectedIds: Array.from(next) };
    });
  }

  function clearVisible() {
    const visibleCandidateIds = new Set(visibleReviewItems.flatMap((item) => item.candidates.map((candidate) => candidate.id)));
    onChange((current) => ({
      ...current,
      selectedIds: current.selectedIds.filter((id) => !visibleCandidateIds.has(id)),
    }));
  }

  function removeVisibleItems(items: CandidateReviewItem[]) {
    if (!items.length || reviewLocked) return;
    const visibleItemIds = items.map((item) => item.id);
    const visibleCandidateIds = new Set(items.flatMap((item) => item.candidates.map((candidate) => candidate.id)));
    setPoppingItemIds((current) => new Set([...current, ...visibleItemIds]));
    window.setTimeout(() => {
      onChange((current) => ({
        ...current,
        selectedIds: current.selectedIds.filter((id) => !visibleCandidateIds.has(id)),
        rejectedItemIds: Array.from(new Set([...current.rejectedItemIds, ...visibleItemIds])),
      }));
      setPoppingItemIds((current) => {
        const next = new Set(current);
        visibleItemIds.forEach((id) => next.delete(id));
        return next;
      });
    }, 360);
  }

  async function confirmBatch() {
    const pendingCandidates = pendingReviewItems.flatMap((item) => item.candidates);
    if (!pendingCandidates.length || busy || draft.confirmed) return;
    const pendingCandidateIds = new Set(pendingCandidates.map((candidate) => candidate.id));
    const selectedPendingIds = draft.selectedIds.filter((id) => pendingCandidateIds.has(id));
    setBusy(true);
    patch({ status: `Approving ${selectedPendingIds.length} and deferring ${pendingCandidates.length - selectedPendingIds.length} candidates…` });
    try {
      let job = await engine.createIngressJob({
        source_kind: sourceKind(source),
        candidate_ids: selectedPendingIds,
        reviewed_candidate_ids: pendingCandidates.map((candidate) => candidate.id),
        options: { guided: true, target, project_id: activeProjectId },
      });
      job = await waitForIngressJob(engine, job);
      if (job.status !== "complete") throw new Error(job.progress_message || "Ingress job failed.");
      onImported(job.imported_media_items);
      setReviewPage(0);
      patch({
        confirmed: false,
        confirmedItemIds: Array.from(new Set([
          ...(draft.confirmedItemIds ?? []),
          ...pendingReviewItems.map((item) => item.id),
        ])),
        selectedIds: [],
        rejectedItemIds: [],
        analysisByCandidateId: {},
        analysisComplete: false,
        batchNumber: draft.batchNumber + 1,
        status: `${job.imported_count} imported · ${job.deferred_count} deferred. ${
          source === "local"
            ? "Choose more files when ready."
            : draft.retrievalExhausted
              ? "Retrieval complete."
              : "Retrieve the next 100 when ready."
        }`,
      });
    } catch (error) {
      patch({ status: error instanceof Error ? error.message : "Could not confirm this batch." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`source-intake-backdrop intake-${source}`} role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose();
    }}>
      <section className="source-intake-window" role="dialog" aria-modal="true" aria-labelledby="source-intake-title">
        <header className="source-intake-header">
          <span className="source-intake-icon"><SourceIcon size={24} aria-hidden="true" /></span>
          <div>
            <small>{targetLabel(target)} source</small>
            <h2 id="source-intake-title">{sourceOption.label}</h2>
          </div>
          <div className="source-intake-totals"><strong>{progress.imported}</strong><span>imported here</span><strong>{progress.batches}</strong><span>batches on this device</span></div>
          <button type="button" className="icon-button" title="Close source" aria-label="Close source" disabled={busy} onClick={onClose}><X size={17} /></button>
        </header>

        {savedItems.length ? <details className="source-saved-media" open>
          <summary>{savedItems.length} items already saved in this project</summary>
          <ProjectMediaLibrary items={savedItems} assetUrl={engine.assetUrl} />
        </details> : null}
        <div className="source-intake-controls">
          {source === "local" ? (
            <div className="local-source-pickers">
              <input ref={fileInputRef} hidden type="file" multiple onChange={(event) => void scanLocal(event.currentTarget.files)} />
              <input ref={(node) => {
                folderInputRef.current = node;
                node?.setAttribute("webkitdirectory", "");
              }} hidden type="file" multiple onChange={(event) => void scanLocal(event.currentTarget.files)} />
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}><Upload size={15} /> Choose files</button>
              <button type="button" onClick={() => folderInputRef.current?.click()} disabled={busy}><FolderOpen size={15} /> Choose folder</button>
              <p>Selections are additive until you confirm the batch.</p>
              <button type="button" className="primary-action local-ai-scan" disabled={!aiCandidateCount || busy || draft.confirmed} onClick={() => void scanWithAi()}>
                {analyzing ? <LoaderCircle className="spin" size={16} /> : <ScanSearch size={16} />} Scan with AI
              </button>
            </div>
          ) : (
            <>
              <label className="source-url-field">
                <span>{sourceOption.label} URL</span>
                <input value={draft.url} placeholder={sourcePlaceholder(source)} onChange={(event) => patch({ url: event.target.value, retrievalCursor: undefined, retrievalExhausted: false, retrievalQueryKey: "" })} />
              </label>
              <label className="source-browser-field">
                <span>Browser</span>
                <select value={draft.browser} onChange={(event) => patch({ browser: event.target.value, retrievalCursor: undefined, retrievalExhausted: false, retrievalQueryKey: "" })}>
                  <option value="chrome">Chrome</option>
                  <option value="brave">Brave</option>
                  <option value="chromium">Chromium</option>
                  <option value="edge">Edge</option>
                  <option value="firefox">Firefox</option>
                  <option value="safari">Safari</option>
                </select>
              </label>
              <div className="source-date-range">
                <div className="source-control-label"><CalendarRange size={14} /><span>Date range</span><button type="button" className={draft.allDates ? "active" : ""} onClick={() => patch({ allDates: !draft.allDates, retrievalCursor: undefined, retrievalExhausted: false, retrievalQueryKey: "" })}>Any date</button></div>
                <div className={draft.allDates ? "date-sliders disabled" : "date-sliders"}>
                  <label><span>From <strong>{draft.fromYear}</strong></span><input type="range" min={earliestYear} max={draft.toYear} value={draft.fromYear} disabled={draft.allDates} onChange={(event) => patch({ fromYear: Number(event.target.value), retrievalCursor: undefined, retrievalExhausted: false, retrievalQueryKey: "" })} /></label>
                  <label><span>Through <strong>{draft.toYear}</strong></span><input type="range" min={draft.fromYear} max={currentYear} value={draft.toYear} disabled={draft.allDates} onChange={(event) => patch({ toYear: Number(event.target.value), retrievalCursor: undefined, retrievalExhausted: false, retrievalQueryKey: "" })} /></label>
                </div>
              </div>
              <div className="source-limit-field source-pool-cap">
                <span>Retrieval pool</span>
                <strong>{guidedRetrievalWindowSize} at a time · no total limit</strong>
              </div>
              {source === "instagram" ? (
                <div className="source-scan-modes" role="group" aria-label="Instagram source filter">
                  {(["all", "feed", "reels", "tagged"] as InstagramScanMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className={draft.surfaceFilter === mode ? "active" : ""}
                      aria-label={`${mode === "all" ? "Everything" : capitalize(mode)} ${mode === "all" ? pendingReviewItems.length : surfaceCounts[mode]}`}
                      aria-pressed={draft.surfaceFilter === mode}
                      onClick={() => {
                        setReviewPage(0);
                        patch({ surfaceFilter: mode });
                      }}
                    >
                      <span>{mode === "all" ? "Everything" : capitalize(mode)}</span>
                      <strong>{mode === "all" ? pendingReviewItems.length : surfaceCounts[mode]}</strong>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="source-action-buttons">
                <button type="button" className="source-retrieve-button" disabled={busy || draft.confirmed || retrievalComplete} onClick={() => void retrieve()}>
                  {busy && !analyzing ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />} {retrieveLabel}
                </button>
                {activeAcquisitionJob && !["complete", "failed", "canceled"].includes(activeAcquisitionJob.status) ? (
                  <button type="button" className="destructive-action" onClick={() => void cancelRetrieval()}>
                    <X size={16} /> Cancel
                  </button>
                ) : null}
                <button type="button" className="primary-action source-ai-scan" disabled={!aiCandidateCount || busy || draft.confirmed} onClick={() => void scanWithAi()}>
                  {analyzing ? <LoaderCircle className="spin" size={16} /> : <ScanSearch size={16} />} Scan with AI
                </button>
              </div>
            </>
          )}
        </div>

        <div className="source-batch-toolbar">
          <div><small>{filteredReviewItems.length ? `Review ${reviewPage + 1} / ${reviewPageCount}` : "Review"}</small><strong>{reviewItems.length ? `${visibleReviewItems.length} shown of ${filteredReviewItems.length} · ${selectedCount} media selected` : "Waiting for retrieval"}</strong></div>
          <span className="source-status" title={draft.status}>{draft.status}</span>
          <button type="button" disabled={!draft.rejectedItemIds.length || reviewLocked} onClick={restoreRejected}>Restore {draft.rejectedItemIds.length || ""} removed</button>
          <button type="button" disabled={!visibleReviewItems.length || reviewLocked} onClick={selectVisible}>Select all shown</button>
          <button type="button" disabled={!visibleReviewItems.length || reviewLocked} onClick={clearVisible}>Deselect all shown</button>
          <button type="button" className="reject-visible" disabled={!selectedVisibleItems.length || reviewLocked} onClick={() => removeVisibleItems(selectedVisibleItems)}>Remove selected ({selectedVisibleItems.length})</button>
          <button type="button" className="reject-visible" disabled={!unselectedVisibleItems.length || reviewLocked} onClick={() => removeVisibleItems(unselectedVisibleItems)}>Remove unselected ({unselectedVisibleItems.length})</button>
        </div>

        <div className="source-candidate-field" aria-label={`${sourceOption.label} media candidates`}>
          {reviewItems.length ? visibleReviewItems.map((item, index) => (
            <SourceCandidateBubble
              key={item.id}
              item={item}
              index={index}
              engine={engine}
              selectedIds={selectedIds}
              disabled={reviewLocked}
              popping={poppingItemIds.has(item.id)}
              analysis={reviewItemAiSummary(item, draft.analysisByCandidateId, target)}
              onToggle={() => toggleItem(item)}
              onReject={() => rejectItem(item)}
              onToggleCandidate={toggleCandidate}
            />
          )) : (
            <div className="source-candidate-empty"><SourceIcon size={34} /><strong>{source === "local" ? "Choose files or a folder to add more media" : "Retrieve the first 100 to see new media"}</strong><span>{source === "local" ? "Your saved project media is available above." : "Review this window, then retrieve the next 100 when you are ready."}</span></div>
          )}
          {reviewItems.length > 0 && visibleReviewItems.length === 0 ? (
            <div className="source-candidate-empty">
              <Sparkles size={34} />
              <strong>{pendingReviewItems.length ? "No bubbles remain in this view" : "Batch saved"}</strong>
              <span>
                {pendingReviewItems.length
                  ? "Restore removed media above or change the source filter."
                  : source === "local"
                    ? "Choose more files when you are ready."
                    : retrievalComplete
                      ? "The retrieval pool is complete."
                      : "Retrieve the next 100 when you are ready."}
              </span>
            </div>
          ) : null}
        </div>

        <footer className="source-intake-footer">
          <span>{draft.confirmed ? <><Check size={14} /> Batch confirmed</> : "Unselected media will be deferred when this batch is confirmed."}</span>
          <div className="source-clear-actions">
            <button type="button" className="destructive-action" disabled={!draft.candidates.length || busy} onClick={clearQueue}><Trash2 size={15} /> Clear queue</button>
            <button
              type="button"
              className={`destructive-action clear-all-action ${confirmingClearAll ? "confirming" : ""}`}
              disabled={busy}
              title="Deletes imported media and dependent workspace data. Installed models, settings, and completed training artifacts are preserved."
              onClick={() => void clearAllMedia()}
            >
              <Trash2 size={15} /> {confirmingClearAll ? "Confirm clear all" : "Clear all media"}
            </button>
          </div>
          <button type="button" disabled={!pendingReviewItems.length || busy || draft.confirmed} onClick={() => void confirmBatch()}><Check size={15} /> Confirm batch</button>
          <button type="button" disabled={reviewPage === 0 || reviewLocked} onClick={() => setReviewPage((page) => Math.max(0, page - 1))}><ArrowLeft size={15} /> Previous 24</button>
          <button type="button" className="primary-action" disabled={reviewPage >= reviewPageCount - 1 || reviewLocked} onClick={() => setReviewPage((page) => Math.min(reviewPageCount - 1, page + 1))}>Next 24 <ArrowRight size={15} /></button>
          <button type="button" disabled={busy} onClick={onClose}>Done</button>
        </footer>
      </section>
    </div>
  );
}

function SourceCandidateBubble({ item, index, engine, selectedIds, disabled, popping, analysis, onToggle, onReject, onToggleCandidate }: {
  item: CandidateReviewItem;
  index: number;
  engine: EngineClient;
  selectedIds: Set<string>;
  disabled: boolean;
  popping: boolean;
  analysis?: IngressCandidateAnalysis;
  onToggle(): void;
  onReject(): void;
  onToggleCandidate(candidate: IngressCandidate): void;
}) {
  const previewPath = item.thumbnailCandidate.thumbnail_path ?? item.thumbnailCandidate.poster_asset_path;
  const posterUrl = previewPath
    ? engine.assetUrl(previewPath)
    : item.videoCandidate?.source_kind === "x_twitter"
      ? engine.ingressCandidateThumbnailUrl(item.videoCandidate.id)
      : undefined;
  const videoUrl = item.videoCandidate ? candidateVideoPreviewUrl(item.videoCandidate, engine) : undefined;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [videoPreviewActive, setVideoPreviewActive] = useState(false);
  const [videoPreviewStatus, setVideoPreviewStatus] = useState<"idle" | "loading" | "playing" | "error">("idle");
  const [videoLoadingSeconds, setVideoLoadingSeconds] = useState(0);
  const readyCandidates = item.candidates.filter((candidate) => candidate.status === "ready");
  const selected = readyCandidates.some((candidate) => selectedIds.has(candidate.id));
  const bubbleStyle = {
    "--bubble-delay": `${(index % 8) * 70}ms`,
    "--bubble-float-delay": `${-((index * 0.63) % 4.8)}s`,
    "--bubble-drift": `${10 + (index % 4) * 3}px`,
    "--bubble-scale": `${0.94 + (index % 3) * 0.035}`,
  } as CSSProperties;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoPreviewActive) return;
    video.muted = false;
    try {
      const playback = video.play();
      if (playback && typeof playback.catch === "function") {
        void playback.catch(() => {
          video.muted = true;
          try {
            const mutedPlayback = video.play();
            if (mutedPlayback && typeof mutedPlayback.catch === "function") void mutedPlayback.catch(() => undefined);
          } catch {
            // The poster remains visible if the browser cannot preview this source.
          }
        });
      }
    } catch {
      video.muted = true;
    }
  }, [videoPreviewActive]);

  useEffect(() => {
    if (!videoPreviewActive || videoPreviewStatus !== "loading") return undefined;
    const startedAt = Date.now();
    setVideoLoadingSeconds(0);
    const timer = window.setInterval(() => {
      setVideoLoadingSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [videoPreviewActive, videoPreviewStatus]);

  function startVideoPreview() {
    setVideoLoadingSeconds(0);
    setVideoPreviewStatus("loading");
    setVideoPreviewActive(true);
  }

  function stopVideoPreview() {
    const video = videoRef.current;
    if (video) {
      try {
        video.pause();
        video.currentTime = 0;
      } catch {
        // The element is about to be replaced by its poster.
      }
    }
    setVideoPreviewActive(false);
    setVideoPreviewStatus("idle");
    setVideoLoadingSeconds(0);
  }

  return (
    <article
      className={`source-candidate-bubble ${selected ? "selected" : ""} ${popping ? "popping" : ""} ${analysis ? `ai-${analysis.recommendation}` : ""}`}
      style={bubbleStyle}
      onMouseLeave={stopVideoPreview}
    >
      <div className="source-bubble-orbit">
        <button type="button" className="source-candidate-preview" disabled={disabled || !readyCandidates.length} aria-pressed={selected} aria-label={`${selected ? "Deselect" : "Select"} ${item.displayName}`} onClick={onToggle}>
          {posterUrl ? <img src={posterUrl} alt="" /> : <MediaPlaceholder item={item} />}
          {videoPreviewActive && videoUrl ? (
            <video
              ref={videoRef}
              className="source-candidate-video"
              title={`Playing ${item.displayName}`}
              src={videoUrl}
              poster={posterUrl}
              playsInline
              loop
              preload="metadata"
              onPlaying={() => setVideoPreviewStatus("playing")}
              onWaiting={() => setVideoPreviewStatus("loading")}
              onError={() => setVideoPreviewStatus("error")}
            />
          ) : null}
          {videoPreviewActive && videoPreviewStatus === "loading" ? (
            <span className="source-video-preview-status loading" role="status">
              <LoaderCircle size={13} /> Loading preview · {videoLoadingSeconds}s
            </span>
          ) : null}
          {videoPreviewActive && videoPreviewStatus === "error" ? (
            <span className="source-video-preview-status error" role="status">Preview unavailable</span>
          ) : null}
          <span className="source-bubble-gloss" aria-hidden="true" />
          <span className="source-candidate-check">{selected ? <Check size={22} /> : null}</span>
        </button>
        {analysis ? (
          <span className={`source-ai-badge ${analysis.recommendation}`} title={[...analysis.reasons, ...analysis.warnings].join(" ")}>
            AI {analysis.recommendation} {Math.round(analysis.confidence * 100)}%
          </span>
        ) : null}
        <button type="button" className="source-bubble-reject" title={`Remove ${item.displayName}`} aria-label={`Remove ${item.displayName}`} disabled={disabled} onClick={onReject}><X size={14} /></button>
        <div className="source-candidate-roles">
          {item.imageCandidate ? <RoleToggle label="Image" candidate={item.imageCandidate} selectedIds={selectedIds} disabled={disabled} onToggle={onToggleCandidate} /> : null}
          {item.videoCandidate ? <RoleToggle label="Video" candidate={item.videoCandidate} selectedIds={selectedIds} disabled={disabled} onToggle={onToggleCandidate} onPreviewStart={startVideoPreview} onPreviewEnd={stopVideoPreview} /> : null}
          {item.audioCandidate ? <RoleToggle label="Voice" candidate={item.audioCandidate} selectedIds={selectedIds} disabled={disabled} onToggle={onToggleCandidate} /> : null}
        </div>
        <strong title={item.displayName}>{item.displayName}</strong>
      </div>
    </article>
  );
}

function RoleToggle({ label, candidate, selectedIds, disabled, onToggle, onPreviewStart, onPreviewEnd }: {
  label: string;
  candidate: IngressCandidate;
  selectedIds: Set<string>;
  disabled: boolean;
  onToggle(candidate: IngressCandidate): void;
  onPreviewStart?(): void;
  onPreviewEnd?(): void;
}) {
  const selected = selectedIds.has(candidate.id);
  return (
    <button
      type="button"
      className={selected ? "selected" : ""}
      aria-pressed={selected}
      disabled={disabled || candidate.status !== "ready"}
      onClick={() => onToggle(candidate)}
      onMouseEnter={onPreviewStart}
      onFocus={onPreviewStart}
      onBlur={onPreviewEnd}
    >
      {label}
    </button>
  );
}

function GraphFilaments({ variant }: { variant: "creation" | "sources" }) {
  return (
    <svg className={`graph-filaments ${variant}`} viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true">
      {variant === "creation" ? (
        <>
          <path d="M500 390 C480 300 480 235 500 150" />
          <path d="M475 410 C390 370 300 340 220 315" />
          <path d="M525 410 C620 365 710 340 790 315" />
          <path d="M220 315 C340 250 405 215 500 150" />
          <path d="M790 315 C665 245 600 210 500 150" />
        </>
      ) : (
        <>
          <path d="M145 135 C210 245 365 280 500 390" />
          <path d="M380 115 C405 240 455 300 500 390" />
          <path d="M620 115 C590 240 545 300 500 390" />
          <path d="M855 135 C790 245 640 280 500 390" />
        </>
      )}
    </svg>
  );
}

function GraphParticles() {
  return <div className="graph-particles" aria-hidden="true">{Array.from({ length: 18 }, (_, index) => <i key={index} />)}</div>;
}

function MediaPlaceholder({ item }: { item: CandidateReviewItem }) {
  const Icon = item.videoCandidate ? Video : item.audioCandidate ? AudioLines : Image;
  return <span className="guided-media-placeholder"><Icon size={25} /></span>;
}

function buildReviewItems(candidates: IngressCandidate[]): CandidateReviewItem[] {
  const candidatesById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
  const posterByVideoId = new Map<string, IngressCandidate>();
  const audioByVideoId = new Map<string, IngressCandidate>();
  for (const candidate of candidates) {
    const videoId = sourceVideoCandidateId(candidate);
    if (!videoId || !candidatesById.has(videoId)) continue;
    if (candidate.media_type === "image") posterByVideoId.set(videoId, candidate);
    if (candidate.media_type === "audio") audioByVideoId.set(videoId, candidate);
  }
  const consumed = new Set<string>();
  const items: CandidateReviewItem[] = [];
  for (const candidate of candidates) {
    if (consumed.has(candidate.id)) continue;
    const pairedVideoId = sourceVideoCandidateId(candidate);
    if (pairedVideoId && candidatesById.has(pairedVideoId)) continue;
    if (candidate.media_type === "video") {
      const imageCandidate = posterByVideoId.get(candidate.id)
        ?? (candidate.source_kind === "x_twitter" ? xVideoPosterCandidate(candidate) : undefined);
      const audioCandidate = audioByVideoId.get(candidate.id);
      const grouped = [imageCandidate, candidate, audioCandidate].filter((value): value is IngressCandidate => Boolean(value));
      grouped.forEach((value) => consumed.add(value.id));
      items.push({
        id: candidate.id,
        displayName: candidate.display_name,
        candidates: grouped,
        imageCandidate,
        videoCandidate: candidate,
        audioCandidate,
        thumbnailCandidate: imageCandidate ?? candidate,
      });
      continue;
    }
    consumed.add(candidate.id);
    items.push({
      id: candidate.id,
      displayName: candidate.display_name,
      candidates: [candidate],
      imageCandidate: candidate.media_type === "image" ? candidate : undefined,
      audioCandidate: candidate.media_type === "audio" ? candidate : undefined,
      thumbnailCandidate: candidate,
    });
  }
  return items;
}

function sourceVideoCandidateId(candidate: IngressCandidate): string | undefined {
  const value = candidate.metadata_json?.source_video_candidate_id;
  return typeof value === "string" && value ? value : undefined;
}

function xVideoPosterCandidate(videoCandidate: IngressCandidate): IngressCandidate {
  return {
    id: `${videoCandidate.id}_poster`,
    source_kind: videoCandidate.source_kind,
    source_locator: `${videoCandidate.source_locator}#poster`,
    display_name: `${videoCandidate.display_name} poster`,
    media_type: "image",
    width: videoCandidate.width,
    height: videoCandidate.height,
    status: "ready",
    selected: true,
    metadata_json: {
      ...(videoCandidate.metadata_json ?? {}),
      source_video_candidate_id: videoCandidate.id,
      asset_role: "video_poster",
      materialize_from_video: true,
    },
  };
}

function reviewItemScanSurfaces(item: CandidateReviewItem): Set<string> {
  const surfaces = new Set<string>();
  for (const candidate of item.candidates) {
    const value = candidate.metadata_json?.scan_surface;
    if (typeof value === "string" && value) surfaces.add(value);
    const values = candidate.metadata_json?.scan_surfaces;
    if (Array.isArray(values)) {
      values.forEach((surface) => {
        if (typeof surface === "string" && surface) surfaces.add(surface);
      });
    }
  }
  if (!surfaces.size) surfaces.add("unknown");
  return surfaces;
}

function instagramSurfaceCounts(items: CandidateReviewItem[]): Record<Exclude<InstagramScanMode, "all">, number> {
  const counts = { feed: 0, reels: 0, tagged: 0 };
  for (const item of items) {
    const surfaces = reviewItemScanSurfaces(item);
    for (const surface of ["feed", "reels", "tagged"] as const) {
      if (surfaces.has(surface)) counts[surface] += 1;
    }
  }
  return counts;
}

function candidateFitsTarget(candidate: IngressCandidate, target: WizardTarget): boolean {
  if (target === "image") return candidate.media_type === "image" || candidate.media_type === "video";
  if (target === "video") return candidate.media_type === "video" || candidate.media_type === "image";
  if (target === "voice") return candidate.media_type === "audio";
  return true;
}

function reviewItemAiSummary(
  item: CandidateReviewItem,
  analyses: Record<string, IngressCandidateAnalysis>,
  target: WizardTarget,
): IngressCandidateAnalysis | undefined {
  const relevant = item.candidates
    .filter((candidate) => candidateFitsTarget(candidate, target))
    .map((candidate) => analyses[candidate.id])
    .filter((analysis): analysis is IngressCandidateAnalysis => Boolean(analysis));
  if (!relevant.length) return undefined;
  const keep = relevant.filter((analysis) => analysis.recommendation === "keep");
  if (keep.length) return keep.sort((left, right) => right.confidence - left.confidence)[0];
  if (relevant.every((analysis) => analysis.recommendation === "reject")) {
    return relevant.sort((left, right) => right.confidence - left.confidence)[0];
  }
  return relevant
    .filter((analysis) => analysis.recommendation === "review")
    .sort((left, right) => right.confidence - left.confidence)[0] ?? relevant[0];
}

function recommendationPriority(analysis?: IngressCandidateAnalysis): number {
  if (analysis?.recommendation === "keep") return 2;
  if (analysis?.recommendation === "review") return 1;
  return 0;
}

function sourceKind(source: GuidedSource): SourceKind {
  return source === "x" ? "x_twitter" : source;
}

function resultNextCursor(metadata?: Record<string, unknown>): string | undefined {
  const value = metadata?.next_cursor;
  return typeof value === "string" && value ? value : undefined;
}

function candidateVideoPreviewUrl(candidate: IngressCandidate, engine: EngineClient): string {
  if (candidate.source_kind === "x_twitter" || candidate.source_kind === "tiktok") {
    return engine.ingressCandidateVideoPreviewUrl(candidate.id);
  }
  const downloadUrl = candidate.metadata_json?.download_url;
  if (typeof downloadUrl === "string" && downloadUrl.trim()) return downloadUrl;
  return candidate.source_locator.startsWith("/") ? engine.assetUrl(candidate.source_locator) : candidate.source_locator;
}

async function waitForIngressJob(engine: EngineClient, initial: IngressJob): Promise<IngressJob> {
  let job = initial;
  for (let attempt = 0; attempt < 60 && (job.status === "queued" || job.status === "running"); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    job = await engine.getIngressJob(job.id);
  }
  return job;
}

function mergeCandidates(current: IngressCandidate[], next: IngressCandidate[]): IngressCandidate[] {
  const merged: IngressCandidate[] = [];
  const indexByKey = new Map<string, number>();
  for (const candidate of [...current, ...next]) {
    const key = candidateDeduplicationKey(candidate);
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, merged.length);
      merged.push(candidate);
      continue;
    }
    const existing = merged[existingIndex];
    const surfaces = new Set([
      ...candidateScanSurfaces(existing),
      ...candidateScanSurfaces(candidate),
    ]);
    merged[existingIndex] = {
      ...existing,
      metadata_json: {
        ...(candidate.metadata_json ?? {}),
        ...(existing.metadata_json ?? {}),
        scan_surfaces: Array.from(surfaces).filter((surface) => surface !== "unknown").sort(),
      },
    };
  }
  return merged;
}

function limitCandidatesToReviewItems(candidates: IngressCandidate[], limit: number): IngressCandidate[] {
  return buildReviewItems(candidates)
    .slice(0, limit)
    .flatMap((item) => item.candidates);
}

function candidateDeduplicationKey(candidate: IngressCandidate): string {
  const metadata = candidate.metadata_json ?? {};
  const platformId = typeof metadata.platform_media_id === "string" ? metadata.platform_media_id : "";
  const normalizedPlatformId = /^\d+(?:_\d+)?$/.test(platformId) ? platformId.split("_", 1)[0] : platformId;
  const sourceUrl = typeof metadata.source_url === "string" ? metadata.source_url : candidate.source_locator;
  const shortcode = instagramShortcode(sourceUrl);
  const identity = normalizedPlatformId || shortcode || sourceUrl;
  const role = typeof metadata.asset_role === "string" ? metadata.asset_role : (candidate.media_type ?? "unknown");
  return `${candidate.source_kind}:${identity}:${role}`;
}

function instagramShortcode(value: string): string {
  try {
    const parts = new URL(value).pathname.split("/").filter(Boolean);
    const markerIndex = parts.findIndex((part) => ["p", "reel", "tv"].includes(part.toLowerCase()));
    return markerIndex >= 0 ? (parts[markerIndex + 1] ?? "").toLowerCase() : "";
  } catch {
    return "";
  }
}

function candidateScanSurfaces(candidate: IngressCandidate): string[] {
  const metadata = candidate.metadata_json ?? {};
  const surfaces = new Set<string>();
  if (typeof metadata.scan_surface === "string" && metadata.scan_surface) surfaces.add(metadata.scan_surface);
  if (Array.isArray(metadata.scan_surfaces)) {
    metadata.scan_surfaces.forEach((surface) => {
      if (typeof surface === "string" && surface) surfaces.add(surface);
    });
  }
  return surfaces.size ? Array.from(surfaces) : ["unknown"];
}

function storedStage(): GuidedStage {
  const value = window.localStorage.getItem(stageStorageKey);
  return guidedStages.some((stage) => stage.id === value) ? value as GuidedStage : "create";
}

function emptyDraft(source: GuidedSource): IntakeDraft {
  return {
    url: source === "instagram" ? "https://www.instagram.com/" : source === "x" ? "https://x.com/" : source === "tiktok" ? "https://www.tiktok.com/@" : "",
    browser: "chrome",
    allDates: true,
    fromYear: Math.max(earliestYear, currentYear - 3),
    toYear: currentYear,
    surfaceFilter: "all",
    candidates: [],
    selectedIds: [],
    rejectedItemIds: [],
    confirmedItemIds: [],
    analysisByCandidateId: {},
    analysisComplete: false,
    batchNumber: 0,
    confirmed: false,
    retrievalExhausted: false,
    status: source === "local" ? "Choose files or a folder to begin." : "Set the source and retrieve a batch when ready.",
  };
}

function emptyDrafts(): Record<GuidedSource, IntakeDraft> {
  return Object.fromEntries(sourceOptions.map((source) => [source.id, emptyDraft(source.id)])) as Record<GuidedSource, IntakeDraft>;
}

function emptyProgress(): Record<GuidedSource, SourceProgress> {
  return Object.fromEntries(sourceOptions.map((source) => [source.id, { batches: 0, imported: 0 }])) as Record<GuidedSource, SourceProgress>;
}

function emptySourceScope(): GuidedSourceScope {
  return {
    progress: emptyProgress(),
    drafts: emptyDrafts(),
    mediaItemIds: [],
  };
}

function guidedSourceScopeKey(projectId: string, target: WizardTarget): string {
  return `${projectId || "unassigned"}:${target}`;
}

function storedSourceScopes(projectId: string, target: WizardTarget): Record<string, GuidedSourceScope> {
  try {
    const stored = JSON.parse(
      window.localStorage.getItem(sourceScopesStorageKey) ?? "{}",
    ) as Record<string, Partial<GuidedSourceScope>>;
    const scopes = Object.fromEntries(
      Object.entries(stored).map(([key, value]) => [key, {
        progress: { ...emptyProgress(), ...(value.progress ?? {}) },
        drafts: Object.fromEntries(
          sourceOptions.map((source) => [
            source.id,
            { ...emptyDraft(source.id), ...(value.drafts?.[source.id] ?? {}) },
          ]),
        ) as Record<GuidedSource, IntakeDraft>,
        mediaItemIds: Array.isArray(value.mediaItemIds)
          ? value.mediaItemIds.filter((item): item is string => typeof item === "string")
          : [],
      }]),
    );
    const scopeKey = guidedSourceScopeKey(projectId, target);
    if (
      !scopes[scopeKey]
      && !window.localStorage.getItem(legacyScopeMigrationKey)
      && (
        window.localStorage.getItem(progressStorageKey)
        || window.localStorage.getItem(draftStorageKey)
      )
    ) {
      scopes[scopeKey] = {
        progress: storedProgress(),
        drafts: storedDrafts(),
        mediaItemIds: [],
      };
      window.localStorage.setItem(legacyScopeMigrationKey, scopeKey);
    }
    return scopes;
  } catch {
    return {};
  }
}

function storedDrafts(): Record<GuidedSource, IntakeDraft> {
  const defaults = emptyDrafts();
  try {
    const stored = JSON.parse(window.localStorage.getItem(draftStorageKey) ?? "{}") as Partial<Record<GuidedSource, Partial<IntakeDraft>>>;
    for (const source of sourceOptions) defaults[source.id] = { ...defaults[source.id], ...(stored[source.id] ?? {}) };
  } catch {
    return defaults;
  }
  return defaults;
}

function storedProgress(): Record<GuidedSource, SourceProgress> {
  const defaults = emptyProgress();
  try {
    const stored = JSON.parse(window.localStorage.getItem(progressStorageKey) ?? "{}") as Partial<Record<GuidedSource, SourceProgress>>;
    for (const source of sourceOptions) defaults[source.id] = { ...defaults[source.id], ...(stored[source.id] ?? {}) };
  } catch {
    return defaults;
  }
  return defaults;
}


function targetLabel(target: WizardTarget): string {
  return targetOptions.find((option) => option.id === target)?.label ?? "LoRA";
}

function sourcePlaceholder(source: GuidedSource): string {
  if (source === "instagram") return "https://www.instagram.com/account/";
  if (source === "x") return "https://x.com/account";
  return "https://www.tiktok.com/@account";
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
