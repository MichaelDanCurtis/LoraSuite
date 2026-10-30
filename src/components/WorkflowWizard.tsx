import { AudioLines, Check, ChevronRight, CircleAlert, Combine, Image, RefreshCw, Sparkles, Video, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import type { CharacterProject, MediaItem, ProviderReadinessMatrix, TrainingWorkflowStatus } from "../lib/types";

export type WizardTarget = "image" | "video" | "voice" | "id_lora";
export type WorkspaceTab = "ingest" | "curate" | "identify" | "train";

type WizardEngine = Pick<
  EngineClient,
  "getCurationHandoff" | "listCharacterProjects" | "listDatasetSnapshots" | "listVideoDatasetSnapshots" | "getVoiceIdentityProfile" | "getVoiceDataset" | "listIdLoraManifests" | "getTrainingWorkflow" | "getProviderReadiness"
>;

interface WorkflowWizardProps {
  engine: WizardEngine;
  target: WizardTarget;
  activeTab: WorkspaceTab;
  mediaItems: MediaItem[];
  activeProjectId?: string;
  onProjectChange?(projectId: string): void;
  onTargetChange(target: WizardTarget): void;
  onNavigate(tab: WorkspaceTab): void;
}

const targetOptions = [
  { id: "image" as const, label: "Image", icon: Image },
  { id: "video" as const, label: "Video", icon: Video },
  { id: "voice" as const, label: "Voice", icon: AudioLines },
  { id: "id_lora" as const, label: "ID-LoRA", icon: Combine },
];

export function WorkflowWizard({ engine, target, activeTab, mediaItems, activeProjectId = "", onProjectChange, onTargetChange, onNavigate }: WorkflowWizardProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [snapshot, setSnapshot] = useState<WizardSnapshot | null>(null);
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [status, setStatus] = useState("Workflow state not inspected yet.");

  async function inspect() {
    if (loading) return;
    setLoading(true);
    setStatus("Inspecting workflow evidence...");
    try {
      const [projects, imageSnapshots, videoSnapshots, idManifests] = await Promise.all([
        engine.listCharacterProjects(),
        engine.listDatasetSnapshots(),
        engine.listVideoDatasetSnapshots(),
        engine.listIdLoraManifests(),
      ]);
      const project = projects.find((candidate) => candidate.id === activeProjectId) ?? projects[0];
      const handoff = await engine.getCurationHandoff(project?.id, target);
      setProjects(projects);
      if (project && project.id !== activeProjectId) onProjectChange?.(project.id);
      let voiceAnchors = 0;
      let voiceExported = false;
      let trainingWorkflow: TrainingWorkflowStatus | null = null;
      let providerReadiness: ProviderReadinessMatrix | null = null;
      if (project) {
        const [profile, compilation, workflow, providerMatrix] = await Promise.allSettled([
          engine.getVoiceIdentityProfile(project.id),
          engine.getVoiceDataset(project.id),
          engine.getTrainingWorkflow(project.id),
          engine.getProviderReadiness(project.id),
        ]);
        if (profile.status === "fulfilled") voiceAnchors = profile.value.anchor_media_item_ids.length;
        if (compilation.status === "fulfilled") voiceExported = Boolean(compilation.value.export_path);
        if (workflow.status === "fulfilled") trainingWorkflow = workflow.value;
        if (providerMatrix.status === "fulfilled") providerReadiness = providerMatrix.value;
      }
      const accepted = handoff.items.filter((item) => item.review_status === "accepted");
      const next: WizardSnapshot = {
        curatedImage: accepted.some((item) => item.lane === "image"),
        curatedVideo: accepted.some((item) => item.lane === "video"),
        curatedVoice: accepted.some((item) => item.lane === "audio"),
        visualIdentity: Boolean(project && project.health.anchor_count > 0),
        voiceIdentity: voiceAnchors > 0,
        imageExported: imageSnapshots.some((item) => item.status === "exported" && Boolean(item.export_path)),
        videoExported: videoSnapshots.some((item) => item.status === "exported" && Boolean(item.export_path)),
        voiceExported,
        idLoraExported: idManifests.some((item) => Boolean(item.export_path)),
        trainingWorkflow,
        providerReadiness,
      };
      setSnapshot(next);
      setStatus("Workflow evidence refreshed.");
    } catch (error) {
      setStatus(`Workflow inspection failed: ${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) void inspect();
  }, [open, target, mediaItems.length, activeProjectId]);

  const steps = useMemo(() => workflowSteps(target, mediaItems, snapshot), [target, mediaItems, snapshot]);
  const completed = steps.filter((step) => step.complete).length;
  const nextStep = steps.find((step) => !step.complete) ?? steps[steps.length - 1];
  const selectedLane = snapshot?.trainingWorkflow ? targetLane(snapshot.trainingWorkflow, target) : null;
  const providerItems = snapshot?.providerReadiness?.items.filter((item) => item.lane === target) ?? [];
  const selectedTarget = targetOptions.find((option) => option.id === target) ?? targetOptions[0];
  const SelectedIcon = selectedTarget.icon;

  function openRecommendedAction() {
    if (selectedLane) {
      if (selectedLane.target_mode !== "evaluate") onTargetChange(selectedLane.target_mode);
      onNavigate(selectedLane.target_workspace);
    } else {
      onNavigate(nextStep.id);
    }
    setOpen(false);
  }

  function openProviderHandoff(lane: WizardTarget) {
    onTargetChange(lane);
    onNavigate("train");
    setOpen(false);
  }

  return (
    <>
      <button className="workflow-wizard-toggle" type="button" aria-label="Open workflow wizard" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Sparkles size={15} /><span>{selectedTarget.label}</span><i>{completed}/4</i>
      </button>
      {open ? (
        <section className="workflow-wizard" role="dialog" aria-label="LoRA workflow wizard">
          <header><div><Sparkles size={17} /><span><strong>Workflow</strong><small>Evidence-guided build path</small></span></div><button type="button" title="Close workflow wizard" onClick={() => setOpen(false)}><X size={15} /></button></header>
          {projects.length ? <label className="wizard-project-select">Character project<select aria-label="Workflow character project" value={projects.some((project) => project.id === activeProjectId) ? activeProjectId : projects[0]?.id ?? ""} onChange={(event) => { setSnapshot(null); onProjectChange?.(event.target.value); }}>{projects.map((project) => <option key={project.id} value={project.id}>{projectOptionLabel(project)}</option>)}</select></label> : null}
          <div className="wizard-targets" role="group" aria-label="LoRA output type">
            {targetOptions.map((option) => { const Icon = option.icon; return <button key={option.id} type="button" aria-pressed={target === option.id} onClick={() => onTargetChange(option.id)}><Icon size={14} /> {option.label}</button>; })}
          </div>
          <div className="wizard-steps">
            {steps.map((step, index) => <button key={step.id} type="button" className={`${step.complete ? "complete" : "pending"} ${activeTab === step.id ? "active" : ""}`} onClick={() => onNavigate(step.id)}><span>{step.complete ? <Check size={13} /> : index + 1}</span><strong>{step.label}</strong>{index < steps.length - 1 ? <ChevronRight size={12} /> : null}</button>)}
          </div>
          {snapshot?.trainingWorkflow ? <div className={`wizard-ai-recommendation ${selectedLane?.state ?? "ready"}`}>
            <Sparkles size={14} />
            <span className="wizard-recommendation-copy"><small>{selectedLane ? `${selectedLane.state} · ${selectedLane.phase}` : "AI next action"}</small><strong>{selectedLane?.action_label ?? snapshot.trainingWorkflow.recommendation}</strong><em>{selectedLane?.summary}</em></span>
            {selectedLane && Object.keys(selectedLane.counts).length ? <dl aria-label="Workflow evidence">{Object.entries(selectedLane.counts).slice(0, 4).map(([label, value]) => <div key={label} aria-label={`${label.replaceAll("_", " ")}: ${value}`}><dt>{label.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl> : null}
          </div> : null}
          {selectedLane && (selectedLane.blockers.length || selectedLane.warnings.length) ? <div className="wizard-evidence-alerts" aria-label="Workflow evidence alerts">
            {[...selectedLane.blockers, ...selectedLane.warnings].slice(0, 2).map((item) => <p key={item}><CircleAlert size={12} />{item}</p>)}
          </div> : null}
          {providerItems.length ? <div className="wizard-provider-readiness" aria-label="Provider readiness">
            {providerItems.map((item) => <button type="button" className={item.state} key={`${item.lane}:${item.provider}`} title={item.summary} aria-label={`${item.provider === "runcomfy" ? "RunComfy" : "RunPod"}: ${item.action_label}`} onClick={() => openProviderHandoff(item.lane)}><span><strong>{item.provider === "runcomfy" ? "RunComfy" : "RunPod"}</strong><small>{item.smoke_ready ? "smoke passed" : item.state.replaceAll("_", " ")}</small></span><em>{item.action_label}</em><ChevronRight size={12} /></button>)}
          </div> : null}
          <footer><button type="button" title="Refresh workflow evidence" onClick={inspect} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={14} /></button><span>{selectedLane?.summary ?? nextStep.summary}</span><button className="primary-action" type="button" onClick={openRecommendedAction}>{selectedLane?.action_label ?? (nextStep.complete ? "Open Build & Train" : `Open ${nextStep.label}`)}<ChevronRight size={14} /></button></footer>
          <p className="status-line" aria-live="polite">{status}</p>
        </section>
      ) : null}
    </>
  );
}

interface WizardSnapshot {
  curatedImage: boolean;
  curatedVideo: boolean;
  curatedVoice: boolean;
  visualIdentity: boolean;
  voiceIdentity: boolean;
  imageExported: boolean;
  videoExported: boolean;
  voiceExported: boolean;
  idLoraExported: boolean;
  trainingWorkflow: TrainingWorkflowStatus | null;
  providerReadiness: ProviderReadinessMatrix | null;
}

interface WizardStep { id: WorkspaceTab; label: string; complete: boolean; summary: string }

function workflowSteps(target: WizardTarget, media: MediaItem[], state: WizardSnapshot | null): WizardStep[] {
  const hasImage = media.some((item) => item.media_type === "image");
  const hasVideo = media.some((item) => item.media_type === "video");
  const hasVoice = media.some((item) => item.media_type === "audio");
  const lane = state?.trainingWorkflow ? targetLane(state.trainingWorkflow, target) : null;
  const trained = lane ? lane.state === "complete" : target === "image" ? state?.imageExported : target === "video" ? state?.videoExported : target === "voice" ? state?.voiceExported : state?.idLoraExported;
  const identityEvidence = target === "voice" ? state?.voiceIdentity : target === "id_lora" ? state?.visualIdentity && state?.voiceIdentity : state?.visualIdentity;
  let identified = Boolean(identityEvidence || trained);
  const curationEvidence = target === "image" ? state?.curatedImage : target === "video" ? state?.curatedVideo : target === "voice" ? state?.curatedVoice : state?.curatedVideo && state?.curatedVoice;
  let curated = Boolean(curationEvidence || identified || trained);
  const sourceEvidence = target === "image" ? hasImage : target === "video" ? hasVideo : target === "voice" ? hasVoice : hasVideo && hasVoice;
  let ingest = Boolean(sourceEvidence || curated || identified || trained);
  if (lane && lane.state !== "complete") {
    if (lane.target_workspace === "train") { ingest = true; curated = true; identified = true; }
    if (lane.target_workspace === "identify") { ingest = true; curated = true; identified = false; }
    if (lane.target_workspace === "curate") { ingest = true; curated = false; identified = false; }
    if (lane.target_workspace === "ingest") { ingest = false; curated = false; identified = false; }
  }
  const verifyLabel = target === "voice" ? "Verify Speaker" : "Verify Identity";
  const verifySummary = target === "voice"
    ? (identified ? "Speaker evidence ready" : "Speaker anchors required")
    : (identified ? "Identity evidence ready" : "Identity anchors required");
  return [
    { id: "ingest", label: "Ingest", complete: ingest, summary: ingest ? "Source media available" : "Source media required" },
    { id: "curate", label: "Prepare", complete: Boolean(curated), summary: curated ? "Prepared candidates available" : "Media preparation required" },
    { id: "identify", label: verifyLabel, complete: Boolean(identified), summary: verifySummary },
    { id: "train", label: "Build & Train", complete: Boolean(trained), summary: lane?.summary ?? (trained ? "Provider export ready" : "Dataset export required") },
  ];
}

function targetLane(workflow: TrainingWorkflowStatus, target: WizardTarget) {
  return workflow.lanes.find((lane) => lane.id === target);
}

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
