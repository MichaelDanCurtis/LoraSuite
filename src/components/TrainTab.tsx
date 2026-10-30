import { TrainingTargetSelect } from "./TrainingTargetSelect";
import { targetsForOutput, trainingTargetLabel } from "../lib/trainingCatalog";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import {
  Archive,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheckBig,
  Copy,
  Database,
  FileText,
  Flag,
  FolderOpen,
  LogIn,
  RefreshCw,
  Save,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { EngineClient } from "../lib/api";
import { credentialIdForVisionProvider } from "../lib/credentials";
import { projectOptionLabel } from "../lib/projects";
import { useCredentialStatus } from "../lib/useCredentialStatus";
import type {
  CharacterProject,
  CaptionGenerationJob,
  DatasetCaptionRecord,
  DatasetDuplicateProposal,
  DatasetItemStatus,
  DatasetSnapshot,
  StrongestSetCandidate,
  DatasetStrongestSetProposal,
  LoraModelCard,
  LoraModelCardOverrides,
  LoraTargetType,
  MediaItem,
  RecipeCompliance,
  RecoveredDatasetExport,
  VisionProviderDialect,
  VisionProviderPreset,
  TrainingTargetProfile,
  VideoDatasetSnapshot,
} from "../lib/types";
import { VoiceDatasetCompiler } from "./VoiceDatasetCompiler";
import { RunComfyTrainingConsole } from "./RunComfyTrainingConsole";
import { VideoDatasetCompiler } from "./VideoDatasetCompiler";
import { IdLoraCompiler } from "./IdLoraCompiler";
import { EvaluationWorkspace } from "./EvaluationWorkspace";
import { RunPodBundleConsole } from "./RunPodBundleConsole";
import { CloudProviderOverview } from "./CloudProviderOverview";
import { RecoveredDatasetConsole } from "./RecoveredDatasetConsole";

type TrainEngine = Pick<
  EngineClient,
  | "assetUrl"
  | "pickDirectory"
  | "listVaultMedia"
  | "listCharacterProjects"
  | "updateCharacterProject"
  | "listDatasetSnapshots"
  | "listTrainingTargets"
  | "getDatasetSnapshot"
  | "compileCharacterDataset"
  | "updateDatasetItem"
  | "updateDatasetModelCard"
  | "bulkUpdateDatasetItems"
  | "proposeDatasetStrongestSet"
  | "proposeDatasetDuplicates"
  | "applyDatasetStrongestSet"
  | "restoreDatasetStrongestSet"
  | "freezeDatasetSnapshot"
  | "exportDatasetSnapshotRunComfy"
  | "listTrainingRuns"
  | "getTrainingRun"
  | "createTrainingRun"
  | "refreshTrainingRun"
  | "resumeTrainingRun"
  | "cancelTrainingRun"
  | "listModelArtifacts"
  | "listModelReleaseCandidates"
  | "selectModelRelease"
  | "registerTrainingArtifacts"
  | "listComfyInstallations"
  | "installModelArtifact"
  | "listVideoDatasetCandidates"
  | "listVideoDatasetSnapshots"
  | "getVideoDatasetSnapshot"
  | "compileVideoDataset"
  | "updateVideoDatasetItem"
  | "bulkUpdateVideoDataset"
  | "freezeVideoDataset"
  | "exportVideoDataset"
  | "listIdLoraManifests"
  | "getIdLoraManifest"
  | "compileIdLoraManifest"
  | "exportIdLoraManifest"
  | "listIdLoraEvaluations"
  | "getIdLoraEvaluation"
  | "createIdLoraEvaluation"
  | "getSyncNetCapability"
  | "getBenchmarkSuite"
  | "prepareBenchmarkWorkspace"
  | "listBenchmarkGenerationRuns"
  | "getBenchmarkGenerationRun"
  | "retryBenchmarkGenerationRun"
  | "createBenchmarkGenerationRun"
  | "createRunPodBenchmarkGenerationRun"
  | "getImageBenchmarkSuite"
  | "prepareImageBenchmarkWorkspace"
  | "createImageBenchmarkGenerationRun"
  | "createRunPodImageBenchmarkGenerationRun"
  | "listImageBenchmarkRuns"
  | "getImageBenchmarkRun"
  | "createImageBenchmarkRun"
  | "listBenchmarkRuns"
  | "getBenchmarkRun"
  | "createBenchmarkRun"
  | "reviewBenchmarkCase"
  | "createRunPodBundle"
  | "listRunPodBundles"
  | "listRunPodInfrastructureProfiles"
  | "provisionRunPodInfrastructure"
  | "listRunPodModelBootstrapRuns"
  | "getRunPodModelBootstrapRun"
  | "createRunPodModelBootstrapRun"
  | "refreshRunPodModelBootstrapRun"
  | "cancelRunPodModelBootstrapRun"
  | "listRunPodBundleUploadJobs"
  | "getRunPodBundleUploadJob"
  | "createRunPodBundleUploadJob"
  | "resumeRunPodBundleUploadJob"
  | "listRunPodPreflightReports"
  | "createRunPodPreflightReport"
  | "listRunPodTrainingRuns"
  | "getRunPodTrainingRun"
  | "createRunPodTrainingRun"
  | "refreshRunPodTrainingRun"
  | "cancelRunPodTrainingRun"
  | "downloadRunPodTrainingArtifacts"
  | "registerRunPodTrainingArtifacts"
  | "getIdentityStatus"
  | "getVoiceIdentityStatus"
  | "listCaptionProviders"
  | "startGrokOAuthLogin"
  | "listCaptionJobs"
  | "getCaptionJob"
  | "cancelCaptionJob"
  | "createCaptionJob"
  | "getCurationHandoff"
  | "getVoiceIdentityProfile"
  | "setVoiceIdentityAnchors"
  | "getVoiceDataset"
  | "compileVoiceDataset"
  | "updateVoiceDatasetSegment"
  | "bulkUpdateVoiceDatasetSegments"
  | "rescoreVoiceDataset"
  | "analyzeVoiceDatasetQuality"
  | "exportVoiceDataset"
  | "listVoiceArtifactEvaluations"
  | "getVoiceArtifactEvaluation"
  | "getRecommendedVoiceArtifactEvaluation"
  | "createVoiceArtifactEvaluation"
  | "selectVoiceArtifactEvaluation"
  | "listCloudProviders"
  | "listCloudRuns"
  | "listRecoveredDatasetExports"
  | "registerRecoveredDatasetExport"
  | "verifyRecoveredDatasetExport"
>;
type DatasetFilter = "all" | DatasetItemStatus;

interface TrainTabProps {
  engine: TrainEngine;
  targetItems?: MediaItem[];
  initialMode?: "image" | "video" | "voice" | "id_lora" | "evaluate";
  evaluationMode?: "image" | "audio_visual";
  activeProjectId?: string;
  guided?: boolean;
  onProjectChange?(projectId: string): void;
  onReturnToPrepare?(): void;
  onReturnToVerify?(): void;
}

const EMPTY_MEDIA_ITEMS: MediaItem[] = [];

export function TrainTab(props: TrainTabProps) {
  const [mode, setMode] = useState<"image" | "video" | "voice" | "id_lora" | "evaluate">(props.initialMode ?? "image");
  const [recoveredDataset, setRecoveredDataset] = useState<RecoveredDatasetExport | null>(null);
  const [recoveredTarget, setRecoveredTarget] = useState<TrainingTargetProfile | undefined>();
  useEffect(() => {
    if (props.initialMode) setMode(props.initialMode);
  }, [props.initialMode]);
  useEffect(() => {
    if (!recoveredDataset) {
      setRecoveredTarget(undefined);
      return;
    }
    let disposed = false;
    props.engine.listTrainingTargets()
      .then((targets) => {
        if (!disposed) {
          setRecoveredTarget(
            targets.find((target) => target.profile_id === recoveredDataset.training_target.profile_id),
          );
        }
      })
      .catch(() => {
        if (!disposed) setRecoveredTarget(undefined);
      });
    return () => {
      disposed = true;
    };
  }, [props.engine, recoveredDataset?.id]);
  const recoveredSnapshot = useMemo(
    () => recoveredDataset ? recoveredTrainingSnapshot(recoveredDataset) : null,
    [recoveredDataset],
  );
  return (
    <div className={`train-mode-workspace ${props.guided ? "guided-train-workspace" : ""}`}>
      {!props.guided ? (
        <div className="train-mode-tabs" role="tablist" aria-label="Dataset compiler modes">
          <button type="button" role="tab" aria-selected={mode === "image"} onClick={() => setMode("image")}>Image Dataset</button>
          <button type="button" role="tab" aria-selected={mode === "video"} onClick={() => setMode("video")}>Video Dataset</button>
          <button type="button" role="tab" aria-selected={mode === "voice"} onClick={() => setMode("voice")}>Voice Dataset</button>
          <button type="button" role="tab" aria-selected={mode === "id_lora"} onClick={() => setMode("id_lora")}>ID-LoRA</button>
          <button type="button" role="tab" aria-selected={mode === "evaluate"} onClick={() => setMode("evaluate")}>Evaluate</button>
        </div>
      ) : null}
      {!props.guided ? <RecoveredDatasetConsole
        engine={props.engine}
        activeRecordId={recoveredDataset?.id}
        onUseForTraining={setRecoveredDataset}
      /> : null}
      {!props.guided && recoveredDataset && recoveredSnapshot ? (
        <section className="recovered-training-provider" aria-label="Recovered dataset training">
          <header>
            <div>
              <Archive size={17} aria-hidden="true" />
              <span>
                <strong>Training from verified export</strong>
                <small>{recoveredDataset.training_target.label} · {recoveredDataset.verified_file_count} verified entries</small>
              </span>
            </div>
            <button type="button" onClick={() => setRecoveredDataset(null)} title="Close recovered training controls">
              <X size={15} />
            </button>
          </header>
          {recoveredDataset.training_target.provider === "runcomfy"
            && (recoveredDataset.modality === "image" || recoveredDataset.modality === "video") ? (
              <RunComfyTrainingConsole
                engine={props.engine}
                snapshot={recoveredSnapshot}
                targetProfile={recoveredTarget}
              />
            ) : null}
          <RunPodBundleConsole
            engine={props.engine}
            sourceExportPath={recoveredDataset.export_path}
            modality={recoveredDataset.modality}
            triggerToken={recoveredDataset.trigger_token}
            fingerprint={recoveredDataset.fingerprint}
            trainingTargetProfileId={recoveredDataset.training_target.profile_id}
          />
        </section>
      ) : null}
      {!props.guided ? <CloudProviderOverview engine={props.engine} projectId={props.activeProjectId} /> : null}
      {props.guided && mode !== "image" && mode !== "evaluate"
        ? <GuidedModalityBuildHeader mode={mode} />
        : null}
      {mode === "image" ? <ImageDatasetCompiler {...props} /> : mode === "video" ? <VideoDatasetCompiler engine={props.engine} activeProjectId={props.activeProjectId} guided={props.guided} onProjectChange={props.onProjectChange} /> : mode === "voice" ? <VoiceDatasetCompiler engine={props.engine} activeProjectId={props.activeProjectId} guided={props.guided} onProjectChange={props.onProjectChange} /> : mode === "id_lora" ? <IdLoraCompiler engine={props.engine} activeProjectId={props.activeProjectId} guided={props.guided} onProjectChange={props.onProjectChange} /> : <EvaluationWorkspace engine={props.engine} activeProjectId={props.activeProjectId} initialMode={props.evaluationMode} onProjectChange={props.onProjectChange} onOpenRevision={setMode} />}
    </div>
  );
}

function GuidedModalityBuildHeader({ mode }: { mode: "video" | "voice" | "id_lora" }) {
  const copy = mode === "video"
    ? {
        eyebrow: "Video LoRA recipe",
        title: "Turn approved motion into a training package",
        detail: "Review clips, captions, split isolation, and recipe checks before freezing the package.",
        steps: ["Clips", "Captions", "Recipe", "Package", "Train"],
      }
    : mode === "voice"
      ? {
          eyebrow: "Voice recipe",
          title: "Turn confirmed speech into a voice package",
          detail: "Segment and transcribe the anchored speaker, pass quality checks, then freeze the package.",
          steps: ["Speech", "Transcript", "Quality", "Package", "Train"],
        }
      : {
          eyebrow: "Living Identity · zero-shot",
          title: "Package references and run the identity adapter",
          detail: "This path aligns frozen video and verified voice references. It does not retrain the adapter per person.",
          steps: ["Video", "Voice", "Alignment", "Package", "Run"],
        };
  return (
    <section className="guided-modality-build-header" aria-label={`${copy.eyebrow} workflow`}>
      <small><Sparkles size={14} aria-hidden="true" /> {copy.eyebrow}</small>
      <h2>{copy.title}</h2>
      <p>{copy.detail}</p>
      <div>
        {copy.steps.map((step, index) => (
          <span key={step}><i>{index + 1}</i>{step}</span>
        ))}
      </div>
    </section>
  );
}

function ImageDatasetCompiler({
  engine,
  targetItems = EMPTY_MEDIA_ITEMS,
  activeProjectId = "",
  guided = false,
  onProjectChange,
  onReturnToPrepare,
  onReturnToVerify,
}: TrainTabProps) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [snapshots, setSnapshots] = useState<DatasetSnapshot[]>([]);
  const [trainingTargets, setTrainingTargets] = useState<TrainingTargetProfile[]>([]);
  const [trainingTargetId, setTrainingTargetId] = useState("runcomfy_flux1_dev_character");
  const [activationWord, setActivationWord] = useState("");
  const [snapshot, setSnapshot] = useState<DatasetSnapshot | null>(null);
  const [vaultMedia, setVaultMedia] = useState<MediaItem[]>(targetItems);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [captionDraft, setCaptionDraft] = useState("");
  const [modelCardDraft, setModelCardDraft] = useState<ModelCardForm>(
    emptyModelCardForm(),
  );
  const [filter, setFilter] = useState<DatasetFilter>("all");
  const [outputDir, setOutputDir] = useState("");
  const [providers, setProviders] = useState<VisionProviderPreset[]>([]);
  const [providerId, setProviderId] = useState("");
  const [providerDialect, setProviderDialect] = useState<VisionProviderDialect>("responses");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");
  const [providerModel, setProviderModel] = useState("");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [oauthLoginPending, setOauthLoginPending] = useState(false);
  const [captionJob, setCaptionJob] = useState<CaptionGenerationJob | null>(null);
  const [liveCaptionHandledIds, setLiveCaptionHandledIds] = useState<Set<string>>(new Set());
  const [liveCaptionActionId, setLiveCaptionActionId] = useState<string | null>(null);
  const liveCaptionProgressRef = useRef(0);
  const storedProviderCredential = useCredentialStatus(
    credentialIdForVisionProvider(providerId),
  );
  const [aiSelectedIds, setAiSelectedIds] = useState<Set<string>>(new Set());
  const aiSelectionSnapshotId = useRef<string | null>(null);
  const [guidedJobId, setGuidedJobId] = useState<string | null>(null);
  const [guidedReviewIds, setGuidedReviewIds] = useState<string[]>([]);
  const [guidedReviewIndex, setGuidedReviewIndex] = useState(0);
  const [guidedDeferredIds, setGuidedDeferredIds] = useState<Set<string>>(new Set());
  const [guidedReviewActive, setGuidedReviewActive] = useState(false);
  const [guidedProvider, setGuidedProvider] = useState<"runcomfy" | "runpod" | null>(null);
  const [advancedOptionsOpen, setAdvancedOptionsOpen] = useState(false);
  const [loadRevision, setLoadRevision] = useState(0);
  const [guidedProviderChooserOpen, setGuidedProviderChooserOpen] = useState(false);
  const [strongestSetTarget, setStrongestSetTarget] = useState(50);
  const [strongestSetProposal, setStrongestSetProposal] = useState<DatasetStrongestSetProposal | null>(null);
  const [strongestSetDisqualified, setStrongestSetDisqualified] = useState<StrongestSetCandidate[]>([]);
  const [strongestSetIncludedIds, setStrongestSetIncludedIds] = useState<string[]>([]);
  const [duplicateProposal, setDuplicateProposal] = useState<DatasetDuplicateProposal | null>(null);
  const [duplicateReviewOpen, setDuplicateReviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading dataset workspace...");
  const canPickOutput = useMemo(
    () => outputDirectoryPicker() !== null || typeof engine.pickDirectory === "function",
    [engine],
  );
  const currentProject = projects.find((candidate) => candidate.id === projectId) ?? null;

  useEffect(() => {
    if (!currentProject) return;
    setActivationWord(
      currentProject.intent.trigger_token || suggestedActivationWord(currentProject),
    );
  }, [currentProject?.id, currentProject?.intent.trigger_token]);

  useEffect(() => {
    let ignore = false;
    async function load() {
      setBusy(true);
      try {
        const [projectPayload, snapshotPayload, mediaPayload, providerPayload, jobPayload, targetPayload] = await Promise.all([
          engine.listCharacterProjects(),
          engine.listDatasetSnapshots(),
          engine.listVaultMedia(),
          engine.listCaptionProviders(),
          engine.listCaptionJobs(),
          engine.listTrainingTargets(),
        ]);
        const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
        const availableSnapshots = Array.isArray(snapshotPayload) ? snapshotPayload : [];
        const initialProjectId = availableProjects.find((project) => project.id === activeProjectId)?.id ?? availableProjects[0]?.id ?? "";
        const initialProject = availableProjects.find((project) => project.id === initialProjectId) ?? null;
        const initialSnapshot = availableSnapshots.find(
          (candidate) => candidate.project_id === initialProjectId,
        ) ?? null;
        const availableTargets = targetsForOutput(Array.isArray(targetPayload) ? targetPayload : [], "image");
        const initialTargetId = initialProject?.intent.training_target_profile_ids?.image
          ?? initialSnapshot?.training_target?.profile_id
          ?? availableTargets[0]?.profile_id
          ?? "runcomfy_flux1_dev_character";
        const availableProviders = Array.isArray(providerPayload) ? providerPayload : [];
        const initialProvider = availableProviders.find((provider) => provider.auth_mode === "local")
          ?? availableProviders[0];
        const initialJob = (Array.isArray(jobPayload) ? jobPayload : []).find(
          (job) => job.snapshot_id === initialSnapshot?.id,
        ) ?? null;
        if (!ignore) {
          setProjects(availableProjects);
          setProjectId(initialProjectId);
          setActivationWord(
            initialProject?.intent.trigger_token
              || (initialProject ? suggestedActivationWord(initialProject) : ""),
          );
          if (initialProjectId && initialProjectId !== activeProjectId) onProjectChange?.(initialProjectId);
          setSnapshots(availableSnapshots);
          setTrainingTargets(availableTargets);
          setTrainingTargetId(initialTargetId);
          setSnapshot(initialSnapshot);
          setVaultMedia(mergeMedia(mediaPayload, targetItems));
          setProviders(availableProviders);
          if (initialProvider) applyProvider(initialProvider);
          setCaptionJob(initialJob);
          setStatus(
            initialSnapshot
              ? `Restored dataset v${initialSnapshot.version}.`
              : availableProjects.length
                ? "No dataset draft has been compiled."
                : "Create an Identity project before compiling a dataset.",
          );
        }
      } catch (error) {
        if (!ignore) setStatus(`Dataset error: ${errorMessage(error)}`);
      } finally {
        if (!ignore) setBusy(false);
      }
    }
    void load();
    return () => {
      ignore = true;
    };
  }, [engine, targetItems, activeProjectId, loadRevision]);

  useEffect(() => {
    const nextSnapshot = snapshots.find(
      (candidate) => candidate.project_id === projectId
        && (candidate.training_target?.profile_id ?? "runcomfy_flux1_dev_character") === trainingTargetId,
    ) ?? null;
    setSnapshot(nextSnapshot);
  }, [projectId, snapshots, trainingTargetId]);

  useEffect(() => {
    const target = trainingTargets.find(
      (candidate) => candidate.profile_id === trainingTargetId,
    );
    const policy = target?.recipe?.dataset;
    const maximum = policy?.maximum_approved_items ?? 80;
    const recommended = policy?.recommended_approved_items ?? 35;
    setStrongestSetTarget(Math.min(maximum, Math.max(recommended, 50)));
    setStrongestSetProposal(null);
    setStrongestSetDisqualified([]);
    setStrongestSetIncludedIds([]);
    setDuplicateProposal(null);
    setDuplicateReviewOpen(false);
  }, [snapshot?.id, trainingTargetId, trainingTargets]);

  const records = useMemo(
    () => Object.values(snapshot?.items ?? {}).sort(compareDatasetRecords),
    [snapshot],
  );
  const visibleRecords = useMemo(
    () => records.filter((record) => filter === "all" || record.status === filter),
    [filter, records],
  );
  const selectedRecord = records.find((record) => record.id === selectedItemId) ?? null;
  const mediaById = useMemo(
    () => new Map(vaultMedia.map((item) => [item.id, item])),
    [vaultMedia],
  );
  const selectedMedia = selectedRecord
    ? mediaById.get(selectedRecord.training_media_item_id) ?? null
    : null;
  const mutable = snapshot?.status === "draft";

  useEffect(() => {
    if (!snapshot) {
      aiSelectionSnapshotId.current = null;
      setAiSelectedIds(new Set());
      return;
    }
    if (aiSelectionSnapshotId.current !== snapshot.id) {
      aiSelectionSnapshotId.current = snapshot.id;
      setAiSelectedIds(new Set(
        Object.values(snapshot.items)
          .filter((record) => record.status === "needs_review")
          .map((record) => record.id),
      ));
    }
  }, [snapshot?.id]);

  useEffect(() => {
    if (visibleRecords.length === 0) {
      setSelectedItemId(null);
      return;
    }
    if (!visibleRecords.some((record) => record.id === selectedItemId)) {
      setSelectedItemId(visibleRecords[0].id);
    }
  }, [selectedItemId, visibleRecords]);

  useEffect(() => {
    setCaptionDraft(selectedRecord?.caption ?? "");
  }, [selectedRecord]);

  useEffect(() => {
    setModelCardDraft(modelCardForm(snapshot?.model_card));
  }, [snapshot?.id, snapshot?.model_card]);

  useEffect(() => {
    liveCaptionProgressRef.current = captionJob?.completed_count ?? 0;
    setLiveCaptionHandledIds(new Set());
    setLiveCaptionActionId(null);
  }, [captionJob?.id]);

  useEffect(() => {
    const jobId = captionJob?.id;
    if (!jobId || !isActiveJob(captionJob)) return;
    const activeJobId = jobId;
    let disposed = false;
    let timer = 0;

    async function pollJob() {
      try {
        const updatedJob = await engine.getCaptionJob(activeJobId);
        if (disposed) return;
        setCaptionJob(updatedJob);
        setStatus(captionJobStatus(updatedJob));
        const hasNewCaptions = updatedJob.completed_count > liveCaptionProgressRef.current;
        let updatedSnapshot: DatasetSnapshot | null = null;
        if (hasNewCaptions || !isActiveJob(updatedJob)) {
          updatedSnapshot = await engine.getDatasetSnapshot(updatedJob.snapshot_id);
          if (disposed) return;
          liveCaptionProgressRef.current = updatedJob.completed_count;
          acceptSnapshot(updatedSnapshot);
        }
        if (isActiveJob(updatedJob)) {
          timer = window.setTimeout(pollJob, 700);
          return;
        }
        updatedSnapshot ??= await engine.getDatasetSnapshot(updatedJob.snapshot_id);
        if (!disposed) {
          acceptSnapshot(updatedSnapshot);
          if (guidedJobId === updatedJob.id) {
            const readyIds = updatedJob.item_ids.filter((itemId) => {
              const record = updatedSnapshot.items[itemId];
              return record?.status === "needs_review" && record.caption_source === "vision";
            });
            if (readyIds.length) beginGuidedReview(readyIds);
            setGuidedJobId(null);
          }
        }
      } catch (error) {
        if (!disposed) setStatus(`Caption job error: ${errorMessage(error)}`);
      }
    }

    timer = window.setTimeout(pollJob, 350);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [captionJob?.id, engine, guidedJobId]);

  useEffect(() => {
    if (!oauthLoginPending) return;
    let cancelled = false;
    let attempts = 0;
    let timer = 0;

    async function refreshOAuthStatus() {
      attempts += 1;
      try {
        const refreshedProviders = await engine.listCaptionProviders();
        if (cancelled) return;
        setProviders(refreshedProviders);
        const grokOAuth = refreshedProviders.find((provider) => provider.id === "grok_oauth");
        if (grokOAuth?.configured) {
          applyProvider(grokOAuth);
          setOauthLoginPending(false);
          setStatus("Grok OAuth connected. It is ready for image captioning.");
          return;
        }
      } catch (error) {
        if (!cancelled) setStatus(`Grok OAuth status error: ${errorMessage(error)}`);
      }
      if (!cancelled && attempts < 150) timer = window.setTimeout(refreshOAuthStatus, 2_000);
    }

    void refreshOAuthStatus();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [engine, oauthLoginPending]);

  function acceptSnapshot(updated: DatasetSnapshot) {
    setSnapshot(updated);
    setSnapshots((existing) => [
      updated,
      ...existing.filter((candidate) => candidate.id !== updated.id),
    ]);
  }

  async function compileDataset() {
    if (!projectId || busy) return;
    if (!trainingTargets.some((target) => target.profile_id === trainingTargetId)) { setStatus("Choose an image recipe before compiling."); return; }
    setBusy(true);
    setStatus("Compiling accepted identity observations and crop lineage...");
    try {
      const updated = await engine.compileCharacterDataset(projectId, trainingTargetId);
      acceptSnapshot(updated);
      const refreshedMedia = await engine.listVaultMedia();
      setVaultMedia(mergeMedia(refreshedMedia, targetItems));
      setStatus(`Dataset v${updated.version} compiled with ${updated.balance.total_count} items.`);
    } catch (error) {
      setStatus(`Dataset error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function selectTrainingTarget(profileId: string) {
    setTrainingTargetId(profileId);
    if (!currentProject || currentProject.intent.training_target_profile_ids?.image === profileId) return;
    const intent = {
      ...currentProject.intent,
      training_target_profile_ids: {
        ...currentProject.intent.training_target_profile_ids,
        image: profileId,
      },
    };
    void engine.updateCharacterProject(currentProject.id, { intent })
      .then((updated) => {
        setProjects((items) => items.map((item) => item.id === updated.id ? updated : item));
      })
      .catch((error) => setStatus(`Could not save the image recipe: ${errorMessage(error)}`));
  }

  async function saveGuidedActivationWord() {
    const normalizedWord = normalizeActivationWord(activationWord);
    if (!currentProject || !normalizedWord || busy) return;
    setBusy(true);
    setStatus("Saving the prompt name and refreshing the dataset...");
    try {
      const updatedProject = await engine.updateCharacterProject(currentProject.id, {
        intent: {
          ...currentProject.intent,
          trigger_token: normalizedWord,
        },
      });
      setProjects((existing) => existing.map((candidate) => (
        candidate.id === updatedProject.id ? updatedProject : candidate
      )));
      setActivationWord(normalizedWord);
      const updatedSnapshot = await engine.compileCharacterDataset(
        updatedProject.id,
        trainingTargetId,
      );
      acceptSnapshot(updatedSnapshot);
      setStatus(`Prompt name saved as ${normalizedWord}.`);
    } catch (error) {
      setStatus(`Prompt name error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function applyProvider(provider: VisionProviderPreset) {
    setProviderId(provider.id);
    setProviderDialect(provider.dialect);
    setProviderBaseUrl(provider.base_url);
    setProviderModel(provider.model);
    setProviderApiKey("");
  }

  function selectProvider(nextProviderId: string) {
    const provider = providers.find((candidate) => candidate.id === nextProviderId);
    if (provider) applyProvider(provider);
  }

  async function beginGrokOAuthLogin() {
    if (busy || captionJobActive) return;
    setBusy(true);
    setStatus("Opening Grok OAuth sign-in...");
    try {
      const result = await engine.startGrokOAuthLogin();
      setOauthLoginPending(result.started);
      setStatus(result.message);
    } catch (error) {
      setStatus(`Grok OAuth error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function generateCaptions(itemIds: string[], startGuidedReview = false) {
    if (!snapshot || !mutable || busy || isActiveJob(captionJob) || !itemIds.length) return;
    const provider = providers.find((candidate) => candidate.id === providerId);
    if (!provider) {
      setStatus("Choose a vision provider before running the AI caption batch.");
      return;
    }
    if (!providerBaseUrl.trim() || !providerModel.trim()) {
      setStatus(`Complete the ${provider.label} endpoint and model before running the AI caption batch.`);
      return;
    }
    if (provider.auth_mode === "grok_oauth" && !provider.configured) {
      setStatus("Connect Grok OAuth before generating captions.");
      return;
    }
    if (provider.auth_mode === "local" && !provider.configured) {
      setStatus("Apple's on-device model is unavailable. Enable Apple Intelligence or choose another provider.");
      return;
    }
    if (provider.auth_mode === "api_key" && !provider.configured && !providerApiKey.trim() && !storedProviderCredential) {
      setStatus(`Enter or save a ${provider.label} API key, or configure its environment variable.`);
      return;
    }
    setBusy(true);
    setStatus(`Queueing ${itemIds.length} image${itemIds.length === 1 ? "" : "s"} for ${provider.label}...`);
    try {
      const job = await engine.createCaptionJob(snapshot.id, {
        item_ids: itemIds,
        provider_id: provider.id,
        provider_label: provider.label,
        dialect: providerDialect,
        base_url: providerBaseUrl.trim(),
        model: providerModel.trim(),
        api_key: provider.auth_mode === "api_key" ? providerApiKey.trim() || undefined : undefined,
      });
      setCaptionJob(job);
      if (startGuidedReview) setGuidedJobId(job.id);
      setProviderApiKey("");
      setStatus(captionJobStatus(job));
    } catch (error) {
      setStatus(`Caption job error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function cancelCaptioning() {
    if (!captionJob || !isActiveJob(captionJob) || busy) return;
    setBusy(true);
    setStatus("Stopping caption generation...");
    try {
      const canceledJob = await engine.cancelCaptionJob(captionJob.id);
      setCaptionJob(canceledJob);
      setGuidedJobId(null);
      setStatus(captionJobStatus(canceledJob));
    } catch (error) {
      setStatus(`Caption job error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function beginGuidedReview(itemIds: string[]) {
    if (!itemIds.length) {
      setGuidedReviewActive(false);
      setStatus("AI review finished without any completed visual analyses. Failed items remain in the review queue.");
      return;
    }
    setGuidedReviewIds(itemIds);
    setGuidedReviewIndex(0);
    setGuidedDeferredIds(new Set());
    setGuidedReviewActive(true);
    setFilter("needs_review");
    setSelectedItemId(itemIds[0]);
    setStatus(`Guided review ready: ${itemIds.length} AI-analyzed decisions.`);
  }

  async function startAiReview() {
    await generateCaptions(selectedReviewIds, true);
  }

  function selectAllForAi() {
    setAiSelectedIds(new Set(reviewItemIds));
  }

  function clearAiSelection() {
    setAiSelectedIds(new Set());
  }

  function toggleAiSelection(itemId: string) {
    setAiSelectedIds((existing) => {
      const updated = new Set(existing);
      if (updated.has(itemId)) updated.delete(itemId);
      else updated.add(itemId);
      return updated;
    });
  }

  function advanceGuidedReview(deferred = false) {
    const currentId = guidedReviewIds[guidedReviewIndex];
    if (deferred && currentId) {
      setGuidedDeferredIds((existing) => new Set(existing).add(currentId));
    }
    const nextIndex = guidedReviewIndex + 1;
    const nextId = guidedReviewIds[nextIndex];
    if (nextId) {
      setGuidedReviewIndex(nextIndex);
      setSelectedItemId(nextId);
      return;
    }
    setGuidedReviewActive(false);
    setFilter("needs_review");
    setStatus(
      `Guided review complete. ${guidedDeferredIds.size + (deferred ? 1 : 0)} deferred item${guidedDeferredIds.size + (deferred ? 1 : 0) === 1 ? " remains" : "s remain"} in the ? queue.`,
    );
  }

  function returnToPreviousGuidedReview() {
    const previousIndex = guidedReviewIndex - 1;
    const previousId = guidedReviewIds[previousIndex];
    if (previousIndex < 0 || !previousId) return;
    setGuidedReviewIndex(previousIndex);
    setSelectedItemId(previousId);
  }

  async function approveGuidedItem() {
    if (!snapshot || !mutable || busy) return;
    const itemId = guidedReviewIds[guidedReviewIndex];
    if (!itemId) return;
    setBusy(true);
    setStatus(`Approving decision ${guidedReviewIndex + 1} of ${guidedReviewIds.length}...`);
    try {
      const updated = await engine.updateDatasetItem(snapshot.id, itemId, { status: "approved" });
      acceptSnapshot(updated);
      setGuidedDeferredIds((existing) => {
        const next = new Set(existing);
        next.delete(itemId);
        return next;
      });
      advanceGuidedReview();
    } catch (error) {
      setStatus(`Caption error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function deferLiveCaption(itemId: string) {
    setLiveCaptionHandledIds((existing) => new Set(existing).add(itemId));
    setStatus("Saved in the caption edit queue. AI is still generating the rest.");
  }

  async function approveLiveCaption(itemId: string) {
    if (!snapshot || !mutable || liveCaptionActionId) return;
    setLiveCaptionActionId(itemId);
    try {
      const updated = await engine.updateDatasetItem(snapshot.id, itemId, {
        status: "approved",
      });
      acceptSnapshot(updated);
      setLiveCaptionHandledIds((existing) => new Set(existing).add(itemId));
      setStatus("Caption approved. AI is still generating the rest.");
    } catch (error) {
      setStatus(`Caption error: ${errorMessage(error)}`);
    } finally {
      setLiveCaptionActionId(null);
    }
  }

  async function approveAllGuidedItems() {
    if (!snapshot || !mutable || busy) return;
    const itemIds = guidedReviewIds.filter((itemId) => (
      !guidedDeferredIds.has(itemId)
      && snapshot.items[itemId]?.status === "needs_review"
    ));
    if (!itemIds.length) {
      setGuidedReviewActive(false);
      setStatus("No remaining AI decisions to approve. Deferred items remain available for review.");
      return;
    }
    setBusy(true);
    setStatus(`YOLO approving ${itemIds.length} AI decision${itemIds.length === 1 ? "" : "s"}...`);
    try {
      const updated = await engine.bulkUpdateDatasetItems(snapshot.id, "approved", itemIds);
      acceptSnapshot(updated);
      setGuidedReviewActive(false);
      setFilter("needs_review");
      const deferredCount = guidedDeferredIds.size;
      setStatus(
        `${itemIds.length} AI decision${itemIds.length === 1 ? "" : "s"} approved.${deferredCount ? ` ${deferredCount} deferred item${deferredCount === 1 ? " remains" : "s remain"} for review.` : ""}`,
      );
    } catch (error) {
      setStatus(`Dataset error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveItem(update: {
    caption?: string;
    status?: DatasetItemStatus;
  }) {
    if (!snapshot || !selectedRecord || !mutable || busy) return;
    setBusy(true);
    setStatus("Saving caption record...");
    try {
      const updated = await engine.updateDatasetItem(snapshot.id, selectedRecord.id, update);
      acceptSnapshot(updated);
      setStatus("Caption record saved.");
    } catch (error) {
      setStatus(`Caption error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function approveReviewQueue() {
    if (!snapshot || !mutable || busy) return;
    const itemIds = records
      .filter((record) => record.status === "needs_review")
      .map((record) => record.id);
    if (!itemIds.length) return;
    setBusy(true);
    setStatus("Approving reviewed caption queue...");
    try {
      const updated = await engine.bulkUpdateDatasetItems(snapshot.id, "approved", itemIds);
      acceptSnapshot(updated);
      setStatus(`${itemIds.length} caption records approved.`);
    } catch (error) {
      setStatus(`Dataset error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function previewStrongestSet() {
    if (!snapshot || busy) return;
    setBusy(true);
    setStatus(`Ranking the strongest ${strongestSetTarget} images locally...`);
    try {
      const proposal = await engine.proposeDatasetStrongestSet(
        snapshot.id,
        strongestSetTarget,
      );
      setStrongestSetProposal(proposal);
      setStrongestSetDisqualified([]);
      setStrongestSetIncludedIds([]);
      setStatus(
        `Strongest-set preview ready: ${proposal.selected_count} keep, ${proposal.excluded_count} parked.`,
      );
    } catch (error) {
      setStatus(`Strongest-set error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function disqualifyStrongestCandidate(candidate: StrongestSetCandidate) {
    if (!snapshot || busy) return;
    const nextDisqualified = [...strongestSetDisqualified, candidate];
    setStrongestSetDisqualified(nextDisqualified);
    setBusy(true);
    setStatus("Moving that image to its group’s disqualified stack...");
    try {
      const disqualifiedIds = nextDisqualified.map((item) => item.item_id);
      const proposal = strongestSetIncludedIds.length
        ? await engine.proposeDatasetStrongestSet(
            snapshot.id,
            strongestSetTarget,
            disqualifiedIds,
            strongestSetIncludedIds,
          )
        : await engine.proposeDatasetStrongestSet(
            snapshot.id,
            strongestSetTarget,
            disqualifiedIds,
          );
      setStrongestSetProposal(proposal);
      setStatus(
        `Image disqualified. The next-best ${candidate.group.replace("_", " ")} candidate was promoted.`,
      );
    } catch (error) {
      setStrongestSetDisqualified(strongestSetDisqualified);
      setStatus(`Strongest-set error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function exchangeStrongestCandidate(
    outgoing: StrongestSetCandidate,
    incomingItemId: string,
  ) {
    if (!snapshot || busy || outgoing.item_id === incomingItemId) return;
    const nextDisqualified = [
      ...strongestSetDisqualified.filter(
        (candidate) => candidate.item_id !== incomingItemId
          && candidate.item_id !== outgoing.item_id,
      ),
      outgoing,
    ];
    const nextIncludedIds = [
      ...strongestSetIncludedIds.filter(
        (itemId) => itemId !== outgoing.item_id && itemId !== incomingItemId,
      ),
      incomingItemId,
    ];
    setBusy(true);
    setStatus("Exchanging the parked image with the selected circle image...");
    try {
      const proposal = await engine.proposeDatasetStrongestSet(
        snapshot.id,
        strongestSetTarget,
        nextDisqualified.map((candidate) => candidate.item_id),
        nextIncludedIds,
      );
      setStrongestSetDisqualified(nextDisqualified);
      setStrongestSetIncludedIds(nextIncludedIds);
      setStrongestSetProposal(proposal);
      setStatus(
        `Exchange staged. ${proposal.selected_count} images remain in the circle; apply the set to save it.`,
      );
    } catch (error) {
      setStatus(`Strongest-set error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function scanDatasetDuplicates() {
    if (!snapshot || busy) return;
    if (duplicateProposal?.snapshot_id === snapshot.id) {
      setDuplicateReviewOpen(true);
      setStatus(
        duplicateProposal.duplicate_count
          ? `Reopened ${duplicateProposal.clusters.length} reviewed duplicate groups.`
          : "Reopened the completed dedupe scan.",
      );
      return;
    }
    setBusy(true);
    setStatus(`Scanning ${records.length} images for exact and near duplicates locally...`);
    try {
      const proposal = await engine.proposeDatasetDuplicates(snapshot.id);
      setDuplicateProposal(proposal);
      setDuplicateReviewOpen(true);
      setStatus(
        proposal.duplicate_count
          ? `Dedupe review ready: ${proposal.duplicate_count} likely duplicate${proposal.duplicate_count === 1 ? "" : "s"} in ${proposal.clusters.length} group${proposal.clusters.length === 1 ? "" : "s"}.`
          : `Dedupe scan complete: no likely duplicates found in ${proposal.scanned_count} images.`,
      );
    } catch (error) {
      setStatus(`Dedupe error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyDatasetDedupe(keepers: Record<string, string>) {
    if (!snapshot || !duplicateProposal || busy) return;
    const duplicateItemIds = duplicateProposal.clusters.flatMap((cluster) => (
      cluster.candidates
        .filter((candidate) => candidate.item_id !== keepers[cluster.id])
        .map((candidate) => candidate.item_id)
    ));
    if (!duplicateItemIds.length) {
      setDuplicateReviewOpen(false);
      return;
    }
    setBusy(true);
    setStatus(`Parking ${duplicateItemIds.length} reviewed duplicate images...`);
    try {
      let workingSnapshot = snapshot;
      if (!mutable) {
        setStatus("Creating an editable dataset version before deduping...");
        workingSnapshot = await engine.compileCharacterDataset(
          projectId,
          trainingTargetId,
        );
        acceptSnapshot(workingSnapshot);
      }
      const updated = await engine.bulkUpdateDatasetItems(
        workingSnapshot.id,
        "excluded",
        duplicateItemIds,
      );
      acceptSnapshot(updated);
      setDuplicateProposal(null);
      setDuplicateReviewOpen(false);
      setStrongestSetProposal(null);
      setStrongestSetDisqualified([]);
      setStrongestSetIncludedIds([]);
      setFilter("all");
      setStatus(
        `Dedupe complete: ${duplicateItemIds.length} duplicate image${duplicateItemIds.length === 1 ? "" : "s"} parked. The chosen keepers remain active.`,
      );
    } catch (error) {
      setStatus(`Dedupe error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyStrongestSet() {
    if (!snapshot || !strongestSetProposal || busy) return;
    setBusy(true);
    setStatus(`Applying the strongest ${strongestSetProposal.selected_count} images...`);
    try {
      let workingSnapshot = snapshot;
      if (!mutable) {
        setStatus("Creating an editable dataset version from the exported package...");
        workingSnapshot = await engine.compileCharacterDataset(
          projectId,
          trainingTargetId,
        );
        acceptSnapshot(workingSnapshot);
      }
      const disqualifiedIds = strongestSetDisqualified.map((item) => item.item_id);
      const result = strongestSetIncludedIds.length
        ? await engine.applyDatasetStrongestSet(
            workingSnapshot.id,
            strongestSetProposal.target_count,
            disqualifiedIds,
            strongestSetIncludedIds,
          )
        : disqualifiedIds.length
        ? await engine.applyDatasetStrongestSet(
            workingSnapshot.id,
            strongestSetProposal.target_count,
            disqualifiedIds,
          )
        : await engine.applyDatasetStrongestSet(
            workingSnapshot.id,
            strongestSetProposal.target_count,
          );
      acceptSnapshot(result.snapshot);
      setStrongestSetProposal(result.proposal);
      setStrongestSetDisqualified([]);
      setStrongestSetIncludedIds([]);
      setFilter("all");
      setStatus(
        `Strongest set applied: ${result.proposal.selected_count} active, ${result.proposal.excluded_count} parked and recoverable.`,
      );
    } catch (error) {
      setStatus(`Strongest-set error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function restoreStrongestSet() {
    if (!snapshot || !mutable || busy) return;
    setBusy(true);
    setStatus("Restoring images parked by the strongest-set pass...");
    try {
      const updated = await engine.restoreDatasetStrongestSet(snapshot.id);
      acceptSnapshot(updated);
      setStrongestSetProposal(null);
      setStrongestSetDisqualified([]);
      setStrongestSetIncludedIds([]);
      setFilter("all");
      setStatus("Strongest-set changes restored. Manual exclusions were preserved.");
    } catch (error) {
      setStatus(`Strongest-set error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveModelCard() {
    if (!snapshot || busy || !engine.updateDatasetModelCard) return;
    setBusy(true);
    setStatus("Saving model card metadata...");
    try {
      const updated = await engine.updateDatasetModelCard(
        snapshot.id,
        modelCardOverrides(modelCardDraft),
      );
      acceptSnapshot(updated);
      setStatus(
        updated.model_card?.validation.status === "ready"
          ? "Model card is release-ready."
          : "Model card saved. Review the remaining release checks.",
      );
    } catch (error) {
      setStatus(`Model card error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function freezeDataset() {
    if (!snapshot || !mutable || busy) return;
    setBusy(true);
    setStatus("Freezing immutable dataset version...");
    try {
      const updated = await engine.freezeDatasetSnapshot(snapshot.id);
      acceptSnapshot(updated);
      setStatus(`Dataset v${updated.version} frozen: ${updated.fingerprint?.slice(0, 12)}.`);
    } catch (error) {
      setStatus(`Freeze error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseOutputFolder() {
    const picker = outputDirectoryPicker();
    try {
      const path = picker
        ? await picker()
        : engine.pickDirectory
          ? (await engine.pickDirectory()).path
          : null;
      if (path) setOutputDir(path);
    } catch (error) {
      if (!isAbortError(error)) setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function exportDataset() {
    const normalizedOutputDir = normalizeOutputPath(outputDir);
    if (!snapshot || snapshot.status === "draft" || !normalizedOutputDir || busy) return;
    setBusy(true);
    setStatus("Writing RunComfy image and caption pairs...");
    setOutputDir(normalizedOutputDir);
    try {
      const result = await engine.exportDatasetSnapshotRunComfy(snapshot.id, normalizedOutputDir);
      acceptSnapshot(result.snapshot);
      setStatus(`Export complete: ${result.package.output_path}`);
    } catch (error) {
      setStatus(`Export error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const balance = snapshot?.balance;
  const selectedProvider = providers.find((provider) => provider.id === providerId);
  const reviewItemIds = records
    .filter((record) => record.status === "needs_review")
    .map((record) => record.id);
  const selectedReviewIds = guided && !advancedOptionsOpen
    ? reviewItemIds
    : reviewItemIds.filter((itemId) => aiSelectedIds.has(itemId));
  const readyReviewIds = records
    .filter((record) => record.status === "needs_review" && record.caption_source === "vision")
    .map((record) => record.id);
  const captionJobActive = isActiveJob(captionJob);
  const liveCaptionRecord = useMemo(() => {
    if (!captionJobActive || !captionJob || !snapshot) return null;
    const processedCount = Math.min(
      captionJob.next_item_index ?? captionJob.completed_count + captionJob.failed_count,
      captionJob.item_ids.length,
    );
    const failedIds = new Set(captionJob.errors.map((error) => error.item_id));
    const availableIds = captionJob.item_ids.slice(0, processedCount).filter((itemId) => {
      const record = snapshot.items[itemId];
      return (
        !failedIds.has(itemId)
        && !liveCaptionHandledIds.has(itemId)
        && record?.caption_source === "vision"
        && record.status === "needs_review"
      );
    });
    const itemId = availableIds[0];
    return itemId ? snapshot.items[itemId] : null;
  }, [captionJob, captionJobActive, liveCaptionHandledIds, snapshot]);
  const liveCaptionMedia = liveCaptionRecord
    ? mediaById.get(liveCaptionRecord.training_media_item_id) ?? null
    : null;
  const selectedTrainingTarget = trainingTargets.find(
    (target) => target.profile_id === trainingTargetId,
  );
  const strongestSetPolicy = selectedTrainingTarget?.recipe?.dataset;
  const strongestSetAppliedCount = records.filter(
    (record) => record.strongest_set_excluded,
  ).length;
  const strongestSetMaximum = strongestSetPolicy?.maximum_approved_items ?? 80;
  const narrowingRequired = records.length > strongestSetMaximum && strongestSetAppliedCount === 0;
  const failedRecipeBlockers = balance?.recipe_compliance?.checks.filter(
    (check) => !check.passed && check.severity === "blocker",
  ) ?? [];
  const activationWordRequired = failedRecipeBlockers.some(
    (check) => check.check_id === "trigger-token",
  );
  const guidedNextAction = guided
    ? guidedBuildAction({
        snapshot,
        reviewCount: balance?.review_count ?? 0,
        readyReviewCount: readyReviewIds.length,
        approvedCount: balance?.approved_count ?? 0,
        failedRecipeBlockers,
        outputDir,
        canPickOutput,
        busy,
        captionJobActive,
        narrowingRequired,
        strongestSetTarget,
        onCompile: compileDataset,
        onNarrowDataset: previewStrongestSet,
        onAnalyzeCaptions: startAiReview,
        onStartReview: () => beginGuidedReview(readyReviewIds),
        onReviewCaptions: () => scrollToElement("vision-captioning"),
        onReturnToPrepare,
        onReturnToVerify,
        onFreeze: freezeDataset,
        onChooseOutput: canPickOutput
          ? chooseOutputFolder
          : () => scrollToElement("dataset-export"),
        onExport: exportDataset,
        onContinue: () => setGuidedProviderChooserOpen(true),
      })
    : null;
  const guidedProviderStage = Boolean(
    snapshot?.status === "exported"
    && snapshot.export_path
    && (guidedProviderChooserOpen || guidedProvider),
  );
  if (guided) {
    return (
      <section className="workspace-section dataset-workspace guided-build-simple">
        {!guidedProviderStage ? (
          <GuidedTrainingRecipe
            targets={trainingTargets}
            selectedTargetId={trainingTargetId}
            snapshot={snapshot}
            action={activationWordRequired ? null : guidedNextAction}
            busy={busy}
            captionJob={captionJob}
            outputDir={outputDir}
            canPickOutput={canPickOutput}
            activationWord={activationWord}
            activationWordRequired={activationWordRequired}
            onCancelCaptioning={cancelCaptioning}
            onSelect={selectTrainingTarget}
            onOutputDirChange={setOutputDir}
            onChooseOutput={chooseOutputFolder}
            onActivationWordChange={(value) => setActivationWord(normalizeActivationWord(value))}
            onSaveActivationWord={saveGuidedActivationWord}
          />
        ) : null}
        {!guidedProviderStage && snapshot && records.length > (strongestSetPolicy?.maximum_approved_items ?? 80) ? (
          <StrongestSetPanel
            records={records}
            mediaById={mediaById}
            proposal={strongestSetProposal}
            disqualified={strongestSetDisqualified}
            includedItemIds={strongestSetIncludedIds}
            duplicateProposal={duplicateReviewOpen ? duplicateProposal : null}
            target={strongestSetTarget}
            minimum={strongestSetPolicy?.minimum_approved_items ?? 20}
            recommended={strongestSetPolicy?.recommended_approved_items ?? 35}
            maximum={strongestSetPolicy?.maximum_approved_items ?? 80}
            appliedCount={strongestSetAppliedCount}
            busy={busy}
            mutable={mutable}
            assetUrl={engine.assetUrl}
            onTargetChange={(value) => {
              setStrongestSetTarget(value);
              setStrongestSetProposal(null);
              setStrongestSetDisqualified([]);
              setStrongestSetIncludedIds([]);
            }}
            onPreview={previewStrongestSet}
            onScanDedupe={scanDatasetDuplicates}
            onApplyDedupe={applyDatasetDedupe}
            onCloseDedupe={() => setDuplicateReviewOpen(false)}
            onDisqualify={disqualifyStrongestCandidate}
            onExchange={exchangeStrongestCandidate}
            onApply={applyStrongestSet}
            onRestore={restoreStrongestSet}
            onCancel={() => {
              setStrongestSetProposal(null);
              setStrongestSetDisqualified([]);
              setStrongestSetIncludedIds([]);
            }}
          />
        ) : null}
        {!guidedProviderStage && captionJobActive && liveCaptionRecord ? (
          <GuidedLiveCaptionReview
            record={liveCaptionRecord}
            media={liveCaptionMedia}
            completed={captionJob?.completed_count ?? 0}
            total={captionJob?.total_count ?? 0}
            flaggedCount={liveCaptionHandledIds.size}
            actionPending={liveCaptionActionId === liveCaptionRecord.id}
            assetUrl={engine.assetUrl}
            onDefer={() => deferLiveCaption(liveCaptionRecord.id)}
            onApprove={() => approveLiveCaption(liveCaptionRecord.id)}
          />
        ) : null}
        {!guidedProviderStage && guidedReviewActive && selectedRecord ? (
          <GuidedCaptionDecision
            record={selectedRecord}
            media={selectedMedia}
            current={guidedReviewIndex + 1}
            total={guidedReviewIds.length}
            busy={busy}
            assetUrl={engine.assetUrl}
            canGoBack={guidedReviewIndex > 0}
            onBack={returnToPreviousGuidedReview}
            onDefer={() => advanceGuidedReview(true)}
            onApprove={approveGuidedItem}
            onApproveAll={approveAllGuidedItems}
          />
        ) : null}
        {!advancedOptionsOpen && snapshot?.status === "exported"
          && snapshot.export_path
          && (guidedProviderChooserOpen || guidedProvider) ? (
          <section
            className="guided-trainer-choice guided-trainer-stage"
            aria-label={guidedProviderChooserOpen ? "Choose training provider" : "Training provider workspace"}
          >
            <header>
              <small><Upload size={13} aria-hidden="true" /> Package ready</small>
              <h3>
                {guidedProviderChooserOpen
                  ? "Where should LoraSuite train it?"
                  : `Training with ${guidedProvider === "runpod" ? "RunPod" : "RunComfy"}`}
              </h3>
              {guidedProviderChooserOpen && guidedProvider ? (
                <button type="button" onClick={() => setGuidedProviderChooserOpen(false)}>
                  Keep {guidedProvider === "runpod" ? "RunPod" : "RunComfy"}
                </button>
              ) : guidedProvider ? (
                <button type="button" onClick={() => setGuidedProviderChooserOpen(true)}>
                  Change provider
                </button>
              ) : null}
            </header>
            {guidedProviderChooserOpen ? (
              <>
                <p className="guided-provider-advice">
                  Not sure? Choose RunComfy. Choose RunPod when you already use it or need control over the endpoint and network volume.
                </p>
                <div className="guided-trainer-buttons" role="group" aria-label="Training provider">
                  <button
                    type="button"
                    className={`recommended ${guidedProvider === "runcomfy" ? "active" : ""}`}
                    onClick={() => {
                      setGuidedProvider("runcomfy");
                      setGuidedProviderChooserOpen(false);
                    }}
                  >
                    <Sparkles size={20} aria-hidden="true" />
                    <span>
                      <strong>RunComfy</strong>
                      <small>Managed setup · simplest first run · pay for the training job</small>
                    </span>
                    <em>Recommended</em>
                  </button>
                  <button
                    type="button"
                    className={guidedProvider === "runpod" ? "active" : ""}
                    onClick={() => {
                      setGuidedProvider("runpod");
                      setGuidedProviderChooserOpen(false);
                    }}
                  >
                    <Database size={20} aria-hidden="true" />
                    <span>
                      <strong>RunPod</strong>
                      <small>Bring your own account · configure infrastructure · maximum control</small>
                    </span>
                    <em>Advanced</em>
                  </button>
                </div>
              </>
            ) : selectedTrainingTarget?.ready && guidedProvider ? (
              guidedProvider === "runcomfy" ? (
                <RunComfyTrainingConsole engine={engine} snapshot={snapshot} targetProfile={selectedTrainingTarget} />
              ) : (
                <RunPodBundleConsole engine={engine} sourceExportPath={snapshot.export_path} modality="image" triggerToken={snapshot.intent.trigger_token} fingerprint={snapshot.fingerprint ?? snapshot.id} trainingTargetProfileId={snapshot.training_target?.profile_id} />
              )
            ) : !guidedProviderChooserOpen ? (
              <div className="guided-launcher-pending">
                <ShieldAlert size={18} aria-hidden="true" />
                <span><strong>The dataset package is ready.</strong><small>Automatic cloud training for {selectedTrainingTarget?.label ?? "this model"} is not enabled until its launcher passes an end-to-end training run. Your package is complete; models marked Cloud ready can train from LoraSuite now.</small></span>
              </div>
            ) : null}
          </section>
        ) : null}
        <details className="guided-advanced-options" onToggle={(event) => setAdvancedOptionsOpen(event.currentTarget.open)}>
          <summary>Advanced dataset options</summary>
          <p>Detailed image selection, caption providers, recipe checks, metadata, export, and training controls for this same dataset.</p>
          {advancedOptionsOpen ? renderAdvanced() : null}
        </details>
        <p aria-live="polite" className="guided-build-status">{status}</p>
      {status.startsWith("Dataset error:") ? <button type="button" onClick={() => setLoadRevision((value) => value + 1)}>Retry dataset workspace</button> : null}
      </section>
    );
  }
  return renderAdvanced();

  function renderAdvanced() {
  return (
    <section className="workspace-section dataset-workspace">
      <header className="dataset-commandbar">
        <div className="dataset-project-title">
          <Database size={20} aria-hidden="true" />
          <div>
            <h2>Dataset Compiler</h2>
            <p>{snapshot ? `${snapshot.project_name} · v${snapshot.version}` : "Character training dataset"}</p>
          </div>
        </div>
        <label className="dataset-project-select">
          Project
          <select value={projectId} onChange={(event) => { setProjectId(event.target.value); onProjectChange?.(event.target.value); }} disabled={busy}>
            {projects.length ? projects.map((project) => <option key={project.id} value={project.id}>{projectOptionLabel(project)} ({project.health.accepted_count} accepted)</option>) : <option value="">No Identity projects</option>}
          </select>
        </label>
        <label className="dataset-target-select">
          Target
          <TrainingTargetSelect targets={trainingTargets} output="image" label="Image target" value={trainingTargetId} onChange={selectTrainingTarget} disabled={busy} />
        </label>
        <span className={`snapshot-state ${snapshot?.status ?? "empty"}`}>{snapshot?.status ?? "not compiled"}</span>
        <div className="dataset-header-actions">
          <button type="button" onClick={compileDataset} disabled={!projectId || busy}>
            <RefreshCw size={14} className={busy ? "spin" : ""} /> {snapshot?.status === "draft" ? "Recompile" : "Build Draft"}
          </button>
          <button type="button" onClick={approveReviewQueue} disabled={!mutable || !balance?.review_count || busy}>
            <Check size={14} /> Approve Review
          </button>
          <button className="primary-action" type="button" onClick={freezeDataset} disabled={!mutable || !!balance?.review_count || !balance?.approved_count || busy}>
            <Archive size={14} /> Freeze
          </button>
        </div>
      </header>

      <dl className="dataset-health-strip compact" aria-label="Compiled dataset balance">
        <Metric label="Items" value={balance?.total_count ?? 0} />
        <Metric label="Approved" value={balance?.approved_count ?? 0} tone="good" />
        <Metric label="Review" value={balance?.review_count ?? 0} tone="warn" />
        <Metric label="Excluded" value={balance?.excluded_count ?? 0} />
        <Metric label="Cropped" value={balance?.cropped_count ?? 0} />
        <Metric label="Sources" value={balance?.source_count ?? 0} />
        <Metric label="Quality" value={percent(balance?.average_quality)} />
        <Metric label="Diversity" value={percent(balance?.average_diversity)} />
      </dl>

      {balance?.warnings.length ? (
        <div className="health-warnings dataset-warnings" aria-label="Dataset compiler warnings">
          <ShieldAlert size={16} aria-hidden="true" />
          <div>{balance.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>
        </div>
      ) : null}

      {snapshot && records.length > (strongestSetPolicy?.maximum_approved_items ?? 80) ? (
        <StrongestSetPanel
          records={records}
          mediaById={mediaById}
          proposal={strongestSetProposal}
          disqualified={strongestSetDisqualified}
          includedItemIds={strongestSetIncludedIds}
          duplicateProposal={duplicateReviewOpen ? duplicateProposal : null}
          target={strongestSetTarget}
          minimum={strongestSetPolicy?.minimum_approved_items ?? 20}
          recommended={strongestSetPolicy?.recommended_approved_items ?? 35}
          maximum={strongestSetPolicy?.maximum_approved_items ?? 80}
          appliedCount={strongestSetAppliedCount}
          busy={busy}
          mutable={mutable}
          assetUrl={engine.assetUrl}
          onTargetChange={(value) => {
            setStrongestSetTarget(value);
            setStrongestSetProposal(null);
            setStrongestSetDisqualified([]);
            setStrongestSetIncludedIds([]);
          }}
          onPreview={previewStrongestSet}
          onScanDedupe={scanDatasetDuplicates}
          onApplyDedupe={applyDatasetDedupe}
          onCloseDedupe={() => setDuplicateReviewOpen(false)}
          onDisqualify={disqualifyStrongestCandidate}
          onExchange={exchangeStrongestCandidate}
          onApply={applyStrongestSet}
          onRestore={restoreStrongestSet}
          onCancel={() => {
            setStrongestSetProposal(null);
            setStrongestSetDisqualified([]);
            setStrongestSetIncludedIds([]);
          }}
        />
      ) : null}

      <section id="vision-captioning" className="vision-caption-bar" aria-label="Vision caption generation">
        <div className="vision-caption-title">
          <Sparkles size={17} aria-hidden="true" />
          <span><strong>Vision Captioning</strong><small>Batch first. Human review after completion.</small></span>
        </div>
        <label>
          Provider
          <select aria-label="Vision provider" value={providerId} onChange={(event) => selectProvider(event.target.value)} disabled={busy || captionJobActive}>
            {providers.length ? providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}{provider.configured ? " · ready" : ""}</option>) : <option value="">No providers</option>}
          </select>
        </label>
        <label>
          Model
          <input aria-label="Vision model" value={providerModel} onChange={(event) => setProviderModel(event.target.value)} disabled={busy || captionJobActive || selectedProvider?.auth_mode === "local"} />
        </label>
        {selectedProvider?.auth_mode === "local" ? (
          <div className={`vision-oauth-connection ${selectedProvider.configured ? "ready" : "required"}`}>
            <span><Sparkles size={14} aria-hidden="true" /> {selectedProvider.configured ? "On-device model ready · no API charges" : "Apple Intelligence unavailable"}</span>
          </div>
        ) : selectedProvider?.auth_mode === "grok_oauth" ? (
          <div className={`vision-oauth-connection ${selectedProvider.configured ? "ready" : "required"}`}>
            <span><LogIn size={14} aria-hidden="true" /> {selectedProvider.configured ? "OAuth session ready" : "OAuth sign-in required"}</span>
            {!selectedProvider.configured ? <button type="button" onClick={beginGrokOAuthLogin} disabled={busy || captionJobActive || oauthLoginPending}><LogIn size={14} /> {oauthLoginPending ? "Waiting for sign-in" : "Sign in"}</button> : null}
          </div>
        ) : (
          <label>
            API key
            <input aria-label="Vision API key" type="password" autoComplete="off" value={providerApiKey} onChange={(event) => setProviderApiKey(event.target.value)} placeholder={selectedProvider?.configured ? "Environment key available" : storedProviderCredential ? "Stored securely or enter an override" : "Used for this job only"} disabled={busy || captionJobActive} />
          </label>
        )}
        <div className="vision-caption-actions">
          {<button type="button" onClick={() => generateCaptions(selectedRecord ? [selectedRecord.id] : [])} disabled={!mutable || !selectedRecord || busy || captionJobActive}><Sparkles size={14} /> Selected</button>}
          <button className="primary-action" type="button" onClick={startAiReview} disabled={!mutable || !selectedReviewIds.length || busy || captionJobActive}><Sparkles size={14} /> {guided && !advancedOptionsOpen ? `Analyze all ${selectedReviewIds.length}` : `AI Review (${selectedReviewIds.length})`}</button>
          {readyReviewIds.length > 0 && !guidedReviewActive && !captionJobActive ? <button type="button" onClick={() => beginGuidedReview(readyReviewIds)} disabled={!mutable || busy}><Check size={14} /> Start Review</button> : null}
        </div>
        <details className="vision-provider-advanced">
          <summary><SlidersHorizontal size={14} /> Provider details</summary>
          <div>
            <label>API format<select aria-label="Vision API format" value={providerDialect} onChange={(event) => setProviderDialect(event.target.value as VisionProviderDialect)} disabled={busy || captionJobActive || selectedProvider?.auth_mode !== "api_key"}><option value="responses">Responses API</option><option value="chat_completions">Chat Completions</option><option value="grok_cli">Grok CLI OAuth</option><option value="apple_foundation">Apple Foundation Models</option></select></label>
            <label>Endpoint<input aria-label="Vision endpoint" value={providerBaseUrl} onChange={(event) => setProviderBaseUrl(event.target.value)} disabled={busy || captionJobActive || selectedProvider?.auth_mode !== "api_key"} /></label>
          </div>
        </details>
        {captionJob ? (
          <div className={`caption-job-progress ${captionJob.status}`} aria-label="Caption job progress">
            <progress max={Math.max(captionJob.total_count, 1)} value={captionJob.completed_count + captionJob.failed_count} />
            <span>{captionJob.progress_message}</span>
            <strong>{captionJob.completed_count}/{captionJob.total_count}</strong>
            {captionJob.failed_count ? <i title={captionJob.errors.map((error) => error.message ?? JSON.stringify(error)).join("\n")}>{captionJob.failed_count} failed</i> : null}
            {captionJobActive ? <button type="button" onClick={cancelCaptioning} disabled={busy}><X size={13} /> Stop</button> : null}
          </div>
        ) : null}
      </section>

      {guidedReviewActive ? (
        <section className="guided-review-bar" aria-label="Guided AI review">
          <div className="guided-review-summary">
            <span><Sparkles size={15} aria-hidden="true" /><strong>AI decision {guidedReviewIndex + 1} of {guidedReviewIds.length}</strong></span>
            <small>{selectedRecord?.unresolved_attributes.length ? `${selectedRecord.unresolved_attributes.length} visual check${selectedRecord.unresolved_attributes.length === 1 ? "" : "s"} still need confirmation` : "All requested visual evidence confirmed"}</small>
          </div>
          <div className="guided-review-sequence" aria-label="AI decision sequence">
            {guidedReviewIds.map((itemId, index) => {
              const record = snapshot?.items[itemId];
              const media = record ? mediaById.get(record.training_media_item_id) : null;
              return (
                <button
                  key={itemId}
                  type="button"
                  className={`${index === guidedReviewIndex ? "current" : ""} ${record?.status === "approved" ? "approved" : ""} ${guidedDeferredIds.has(itemId) ? "deferred" : ""}`}
                  onClick={() => { setGuidedReviewIndex(index); setSelectedItemId(itemId); }}
                  aria-label={`Decision ${index + 1}`}
                >
                  {media?.raw_path ? <img src={engine.assetUrl(media.raw_path)} alt="" /> : <span>{index + 1}</span>}
                </button>
              );
            })}
          </div>
          <div className="guided-review-actions">
            <button type="button" onClick={() => advanceGuidedReview(true)} disabled={busy}>Not Yet <ChevronRight size={14} /></button>
            <button className="primary-action" type="button" onClick={approveGuidedItem} disabled={busy}><Check size={15} /> Yes, Approve <ChevronRight size={14} /></button>
          </div>
        </section>
      ) : null}

      {!snapshot ? (
        <div className="empty-state dataset-empty">
          <Database size={28} aria-hidden="true" />
          <p>Compile the accepted candidates from an Identity project.</p>
          <button className="primary-action" type="button" onClick={compileDataset} disabled={!projectId || busy}>Build Dataset Draft</button>
        </div>
      ) : (
        <div className="dataset-compiler-layout">
          <aside className="dataset-queue" aria-label="Caption review queue">
            <div className="dataset-queue-header">
              <div className="segmented-control" role="group" aria-label="Caption status filter">
                {(["all", "needs_review", "approved", "excluded"] as DatasetFilter[]).map((option) => (
                  <button key={option} type="button" aria-label={filterAriaLabel(option)} title={filterAriaLabel(option)} aria-pressed={filter === option} onClick={() => setFilter(option)}>{filterLabel(option)}</button>
                ))}
              </div>
              <span>{visibleRecords.length}</span>
            </div>
            {!guided || advancedOptionsOpen ? (
              <div className="dataset-ai-selection" aria-label="AI review selection controls">
                <span><Sparkles size={12} /> {selectedReviewIds.length} of {reviewItemIds.length} selected</span>
                <div>
                  <button type="button" onClick={selectAllForAi} disabled={!mutable || !reviewItemIds.length || selectedReviewIds.length === reviewItemIds.length}>Select All</button>
                  <button type="button" onClick={clearAiSelection} disabled={!mutable || !selectedReviewIds.length}>Clear</button>
                </div>
              </div>
            ) : null}
            <div className="dataset-queue-list">
              {visibleRecords.map((record) => {
                const media = mediaById.get(record.training_media_item_id);
                return (
                  <div key={record.id} className={`dataset-queue-item ${record.id === selectedItemId ? "active" : ""}`}>
                    <button type="button" className="dataset-queue-focus" onClick={() => setSelectedItemId(record.id)} aria-label={`Review caption ${fileName(media)}`}>
                      {media?.raw_path ? <img src={engine.assetUrl(media.raw_path)} alt="" /> : <span className="dataset-thumb-placeholder"><Database size={16} /></span>}
                      <span><strong>{fileName(media)}</strong><small>{record.view.replace("_", " ")} · {record.crop_recipe_id ? "crop" : "original"}</small></span>
                      <i className={record.status}>{statusLetter(record.status)}</i>
                    </button>
                    {record.status === "needs_review" ? (
                      <button
                        type="button"
                        className={`dataset-ai-toggle ${aiSelectedIds.has(record.id) ? "selected" : ""}`}
                        aria-label={`${aiSelectedIds.has(record.id) ? "Remove" : "Select"} ${fileName(media)} ${aiSelectedIds.has(record.id) ? "from" : "for"} AI review`}
                        aria-pressed={aiSelectedIds.has(record.id)}
                        onClick={() => toggleAiSelection(record.id)}
                        disabled={!mutable || captionJobActive}
                      >
                        {aiSelectedIds.has(record.id) ? <Check size={12} /> : null}
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </aside>

          <section className="dataset-canvas" aria-label="Caption image preview">
            <div className="dataset-canvas-toolbar">
              <strong>{fileName(selectedMedia)}</strong>
              <span>{selectedRecord?.crop_recipe_id ? "materialized crop" : "source image"}</span>
            </div>
            <div className="dataset-image-stage">
              {selectedMedia?.raw_path ? (
                <div className="dataset-training-frame">
                  <img src={engine.assetUrl(selectedMedia.raw_path)} alt={fileName(selectedMedia)} />
                  <span className="training-boundary"><i>{selectedRecord?.crop_recipe_id ? "Exported crop boundary" : "Full source boundary"}</i></span>
                  {selectedRecord ? <div className="training-caption-overlay"><small>Training caption</small><span>{selectedRecord.caption}</span></div> : null}
                </div>
              ) : <p>Select a caption record.</p>}
            </div>
            {selectedRecord ? <div className="dataset-image-facts"><span>{selectedRecord.view.replace("_", " ")}</span><span>Q {percent(selectedRecord.quality_score)}</span><span>ID {selectedRecord.identity_score == null ? "--" : percent(selectedRecord.identity_score)}</span></div> : null}
          </section>

          <aside className="caption-inspector" aria-label="Caption inspector">
            {selectedRecord ? (
              <>
                <section className="caption-section">
                  <div className="caption-heading"><h3>Training Caption</h3><span>{selectedRecord.caption_source.replace("_", " ")}</span></div>
                  <textarea aria-label="Training caption" rows={6} value={captionDraft} onChange={(event) => setCaptionDraft(event.target.value)} disabled={!mutable || busy} />
                  <button type="button" onClick={() => saveItem({ caption: captionDraft })} disabled={!mutable || busy || captionDraft.trim() === selectedRecord.caption}><Save size={14} /> Save Caption</button>
                </section>
                <section className="caption-section">
                  <div className="caption-heading"><h3>Known Evidence</h3><span>{selectedRecord.tags.length}</span></div>
                  <div className="caption-tags">{selectedRecord.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                  {selectedRecord.unresolved_attributes.length ? <div className="unresolved-attributes"><strong>Needs visual confirmation</strong>{selectedRecord.unresolved_attributes.map((attribute) => <span key={attribute}>{attribute}</span>)}</div> : null}
                  {selectedRecord.caption_provider ? <div className="caption-provenance"><span><strong>{selectedRecord.caption_provider}</strong>{selectedRecord.caption_model}</span><span>{selectedRecord.caption_confidence == null ? "" : percent(selectedRecord.caption_confidence)}</span></div> : null}
                </section>
                <section className="caption-section">
                  <div className="caption-heading"><h3>Decision</h3><span>{selectedRecord.status.replace("_", " ")}</span></div>
                  <div className="caption-decisions" role="group" aria-label={`Dataset decision for ${fileName(selectedMedia)}`}>
                    <button type="button" className={selectedRecord.status === "approved" ? "active approve" : "approve"} onClick={() => saveItem({ status: "approved" })} disabled={!mutable || busy} title="Approve"><Check size={15} /></button>
                    <button type="button" className={selectedRecord.status === "needs_review" ? "active review" : "review"} onClick={() => saveItem({ status: "needs_review" })} disabled={!mutable || busy} title="Needs review"><RefreshCw size={14} /></button>
                    <button type="button" className={selectedRecord.status === "excluded" ? "active exclude" : "exclude"} onClick={() => saveItem({ status: "excluded" })} disabled={!mutable || busy} title="Exclude"><X size={15} /></button>
                  </div>
                </section>
              </>
            ) : null}
          </aside>
        </div>
      )}

      {snapshot?.model_card ? (
        <ModelCardBuilder
          card={snapshot.model_card}
          draft={modelCardDraft}
          onChange={setModelCardDraft}
          onSave={saveModelCard}
          busy={busy}
          guided={guided}
        />
      ) : null}

      {snapshot?.status === "exported" && snapshot.export_path ? (
        <section className="dataset-export-success" aria-label="Dataset export complete">
          <CircleCheckBig size={21} aria-hidden="true" />
          <span><strong>Dataset export complete</strong><small>{normalizeOutputPath(snapshot.export_path)}</small></span>
        </section>
      ) : null}
      <section id="dataset-export" className={`dataset-export-bar ${canPickOutput ? "with-picker" : "web-output"}`} aria-label="RunComfy dataset export">
        <div><Upload size={17} aria-hidden="true" /><span><strong>RunComfy</strong><small>{snapshot?.fingerprint ? `Fingerprint ${snapshot.fingerprint.slice(0, 12)}` : "Freeze a reviewed version before export"}</small></span></div>
        <label>Output folder<input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} onBlur={() => setOutputDir(normalizeOutputPath(outputDir))} placeholder="/absolute/path/to/runcomfy-dataset" /></label>
        {canPickOutput ? <button type="button" onClick={chooseOutputFolder} disabled={busy} title="Choose output folder"><FolderOpen size={15} /></button> : null}
        <button className="primary-action" type="button" onClick={exportDataset} disabled={!snapshot || snapshot.status === "draft" || !outputDir.trim() || busy}><Upload size={15} /> Export Dataset</button>
      </section>
      {snapshot?.status === "exported" ? (
        <div id="training-provider">
          <RunComfyTrainingConsole
            engine={engine}
            snapshot={snapshot}
            targetProfile={selectedTrainingTarget}
          />
          {snapshot.export_path ? <RunPodBundleConsole engine={engine} sourceExportPath={snapshot.export_path} modality="image" triggerToken={snapshot.intent.trigger_token} fingerprint={snapshot.fingerprint ?? snapshot.id} trainingTargetProfileId={snapshot.training_target?.profile_id} /> : null}
        </div>
      ) : null}
      <p aria-live="polite" className="status-line dataset-status-line">{status}</p>
      {status.startsWith("Dataset error:") ? <button type="button" onClick={() => setLoadRevision((value) => value + 1)}>Retry dataset workspace</button> : null}
    </section>
  );
}
}

interface GuidedBuildAction {
  label: string;
  detail: string;
  tone: "primary" | "warning" | "complete";
  run(): void;
  disabled?: boolean;
}

function GuidedBuildPreflight({
  snapshot,
  action,
  busy,
}: {
  snapshot: DatasetSnapshot | null;
  action: GuidedBuildAction | null;
  busy: boolean;
}) {
  const balance = snapshot?.balance;
  const compliance = balance?.recipe_compliance;
  const modelCard = snapshot?.model_card;
  const checks = [
    {
      id: "dataset",
      label: "Dataset",
      state: snapshot ? "ready" : "pending",
      detail: snapshot
        ? `${balance?.total_count ?? 0} compiled · ${balance?.approved_count ?? 0} approved`
        : "Build accepted identity evidence",
    },
    {
      id: "captions",
      label: "Captions",
      state: !snapshot
        ? "pending"
        : balance?.review_count
          ? "blocked"
          : "ready",
      detail: !snapshot
        ? "Waiting for dataset"
        : balance?.review_count
          ? `${balance.review_count} need review`
          : "Reviewed and approved",
    },
    {
      id: "recipe",
      label: "Recipe",
      state: !compliance
        ? "pending"
        : compliance.blocker_count
          ? "blocked"
          : compliance.warning_count
            ? "review"
            : "ready",
      detail: !compliance
        ? "Compile to measure"
        : compliance.blocker_count
          ? `${compliance.blocker_count} blocking check${compliance.blocker_count === 1 ? "" : "s"}`
          : compliance.warning_count
            ? `${compliance.warning_count} coverage advisory`
            : "All targets met",
    },
    {
      id: "metadata",
      label: "Metadata",
      state: !modelCard
        ? "pending"
        : modelCard.validation.blocker_count
          ? "blocked"
          : modelCard.validation.warning_count
            ? "review"
            : "ready",
      detail: !modelCard
        ? "Generated with the dataset"
        : modelCard.validation.blocker_count
          ? `${modelCard.validation.blocker_count} required field${modelCard.validation.blocker_count === 1 ? "" : "s"}`
          : modelCard.validation.warning_count
            ? `${modelCard.validation.warning_count} release advisory`
            : "Release-ready model card",
    },
    {
      id: "package",
      label: "Package",
      state: snapshot?.status === "exported"
        ? "ready"
        : snapshot?.status === "frozen"
          ? "review"
          : "pending",
      detail: snapshot?.status === "exported"
        ? "Ready for a provider"
        : snapshot?.status === "frozen"
          ? "Choose a destination"
          : "Freeze the reviewed version",
    },
  ];
  return (
    <section className="guided-build-preflight" aria-label="Guided build preflight">
      <div className="guided-preflight-track">
        {checks.map((check, index) => (
          <div className={`guided-preflight-step ${check.state}`} key={check.id}>
            {index > 0 ? <i aria-hidden="true" /> : null}
            <span>{check.state === "ready" ? <Check size={13} /> : index + 1}</span>
            <div><strong>{check.label}</strong><small>{check.detail}</small></div>
          </div>
        ))}
      </div>
      {action ? (
        <button
          className={`guided-preflight-action ${action.tone === "primary" ? "primary-action" : action.tone}`}
          type="button"
          onClick={action.run}
          disabled={busy || action.disabled}
        >
          <span><strong>{action.label}</strong><small>{action.detail}</small></span>
          <ChevronRight size={16} />
        </button>
      ) : null}
    </section>
  );
}

function guidedBuildAction({
  snapshot,
  reviewCount,
  readyReviewCount,
  approvedCount,
  failedRecipeBlockers,
  outputDir,
  canPickOutput,
  busy,
  captionJobActive,
  narrowingRequired,
  strongestSetTarget,
  onCompile,
  onNarrowDataset,
  onAnalyzeCaptions,
  onStartReview,
  onReviewCaptions,
  onReturnToPrepare,
  onReturnToVerify,
  onFreeze,
  onChooseOutput,
  onExport,
  onContinue,
}: {
  snapshot: DatasetSnapshot | null;
  reviewCount: number;
  readyReviewCount: number;
  approvedCount: number;
  failedRecipeBlockers: RecipeCompliance["checks"];
  outputDir: string;
  canPickOutput: boolean;
  busy: boolean;
  captionJobActive: boolean;
  narrowingRequired: boolean;
  strongestSetTarget: number;
  onCompile(): void;
  onNarrowDataset(): void;
  onAnalyzeCaptions(): void;
  onStartReview(): void;
  onReviewCaptions(): void;
  onReturnToPrepare?(): void;
  onReturnToVerify?(): void;
  onFreeze(): void;
  onChooseOutput(): void;
  onExport(): void;
  onContinue(): void;
}): GuidedBuildAction {
  if (!snapshot) {
    return {
      label: "Build dataset draft",
      detail: "Compile the accepted identity evidence against this recipe.",
      tone: "primary",
      run: onCompile,
      disabled: busy,
    };
  }
  const identityBlocker = failedRecipeBlockers.find(
    (check) => check.check_id === "intent" || check.check_id === "trigger-token",
  );
  if (identityBlocker) {
    return {
      label: "Return to identity",
      detail: identityBlocker.detail,
      tone: "warning",
      run: onReturnToVerify ?? onReviewCaptions,
    };
  }
  if (narrowingRequired) {
    return {
      label: `Review strongest ${strongestSetTarget}`,
      detail: "Remove duplicates and park weaker images before spending time or tokens on captions.",
      tone: "primary",
      run: onNarrowDataset,
    };
  }
  if (captionJobActive) {
    return {
      label: "AI is preparing the captions",
      detail: "Finished captions appear below for review while LoraSuite keeps working.",
      tone: "complete",
      run: onReviewCaptions,
      disabled: true,
    };
  }
  if (readyReviewCount > 0) {
    return {
      label: `Review ${readyReviewCount} AI decision${readyReviewCount === 1 ? "" : "s"}`,
      detail: "Check the finished suggestions quickly before LoraSuite packages them.",
      tone: "primary",
      run: onStartReview,
    };
  }
  if (reviewCount > 0 || failedRecipeBlockers.some((check) => check.check_id.startsWith("caption"))) {
    return {
      label: `Let AI caption ${reviewCount} item${reviewCount === 1 ? "" : "s"}`,
      detail: "Captions appear as they finish, and the batch keeps running while you review.",
      tone: "primary",
      run: onAnalyzeCaptions,
    };
  }
  if (!approvedCount) {
    return {
      label: "Return to Prepare",
      detail: "Select usable identity media before building the package.",
      tone: "warning",
      run: onReturnToPrepare ?? onReviewCaptions,
    };
  }
  if (snapshot.status === "draft") {
    return {
      label: "Freeze reviewed version",
      detail: "Create the immutable fingerprint used by training and evaluation.",
      tone: "primary",
      run: onFreeze,
    };
  }
  if (snapshot.status === "frozen" && !outputDir.trim()) {
    return {
      label: canPickOutput ? "Choose package destination" : "Enter package destination",
      detail: "Select where LoraSuite should write the provider-ready package.",
      tone: "primary",
      run: onChooseOutput,
    };
  }
  if (snapshot.status === "frozen") {
    return {
      label: "Export training package",
      detail: "Write images, captions, recipe, fingerprint, and model card.",
      tone: "primary",
      run: onExport,
    };
  }
  return {
    label: "Choose training provider",
    detail: "The package is complete. Continue with RunComfy or RunPod.",
    tone: "complete",
    run: onContinue,
  };
}

function scrollToElement(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

interface ModelCardForm {
  name: string;
  displayName: string;
  description: string;
  license: string;
  tags: string;
  intendedUse: string;
  limitations: string;
  samplePrompts: string;
  recommendedStrength: string;
}

function ModelCardBuilder({
  card,
  draft,
  onChange,
  onSave,
  busy,
  guided,
}: {
  card: LoraModelCard;
  draft: ModelCardForm;
  onChange(value: ModelCardForm): void;
  onSave(): void;
  busy: boolean;
  guided: boolean;
}) {
  const failedChecks = card.validation.checks.filter((check) => !check.passed);
  const update = (field: keyof ModelCardForm, value: string) => {
    onChange({ ...draft, [field]: value });
  };
  return (
    <details className="model-card-builder" open={guided || undefined}>
      <summary>
        <span>
          <FileText size={17} aria-hidden="true" />
          <strong>LoRA Metadata</strong>
          <small>{card.name} · {card.base_model}</small>
        </span>
        <i className={card.validation.status}>
          {card.validation.status === "ready"
            ? "Release ready"
            : `${failedChecks.length} check${failedChecks.length === 1 ? "" : "s"}`}
        </i>
      </summary>
      <div className="model-card-body">
        <div className="model-card-facts" aria-label="Generated model facts">
          <span><small>Base model</small><strong>{card.base_model}</strong></span>
          <span><small>Trigger</small><strong>{card.trigger_token || "Not set"}</strong></span>
          <span><small>Recipe</small><strong>{card.recipe_id ? `${card.recipe_id} v${card.recipe_version}` : "Custom"}</strong></span>
          <span><small>Dataset</small><strong>{String(card.dataset.fingerprint ?? "Draft")}</strong></span>
        </div>
        <div className="model-card-editor">
          <label>
            Artifact name
            <input aria-label="Artifact name" value={draft.name} onChange={(event) => update("name", event.target.value)} />
          </label>
          <label>
            Display name
            <input aria-label="Model display name" value={draft.displayName} onChange={(event) => update("displayName", event.target.value)} />
          </label>
          <label>
            License
            <input aria-label="Model license" value={draft.license} onChange={(event) => update("license", event.target.value)} placeholder="Specify before publishing" />
          </label>
          <label>
            Recommended strength
            <input aria-label="Recommended LoRA strength" type="number" min="0" max="2" step="0.05" value={draft.recommendedStrength} onChange={(event) => update("recommendedStrength", event.target.value)} placeholder="Verify after evaluation" />
          </label>
          <label className="wide">
            Description
            <textarea aria-label="Model description" rows={3} value={draft.description} onChange={(event) => update("description", event.target.value)} />
          </label>
          <label className="wide">
            Tags
            <input aria-label="Model tags" value={draft.tags} onChange={(event) => update("tags", event.target.value)} placeholder="character, flux1, portrait" />
          </label>
          <label>
            Sample prompts
            <textarea aria-label="Sample prompts" rows={4} value={draft.samplePrompts} onChange={(event) => update("samplePrompts", event.target.value)} />
          </label>
          <label>
            Intended use
            <textarea aria-label="Intended use" rows={4} value={draft.intendedUse} onChange={(event) => update("intendedUse", event.target.value)} />
          </label>
          <label className="wide">
            Limitations
            <textarea aria-label="Model limitations" rows={3} value={draft.limitations} onChange={(event) => update("limitations", event.target.value)} />
          </label>
        </div>
        <div className="model-card-validation">
          <div>
            <strong>Release checks</strong>
            <small>Generated facts are locked; these checks cover publishable metadata.</small>
          </div>
          <ul>
            {card.validation.checks.map((check) => (
              <li key={check.check_id} className={check.passed ? "passed" : check.severity}>
                {check.passed ? <Check size={13} /> : <ShieldAlert size={13} />}
                <span><strong>{check.label}</strong><small>{check.passed ? "Complete" : check.message}</small></span>
              </li>
            ))}
          </ul>
          <button className="primary-action" type="button" onClick={onSave} disabled={busy}>
            <Save size={14} /> Save Metadata
          </button>
        </div>
      </div>
    </details>
  );
}

function emptyModelCardForm(): ModelCardForm {
  return {
    name: "",
    displayName: "",
    description: "",
    license: "",
    tags: "",
    intendedUse: "",
    limitations: "",
    samplePrompts: "",
    recommendedStrength: "",
  };
}

function modelCardForm(card: LoraModelCard | null | undefined): ModelCardForm {
  if (!card) return emptyModelCardForm();
  return {
    name: card.name,
    displayName: card.display_name,
    description: card.description,
    license: card.license,
    tags: card.tags.join(", "),
    intendedUse: stringList(card.usage.intended_use).join("\n"),
    limitations: stringList(card.usage.limitations).join("\n"),
    samplePrompts: stringList(card.usage.sample_prompts).join("\n"),
    recommendedStrength: typeof card.usage.recommended_strength === "number"
      ? String(card.usage.recommended_strength)
      : "",
  };
}

function modelCardOverrides(form: ModelCardForm): LoraModelCardOverrides {
  const strength = form.recommendedStrength.trim();
  return {
    name: form.name.trim(),
    display_name: form.displayName.trim(),
    description: form.description.trim(),
    license: form.license.trim(),
    tags: splitTerms(form.tags, /[,\n]/),
    intended_use: splitTerms(form.intendedUse, /\n/),
    limitations: splitTerms(form.limitations, /\n/),
    sample_prompts: splitTerms(form.samplePrompts, /\n/),
    recommended_strength: strength ? Number(strength) : null,
  };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function splitTerms(value: string, separator: RegExp): string[] {
  return value.split(separator).map((item) => item.trim()).filter(Boolean);
}

function Metric({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return <div className={tone}><dt>{label}</dt><dd>{value}</dd></div>;
}

const strongestSetGroups = [
  { id: "face", label: "Face", startAngle: -135, endAngle: -45 },
  { id: "upper_body", label: "Upper body", startAngle: -45, endAngle: 45 },
  { id: "full_body", label: "Full body", startAngle: 45, endAngle: 135 },
  { id: "environment", label: "Environment", startAngle: 135, endAngle: 225 },
] as const;

function StrongestSetPanel({
  records,
  mediaById,
  proposal,
  disqualified,
  includedItemIds,
  duplicateProposal,
  target,
  minimum,
  recommended,
  maximum,
  appliedCount,
  busy,
  mutable,
  assetUrl,
  onTargetChange,
  onPreview,
  onScanDedupe,
  onApplyDedupe,
  onCloseDedupe,
  onDisqualify,
  onExchange,
  onApply,
  onRestore,
  onCancel,
}: {
  records: DatasetCaptionRecord[];
  mediaById: Map<string, MediaItem>;
  proposal: DatasetStrongestSetProposal | null;
  disqualified: StrongestSetCandidate[];
  includedItemIds: string[];
  duplicateProposal: DatasetDuplicateProposal | null;
  target: number;
  minimum: number;
  recommended: number;
  maximum: number;
  appliedCount: number;
  busy: boolean;
  mutable: boolean;
  assetUrl(path: string): string;
  onTargetChange(value: number): void;
  onPreview(): void;
  onScanDedupe(): void;
  onApplyDedupe(keepers: Record<string, string>): void;
  onCloseDedupe(): void;
  onDisqualify(candidate: StrongestSetCandidate): void;
  onExchange(outgoing: StrongestSetCandidate, incomingItemId: string): void;
  onApply(): void;
  onRestore(): void;
  onCancel(): void;
}) {
  const [mapView, setMapView] = useState({ zoom: 1, originX: 50, originY: 50 });
  const [hoveredStrengthId, setHoveredStrengthId] = useState<string | null>(null);
  const [parkedReviewOpen, setParkedReviewOpen] = useState(false);
  const [pendingSwapInId, setPendingSwapInId] = useState<string | null>(null);
  const [parkedSearch, setParkedSearch] = useState("");
  const [parkedPage, setParkedPage] = useState(0);
  const [dedupeKeepers, setDedupeKeepers] = useState<Record<string, string>>({});
  useEffect(() => {
    setDedupeKeepers(Object.fromEntries(
      duplicateProposal?.clusters.map((cluster) => [
        cluster.id,
        cluster.recommended_keep_item_id,
      ]) ?? [],
    ));
  }, [duplicateProposal]);
  useEffect(() => {
    if (!proposal) {
      setPendingSwapInId(null);
      setParkedReviewOpen(false);
    }
  }, [proposal]);
  const activeCount = records.filter((record) => record.status !== "excluded").length;
  const recordById = useMemo(
    () => new Map(records.map((record) => [record.id, record])),
    [records],
  );
  const strengthMap = useMemo(() => {
    if (!proposal) return [];
    const disqualifiedIds = new Set(disqualified.map((candidate) => candidate.item_id));
    const ranked = proposal.selected
      .filter((candidate) => !disqualifiedIds.has(candidate.item_id))
      .sort((left, right) => (
        right.score - left.score || left.item_id.localeCompare(right.item_id)
      ));
    const groupSizes = new Map<string, number>();
    ranked.forEach((candidate) => {
      const group = strongestSetGroups.some(({ id }) => id === candidate.group)
        ? candidate.group
        : "environment";
      groupSizes.set(group, (groupSizes.get(group) ?? 0) + 1);
    });
    const groupPositions = new Map<string, number>();
    const occupied: Array<{ left: number; top: number; center: boolean }> = [];
    return ranked.map((candidate, rank) => {
      const group = strongestSetGroups.some(({ id }) => id === candidate.group)
        ? candidate.group
        : "environment";
      const groupDefinition = strongestSetGroups.find(({ id }) => id === group)
        ?? strongestSetGroups[3];
      const groupIndex = groupPositions.get(group) ?? 0;
      const groupSize = groupSizes.get(group) ?? 1;
      groupPositions.set(group, groupIndex + 1);
      let left = 50;
      let top = 50;
      if (rank > 0) {
        const desiredRadius = 14 + (rank / Math.max(1, ranked.length - 1)) * 31;
        const preferredAngle = groupDefinition.startAngle + 8
          + ((groupIndex + 0.5) / groupSize)
            * (groupDefinition.endAngle - groupDefinition.startAngle - 16);
        const radii = Array.from({ length: 32 }, (_, index) => 14 + index)
          .sort((a, b) => (
            Math.abs(a - desiredRadius) - Math.abs(b - desiredRadius)
            || a - b
          ));
        const angles = Array.from(
          { length: 19 },
          (_, index) => groupDefinition.startAngle + index * 5,
        ).sort((a, b) => (
          Math.abs(a - preferredAngle) - Math.abs(b - preferredAngle)
          || a - b
        ));
        let placement: { left: number; top: number } | null = null;
        for (const radius of radii) {
          for (const angle of angles) {
            const radians = angle * (Math.PI / 180);
            const candidatePosition = {
              left: 50 + Math.cos(radians) * radius,
              top: 50 + Math.sin(radians) * radius,
            };
            const clearsEveryImage = occupied.every((position) => {
              const distance = Math.hypot(
                candidatePosition.left - position.left,
                candidatePosition.top - position.top,
              );
              return distance >= (position.center ? 11.25 : 7.6);
            });
            if (clearsEveryImage) {
              placement = candidatePosition;
              break;
            }
          }
          if (placement) break;
        }
        if (placement) {
          left = placement.left;
          top = placement.top;
        }
      }
      occupied.push({ left, top, center: rank === 0 });
      const record = recordById.get(candidate.item_id);
      return {
        candidate,
        media: record
          ? mediaById.get(record.training_media_item_id) ?? null
          : null,
        rank,
        group,
        left,
        top,
      };
    });
  }, [disqualified, mediaById, proposal, recordById]);
  const disqualifiedByGroup = useMemo(() => {
    const grouped = new Map<string, Array<{
      candidate: StrongestSetCandidate;
      media: MediaItem | null;
    }>>();
    strongestSetGroups.forEach(({ id }) => grouped.set(id, []));
    disqualified.forEach((candidate) => {
      const group = strongestSetGroups.some(({ id }) => id === candidate.group)
        ? candidate.group
        : "environment";
      const record = recordById.get(candidate.item_id);
      grouped.get(group)?.push({
        candidate,
        media: record
          ? mediaById.get(record.training_media_item_id) ?? null
          : null,
      });
    });
    return grouped;
  }, [disqualified, mediaById, recordById]);
  const parkedItems = useMemo(() => (
    (proposal?.excluded_item_ids ?? []).flatMap((itemId) => {
      const record = recordById.get(itemId);
      if (!record) return [];
      return [{
        itemId,
        record,
        media: mediaById.get(record.training_media_item_id) ?? null,
      }];
    })
  ), [mediaById, proposal, recordById]);
  const filteredParkedItems = useMemo(() => {
    const query = parkedSearch.trim().toLowerCase();
    if (!query) return parkedItems;
    return parkedItems.filter(({ itemId, record }) => (
      itemId.toLowerCase().includes(query)
      || record.caption.toLowerCase().includes(query)
      || record.view.replace("_", " ").includes(query)
    ));
  }, [parkedItems, parkedSearch]);
  const parkedPageSize = 48;
  const parkedPageCount = Math.max(
    1,
    Math.ceil(filteredParkedItems.length / parkedPageSize),
  );
  const visibleParkedItems = filteredParkedItems.slice(
    parkedPage * parkedPageSize,
    (parkedPage + 1) * parkedPageSize,
  );
  const pendingSwapItem = parkedItems.find(
    ({ itemId }) => itemId === pendingSwapInId,
  ) ?? null;
  const hoveredStrength = strengthMap.find(
    ({ candidate }) => candidate.item_id === hoveredStrengthId,
  ) ?? null;
  return (
    <section className="strongest-set-panel" aria-label="Build strongest image set">
      <header>
        <div className="strongest-set-title">
          <span><Sparkles size={18} aria-hidden="true" /></span>
          <div>
            <small>Local dataset optimizer</small>
            <h3>Build the strongest image set</h3>
            <p>Balance identity, quality, framing, sources, and visual variety before captioning or training.</p>
          </div>
        </div>
        {appliedCount > 0 ? (
          <div className="strongest-set-active">
            <strong>{activeCount} active</strong>
            <span>{appliedCount} parked · recoverable</span>
            <button type="button" onClick={onRestore} disabled={!mutable || busy}>
              <RefreshCw size={13} /> Restore parked
            </button>
          </div>
        ) : null}
      </header>

      <div className="strongest-set-controls">
        <label>
          Target images
          <input
            aria-label="Strongest set target images"
            type="number"
            min={minimum}
            max={maximum}
            value={target}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value)) onTargetChange(value);
            }}
            disabled={busy}
          />
        </label>
        <span>
          Recipe range <strong>{minimum}–{maximum}</strong>
          <small>{recommended} recommended · {records.length} available</small>
        </span>
        <button
          type="button"
          className="strongest-set-dedupe-action"
          onClick={onScanDedupe}
          disabled={busy}
        >
          <Copy size={15} /> Dedupe
        </button>
        <button
          type="button"
          className="strongest-set-preview-action"
          onClick={onPreview}
          disabled={busy}
        >
          <SlidersHorizontal size={15} /> Preview strongest {target}
        </button>
      </div>

      {proposal ? (
        <div className="strongest-set-proposal" aria-label="Strongest set preview">
          <div className="strongest-set-metrics">
            <span><small>Keep</small><strong>{proposal.selected_count}</strong></span>
            <span><small>Park</small><strong>{proposal.excluded_count}</strong></span>
            <span><small>Quality</small><strong>{percent(proposal.average_quality)}</strong></span>
            <span><small>Identity</small><strong>{percent(proposal.average_identity)}</strong></span>
            <span><small>Sources</small><strong>{Object.keys(proposal.source_counts).length}</strong></span>
          </div>
          <div className="strongest-set-coverage">
            {Object.entries(proposal.view_counts).map(([view, count]) => (
              <span key={view}>{view.replace("_", " ")} <strong>{count}</strong></span>
            ))}
            <button
              type="button"
              className="strongest-set-browse-parked"
              onClick={() => setParkedReviewOpen(true)}
            >
              Browse parked <strong>{proposal.excluded_count}</strong>
            </button>
          </div>
          <div className="strongest-set-map-shell">
            <div className="strongest-set-map-groups" aria-label="Strength map groups">
              {strongestSetGroups.map(({ id, label }) => (
                <span aria-label={`${label} group`} key={id}>
                  {label}
                  <strong>{proposal.view_counts[id] ?? 0}</strong>
                </span>
              ))}
            </div>
            <div className="strongest-set-map-workspace">
              <div
                className="strongest-set-map-viewport"
                aria-label="Zoomable image strength map"
                onWheel={(event) => {
                  event.preventDefault();
                  const bounds = event.currentTarget.getBoundingClientRect();
                  const originX = bounds.width
                    ? ((event.clientX - bounds.left) / bounds.width) * 100
                    : 50;
                  const originY = bounds.height
                    ? ((event.clientY - bounds.top) / bounds.height) * 100
                    : 50;
                  setMapView((current) => ({
                    zoom: Math.max(1, Math.min(3, current.zoom - event.deltaY * 0.0015)),
                    originX: Math.max(0, Math.min(100, originX)),
                    originY: Math.max(0, Math.min(100, originY)),
                  }));
                }}
              >
                <div
                  className="strongest-set-map"
                  aria-label="Selected image strength map"
                  role="group"
                  style={{
                    transform: `scale(${mapView.zoom})`,
                    transformOrigin: `${mapView.originX}% ${mapView.originY}%`,
                  }}
                >
                  {strengthMap.map(({ candidate, media, rank, group, left, top }) => (
                    <button
                      aria-label={
                        pendingSwapInId
                          ? `Replace rank ${rank + 1} ${group.replace("_", " ")} image with parked image`
                          : `Disqualify rank ${rank + 1} ${group.replace("_", " ")} image`
                      }
                      className={`strongest-set-map-point strongest-set-map-point-${group}${rank === 0 ? " is-center" : ""}${includedItemIds.includes(candidate.item_id) ? " is-exchanged" : ""}`}
                      data-strength-rank={rank + 1}
                      disabled={busy}
                      key={candidate.item_id}
                      onClick={() => {
                        if (pendingSwapInId) {
                          onExchange(candidate, pendingSwapInId);
                          setPendingSwapInId(null);
                        } else {
                          onDisqualify(candidate);
                        }
                      }}
                      onFocus={() => setHoveredStrengthId(candidate.item_id)}
                      onMouseEnter={() => setHoveredStrengthId(candidate.item_id)}
                      onMouseLeave={() => setHoveredStrengthId(null)}
                      style={{
                        left: `${left}%`,
                        top: `${top}%`,
                        zIndex: proposal.selected_count - rank + 1,
                      }}
                      title={`#${rank + 1} · ${candidate.reasons.join(" · ")}`}
                    >
                      {media?.raw_path
                        ? <img src={assetUrl(media.raw_path)} alt="" />
                        : <Database size={rank === 0 ? 20 : 14} aria-hidden="true" />}
                      <small>{rank + 1}</small>
                      <i aria-hidden="true">×</i>
                    </button>
                  ))}
                  <span className="strongest-set-map-core" aria-hidden="true" />
                </div>
              </div>
              <aside className="strongest-set-hover-preview" aria-label="Hovered image preview">
                {hoveredStrength ? (
                  <>
                    <div>
                      {hoveredStrength.media?.raw_path ? (
                        <img
                          src={assetUrl(hoveredStrength.media.raw_path)}
                          alt={`Rank ${hoveredStrength.rank + 1} ${hoveredStrength.group.replace("_", " ")} preview`}
                        />
                      ) : (
                        <Database size={34} aria-hidden="true" />
                      )}
                    </div>
                    <header>
                      <span>Rank {hoveredStrength.rank + 1}</span>
                      <strong>{hoveredStrength.group.replace("_", " ")}</strong>
                    </header>
                    <p>{hoveredStrength.candidate.reasons.join(" · ")}</p>
                  </>
                ) : (
                  <span className="strongest-set-hover-empty">
                    <Database size={24} aria-hidden="true" />
                    Hover an image for a large preview
                  </span>
                )}
              </aside>
            </div>
            {pendingSwapItem ? (
              <div className="strongest-set-swap-prompt" role="status">
                {pendingSwapItem.media?.raw_path ? (
                  <img src={assetUrl(pendingSwapItem.media.raw_path)} alt="" />
                ) : (
                  <Database size={20} aria-hidden="true" />
                )}
                <span>
                  <strong>Choose its replacement</strong>
                  <small>Click one image in the circle to exchange it with this parked image.</small>
                </span>
                <button type="button" onClick={() => setPendingSwapInId(null)}>Cancel exchange</button>
              </div>
            ) : null}
            <p className="strongest-set-map-key">
              <strong>Strongest</strong> in the center
              <span aria-hidden="true">→</span>
              weaker selected images toward the edge
              <span aria-hidden="true">·</span>
              click any image to disqualify it
              <span aria-hidden="true">·</span>
              mouse wheel to zoom
              {mapView.zoom > 1 ? (
                <button
                  type="button"
                  onClick={() => setMapView({ zoom: 1, originX: 50, originY: 50 })}
                >
                  Reset {Math.round(mapView.zoom * 100)}%
                </button>
              ) : null}
            </p>
            {disqualified.length ? (
              <div className="strongest-set-disqualified" aria-label="Disqualified image stacks">
                {strongestSetGroups.map(({ id, label }) => {
                  const items = disqualifiedByGroup.get(id) ?? [];
                  return (
                    <section aria-label={`${label} disqualified stack`} key={id}>
                      <span>{label}</span>
                      <div>
                        {items.map(({ candidate, media }, index) => (
                          <span
                            key={candidate.item_id}
                            style={{ zIndex: index + 1 }}
                            title={`Disqualified · ${candidate.reasons.join(" · ")}`}
                          >
                            {media?.raw_path
                              ? <img src={assetUrl(media.raw_path)} alt="" />
                              : <Database size={14} aria-hidden="true" />}
                          </span>
                        ))}
                        {!items.length ? <small>—</small> : null}
                      </div>
                    </section>
                  );
                })}
              </div>
            ) : null}
          </div>
          {proposal.warnings.length ? (
            <div className="strongest-set-warnings">
              <ShieldAlert size={15} aria-hidden="true" />
              <span>{proposal.warnings.map((warning) => <small key={warning}>{warning}</small>)}</span>
            </div>
          ) : null}
          <footer>
            <span>Nothing is deleted. Parked images stay available under the excluded filter.</span>
            <div>
              <button type="button" onClick={onCancel} disabled={busy}>Cancel preview</button>
              <button className="primary-action" type="button" onClick={onApply} disabled={busy}>
                <Check size={14} /> {
                  appliedCount > 0
                    ? "Update strongest set"
                    : mutable
                      ? `Use these ${proposal.selected_count}`
                      : `Create editable set of ${proposal.selected_count}`
                }
              </button>
            </div>
          </footer>
        </div>
      ) : (
        <p className="strongest-set-note">
          Preview is read-only. LoraSuite will show the proposed set before changing any decisions.
          {!mutable ? " Applying it creates a new editable version; this exported package stays unchanged." : ""}
        </p>
      )}
      {duplicateProposal ? (
        <div
          className="dataset-dedupe-backdrop"
          role="presentation"
          onMouseDown={onCloseDedupe}
        >
          <section
            className="dataset-dedupe-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dataset-dedupe-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <Copy size={19} aria-hidden="true" />
                <span>
                  <h3 id="dataset-dedupe-title">Dedupe</h3>
                  <p>
                    {duplicateProposal.duplicate_count
                      ? `${duplicateProposal.duplicate_count} likely duplicate image${duplicateProposal.duplicate_count === 1 ? "" : "s"} found. Pick the keeper in each group before parking the rest.`
                      : `No likely duplicates found in ${duplicateProposal.scanned_count} active images.`}
                  </p>
                </span>
              </div>
              <button type="button" aria-label="Close dedupe review" onClick={onCloseDedupe}>
                <X size={16} />
              </button>
            </header>
            {duplicateProposal.clusters.length ? (
              <div className="dataset-dedupe-groups">
                {duplicateProposal.clusters.map((cluster, clusterIndex) => (
                  <article aria-label={`Duplicate group ${clusterIndex + 1}`} key={cluster.id}>
                    <header>
                      <strong>Duplicate group {clusterIndex + 1}</strong>
                      <span>{cluster.candidates.length} similar images</span>
                    </header>
                    <div>
                      {cluster.candidates.map((candidate) => {
                        const record = recordById.get(candidate.item_id);
                        const media = record
                          ? mediaById.get(record.training_media_item_id) ?? null
                          : null;
                        const kept = dedupeKeepers[cluster.id] === candidate.item_id;
                        return (
                          <button
                            type="button"
                            aria-pressed={kept}
                            className={kept ? "is-keeper" : "is-duplicate"}
                            key={candidate.item_id}
                            onClick={() => setDedupeKeepers((current) => ({
                              ...current,
                              [cluster.id]: candidate.item_id,
                            }))}
                          >
                            {media?.raw_path
                              ? <img src={assetUrl(media.raw_path)} alt="" />
                              : <Database size={22} aria-hidden="true" />}
                            <span>
                              <strong>{kept ? "Keep" : "Park"}</strong>
                              <small>
                                {candidate.hash_distance === 0
                                  ? "Exact match"
                                  : `${Math.round((1 - candidate.hash_distance / 64) * 100)}% visual match`}
                              </small>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="dataset-dedupe-empty">
                <CircleCheckBig size={28} aria-hidden="true" />
                <strong>This set is already distinct.</strong>
                {duplicateProposal.unreadable_count ? (
                  <small>{duplicateProposal.unreadable_count} images could not be inspected.</small>
                ) : null}
              </div>
            )}
            <footer>
              <span>Nothing is deleted. Parked duplicates remain recoverable in the excluded filter.</span>
              <div>
                <button type="button" onClick={onCloseDedupe}>Cancel</button>
                {duplicateProposal.duplicate_count ? (
                  <button
                    className="primary-action"
                    type="button"
                    disabled={busy}
                    onClick={() => onApplyDedupe(dedupeKeepers)}
                  >
                    <Check size={14} /> Park {duplicateProposal.duplicate_count} duplicates
                  </button>
                ) : (
                  <button className="primary-action" type="button" onClick={onCloseDedupe}>Done</button>
                )}
              </div>
            </footer>
          </section>
        </div>
      ) : null}
      {parkedReviewOpen && proposal ? (
        <div
          className="strongest-set-parked-backdrop"
          role="presentation"
          onMouseDown={() => setParkedReviewOpen(false)}
        >
          <section
            className="strongest-set-parked-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="strongest-set-parked-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <Database size={19} aria-hidden="true" />
                <span>
                  <h3 id="strongest-set-parked-title">Parked images</h3>
                  <p>Choose one to bring into the circle, then choose the circle image it replaces.</p>
                </span>
              </div>
              <button
                type="button"
                aria-label="Close parked images"
                onClick={() => setParkedReviewOpen(false)}
              >
                <X size={16} />
              </button>
            </header>
            <div className="strongest-set-parked-tools">
              <input
                aria-label="Search parked images"
                type="search"
                placeholder="Search caption, view, or item…"
                value={parkedSearch}
                onChange={(event) => {
                  setParkedSearch(event.target.value);
                  setParkedPage(0);
                }}
              />
              <span>{filteredParkedItems.length} parked images</span>
            </div>
            <div className="strongest-set-parked-grid">
              {visibleParkedItems.map(({ itemId, record, media }) => (
                <button
                  type="button"
                  aria-label={`Exchange parked image ${itemId}`}
                  key={itemId}
                  onClick={() => {
                    setPendingSwapInId(itemId);
                    setParkedReviewOpen(false);
                  }}
                >
                  {media?.raw_path ? (
                    <img src={assetUrl(media.raw_path)} alt="" />
                  ) : (
                    <Database size={22} aria-hidden="true" />
                  )}
                  <span>
                    <strong>Swap into circle</strong>
                    <small>{record.view.replace("_", " ")}</small>
                  </span>
                </button>
              ))}
            </div>
            <footer>
              <span>Page {parkedPage + 1} of {parkedPageCount}</span>
              <div>
                <button
                  type="button"
                  disabled={parkedPage === 0}
                  onClick={() => setParkedPage((page) => Math.max(0, page - 1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={parkedPage + 1 >= parkedPageCount}
                  onClick={() => setParkedPage((page) => Math.min(parkedPageCount - 1, page + 1))}
                >
                  Next
                </button>
              </div>
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function GuidedTrainingRecipe({
  targets,
  selectedTargetId,
  snapshot,
  action,
  busy,
  captionJob,
  outputDir,
  canPickOutput,
  activationWord,
  activationWordRequired,
  onCancelCaptioning,
  onSelect,
  onOutputDirChange,
  onChooseOutput,
  onActivationWordChange,
  onSaveActivationWord,
}: {
  targets: TrainingTargetProfile[];
  selectedTargetId: string;
  snapshot: DatasetSnapshot | null;
  action: GuidedBuildAction | null;
  busy: boolean;
  captionJob: CaptionGenerationJob | null;
  outputDir: string;
  canPickOutput: boolean;
  activationWord: string;
  activationWordRequired: boolean;
  onCancelCaptioning(): void;
  onSelect(targetId: string): void;
  onOutputDirChange(value: string): void;
  onChooseOutput(): void;
  onActivationWordChange(value: string): void;
  onSaveActivationWord(): void;
}) {
  const target = targets.find((candidate) => candidate.profile_id === selectedTargetId);
  const [modelChooserOpen, setModelChooserOpen] = useState(false);
  const imageTargets = targetsForOutput(targets, "image");
  const featuredIds = [
    "runcomfy_krea2_raw_character",
    "runcomfy_flux1_dev_character",
    "runcomfy_qwen_image_character",
  ];
  const modelChoices = [
    ...featuredIds
      .map((profileId) => imageTargets.find((candidate) => candidate.profile_id === profileId))
      .filter((candidate): candidate is TrainingTargetProfile => Boolean(candidate)),
    ...imageTargets.filter((candidate) => !featuredIds.includes(candidate.profile_id)),
  ];
  const packageReady = snapshot?.status === "frozen" || snapshot?.status === "exported";
  const exported = snapshot?.status === "exported";
  const needsDestination = snapshot?.status === "frozen";
  return (
    <section className="guided-training-recipe" aria-label="Training recipe">
      <header className="guided-build-heading">
        <div className="guided-build-ai-mark"><Sparkles size={21} aria-hidden="true" /></div>
        <div>
          <small>LoraSuite AI</small>
          <h2>Where should this LoRA work?</h2>
          <p>Pick the model. LoraSuite will build its dataset, captions, metadata, and training package.</p>
        </div>
      </header>

      {modelChooserOpen ? (
        <div className="guided-model-bubbles" role="group" aria-label="Model choices">
          {modelChoices.map((candidate, index) => {
            const selected = candidate.profile_id === selectedTargetId;
            const isKrea = candidate.model_family === "krea2";
            return (
              <button
                key={candidate.profile_id}
                type="button"
                className={`${selected ? "selected" : ""} ${isKrea ? "krea" : ""}`}
                style={{ animationDelay: `${index * -0.8}s` }}
                aria-pressed={selected}
                onClick={() => {
                  onSelect(candidate.profile_id);
                  setModelChooserOpen(false);
                }}
              >
                <span className="guided-model-icon">{isKrea ? <Sparkles size={21} aria-hidden="true" /> : <Database size={20} aria-hidden="true" />}</span>
                <span><strong>{trainingTargetLabel(candidate)}</strong><small>{guidedModelSummary(candidate)}</small></span>
                <em>{candidate.recipe?.status === "experimental" ? "Experimental" : candidate.ready ? "Training available" : "Dataset recipe"}</em>
                {selected ? <i><Check size={13} aria-hidden="true" /></i> : null}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="guided-build-selection">
        <span><small>Selected model</small><strong>{target?.label ?? "Choose a model"}</strong></span>
        <div className="guided-build-selection-actions">
          <span className={target?.ready ? "ready" : "preview"}>{target?.ready ? "Training available" : "Dataset recipe available"}</span>
          <button type="button" onClick={() => setModelChooserOpen((open) => !open)}>
            {modelChooserOpen ? "Close choices" : "Change model"}
          </button>
        </div>
      </div>

      {activationWordRequired ? (
        <div className="guided-activation-word" aria-label="Choose prompt name">
          <div>
            <Sparkles size={18} aria-hidden="true" />
            <span>
              <strong>Give this character a unique prompt name</strong>
              <small>Type this word in a prompt whenever you want this person to appear.</small>
            </span>
          </div>
          <label>
            Prompt name
            <input
              aria-label="Prompt name"
              value={activationWord}
              onChange={(event) => onActivationWordChange(event.target.value)}
              placeholder="unique_person"
            />
          </label>
          <button type="button" onClick={onSaveActivationWord} disabled={busy || !activationWord}>
            <Save size={15} aria-hidden="true" />
            Save name and continue
          </button>
        </div>
      ) : null}

      <div className="guided-build-track" aria-label="Build progress">
        <span className="complete"><i><Check size={12} aria-hidden="true" /></i><strong>Model</strong></span>
        <b aria-hidden="true" />
        <span className={packageReady ? "complete" : "current"}><i>{packageReady ? <Check size={12} aria-hidden="true" /> : "2"}</i><strong>Package</strong></span>
        <b aria-hidden="true" />
        <span className={exported ? "complete" : packageReady ? "current" : "pending"}><i>{exported ? <Check size={12} aria-hidden="true" /> : "3"}</i><strong>Train</strong></span>
      </div>

      {captionJob && (captionJob.status === "queued" || captionJob.status === "running") ? (
        <div className="guided-build-progress" aria-label="AI build progress">
          <progress max={Math.max(captionJob.total_count, 1)} value={captionJob.completed_count + captionJob.failed_count} />
          <span>{captionJob.progress_message}</span>
          <strong>{captionJob.completed_count}/{captionJob.total_count}</strong>
          {captionJob.failed_count ? <em>{captionJob.failed_count} failed</em> : null}
          <button type="button" onClick={onCancelCaptioning} disabled={busy}><X size={13} /> Stop captioning</button>
        </div>
      ) : null}

      {needsDestination ? (
        <label className="guided-output-destination">
          Package folder
          <span>
            <input readOnly={canPickOutput} value={outputDir} onChange={(event) => onOutputDirChange(event.target.value)} placeholder="Choose a package folder" />
            <button type="button" onClick={onChooseOutput} disabled={busy} title="Choose package folder" aria-label="Choose package folder"><FolderOpen size={15} /></button>
          </span>
        </label>
      ) : null}

      {action ? (
        <button className={`guided-build-primary ${action.tone}`} type="button" onClick={action.run} disabled={busy || action.disabled}>
          <span><strong>{action.label}</strong><small>{action.detail}</small></span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      ) : null}
    </section>
  );
}

function GuidedCaptionDecision({ record, media, current, total, busy, assetUrl, canGoBack, onBack, onDefer, onApprove, onApproveAll }: {
  record: DatasetCaptionRecord;
  media: MediaItem | null;
  current: number;
  total: number;
  busy: boolean;
  assetUrl(path: string): string;
  canGoBack: boolean;
  onBack(): void;
  onDefer(): void;
  onApprove(): void;
  onApproveAll(): void;
}) {
  return (
    <section className="guided-caption-decision" aria-label="Review AI caption decision">
      <header><small>Quick check</small><strong>{current} of {total}</strong></header>
      <div className="guided-caption-decision-body">
        <div className="guided-caption-image">{media?.raw_path ? <img src={assetUrl(media.raw_path)} alt="" /> : <Database size={30} aria-hidden="true" />}</div>
        <div>
          <h3>Does this description match the image?</h3>
          <p>{record.caption}</p>
          {record.unresolved_attributes.length ? <small>LoraSuite is less certain about: {record.unresolved_attributes.join(", ")}</small> : <small>The visible details were confirmed.</small>}
          <div className="guided-caption-actions">
            <button type="button" onClick={onBack} disabled={busy || !canGoBack}><ChevronLeft size={15} aria-hidden="true" /> Back</button>
            <button type="button" onClick={onDefer} disabled={busy}><X size={15} aria-hidden="true" /> Not this one</button>
            <button className="guided-yolo-action" type="button" onClick={onApproveAll} disabled={busy} title="Approve every remaining AI decision except items marked Not Yet"><Sparkles size={15} aria-hidden="true" /> YOLO: Approve All</button>
            <button className="primary-action" type="button" onClick={onApprove} disabled={busy}><Check size={15} aria-hidden="true" /> Yes, keep it</button>
          </div>
        </div>
      </div>
    </section>
  );
}

function GuidedLiveCaptionReview({
  record,
  media,
  completed,
  total,
  flaggedCount,
  actionPending,
  assetUrl,
  onDefer,
  onApprove,
}: {
  record: DatasetCaptionRecord;
  media: MediaItem | null;
  completed: number;
  total: number;
  flaggedCount: number;
  actionPending: boolean;
  assetUrl(path: string): string;
  onDefer(): void;
  onApprove(): void;
}) {
  return (
    <section className="guided-live-caption" aria-label="Review captions while AI works">
      <header>
        <div>
          <small>Ready now · {completed} of {total} generated</small>
          <strong>Review this one while the batch continues</strong>
        </div>
        <span><Sparkles size={14} aria-hidden="true" /> AI still working</span>
      </header>
      <div className="guided-live-caption-body">
        <figure>
          {media?.raw_path ? <img src={assetUrl(media.raw_path)} alt="" /> : <Database size={30} aria-hidden="true" />}
          <figcaption>{fileName(media)}</figcaption>
        </figure>
        <div className="guided-live-caption-copy">
          <small>Generated training caption</small>
          <p>{record.caption}</p>
          {record.unresolved_attributes.length ? (
            <span>Check later: {record.unresolved_attributes.join(", ")}</span>
          ) : (
            <span>The visible details were identified with no unresolved fields.</span>
          )}
          <div className="guided-live-caption-actions">
            <button type="button" onClick={onDefer} disabled={actionPending}>
              <Flag size={15} aria-hidden="true" /> Edit later
            </button>
            <button className="primary-action" type="button" onClick={onApprove} disabled={actionPending}>
              {actionPending ? <RefreshCw className="spin" size={15} aria-hidden="true" /> : <Check size={15} aria-hidden="true" />}
              Looks right
            </button>
          </div>
          <small className="guided-live-caption-note">
            Neither choice pauses generation. Edit later keeps it in the caption queue
            {flaggedCount ? ` with ${flaggedCount} other saved item${flaggedCount === 1 ? "" : "s"}` : ""}.
          </small>
        </div>
      </div>
    </section>
  );
}

function guidedModelSummary(target: TrainingTargetProfile): string {
  if (target.model_family === "krea2") return "Expressive, style-rich character results";
  if (target.model_family === "flux1") return "Reliable character identity and realism";
  if (target.model_family === "qwen_image") return "Strong prompts and character fidelity";
  return target.description;
}

function suggestedActivationWord(project: CharacterProject): string {
  const projectName = project.name.trim();
  const namedProject = /^(character dataset|untitled|new project)$/i.test(projectName)
    ? ""
    : projectName;
  const sourceName = project.intent.subject_name.trim() || namedProject;
  if (!sourceName) {
    const suffix = normalizeActivationWord(project.id).slice(-6) || "subject";
    return `person_${suffix}`;
  }
  const subject = normalizeActivationWord(sourceName);
  const safeSubject = /^[a-z]/.test(subject) ? subject : `person_${subject}`;
  return safeSubject.endsWith("_person") ? safeSubject : `${safeSubject}_person`;
}

function normalizeActivationWord(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
}

function filterLabel(filter: DatasetFilter): string {
  return ({ all: "All", needs_review: "?", approved: "Yes", excluded: "No" } as Record<DatasetFilter, string>)[filter];
}

function filterAriaLabel(filter: DatasetFilter): string {
  return ({ all: "Show all captions", needs_review: "Show captions needing review", approved: "Show approved captions", excluded: "Show excluded captions" } as Record<DatasetFilter, string>)[filter];
}

function statusLetter(status: DatasetItemStatus): string {
  return status === "approved" ? "Y" : status === "excluded" ? "N" : "?";
}

function isActiveJob(job: CaptionGenerationJob | null | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}

function captionJobStatus(job: CaptionGenerationJob): string {
  if (job.status === "complete") {
    return `Vision captions ready: ${job.completed_count} generated${job.failed_count ? `, ${job.failed_count} failed` : ""}. Review before approval.`;
  }
  if (job.status === "failed") {
    return `Vision caption job failed: ${job.progress_message}`;
  }
  if (job.status === "canceled") {
    return `${job.progress_message}. ${job.completed_count} caption${job.completed_count === 1 ? "" : "s"} completed before it stopped.`;
  }
  return `${job.provider_label}: ${job.progress_message} (${job.completed_count + job.failed_count}/${job.total_count})`;
}

function compareDatasetRecords(left: DatasetCaptionRecord, right: DatasetCaptionRecord): number {
  return (
    Number(right.is_anchor) - Number(left.is_anchor)
    || Number(Boolean(right.crop_recipe_id)) - Number(Boolean(left.crop_recipe_id))
    || right.quality_score - left.quality_score
    || left.id.localeCompare(right.id)
  );
}

function fileName(item: MediaItem | null | undefined): string {
  const path = item?.raw_path?.replace(/\\/g, "/");
  return path?.split("/").filter(Boolean).at(-1) ?? item?.id ?? "No media";
}

function percent(value?: number | null): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function mergeMedia(existing: MediaItem[], incoming: MediaItem[]): MediaItem[] {
  const merged = new Map(existing.map((item) => [item.id, item]));
  for (const item of incoming) merged.set(item.id, item);
  return [...merged.values()];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function normalizeOutputPath(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed[0] === trimmed.at(-1) && (trimmed[0] === "'" || trimmed[0] === '"')) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function outputDirectoryPicker(): (() => Promise<string | null>) | null {
  const host = typeof window !== "undefined"
    ? (window as Window & { loraSuiteHost?: { pickDestinationPath?: () => Promise<string | string[] | null> } }).loraSuiteHost
    : undefined;
  if (host?.pickDestinationPath) {
    return async () => {
      const selection = await host.pickDestinationPath?.();
      return Array.isArray(selection) ? selection[0] ?? null : selection ?? null;
    };
  }
  try {
    if (!isTauri()) return null;
  } catch {
    return null;
  }
  return async () => {
    const selection = await open({
      directory: true,
      multiple: false,
      title: "Choose RunComfy dataset destination",
      canCreateDirectories: true,
    });
    return Array.isArray(selection) ? selection[0] ?? null : selection;
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function recoveredTrainingSnapshot(
  record: RecoveredDatasetExport,
): DatasetSnapshot | VideoDatasetSnapshot {
  const projectName = record.model_card?.display_name
    || record.model_card?.subject_name
    || record.trigger_token
    || "Recovered dataset";
  const common = {
    id: record.snapshot_id,
    project_id: record.project_id,
    project_name: projectName,
    version: record.dataset_version,
    status: "exported" as const,
    fingerprint: record.fingerprint,
    export_path: record.export_path,
    parent_snapshot_id: record.revision_lineage.parent_snapshot_id,
    parent_fingerprint: record.revision_lineage.parent_dataset_fingerprint,
    improvement_request_id: record.revision_lineage.improvement_request_id,
    source_artifact_id: record.revision_lineage.parent_artifact_id,
    source_checkpoint_sha256: record.revision_lineage.parent_checkpoint_sha256,
    revision_plan: [],
    created_at: record.imported_at,
    updated_at: record.verified_at,
    frozen_at: record.verified_at,
  };
  if (record.modality === "video") {
    return {
      ...common,
      trigger_token: record.trigger_token,
      target_profile_id: record.training_target.profile_id,
      target_label: record.training_target.label,
      items: {},
      balance: {
        total_count: record.file_count,
        approved_count: record.verified_file_count,
        review_count: 0,
        excluded_count: Math.max(0, record.file_count - record.verified_file_count),
        source_count: 0,
        total_duration_seconds: 0,
        train_count: record.verified_file_count,
        validation_count: 0,
        average_quality: 0,
        average_identity: 0,
        warnings: record.warnings,
      },
    };
  }
  return {
    ...common,
    intent: {
      target_type: recoveredTargetType(record.model_card?.target_type),
      subject_name: record.model_card?.subject_name || projectName,
      trigger_token: record.trigger_token,
      description: record.model_card?.description || "Read-only recovered dataset export.",
      learned_attributes: ["identity"],
      controllable_attributes: [],
      excluded_attributes: [],
    },
    training_target: record.training_target,
    items: {},
    balance: {
      total_count: record.file_count,
      approved_count: record.verified_file_count,
      review_count: 0,
      excluded_count: Math.max(0, record.file_count - record.verified_file_count),
      source_count: 0,
      cropped_count: 0,
      average_quality: 0,
      average_diversity: 0,
      view_counts: {},
      crop_counts: {},
      warnings: record.warnings,
    },
    model_card: record.model_card,
  };
}

function recoveredTargetType(value?: string): LoraTargetType {
  return value === "style"
    || value === "concept"
    || value === "pose"
    || value === "clothing"
    || value === "object"
    ? value
    : "character";
}
