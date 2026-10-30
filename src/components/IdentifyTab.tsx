import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BrainCircuit,
  AudioLines,
  Check,
  Crop,
  Download,
  Images,
  RefreshCw,
  Save,
  ScanFace,
  ShieldCheck,
  Video,
  X,
} from "lucide-react";

import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import type { WizardTarget } from "./WorkflowWizard";
import type {
  CharacterProject,
  CurationHandoff,
  CurationReviewStatus,
  CropKind,
  CropRecipe,
  DatasetObservation,
  DatasetReviewStatus,
  DatasetView,
  IdentityRuntimeStatus,
  LoraTargetType,
  MediaItem,
  NormalizedRect,
  SpeakerConfirmation,
  TrainingIntent,
  VoiceIdentityProfile,
} from "../lib/types";

type IdentifyEngine = Pick<
  EngineClient,
  | "assetUrl"
  | "listVaultMedia"
  | "getIdentityStatus"
  | "installIdentityModels"
  | "getVoiceIdentityStatus"
  | "installVoiceIdentityModel"
  | "getVoiceIdentityProfile"
  | "setVoiceIdentityAnchors"
  | "confirmVoiceIdentitySample"
  | "analyzeVoiceIdentity"
  | "listCharacterProjects"
  | "createCharacterProject"
  | "updateCharacterProject"
  | "addCharacterProjectCandidates"
  | "setCharacterProjectAnchors"
  | "updateCharacterProjectObservation"
  | "analyzeCharacterProject"
  | "selectCharacterProjectFace"
  | "updateCharacterProjectCrop"
  | "materializeCharacterProjectCrop"
  | "getCurationHandoff"
  | "updateCurationReview"
>;

type ReviewFilter = "all" | DatasetReviewStatus | "anchors";
type IdentifyLane = "image" | "video" | "audio";

interface IdentifyTabProps {
  mediaItems: MediaItem[];
  engine: IdentifyEngine;
  activeProjectId?: string;
  guided?: boolean;
  guidedTarget?: WizardTarget;
  onProjectChange?(projectId: string): void;
  onBuildDatasets?(): void;
}

interface IntentDraft {
  name: string;
  targetType: LoraTargetType;
  subjectName: string;
  triggerToken: string;
  description: string;
  learnedAttributes: string;
  controllableAttributes: string;
  excludedAttributes: string;
}

export function IdentifyTab({ mediaItems, engine, activeProjectId = "", guided = false, guidedTarget = "image", onProjectChange, onBuildDatasets }: IdentifyTabProps) {
  const [project, setProject] = useState<CharacterProject | null>(null);
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [vaultMedia, setVaultMedia] = useState<MediaItem[]>(mediaItems);
  const [identityStatus, setIdentityStatus] = useState<IdentityRuntimeStatus | null>(null);
  const [voiceIdentityStatus, setVoiceIdentityStatus] = useState<IdentityRuntimeStatus | null>(null);
  const [voiceProfile, setVoiceProfile] = useState<VoiceIdentityProfile | null>(null);
  const [draft, setDraft] = useState<IntentDraft>(() => emptyDraft());
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const [identifyLane, setIdentifyLane] = useState<IdentifyLane>("image");
  const [handoff, setHandoff] = useState<CurationHandoff | null>(null);
  const [selectedMediaId, setSelectedMediaId] = useState<string | null>(null);
  const [selectedCropId, setSelectedCropId] = useState<string | null>(null);
  const [cropDraft, setCropDraft] = useState<NormalizedRect | null>(null);
  const [busy, setBusy] = useState(false);
  const [advancedIdentityOpen, setAdvancedIdentityOpen] = useState(false);
  const [status, setStatus] = useState("Loading character project...");

  useEffect(() => {
    let ignore = false;
    async function loadWorkspace() {
      setBusy(true);
      try {
        const projectPayload = await engine.listCharacterProjects();
        const projects = Array.isArray(projectPayload)
          ? projectPayload.filter(isCharacterProject)
          : [];
        let currentProject = projects.find((candidate) => candidate.id === activeProjectId) ?? projects[0];
        if (!currentProject) {
          const createdProject = await engine.createCharacterProject();
          if (!isCharacterProject(createdProject)) {
            throw new Error("engine returned an invalid character project");
          }
          currentProject = createdProject;
          onProjectChange?.(createdProject.id);
        }
        const [mediaPayload, runtimeStatus, voiceRuntimeStatus, handoffPayload] = await Promise.all([
          engine.listVaultMedia(),
          engine.getIdentityStatus(),
          engine.getVoiceIdentityStatus(),
          engine.getCurationHandoff(currentProject.id, guidedTarget),
        ]);
        const storedMedia = Array.isArray(mediaPayload) ? mediaPayload.filter(isMediaItem) : [];
        const incomingIds = mediaItems
          .filter((item) => item.media_type === "image")
          .map((item) => item.id);
        const newIds = incomingIds.filter(
          (mediaItemId) => !currentProject.candidate_media_item_ids.includes(mediaItemId),
        );
        if (newIds.length > 0) {
          currentProject = await engine.addCharacterProjectCandidates(currentProject.id, newIds);
          currentProject = await engine.analyzeCharacterProject(currentProject.id);
        }
        const voiceIdentityProfile = await engine.getVoiceIdentityProfile(currentProject.id);
        if (!ignore) {
          setVaultMedia(mergeMediaItems(storedMedia, mediaItems));
          setProject(currentProject);
          setProjects(projects.some((candidate) => candidate.id === currentProject.id) ? projects : [currentProject, ...projects]);
          if (currentProject.id !== activeProjectId) onProjectChange?.(currentProject.id);
          setDraft(projectDraft(currentProject));
          setIdentityStatus(runtimeStatus);
          setVoiceIdentityStatus(voiceRuntimeStatus);
          setVoiceProfile(voiceIdentityProfile);
          setHandoff(handoffPayload);
          setStatus(
            newIds.length > 0
              ? `Compiled ${newIds.length} new candidate${newIds.length === 1 ? "" : "s"}.`
              : "Project restored from the local vault.",
          );
        }
      } catch (error) {
        if (!ignore) {
          const fallback = fallbackProject(mediaItems);
          setVaultMedia(mediaItems);
          setProject(fallback);
          setDraft(projectDraft(fallback));
          setStatus(`Identify error: ${errorMessage(error)}`);
        }
      } finally {
        if (!ignore) {
          setBusy(false);
        }
      }
    }
    void loadWorkspace();
    return () => {
      ignore = true;
    };
  }, [engine, mediaItems, activeProjectId]);

  const projectMedia = useMemo(() => {
    if (!project) {
      return [];
    }
    const mediaById = new Map(vaultMedia.map((item) => [item.id, item]));
    return project.candidate_media_item_ids
      .map((mediaItemId) => mediaById.get(mediaItemId))
      .filter((item): item is MediaItem => item !== undefined);
  }, [project, vaultMedia]);
  const visibleMedia = useMemo(() => {
    if (!project || filter === "all") {
      return projectMedia;
    }
    return projectMedia.filter((item) => {
      const observation = project.observations[item.id];
      return filter === "anchors"
        ? observation?.is_anchor
        : observation?.review_status === filter;
    });
  }, [filter, project, projectMedia]);
  const selectedItem = projectMedia.find((item) => item.id === selectedMediaId) ?? null;
  const selectedObservation = selectedMediaId
    ? project?.observations[selectedMediaId] ?? null
    : null;
  const selectedRecipes = useMemo(
    () => projectRecipes(project, selectedObservation),
    [project, selectedObservation],
  );
  const selectedRecipe = selectedRecipes.find((recipe) => recipe.id === selectedCropId) ?? null;

  useEffect(() => {
    if (visibleMedia.length === 0) {
      setSelectedMediaId(null);
      return;
    }
    if (!visibleMedia.some((item) => item.id === selectedMediaId)) {
      setSelectedMediaId(visibleMedia[0].id);
    }
  }, [selectedMediaId, visibleMedia]);

  useEffect(() => {
    if (selectedRecipes.length === 0) {
      setSelectedCropId(null);
      setCropDraft(null);
      return;
    }
    const recipe =
      selectedRecipes.find((candidate) => candidate.id === selectedCropId) ??
      selectedRecipes.find((candidate) => candidate.kind === "upper_body") ??
      selectedRecipes[0];
    setSelectedCropId(recipe.id);
    setCropDraft(recipe.rect);
  }, [selectedCropId, selectedRecipes]);

  async function runAction(
    progress: string,
    action: () => Promise<CharacterProject>,
    complete: (updated: CharacterProject) => string,
  ) {
    if (busy) {
      return;
    }
    setBusy(true);
    setStatus(progress);
    try {
      const updated = await action();
      setProject(updated);
      setStatus(complete(updated));
    } catch (error) {
      setStatus(`Identify error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveIntent() {
    if (!project) {
      return;
    }
    await runAction(
      "Saving training intent...",
      () =>
        engine.updateCharacterProject(project.id, {
          name: draft.name,
          intent: intentFromDraft(draft, project.intent),
        }),
      (updated) => {
        setDraft(projectDraft(updated));
        return "Training intent saved.";
      },
    );
  }

  async function installIdentityRuntime() {
    if (busy) {
      return;
    }
    setBusy(true);
    setStatus("Installing the licensed SFace identity models...");
    try {
      const runtimeStatus = await engine.installIdentityModels();
      setIdentityStatus(runtimeStatus);
      if (project && runtimeStatus.ready) {
        const updated = await engine.analyzeCharacterProject(project.id);
        setProject(updated);
      }
      setStatus(runtimeStatus.message);
    } catch (error) {
      setStatus(`Identity runtime error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function autoFindVisualIdentity() {
    if (!project || busy) return;
    setBusy(true);
    setStatus("Finding clear reference faces across the full image set...");
    try {
      let runtimeStatus = identityStatus;
      if (!runtimeStatus?.ready) {
        setStatus("Installing the local face matcher, then finding the subject...");
        runtimeStatus = await engine.installIdentityModels();
        setIdentityStatus(runtimeStatus);
      }
      if (!runtimeStatus.ready) {
        setStatus(runtimeStatus.message || "The local face matcher is not ready.");
        return;
      }

      let updated = await engine.analyzeCharacterProject(project.id);
      const existingAnchorIds = Object.values(updated.observations)
        .filter((observation) => observation.is_anchor)
        .map((observation) => observation.media_item_id);
      const proposedIds = proposeVisualAnchorIds(updated, 5);
      const nextAnchorIds = [...new Set([...existingAnchorIds, ...proposedIds])].slice(0, 5);
      if (nextAnchorIds.length === 0) {
        setProject(updated);
        setStatus("I could not find a clear single-face reference. Keep a clearer portrait in Prepare, then try again.");
        return;
      }
      if (nextAnchorIds.some((mediaItemId) => !existingAnchorIds.includes(mediaItemId))) {
        await engine.setCharacterProjectAnchors(project.id, nextAnchorIds);
        updated = await engine.analyzeCharacterProject(project.id);
      }
      setProject(updated);
      setStatus(
        `${updated.health.anchor_count} trusted face${updated.health.anchor_count === 1 ? "" : "s"} selected automatically. Review the shield-marked photos or continue.`,
      );
    } catch (error) {
      setStatus(`Identity setup error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleAnchor(mediaItemId: string) {
    if (!project) {
      return;
    }
    const anchorIds = Object.values(project.observations)
      .filter((observation) => observation.is_anchor)
      .map((observation) => observation.media_item_id);
    const nextAnchorIds = anchorIds.includes(mediaItemId)
      ? anchorIds.filter((anchorId) => anchorId !== mediaItemId)
      : [...anchorIds, mediaItemId];
    await runAction(
      "Saving identity anchors...",
      async () => {
        await engine.setCharacterProjectAnchors(project.id, nextAnchorIds);
        return engine.analyzeCharacterProject(project.id);
      },
      (updated) => `${updated.health.anchor_count} anchors compiled into identity consensus.`,
    );
  }

  async function anchorVisualSubject(mediaItemId: string, faceIndex?: number): Promise<boolean> {
    if (!project || busy) return false;
    setBusy(true);
    setStatus("Anchoring the selected person and rebuilding identity consensus...");
    try {
      let updated = project;
      if (faceIndex !== undefined) {
        updated = await engine.selectCharacterProjectFace(project.id, mediaItemId, faceIndex);
      }
      const anchorIds = Object.values(updated.observations)
        .filter((observation) => observation.is_anchor)
        .map((observation) => observation.media_item_id);
      if (!anchorIds.includes(mediaItemId)) {
        updated = await engine.setCharacterProjectAnchors(project.id, [...anchorIds, mediaItemId]);
      }
      setProject(updated);
      setStatus(
        `Reference saved. Comparing ${project.candidate_media_item_ids.length} photos with the trusted face; this can take several minutes.`,
      );
      updated = await engine.analyzeCharacterProject(project.id);
      setProject(updated);
      setStatus(
        `${updated.health.anchor_count} trusted face${updated.health.anchor_count === 1 ? "" : "s"} ${updated.health.anchor_count === 1 ? "now defines" : "now define"} the person. Identity consensus was refreshed.`,
      );
      return true;
    } catch (error) {
      setStatus(`Identity anchor error: ${errorMessage(error)}`);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function analyzeProject() {
    if (!project) {
      return;
    }
    await runAction(
      "Compiling face identity, crops, quality, and diversity...",
      () => engine.analyzeCharacterProject(project.id),
      (updated) =>
        `Compiled ${updated.health.candidate_count} candidates; ${updated.health.review_count} need review.`,
    );
  }

  async function updateObservation(
    mediaItemId: string,
    reviewStatus: DatasetReviewStatus,
    view?: DatasetView,
  ) {
    if (!project) {
      return;
    }
    await runAction(
      "Saving review decision...",
      () =>
        engine.updateCharacterProjectObservation(project.id, mediaItemId, {
          review_status: reviewStatus,
          view,
        }),
      () => `Candidate marked ${reviewStatus.replace("_", " ")}.`,
    );
  }

  async function selectSubjectFace(faceIndex: number) {
    if (!project || !selectedItem) {
      return;
    }
    await runAction(
      "Recompiling the selected subject face...",
      () => engine.selectCharacterProjectFace(project.id, selectedItem.id, faceIndex),
      () => `Face ${faceIndex + 1} selected as the identity subject.`,
    );
  }

  async function saveCrop(materialize: boolean) {
    if (!project || !selectedRecipe || !cropDraft) {
      return;
    }
    if (busy) {
      return;
    }
    setBusy(true);
    setStatus(materialize ? "Materializing training crop..." : "Saving crop recipe...");
    try {
      let updated = await engine.updateCharacterProjectCrop(project.id, selectedRecipe.id, {
        rect: cropDraft,
        status: "approved",
      });
      if (materialize) {
        const result = await engine.materializeCharacterProjectCrop(
          project.id,
          selectedRecipe.id,
        );
        updated = result.project;
        setVaultMedia((items) => mergeMediaItems(items, [result.media_item]));
      }
      setProject(updated);
      setStatus(materialize ? "Training crop materialized in the vault." : "Crop recipe approved.");
    } catch (error) {
      setStatus(`Crop error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function installVoiceIdentityRuntime() {
    if (busy) return;
    setBusy(true);
    setStatus("Installing the local voice identity model...");
    try {
      const runtimeStatus = await engine.installVoiceIdentityModel();
      setVoiceIdentityStatus(runtimeStatus);
      setStatus(runtimeStatus.message);
    } catch (error) {
      setStatus(`Voice identity runtime error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function confirmVoiceSample(mediaItemId: string) {
    if (!project || busy) return;
    const subjectLabel = project.intent.subject_name.trim() || project.name.trim() || "the subject";
    setBusy(true);
    setStatus(`Confirming this sample as ${subjectLabel}'s voice...`);
    try {
      const result = await engine.confirmVoiceIdentitySample(
        project.id,
        mediaItemId,
        subjectLabel,
        guidedTarget === "id_lora" ? "id_lora" : "voice",
      );
      setProject(result.project);
      setDraft(projectDraft(result.project));
      setVoiceProfile(result.profile);
      setHandoff(result.handoff);
      setStatus(`Confirmed and accepted this sample as ${subjectLabel}'s voice.`);
    } catch (error) {
      setStatus(`Voice confirmation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function analyzeVoiceCandidates() {
    if (!project || busy) return;
    const audioIds = crossMediaItems.map((item) => item.id);
    setBusy(true);
    setStatus(`Comparing ${audioIds.length} clips with the trusted voice consensus...`);
    try {
      const updated = await engine.analyzeVoiceIdentity(project.id, audioIds);
      setVoiceProfile(updated);
      const matches = Object.values(updated.evidence).filter(
        (evidence) => !evidence.is_anchor && evidence.recommendation === "keep",
      ).length;
      setStatus(`Voice comparison complete; ${matches} likely match${matches === 1 ? "" : "es"} found.`);
    } catch (error) {
      setStatus(`Voice identity error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateCrossMediaReview(
    mediaItemId: string,
    reviewStatus: CurationReviewStatus,
  ) {
    if (busy) return;
    if (
      identifyLane === "audio"
      && reviewStatus === "accepted"
      && !(voiceProfile?.anchor_media_item_ids.length)
    ) {
      await confirmVoiceSample(mediaItemId);
      return;
    }
    setBusy(true);
    setStatus(`Saving ${identifyLane} identity decision...`);
    try {
      let speakerConfirmation: SpeakerConfirmation | undefined;
      if (identifyLane === "audio" && reviewStatus === "accepted") {
        speakerConfirmation = voiceProfile?.anchor_media_item_ids.includes(mediaItemId)
          ? "anchor"
          : voiceProfile?.evidence[mediaItemId]?.recommendation === "keep"
            ? "model_match"
            : "human_override";
      }
      const updated = await engine.updateCurationReview(
        mediaItemId,
        reviewStatus,
        project?.id,
        guidedTarget,
        speakerConfirmation,
      );
      setHandoff(updated);
      setStatus(`${identifyLane === "audio" ? "Speaker" : "Temporal identity"} candidate marked ${reviewStatus}.`);
    } catch (error) {
      setStatus(`Identify error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const health = project?.health;
  const laneHandoffIds = new Set(
    (handoff?.items ?? [])
      .filter((item) => item.lane === identifyLane)
      .map((item) => item.media_item_id),
  );
  const crossMediaItems = vaultMedia.filter((item) => {
    if (item.media_type !== identifyLane) return false;
    const sourceMediaItemId = typeof item.metadata_json?.source_media_item_id === "string"
      ? item.metadata_json.source_media_item_id
      : null;
    return laneHandoffIds.has(item.id) || (sourceMediaItemId !== null && laneHandoffIds.has(sourceMediaItemId));
  });
  const handoffStatusById = new Map(
    (handoff?.items ?? []).map((item) => [item.media_item_id, item.review_status]),
  );
  const laneCounts = {
    image: projectMedia.length,
    video: (handoff?.items ?? []).filter((item) => item.lane === "video").length,
    audio: (handoff?.items ?? []).filter((item) => item.lane === "audio").length,
  };
  const acceptedVideoCount = (handoff?.items ?? []).filter(
    (item) => item.lane === "video" && item.review_status === "accepted",
  ).length;
  const acceptedAudioItems = (handoff?.items ?? []).filter(
    (item) => item.lane === "audio" && item.review_status === "accepted",
  );
  const acceptedAudioCount = acceptedAudioItems.length;
  const visualIdentityReady = Boolean(health && health.anchor_count > 0 && health.accepted_count > 0);
  const motionIdentityReady = acceptedVideoCount > 0;
  const voiceIdentityReady = Boolean(
    voiceProfile?.anchor_media_item_ids.length
    && acceptedAudioCount > 0
    && acceptedAudioItems.every((item) =>
      Boolean(
        item.speaker_confirmation
        || voiceProfile?.anchor_media_item_ids.includes(item.media_item_id)
        || voiceProfile?.evidence[item.media_item_id]?.recommendation === "keep",
      ),
    ),
  );
  const guidedReady = guidedTarget === "image"
    ? visualIdentityReady
    : guidedTarget === "video"
      ? visualIdentityReady && motionIdentityReady
      : guidedTarget === "voice"
        ? voiceIdentityReady
        : visualIdentityReady && motionIdentityReady && voiceIdentityReady;

  if (guided) {
    return (
      <>
      {!advancedIdentityOpen ? <GuidedIdentityVerifier
        target={guidedTarget}
        project={project}
        projectMedia={projectMedia}
        visibleMedia={visibleMedia}
        selectedItem={selectedItem}
        selectedObservation={selectedObservation}
        selectedRecipes={selectedRecipes}
        selectedCropId={selectedCropId}
        cropDraft={cropDraft}
        identityStatus={identityStatus}
        voiceIdentityStatus={voiceIdentityStatus}
        voiceProfile={voiceProfile}
        lane={identifyLane}
        laneCounts={laneCounts}
        crossMediaItems={crossMediaItems}
        handoffStatusById={handoffStatusById}
        acceptedVideoCount={acceptedVideoCount}
        voiceReady={voiceIdentityReady}
        ready={guidedReady}
        busy={busy}
        status={status}
        filter={filter}
        assetUrl={engine.assetUrl}
        vaultMedia={vaultMedia}
        onLaneChange={setIdentifyLane}
        onFilterChange={setFilter}
        onSelectMedia={setSelectedMediaId}
        onSelectCrop={(recipe) => {
          setSelectedCropId(recipe.id);
          setCropDraft(recipe.rect);
        }}
        onSelectFace={selectSubjectFace}
        onToggleAnchor={toggleAnchor}
        onAnchorSubject={anchorVisualSubject}
        onReviewObservation={updateObservation}
        onAutoFindSubject={autoFindVisualIdentity}
        onInstallVoiceIdentity={installVoiceIdentityRuntime}
        onConfirmVoiceSample={confirmVoiceSample}
        onAnalyzeVoices={analyzeVoiceCandidates}
        onReviewCrossMedia={updateCrossMediaReview}
        onConfirm={onBuildDatasets}
      /> : null}
      <details className="guided-advanced-options" onToggle={(event) => setAdvancedIdentityOpen(event.currentTarget.open)}>
        <summary>Advanced identity options</summary>
        {advancedIdentityOpen ? renderAdvanced() : null}
      </details>
      </>
    );
  }

  return renderAdvanced();

  function renderAdvanced() {
  if (identifyLane !== "image") {
    const LaneIcon = identifyLane === "video" ? Video : AudioLines;
    return (
      <section className="workspace-section identify-workspace cross-media-identify">
        <header className="identity-commandbar">
          <div className="identity-project-title">
            <LaneIcon size={20} aria-hidden="true" />
            <div>
              <h2>{identifyLane === "video" ? "Video Subject" : "Speaker Identity"}</h2>
              <p>{identifyLane === "video" ? "Verify the subject throughout each clip" : "Verify speaker ownership and voice quality"}</p>
            </div>
          </div>
          <div className="identity-runtime" data-ready={identifyLane === "audio" ? voiceIdentityStatus?.ready ?? false : false}>
            <span>{identifyLane === "video" ? "Temporal analysis pending" : voiceIdentityStatus?.ready ? "CAM++ speaker model ready" : "Speaker model required"}</span>
            {identifyLane === "audio" && !voiceIdentityStatus?.ready ? (
              <button type="button" onClick={installVoiceIdentityRuntime} disabled={busy}>
                <Download size={14} aria-hidden="true" /> Install
              </button>
            ) : null}
          </div>
          <div className="identify-header-actions">
          {identifyLane === "audio" ? (
            <button
              className="primary-action"
              type="button"
              onClick={analyzeVoiceCandidates}
              disabled={busy || !voiceIdentityStatus?.ready || !(voiceProfile?.anchor_media_item_ids.length)}
            >
              {busy ? <RefreshCw className="spin" size={15} aria-hidden="true" /> : <BrainCircuit size={15} aria-hidden="true" />}
              Compare Voices
            </button>
          ) : null}
          <button type="button" onClick={onBuildDatasets} disabled={!project}>
            Build Datasets <ArrowRight size={14} aria-hidden="true" />
          </button>
          </div>
        </header>
        <IdentifyLaneTabs current={identifyLane} counts={laneCounts} onSelect={setIdentifyLane} />
        <CrossMediaIdentityQueue
          lane={identifyLane}
          items={crossMediaItems}
          assetUrl={engine.assetUrl}
          statusById={handoffStatusById}
          busy={busy}
          voiceProfile={identifyLane === "audio" ? voiceProfile : null}
          subjectLabel={project?.intent.subject_name || project?.name || "the subject"}
          onConfirmVoiceSample={confirmVoiceSample}
          onReview={updateCrossMediaReview}
        />
        <p aria-live="polite" className="status-line identity-status-line">{status}</p>
      </section>
    );
  }
  return (
    <section className="workspace-section identify-workspace">
      <header className="identity-commandbar">
        <div className="identity-project-title">
          <ScanFace size={20} aria-hidden="true" />
          <div>
            <h2>Face Identity</h2>
            <p>{draft.name} · {draft.subjectName || "Unnamed subject"}</p>
          </div>
        </div>
        <label className="identity-project-select">Character<select aria-label="Identity character project" value={project?.id ?? ""} onChange={(event) => { const next = projects.find((candidate) => candidate.id === event.target.value); if (next) { setProject(next); setDraft(projectDraft(next)); onProjectChange?.(next.id); } }} disabled={busy}>{projects.map((candidate) => <option key={candidate.id} value={candidate.id}>{projectOptionLabel(candidate)}</option>)}</select></label>
        <div className="identity-runtime" data-ready={identityStatus?.ready ?? false}>
          <span>{identityStatus?.ready ? "SFace ready" : "Identity model required"}</span>
          {!identityStatus?.ready ? (
            <button type="button" onClick={installIdentityRuntime} disabled={busy}>
              <Download size={14} aria-hidden="true" /> Install
            </button>
          ) : null}
        </div>
        <div className="identify-header-actions">
          <button type="button" onClick={saveIntent} disabled={!project || busy}>
            <Save size={15} aria-hidden="true" /> Save Intent
          </button>
          <button
            className="primary-action"
            type="button"
            onClick={analyzeProject}
            disabled={!project || busy || projectMedia.length === 0}
          >
            {busy ? <RefreshCw className="spin" size={15} aria-hidden="true" /> : <BrainCircuit size={15} aria-hidden="true" />}
            Analyze Faces
          </button>
          <button type="button" onClick={onBuildDatasets} disabled={!project}>
            Build Datasets <ArrowRight size={14} aria-hidden="true" />
          </button>
        </div>
      </header>

      <IdentifyLaneTabs current={identifyLane} counts={laneCounts} onSelect={setIdentifyLane} />

      <details className="intent-editor" open>
        <summary>Training intent and attribute policy</summary>
        <div className="intent-editor-grid">
          <label>Project<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <label>
            LoRA type
            <select value={draft.targetType} onChange={(event) => setDraft({ ...draft, targetType: event.target.value as LoraTargetType })}>
              <option value="character">Character</option><option value="style">Style</option><option value="concept">Concept</option><option value="pose">Pose</option><option value="clothing">Clothing</option><option value="object">Object</option>
            </select>
          </label>
          <label>Subject<input value={draft.subjectName} onChange={(event) => setDraft({ ...draft, subjectName: event.target.value })} placeholder="Person or character name" /></label>
          <label>Trigger token <small>Type a unique prompt word</small><input aria-label="Trigger token" value={draft.triggerToken} onChange={(event) => setDraft({ ...draft, triggerToken: event.target.value })} placeholder="e.g. marysue_person" /></label>
          <label className="wide">Purpose<input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
          <label>Learn<input value={draft.learnedAttributes} onChange={(event) => setDraft({ ...draft, learnedAttributes: event.target.value })} /></label>
          <label>Keep controllable<input value={draft.controllableAttributes} onChange={(event) => setDraft({ ...draft, controllableAttributes: event.target.value })} /></label>
          <label>Exclude<input value={draft.excludedAttributes} onChange={(event) => setDraft({ ...draft, excludedAttributes: event.target.value })} /></label>
        </div>
      </details>

      <dl className="dataset-health-strip compact" aria-label="Dataset health">
        <HealthMetric label="Candidates" value={health?.candidate_count ?? 0} />
        <HealthMetric label="Accepted" value={health?.accepted_count ?? 0} tone="good" />
        <HealthMetric label="Review" value={health?.review_count ?? 0} tone="warn" />
        <HealthMetric label="Rejected" value={health?.rejected_count ?? 0} />
        <HealthMetric label="Anchors" value={health?.anchor_count ?? 0} />
        <HealthMetric label="Effective" value={health?.effective_observation_count ?? 0} />
        <HealthMetric label="Sources" value={health?.source_count ?? 0} />
        <HealthMetric label="Quality" value={formatPercent(health?.average_quality)} />
      </dl>

      {health?.warnings.length ? (
        <div className="health-warnings" aria-label="Dataset health warnings">
          <ShieldCheck size={16} aria-hidden="true" />
          <div>{health.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>
        </div>
      ) : null}

      {projectMedia.length === 0 ? (
        <p className="empty-state">Finish curation with image candidates to begin face verification.</p>
      ) : (
        <div className="identity-compiler-layout">
          <aside className="identity-queue" aria-label="Identity candidate queue">
            <div className="identity-queue-header">
              <div className="segmented-control" role="group" aria-label="Identify filter">
                {(["all", "anchors", "accepted", "needs_review", "rejected"] as ReviewFilter[]).map((option) => (
                  <button key={option} type="button" aria-pressed={filter === option} onClick={() => setFilter(option)}>{filterShortLabel(option)}</button>
                ))}
              </div>
              <span>{visibleMedia.length}</span>
            </div>
            <div className="identity-queue-list">
              {visibleMedia.map((item) => {
                const observation = project?.observations[item.id];
                if (!observation) return null;
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`identity-queue-item ${selectedMediaId === item.id ? "active" : ""}`}
                    onClick={() => setSelectedMediaId(item.id)}
                    aria-label={`Inspect ${displayName(item)}`}
                  >
                    {item.raw_path ? <img src={engine.assetUrl(item.raw_path)} alt="" /> : <span className="queue-placeholder"><Images size={18} /></span>}
                    <span className="queue-copy"><strong>{displayName(item)}</strong><small>{viewLabel(observation.view)} · Q {formatPercent(observation.quality_score)}</small></span>
                    <span className={`queue-state ${observation.review_status}`}>{observation.is_anchor ? "A" : stateLetter(observation.review_status)}</span>
                  </button>
                );
              })}
            </div>
          </aside>

          <section className="identity-canvas" aria-label="Identity inspection canvas">
            {selectedItem && selectedObservation && selectedItem.raw_path ? (
              <>
                <div className="identity-canvas-toolbar">
                  <strong>{displayName(selectedItem)}</strong>
                  <span>{selectedObservation.identity_backend ?? "identity pending"}</span>
                </div>
                <div className="identity-image-stage">
                  <div className="identity-image-wrap">
                    <img src={engine.assetUrl(selectedItem.raw_path)} alt={displayName(selectedItem)} />
                    {cropDraft ? <span className="crop-overlay" style={rectStyle(cropDraft)} aria-hidden="true" /> : null}
                    {(selectedObservation.faces ?? []).map((face) => (
                      <button
                        type="button"
                        key={face.index}
                        className={`face-overlay ${face.selected ? "selected" : ""}`}
                        style={rectStyle(face.bounding_box)}
                        onClick={() => selectSubjectFace(face.index)}
                        aria-label={`Select face ${face.index + 1}`}
                        title={`Face ${face.index + 1}: ${face.anchor_similarity == null ? "unscored" : formatPercent(face.anchor_similarity)}`}
                      ><span>{face.index + 1}</span></button>
                    ))}
                  </div>
                </div>
                <div className="crop-preset-bar" role="group" aria-label="Crop proposal">
                  {selectedRecipes.map((recipe) => (
                    <button key={recipe.id} type="button" aria-pressed={selectedCropId === recipe.id} onClick={() => { setSelectedCropId(recipe.id); setCropDraft(recipe.rect); }}>
                      <Crop size={13} aria-hidden="true" /> {cropLabel(recipe.kind)} {recipe.aspect_ratio}
                    </button>
                  ))}
                </div>
              </>
            ) : <p className="empty-state">Select a candidate to inspect.</p>}
          </section>

          <aside className="identity-inspector" aria-label="Identity evidence inspector">
            {selectedItem && selectedObservation ? (
              <Inspector
                item={selectedItem}
                observation={selectedObservation}
                recipe={selectedRecipe}
                cropDraft={cropDraft}
                busy={busy}
                onToggleAnchor={() => toggleAnchor(selectedItem.id)}
                onReview={(reviewStatus) => updateObservation(selectedItem.id, reviewStatus, selectedObservation.view)}
                onView={(view) => updateObservation(selectedItem.id, selectedObservation.review_status, view)}
                onCropChange={setCropDraft}
                onSaveCrop={() => saveCrop(false)}
                onMaterialize={() => saveCrop(true)}
              />
            ) : null}
          </aside>
        </div>
      )}
      <p aria-live="polite" className="status-line identity-status-line">{status}</p>
    </section>
  );
}

}

function IdentifyLaneTabs({
  current,
  counts,
  onSelect,
}: {
  current: IdentifyLane;
  counts: Record<IdentifyLane, number>;
  onSelect(lane: IdentifyLane): void;
}) {
  const lanes: Array<{ id: IdentifyLane; label: string; icon: typeof Images }> = [
    { id: "image", label: "Face", icon: Images },
    { id: "video", label: "Video Subject", icon: Video },
    { id: "audio", label: "Speaker", icon: AudioLines },
  ];
  return (
    <div className="identify-lane-tabs" role="tablist" aria-label="Identity lanes">
      {lanes.map((lane) => {
        const Icon = lane.icon;
        return (
          <button
            key={lane.id}
            type="button"
            role="tab"
            aria-selected={current === lane.id}
            onClick={() => onSelect(lane.id)}
          >
            <Icon size={14} aria-hidden="true" /> {lane.label} <small>{counts[lane.id]}</small>
          </button>
        );
      })}
    </div>
  );
}

interface GuidedIdentityVerifierProps {
  target: WizardTarget;
  project: CharacterProject | null;
  projectMedia: MediaItem[];
  visibleMedia: MediaItem[];
  selectedItem: MediaItem | null;
  selectedObservation: DatasetObservation | null;
  selectedRecipes: CropRecipe[];
  selectedCropId: string | null;
  cropDraft: NormalizedRect | null;
  identityStatus: IdentityRuntimeStatus | null;
  voiceIdentityStatus: IdentityRuntimeStatus | null;
  voiceProfile: VoiceIdentityProfile | null;
  lane: IdentifyLane;
  laneCounts: Record<IdentifyLane, number>;
  crossMediaItems: MediaItem[];
  handoffStatusById: Map<string, CurationReviewStatus>;
  acceptedVideoCount: number;
  voiceReady: boolean;
  ready: boolean;
  busy: boolean;
  status: string;
  filter: ReviewFilter;
  assetUrl(path: string): string;
  vaultMedia: MediaItem[];
  onLaneChange(lane: IdentifyLane): void;
  onFilterChange(filter: ReviewFilter): void;
  onSelectMedia(mediaItemId: string): void;
  onSelectCrop(recipe: CropRecipe): void;
  onSelectFace(faceIndex: number): void;
  onToggleAnchor(mediaItemId: string): void;
  onAnchorSubject(mediaItemId: string, faceIndex?: number): Promise<boolean>;
  onReviewObservation(mediaItemId: string, status: DatasetReviewStatus, view?: DatasetView): void;
  onAutoFindSubject(): void;
  onInstallVoiceIdentity(): void;
  onConfirmVoiceSample(mediaItemId: string): void;
  onAnalyzeVoices(): void;
  onReviewCrossMedia(mediaItemId: string, status: CurationReviewStatus): void;
  onConfirm?(): void;
}

function GuidedIdentityVerifier({
  target,
  project,
  projectMedia,
  visibleMedia,
  selectedItem,
  selectedObservation,
  selectedRecipes,
  selectedCropId,
  cropDraft,
  identityStatus,
  voiceIdentityStatus,
  voiceProfile,
  lane,
  laneCounts,
  crossMediaItems,
  handoffStatusById,
  acceptedVideoCount,
  voiceReady,
  ready,
  busy,
  status,
  filter,
  assetUrl,
  vaultMedia,
  onLaneChange,
  onFilterChange,
  onSelectMedia,
  onSelectCrop,
  onSelectFace,
  onToggleAnchor,
  onAnchorSubject,
  onReviewObservation,
  onAutoFindSubject,
  onInstallVoiceIdentity,
  onConfirmVoiceSample,
  onAnalyzeVoices,
  onReviewCrossMedia,
  onConfirm,
}: GuidedIdentityVerifierProps) {
  const [reviewKind, setReviewKind] = useState<"references" | "uncertain" | null>(null);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewFaceIndex, setReviewFaceIndex] = useState<number | undefined>(undefined);
  const [heldReviewItem, setHeldReviewItem] = useState<MediaItem | null>(null);
  const [detailLane, setDetailLane] = useState<"video" | "audio" | null>(null);
  const health = project?.health;
  const voiceAnchorCount = voiceProfile?.anchor_media_item_ids.length ?? 0;
  const visualReady = Boolean(health && health.anchor_count > 0 && health.accepted_count > 0);
  const motionReady = acceptedVideoCount > 0;
  const visualRequired = target !== "voice";
  const motionRequired = target === "video" || target === "id_lora";
  const voiceRequired = target === "voice" || target === "id_lora";
  const requirement = guidedIdentityRequirement(target, visualReady, motionReady, voiceReady);
  const referenceItems = projectMedia.filter((item) => project?.observations[item.id]?.is_anchor);
  const uncertainItems = projectMedia
    .filter((item) => {
      const observation = project?.observations[item.id];
      return observation?.review_status === "needs_review" && !observation.is_anchor;
    })
    .sort((left, right) =>
      visualReviewPriority(project?.observations[right.id])
      - visualReviewPriority(project?.observations[left.id]),
    );
  const reviewItems = reviewKind === "references" ? referenceItems : uncertainItems;
  const activeReviewIndex = Math.min(reviewIndex, Math.max(0, reviewItems.length - 1));
  const activeReviewItem = heldReviewItem ?? reviewItems[activeReviewIndex] ?? null;
  const activeReviewObservation = activeReviewItem ? project?.observations[activeReviewItem.id] : null;

  useEffect(() => {
    const faces = activeReviewObservation?.faces ?? [];
    const selected = activeReviewObservation?.selected_face_index;
    setReviewFaceIndex(selected ?? faces.find((face) => face.selected)?.index ?? faces[0]?.index);
  }, [activeReviewItem?.id, activeReviewObservation?.selected_face_index]);

  function openReview(kind: "references" | "uncertain") {
    setHeldReviewItem(null);
    setReviewIndex(0);
    setReviewKind(kind);
  }

  function advanceReview() {
    if (activeReviewIndex >= reviewItems.length - 1) {
      setReviewKind(null);
      setReviewIndex(0);
      return;
    }
    setReviewIndex((current) => current + 1);
  }

  function openLane(nextLane: "video" | "audio") {
    setDetailLane(nextLane);
    onLaneChange(nextLane);
  }

  if (detailLane) {
    return (
      <section className="workspace-section identify-workspace guided-identity-workspace">
        <div className="guided-verify-detail">
          <header>
            <button type="button" onClick={() => setDetailLane(null)}><ArrowRight size={14} aria-hidden="true" /> Back to identity check</button>
            <span>
              <small>{detailLane === "video" ? "Motion check" : "Voice check"}</small>
              <strong>{detailLane === "video" ? "Keep clips with the same person" : "Keep samples spoken by the same person"}</strong>
            </span>
          </header>
          {lane === detailLane ? (
            <GuidedCrossMediaVerifier
              lane={detailLane}
              items={crossMediaItems}
              assetUrl={assetUrl}
              vaultMedia={vaultMedia}
              statusById={handoffStatusById}
              voiceProfile={detailLane === "audio" ? voiceProfile : null}
              subjectLabel={project?.intent.subject_name || project?.name || "the subject"}
              voiceIdentityReady={voiceIdentityStatus?.ready ?? false}
              busy={busy}
              onInstallVoiceIdentity={onInstallVoiceIdentity}
              onAnalyzeVoices={onAnalyzeVoices}
              onConfirmVoiceSample={onConfirmVoiceSample}
              onReview={onReviewCrossMedia}
            />
          ) : <div className="guided-identity-empty"><RefreshCw className="spin" size={24} aria-hidden="true" /><span>Opening the review...</span></div>}
        </div>
        <p aria-live="polite" className="status-line guided-identity-status">{status}</p>
      </section>
    );
  }

  return (
    <section className="workspace-section identify-workspace guided-identity-workspace">
      <div className="guided-verify-simple">
        <div className="guided-verify-ai-mark"><BrainCircuit size={22} aria-hidden="true" /></div>
        <small>LoraSuite AI</small>
        <h3>{ready ? "Identity match ready" : busy ? "Finding the identity..." : "One more identity check"}</h3>
        <p className="guided-verify-summary">
          {visualRequired && visualReady
            ? `I used ${referenceItems.length} clear reference photo${referenceItems.length === 1 ? "" : "s"} to match ${health?.accepted_count ?? 0} image${health?.accepted_count === 1 ? "" : "s"}.`
            : visualRequired
              ? "Choose one clear photo of the person. I will use it to compare the rest."
              : voiceReady
                ? "The speaker evidence is ready."
                : "I need one clear voice sample from the person."}
        </p>

        {visualRequired && referenceItems.length > 0 ? (
          <div className="guided-reference-cloud" aria-label="AI reference photos">
            {referenceItems.slice(0, 5).map((item, index) => (
              <button key={item.id} type="button" style={{ animationDelay: `${index * -0.7}s` }} onClick={() => openReview("references")} aria-label={`Check reference photo ${index + 1}`}>
                {item.raw_path ? <img src={assetUrl(item.raw_path)} alt="" /> : <Images size={24} aria-hidden="true" />}
              </button>
            ))}
            <span><ScanFace size={25} aria-hidden="true" /><strong>Same person</strong></span>
          </div>
        ) : null}

        <div className="guided-proof-row" aria-label="Required identity checks">
          {visualRequired ? <GuidedProof label="Identity anchors" value={visualReady ? `${referenceItems.length} selected` : "Anchor needed"} ready={visualReady} /> : null}
          {motionRequired ? <GuidedProof label="Motion" value={motionReady ? `${acceptedVideoCount} clips` : "Clip review needed"} ready={motionReady} /> : null}
          {voiceRequired ? <GuidedProof label="Voice" value={voiceReady ? `${voiceAnchorCount} samples` : "Voice sample needed"} ready={voiceReady} /> : null}
        </div>

        <div className="guided-verify-actions">
          {referenceItems.length > 0 ? <button type="button" onClick={() => openReview("references")}><ScanFace size={15} aria-hidden="true" /> Check reference photos</button> : null}
          {visualRequired && !visualReady && uncertainItems.length > 0 ? (
            <button className="primary-action" type="button" onClick={() => openReview("uncertain")} disabled={busy}>
              <Images size={15} aria-hidden="true" /> Choose reference photo
            </button>
          ) : uncertainItems.length > 0 ? (
            <button type="button" onClick={() => openReview("uncertain")}><RefreshCw size={14} aria-hidden="true" /> Review {uncertainItems.length} uncertain</button>
          ) : null}
          {visualRequired && !visualReady ? <button type="button" onClick={onAutoFindSubject} disabled={busy || projectMedia.length === 0}><BrainCircuit size={15} aria-hidden="true" /> Find automatically</button> : null}
          {motionRequired && !motionReady ? <button className="primary-action" type="button" onClick={() => openLane("video")}><Video size={15} aria-hidden="true" /> Review motion</button> : null}
          {voiceRequired && !voiceReady ? <button className="primary-action" type="button" onClick={() => openLane("audio")}><AudioLines size={15} aria-hidden="true" /> Review voice</button> : null}
          <button className="guided-verify-continue" aria-label="Confirm Identity" type="button" disabled={!ready || busy || !project} onClick={onConfirm}>
            <Check size={16} aria-hidden="true" /> {ready ? "Looks right, continue" : "Continue when ready"} <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>

        <p className="guided-verify-requirement">{ready ? "Everything required for this LoRA is ready." : requirement}</p>
        <p aria-live="polite" className="guided-verify-status">{status}</p>
      </div>

      {reviewKind && activeReviewItem && activeReviewObservation ? (
        <div className="guided-verify-review-overlay" role="dialog" aria-modal="true" aria-busy={busy} aria-label={reviewKind === "references" ? "Review reference photos" : "Review uncertain photos"}>
          <button type="button" className="guided-verify-review-backdrop" aria-label="Close photo review" onClick={() => setReviewKind(null)} />
          <article className="guided-verify-review-card">
            <header>
              <span><small>{reviewKind === "references" ? "AI reference photo" : "Needs your decision"}</small><strong>{activeReviewIndex + 1} of {reviewItems.length}</strong></span>
              <button type="button" title="Close review" onClick={() => setReviewKind(null)}><X size={15} aria-hidden="true" /></button>
            </header>
            <div className="guided-verify-review-media">
              {activeReviewItem.raw_path ? <img src={assetUrl(activeReviewItem.raw_path)} alt={displayName(activeReviewItem)} /> : <Images size={32} aria-hidden="true" />}
            </div>
            <div className="guided-verify-review-copy">
              <strong>{reviewKind === "references" ? "Does this clearly show the right person?" : "Should this image represent the person?"}</strong>
              <p>{reviewKind === "references"
                ? "This photo is anchored as trusted identity evidence."
                : "Keep it as ordinary evidence, or anchor the correct face to define the person."}</p>
              {busy ? (
                <div className="guided-verify-review-wait" role="status" aria-live="polite">
                  <RefreshCw className="spin" size={22} aria-hidden="true" />
                  <span>
                    <strong>Matching this person across {projectMedia.length.toLocaleString()} image{projectMedia.length === 1 ? "" : "s"}</strong>
                    <p>Hang tight—nothing is needed from you. Large collections can take several minutes, and these choices will unlock automatically.</p>
                    <small>{status}</small>
                  </span>
                  <i aria-hidden="true" />
                </div>
              ) : (
                <>
                  {(activeReviewObservation.faces?.length ?? 0) > 1 ? (
                    <div className="guided-face-choices" role="group" aria-label="Choose the person in this photo">
                      <small>Choose the face to anchor</small>
                      <span>
                        {activeReviewObservation.faces?.map((face) => (
                          <button
                            className={reviewFaceIndex === face.index ? "selected" : ""}
                            key={face.index}
                            type="button"
                            aria-pressed={reviewFaceIndex === face.index}
                            onClick={() => setReviewFaceIndex(face.index)}
                          >
                            Face {face.index + 1} <small>{formatPercent(face.confidence)}</small>
                          </button>
                        ))}
                      </span>
                    </div>
                  ) : null}
                  <div className={reviewKind === "uncertain" ? "three" : ""}>
                    <button type="button" onClick={() => { reviewKind === "references" ? onToggleAnchor(activeReviewItem.id) : onReviewObservation(activeReviewItem.id, "rejected", activeReviewObservation.view); advanceReview(); }}><X size={15} aria-hidden="true" /> {reviewKind === "references" ? "Wrong reference" : "Leave out"}</button>
                    {reviewKind === "uncertain" ? (
                      <button type="button" onClick={() => { onReviewObservation(activeReviewItem.id, "accepted", activeReviewObservation.view); advanceReview(); }}><Check size={15} aria-hidden="true" /> Keep image</button>
                    ) : null}
                    <button
                      className="primary-action"
                      type="button"
                      onClick={async () => {
                        if (reviewKind === "uncertain") {
                          setHeldReviewItem(activeReviewItem);
                          try {
                            if (await onAnchorSubject(activeReviewItem.id, reviewFaceIndex)) advanceReview();
                          } finally {
                            setHeldReviewItem(null);
                          }
                        } else {
                          advanceReview();
                        }
                      }}
                    >
                      <ShieldCheck size={15} aria-hidden="true" /> {reviewKind === "references" ? "This is the person" : "Anchor this person"}
                    </button>
                  </div>
                </>
              )}
            </div>
          </article>
        </div>
      ) : null}
    </section>
  );
}

function GuidedProof({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return <span className={ready ? "ready" : "pending"}><i>{ready ? <Check size={12} aria-hidden="true" /> : null}</i><strong>{label}</strong><small>{value}</small></span>;
}

function GuidedCrossMediaVerifier({ lane, items, assetUrl, vaultMedia, statusById, voiceProfile, subjectLabel, voiceIdentityReady, busy, onInstallVoiceIdentity, onAnalyzeVoices, onConfirmVoiceSample, onReview }: {
  lane: "video" | "audio";
  items: MediaItem[];
  assetUrl(path: string): string;
  vaultMedia: MediaItem[];
  statusById: Map<string, CurationReviewStatus>;
  voiceProfile: VoiceIdentityProfile | null;
  subjectLabel: string;
  voiceIdentityReady: boolean;
  busy: boolean;
  onInstallVoiceIdentity(): void;
  onAnalyzeVoices(): void;
  onConfirmVoiceSample(mediaItemId: string): void;
  onReview(mediaItemId: string, status: CurationReviewStatus): void;
}) {
  const voiceAnchorCount = voiceProfile?.anchor_media_item_ids.length ?? 0;
  return (
    <div className="guided-cross-media-verifier">
      <div className="guided-cross-media-heading">
        <span><strong>{lane === "video" ? "Motion continuity" : "Voice ownership"}</strong><small>{lane === "video" ? "Keep clips where the same subject remains visually consistent." : "Choose trusted samples, then compare every speaker candidate."}</small></span>
        {lane === "audio" && !voiceIdentityReady ? (
          <button type="button" onClick={onInstallVoiceIdentity} disabled={busy}><Download size={14} aria-hidden="true" /> Install speaker model</button>
        ) : lane === "audio" ? (
          <button type="button" onClick={onAnalyzeVoices} disabled={busy || voiceAnchorCount === 0}><BrainCircuit size={14} aria-hidden="true" /> Compare Voices</button>
        ) : null}
      </div>
      {items.length === 0 ? (
        <div className="guided-identity-empty"><span>No {lane === "video" ? "video clips" : "voice tracks"} reached Verify.</span></div>
      ) : (
        <div className="guided-cross-media-bubbles">
          {items.map((item) => {
            const reviewStatus = statusById.get(item.id) ?? "pending";
            const source = item.raw_path ? assetUrl(item.raw_path) : undefined;
            const voiceEvidence = lane === "audio" ? voiceProfile?.evidence[item.id] : undefined;
            const isVoiceAnchor = lane === "audio" && (voiceProfile?.anchor_media_item_ids.includes(item.id) ?? false);
            const artwork = lane === "audio" ? identityArtworkPath(item, vaultMedia) : null;
            return (
              <article key={item.id} className={`guided-cross-media-bubble ${reviewStatus} ${isVoiceAnchor ? "anchor" : ""}`}>
                <div className="guided-cross-media-preview">
                  {lane === "video" && source ? <video src={source} controls preload="metadata" /> : (
                    <>
                      {artwork ? <img src={assetUrl(artwork)} alt="" /> : null}
                      <AudioLines size={30} aria-hidden="true" />
                      {source ? <audio src={source} controls preload="metadata" /> : null}
                    </>
                  )}
                  <span className={`guided-cross-media-state ${reviewStatus}`}>{reviewStatus}</span>
                </div>
                <div className="guided-cross-media-actions">
                  {lane === "audio" ? (
                    <button type="button" className={isVoiceAnchor ? "active" : ""} onClick={() => onConfirmVoiceSample(item.id)} disabled={busy || isVoiceAnchor} title={isVoiceAnchor ? `Confirmed as ${subjectLabel}'s voice` : `Confirm as ${subjectLabel}'s voice`}><ShieldCheck size={14} aria-hidden="true" /> {isVoiceAnchor ? "Confirmed voice" : `Confirm ${subjectLabel}'s voice`}</button>
                  ) : null}
                  {lane !== "audio" || voiceAnchorCount > 0 ? (
                    <button type="button" onClick={() => onReview(item.id, "accepted")} disabled={busy} title="Accept"><Check size={14} aria-hidden="true" /></button>
                  ) : null}
                  <button type="button" onClick={() => onReview(item.id, "pending")} disabled={busy} title="Pending"><RefreshCw size={13} aria-hidden="true" /></button>
                  <button type="button" onClick={() => onReview(item.id, "rejected")} disabled={busy} title="Reject"><X size={14} aria-hidden="true" /></button>
                </div>
                {voiceEvidence ? <small className={`guided-voice-match ${voiceEvidence.recommendation}`}>{formatPercent(voiceEvidence.similarity)} voice match</small> : null}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CrossMediaIdentityQueue({
  lane,
  items,
  assetUrl,
  statusById,
  busy,
  voiceProfile,
  subjectLabel,
  onConfirmVoiceSample,
  onReview,
}: {
  lane: "video" | "audio";
  items: MediaItem[];
  assetUrl(path: string): string;
  statusById: Map<string, CurationReviewStatus>;
  busy: boolean;
  voiceProfile: VoiceIdentityProfile | null;
  subjectLabel: string;
  onConfirmVoiceSample(mediaItemId: string): void;
  onReview(mediaItemId: string, status: CurationReviewStatus): void;
}) {
  if (items.length === 0) {
    const mediaLabel = lane === "video" ? "video clips" : "voice tracks";
    const verificationLabel = lane === "video" ? "video subject" : "speaker";
    return <p className="empty-state">Finish curation with {mediaLabel} to begin {verificationLabel} verification.</p>;
  }
  return (
    <div className="cross-media-identity-grid">
      {items.map((item) => {
        const reviewStatus = statusById.get(item.id) ?? "pending";
        const source = item.raw_path ? assetUrl(item.raw_path) : undefined;
        const voiceEvidence = lane === "audio" ? voiceProfile?.evidence[item.id] : undefined;
        const isVoiceAnchor = lane === "audio" && (voiceProfile?.anchor_media_item_ids.includes(item.id) ?? false);
        return (
          <article key={item.id} className={`cross-media-identity-card ${reviewStatus}`}>
            <div className="cross-media-player">
              {lane === "video" && source ? (
                <video src={source} controls preload="metadata" />
              ) : source ? (
                <div className="speaker-player">
                  <AudioLines size={28} aria-hidden="true" />
                  <audio src={source} controls preload="metadata" />
                </div>
              ) : null}
            </div>
            <div className="cross-media-card-body">
              <div>
                <strong>{displayName(item)}</strong>
                <span>{lane === "video" ? "Temporal subject verification" : "Speaker and speech verification"}</span>
              </div>
              {lane === "audio" ? (
                <button
                  type="button"
                  className={isVoiceAnchor ? "voice-anchor-toggle active" : "voice-anchor-toggle"}
                  aria-pressed={isVoiceAnchor}
                  onClick={() => onConfirmVoiceSample(item.id)}
                  disabled={busy || isVoiceAnchor}
                  title={isVoiceAnchor ? `Confirmed as ${subjectLabel}'s voice` : `Confirm as ${subjectLabel}'s voice`}
                >
                  <ShieldCheck size={14} aria-hidden="true" /> {isVoiceAnchor ? "Confirmed voice" : `Confirm ${subjectLabel}'s voice`}
                </button>
              ) : null}
              <span className={`verification-state ${reviewStatus}`}>{reviewStatus}</span>
              {voiceEvidence ? (
                <div className={`voice-similarity ${voiceEvidence.recommendation}`}>
                  <span><strong>{formatPercent(voiceEvidence.similarity)}</strong> similarity</span>
                  <small>{voiceEvidence.reasons[0]}</small>
                </div>
              ) : lane === "audio" ? (
                <p className="voice-awaiting">Select trusted anchors, then compare voices.</p>
              ) : null}
              <div className="decision-buttons" role="group" aria-label={`Review ${displayName(item)}`}>
                {lane !== "audio" || (voiceProfile?.anchor_media_item_ids.length ?? 0) > 0 ? (
                  <button type="button" className={reviewStatus === "accepted" ? "active accept" : "accept"} onClick={() => onReview(item.id, "accepted")} disabled={busy} title="Accept"><Check size={15} /></button>
                ) : null}
                <button type="button" className={reviewStatus === "pending" ? "active review" : "review"} onClick={() => onReview(item.id, "pending")} disabled={busy} title="Pending"><RefreshCw size={14} /></button>
                <button type="button" className={reviewStatus === "rejected" ? "active reject" : "reject"} onClick={() => onReview(item.id, "rejected")} disabled={busy} title="Reject"><X size={15} /></button>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function Inspector({ item, observation, recipe, cropDraft, busy, onToggleAnchor, onReview, onView, onCropChange, onSaveCrop, onMaterialize }: {
  item: MediaItem;
  observation: DatasetObservation;
  recipe: CropRecipe | null;
  cropDraft: NormalizedRect | null;
  busy: boolean;
  onToggleAnchor(): void;
  onReview(status: DatasetReviewStatus): void;
  onView(view: DatasetView): void;
  onCropChange(rect: NormalizedRect): void;
  onSaveCrop(): void;
  onMaterialize(): void;
}) {
  const immutable = recipe?.status === "materialized";
  return (
    <>
      <section className="inspector-section">
        <div className="inspector-heading"><h3>Identity</h3><button type="button" className={observation.is_anchor ? "anchor-toggle active" : "anchor-toggle"} aria-pressed={observation.is_anchor} onClick={onToggleAnchor} disabled={busy} title="Trusted identity anchor"><ShieldCheck size={16} /></button></div>
        <dl className="evidence-grid">
          <div><dt>Similarity</dt><dd>{observation.identity_score == null ? "--" : formatPercent(observation.identity_score)}</dd></div>
          <div><dt>Faces</dt><dd>{observation.face_count}</dd></div>
          <div><dt>Quality</dt><dd>{formatPercent(observation.quality_score)}</dd></div>
          <div><dt>Diversity</dt><dd>{formatPercent(observation.diversity_score)}</dd></div>
        </dl>
        <p>{observation.reasons[0] ?? "Awaiting identity compilation"}</p>
        {observation.warnings.map((warning) => <p className="candidate-warning" key={warning}>{warning}</p>)}
        <div className="decision-buttons" role="group" aria-label={`Review ${displayName(item)}`}>
          <button type="button" className={observation.review_status === "accepted" ? "active accept" : "accept"} onClick={() => onReview("accepted")} disabled={busy} title="Accept"><Check size={15} /></button>
          <button type="button" className={observation.review_status === "needs_review" ? "active review" : "review"} onClick={() => onReview("needs_review")} disabled={busy} title="Needs review"><RefreshCw size={14} /></button>
          <button type="button" className={observation.review_status === "rejected" ? "active reject" : "reject"} onClick={() => onReview("rejected")} disabled={busy} title="Reject"><X size={15} /></button>
          <select aria-label={`View for ${displayName(item)}`} value={observation.view} onChange={(event) => onView(event.target.value as DatasetView)} disabled={busy}>
            <option value="face">Face</option><option value="upper_body">Upper body</option><option value="full_body">Full body</option><option value="environment">Environment</option><option value="unknown">Unknown</option>
          </select>
        </div>
      </section>
      <section className="inspector-section crop-controls">
        <div className="inspector-heading"><h3>Crop Recipe</h3><span>{recipe?.status ?? "none"}</span></div>
        {recipe && cropDraft ? (
          <>
            <label>Horizontal<input type="range" min="0" max={Math.max(0, 1 - cropDraft.width)} step="0.005" value={cropDraft.x} disabled={immutable || busy} onChange={(event) => onCropChange({ ...cropDraft, x: Number(event.target.value) })} /></label>
            <label>Vertical<input type="range" min="0" max={Math.max(0, 1 - cropDraft.height)} step="0.005" value={cropDraft.y} disabled={immutable || busy} onChange={(event) => onCropChange({ ...cropDraft, y: Number(event.target.value) })} /></label>
            <label>Zoom<input type="range" min="0.12" max="1" step="0.005" value={cropDraft.width} disabled={immutable || busy} onChange={(event) => onCropChange(resizeCrop(cropDraft, Number(event.target.value), recipe.aspect_ratio))} /></label>
            <dl className="crop-readout"><div><dt>Format</dt><dd>{cropLabel(recipe.kind)}</dd></div><div><dt>Aspect</dt><dd>{recipe.aspect_ratio}</dd></div></dl>
            <div className="crop-actions"><button type="button" onClick={onSaveCrop} disabled={immutable || busy}><Save size={14} /> Approve</button><button className="primary-action" type="button" onClick={onMaterialize} disabled={immutable || busy}><Crop size={14} /> Materialize</button></div>
          </>
        ) : <p>Compile identity to generate crop proposals.</p>}
      </section>
    </>
  );
}

function HealthMetric({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return <div className={tone}><dt>{label}</dt><dd>{value}</dd></div>;
}

function emptyDraft(): IntentDraft {
  return { name: "Character Dataset", targetType: "character", subjectName: "", triggerToken: "", description: "", learnedAttributes: "identity, face, body", controllableAttributes: "expression, pose, clothing, environment", excludedAttributes: "background, other people, watermark" };
}

function projectDraft(project: CharacterProject): IntentDraft {
  return { name: project.name, targetType: project.intent.target_type, subjectName: project.intent.subject_name, triggerToken: project.intent.trigger_token, description: project.intent.description, learnedAttributes: project.intent.learned_attributes.join(", "), controllableAttributes: project.intent.controllable_attributes.join(", "), excludedAttributes: project.intent.excluded_attributes.join(", ") };
}

function intentFromDraft(draft: IntentDraft, existing?: TrainingIntent): TrainingIntent {
  return {
    ...existing,
    target_type: draft.targetType,
    subject_name: draft.subjectName.trim(),
    requested_outputs: existing?.requested_outputs?.length ? existing.requested_outputs : ["image"],
    trigger_token: draft.triggerToken.trim(),
    description: draft.description.trim(),
    learned_attributes: parseAttributes(draft.learnedAttributes),
    controllable_attributes: parseAttributes(draft.controllableAttributes),
    excluded_attributes: parseAttributes(draft.excludedAttributes),
  };
}

function parseAttributes(value: string): string[] { return [...new Set(value.split(",").map((part) => part.trim()).filter(Boolean))]; }
function mergeMediaItems(existing: MediaItem[], incoming: MediaItem[]): MediaItem[] { const items = new Map(existing.map((item) => [item.id, item])); for (const item of incoming) items.set(item.id, item); return [...items.values()]; }
function displayName(item: MediaItem): string { const normalized = item.raw_path?.replace(/\\/g, "/"); return normalized?.split("/").filter(Boolean).at(-1) ?? item.id; }
function formatPercent(value?: number | null): string { return value == null ? "0%" : `${Math.round(value * 100)}%`; }
function filterShortLabel(filter: ReviewFilter): string { return ({ all: "All", anchors: "A", accepted: "Yes", needs_review: "?", rejected: "No" } as Record<ReviewFilter, string>)[filter]; }
function stateLetter(status: DatasetReviewStatus): string { return status === "accepted" ? "Y" : status === "rejected" ? "N" : "?"; }
function viewLabel(view: DatasetView): string { return view.replace("_", " "); }
function cropLabel(kind: CropKind): string { return kind === "upper_body" ? "Upper" : kind === "full_body" ? "Full" : kind.charAt(0).toUpperCase() + kind.slice(1); }
function guidedTargetLabel(target: WizardTarget): string { return ({ image: "Image LoRA", video: "Video LoRA", voice: "Voice dataset", id_lora: "Audio-visual ID-LoRA" } as Record<WizardTarget, string>)[target]; }
function guidedFilterLabel(filter: ReviewFilter): string { return ({ all: "All", anchors: "Trusted faces", accepted: "Accepted", needs_review: "Review", rejected: "Rejected" } as Record<ReviewFilter, string>)[filter]; }
function reviewLabel(status: DatasetReviewStatus): string { return status === "needs_review" ? "Needs review" : status.charAt(0).toUpperCase() + status.slice(1); }
function guidedIdentityRequirement(target: WizardTarget, visualReady: boolean, motionReady: boolean, voiceReady: boolean): string {
  const missing: string[] = [];
  if ((target === "image" || target === "video" || target === "id_lora") && !visualReady) missing.push("a trusted reference face");
  if ((target === "video" || target === "id_lora") && !motionReady) missing.push("one accepted motion clip");
  if ((target === "voice" || target === "id_lora") && !voiceReady) {
    missing.push("confirmation for every accepted voice clip");
  }
  return missing.length ? `Still needed: ${missing.join(", ")}.` : "Identity is ready to build.";
}

function visualReviewPriority(observation?: DatasetObservation): number {
  if (!observation) return -1;
  const singleFaceBoost = observation.face_count === 1 ? 0.4 : 0;
  const faceArea = Math.min(observation.face_area / 0.18, 1);
  const viewBoost = observation.view === "face" ? 0.2 : observation.view === "upper_body" ? 0.1 : 0;
  return singleFaceBoost
    + observation.quality_score * 0.25
    + observation.aesthetic_score * 0.1
    + faceArea * 0.25
    + viewBoost;
}

function proposeVisualAnchorIds(project: CharacterProject, limit: number): string[] {
  return Object.values(project.observations)
    .filter((observation) =>
      observation.review_status !== "rejected"
      && observation.face_count === 1
      && (observation.faces?.length ?? 1) === 1
      && observation.quality_score >= 0.35
      && observation.face_area >= 0.015,
    )
    .map((observation) => {
      const faceConfidence = observation.faces?.[0]?.confidence ?? 0.75;
      const faceScale = Math.min(observation.face_area / 0.18, 1);
      const viewBoost = observation.view === "face" ? 0.12 : observation.view === "upper_body" ? 0.06 : 0;
      const score = observation.quality_score * 0.4
        + observation.aesthetic_score * 0.1
        + observation.diversity_score * 0.12
        + faceConfidence * 0.16
        + faceScale * 0.22
        + viewBoost;
      return { id: observation.media_item_id, score };
    })
    .sort((left, right) => right.score - left.score)
    .slice(0, Math.max(1, limit))
    .map((candidate) => candidate.id);
}
function identityArtworkPath(item: MediaItem, mediaItems: MediaItem[]): string | null {
  const direct = metadataPath(item, "thumbnail_path")
    ?? metadataPath(item, "poster_asset_path")
    ?? metadataPath(item, "source_thumbnail_path")
    ?? metadataPath(item, "poster_source_path");
  if (direct) return direct;
  const bundleKey = metadataPath(item, "source_bundle_key");
  if (bundleKey) {
    const artworkCandidates = mediaItems.filter(
      (candidate) =>
        candidate.media_type === "image"
        && metadataPath(candidate, "source_bundle_key") === bundleKey,
    );
    const artwork = artworkCandidates.find(
      (candidate) => metadataPath(candidate, "asset_role") === "video_poster",
    )
      ?? artworkCandidates.find(
        (candidate) => metadataPath(candidate, "derivative_type") === "video_frame",
      )
      ?? artworkCandidates[0];
    if (artwork?.raw_path) return artwork.raw_path;
  }
  const sourceId = typeof item.metadata_json?.source_media_item_id === "string" ? item.metadata_json.source_media_item_id : null;
  const source = sourceId ? mediaItems.find((candidate) => candidate.id === sourceId) : null;
  if (!source) return null;
  return metadataPath(source, "thumbnail_path") ?? metadataPath(source, "poster_asset_path") ?? (source.media_type === "image" ? source.raw_path ?? null : null);
}
function metadataPath(item: MediaItem, key: string): string | null { const value = item.metadata_json?.[key]; return typeof value === "string" && value.trim() ? value : null; }
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function projectRecipes(project: CharacterProject | null, observation: DatasetObservation | null): CropRecipe[] { if (!project || !observation) return []; const recipes = project.crop_recipes ?? {}; return (observation.crop_recipe_ids ?? []).map((id) => recipes[id]).filter((recipe): recipe is CropRecipe => recipe !== undefined); }
function rectStyle(rect: NormalizedRect) { return { left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` }; }
function resizeCrop(rect: NormalizedRect, width: number, aspect: string): NormalizedRect { const ratio = parseAspect(aspect, rect); const height = Math.min(1, width / ratio); const adjustedWidth = Math.min(1, height * ratio); const centerX = rect.x + rect.width / 2; const centerY = rect.y + rect.height / 2; return { x: Math.max(0, Math.min(1 - adjustedWidth, centerX - adjustedWidth / 2)), y: Math.max(0, Math.min(1 - height, centerY - height / 2)), width: adjustedWidth, height }; }
function parseAspect(aspect: string, rect: NormalizedRect): number { const parts = aspect.split(":").map(Number); return parts.length === 2 && parts.every(Number.isFinite) ? parts[0] / parts[1] : rect.width / rect.height; }

function isCharacterProject(value: unknown): value is CharacterProject { return typeof value === "object" && value !== null && "id" in value && typeof value.id === "string" && "candidate_media_item_ids" in value && Array.isArray(value.candidate_media_item_ids) && "observations" in value && typeof value.observations === "object" && value.observations !== null && "health" in value && typeof value.health === "object" && value.health !== null; }
function isMediaItem(value: unknown): value is MediaItem { return typeof value === "object" && value !== null && "id" in value && typeof value.id === "string" && "media_type" in value && ["image", "video", "audio"].includes(String(value.media_type)); }

function fallbackProject(items: MediaItem[]): CharacterProject {
  const images = items.filter((item) => item.media_type === "image");
  return { id: "offline-character-project", name: "Character Dataset", intent: intentFromDraft(emptyDraft()), candidate_media_item_ids: images.map((item) => item.id), observations: Object.fromEntries(images.map((item) => [item.id, { media_item_id: item.id, review_status: "needs_review" as const, decision_source: "automatic" as const, view: "unknown" as const, is_anchor: false, quality_score: 0, diversity_score: 0, identity_score: null, face_count: 0, face_area: 0, body_coverage: 0, aesthetic_score: 0, head_yaw: null, reasons: ["engine analysis unavailable"], warnings: [], analyzer: "offline", identity_backend: "unavailable", selected_face_index: null, faces: [], crop_recipe_ids: [], updated_at: new Date().toISOString() }])), crop_recipes: {}, health: { candidate_count: images.length, accepted_count: 0, review_count: images.length, rejected_count: 0, anchor_count: 0, effective_observation_count: 0, source_count: 0, largest_source_share: 0, average_quality: 0, average_diversity: 0, view_counts: {}, analyzer: "offline", warnings: ["Character project engine is unavailable."] }, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
}
