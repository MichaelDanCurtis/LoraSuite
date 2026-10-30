import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, CircleAlert, Combine, FolderOpen, PackageOpen, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import type { CharacterProject, IdLoraManifest, MediaItem } from "../lib/types";
import { RunPodBundleConsole } from "./RunPodBundleConsole";
import { IdLoraAcceptance } from "./IdLoraAcceptance";

type IdLoraEngine = Pick<
  EngineClient,
  "assetUrl" | "listVaultMedia" | "listCharacterProjects" | "listIdLoraManifests" | "compileIdLoraManifest" | "exportIdLoraManifest" | "createRunPodBundle" | "listRunPodBundles" | "listRunPodInfrastructureProfiles" | "provisionRunPodInfrastructure" | "listRunPodModelBootstrapRuns" | "getRunPodModelBootstrapRun" | "createRunPodModelBootstrapRun" | "refreshRunPodModelBootstrapRun" | "cancelRunPodModelBootstrapRun" | "listRunPodBundleUploadJobs" | "getRunPodBundleUploadJob" | "createRunPodBundleUploadJob" | "resumeRunPodBundleUploadJob" | "listRunPodPreflightReports" | "createRunPodPreflightReport" | "listRunPodTrainingRuns" | "getRunPodTrainingRun" | "createRunPodTrainingRun" | "refreshRunPodTrainingRun" | "cancelRunPodTrainingRun" | "downloadRunPodTrainingArtifacts" | "registerRunPodTrainingArtifacts" | "listIdLoraEvaluations" | "getIdLoraEvaluation" | "createIdLoraEvaluation" | "getSyncNetCapability"
>;

export function IdLoraCompiler({ engine, activeProjectId = "", guided = false, onProjectChange }: { engine: IdLoraEngine; activeProjectId?: string; guided?: boolean; onProjectChange?(projectId: string): void }) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [manifest, setManifest] = useState<IdLoraManifest | null>(null);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [outputDir, setOutputDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading multimodal inputs...");
  const [runRevision, setRunRevision] = useState(0);

  useEffect(() => {
    let disposed = false;
    Promise.all([engine.listCharacterProjects(), engine.listIdLoraManifests(), engine.listVaultMedia()])
      .then(([projectPayload, manifestPayload, mediaPayload]) => {
        if (disposed) return;
        const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
        const initialProject = availableProjects.find((project) => project.id === activeProjectId)?.id ?? availableProjects[0]?.id ?? "";
        setProjects(availableProjects);
        setProjectId(initialProject);
        if (initialProject && initialProject !== activeProjectId) onProjectChange?.(initialProject);
        setManifest((Array.isArray(manifestPayload) ? manifestPayload : []).find((item) => item.project_id === initialProject) ?? null);
        setMedia(Array.isArray(mediaPayload) ? mediaPayload : []);
        setStatus("Compile after the video and voice datasets have been reviewed.");
      })
      .catch((error) => setStatus(`ID-LoRA error: ${errorMessage(error)}`));
    return () => { disposed = true; };
  }, [engine, activeProjectId]);

  useEffect(() => {
    if (!projectId) return;
    engine.listIdLoraManifests(projectId)
      .then((items) => setManifest((Array.isArray(items) ? items : [])[0] ?? null))
      .catch((error) => setStatus(`ID-LoRA error: ${errorMessage(error)}`));
  }, [engine, projectId]);

  const mediaById = useMemo(() => new Map(media.map((item) => [item.id, item])), [media]);
  const examples = useMemo(() => Object.values(manifest?.examples ?? {}), [manifest]);
  const compliance = manifest?.balance.recipe_compliance;

  async function compile() {
    if (!projectId || busy) return;
    setBusy(true);
    setStatus("Resolving visual lineage and synchronized speech windows...");
    try {
      const result = await engine.compileIdLoraManifest(projectId);
      setManifest(result);
      setStatus(result.status === "ready" ? "ID-LoRA input contract is ready." : "ID-LoRA contract compiled with blocking gaps.");
    } catch (error) {
      setStatus(`ID-LoRA compile error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseOutput() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose ID-LoRA package destination" });
      if (typeof selected === "string") setOutputDir(selected);
    } catch (error) {
      setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function exportPackage() {
    if (!manifest || manifest.status !== "ready" || !outputDir.trim() || busy) return;
    setBusy(true);
    setStatus("Packaging aligned video, speech, captions, and voice references...");
    try {
      const result = await engine.exportIdLoraManifest(manifest.id, outputDir.trim());
      setManifest(result.manifest);
      setStatus(`ID-LoRA package exported: ${result.package.output_path}`);
    } catch (error) {
      setStatus(`ID-LoRA export error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-section id-lora-workspace">
      <header className="id-lora-header">
        <div><Combine size={19} /><span><strong>ID-LoRA Zero-Shot References</strong><small>Inference conditioning · no per-person adapter training</small></span></div>
        <label>Project<select value={projectId} onChange={(event) => { setProjectId(event.target.value); onProjectChange?.(event.target.value); }} disabled={busy}>{projects.length ? projects.map((project) => <option key={project.id} value={project.id}>{projectOptionLabel(project)}</option>) : <option value="">No Identity projects</option>}</select></label>
        <span className={`id-lora-state ${manifest?.status ?? "empty"}`}>{manifest?.status ?? "not compiled"}</span>
        <button className="primary-action" type="button" onClick={compile} disabled={!projectId || busy}><RefreshCw size={14} /> Compile Contract</button>
      </header>
      <dl className="id-lora-metrics">
        <Metric label="Visual" value={manifest?.balance.visual_example_count ?? 0} />
        <Metric label="Synced AV" value={manifest?.balance.synchronized_pair_count ?? 0} />
        <Metric label="Visual only" value={manifest?.balance.visual_only_count ?? 0} />
        <Metric label="Voice refs" value={manifest?.balance.voice_reference_count ?? 0} />
        <Metric label="Train" value={manifest?.balance.train_count ?? 0} />
        <Metric label="Validation" value={manifest?.balance.validation_count ?? 0} />
      </dl>
      {compliance ? (
        <details className={`video-recipe-compliance id-lora-recipe-compliance ${compliance.status}`} open={compliance.status !== "ready"}>
          <summary>
            <span>
              {compliance.status === "ready" ? <ShieldCheck size={15} /> : <CircleAlert size={15} />}
              <strong>{compliance.recipe_label}</strong>
              <small>Inference recipe v{compliance.recipe_version} · {Math.round(compliance.score * 100)}% preflight</small>
            </span>
            <span className="video-recipe-state">{compliance.status}</span>
          </summary>
          <div className="video-recipe-checks">
            {compliance.checks.map((check) => (
              <article className={check.passed ? "passed" : check.severity} key={check.check_id} title={check.detail}>
                <span>{check.passed ? <Check size={12} /> : <X size={12} />}</span>
                <div><strong>{check.label}</strong><small>{check.passed ? `${check.current ?? "ready"}` : check.detail}</small></div>
              </article>
            ))}
          </div>
        </details>
      ) : manifest?.balance.warnings.length ? <div className="id-lora-warnings"><CircleAlert size={15} />{manifest.balance.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div> : manifest ? <div className="id-lora-ready"><ShieldCheck size={15} /> Source alignment and split isolation passed.</div> : null}
      <section className="id-lora-grid">
        {examples.map((example) => {
          const video = mediaById.get(example.video_media_item_id);
          return (
            <article className={`id-lora-card ${example.pairing_kind}`} key={example.id}>
              <video src={video?.raw_path ? engine.assetUrl(video.raw_path) : undefined} controls preload="metadata" />
              <div className="id-lora-card-badges"><span>{example.pairing_kind === "synchronized_av" ? "Synced AV" : "Visual only"}</span><span>{example.split}</span><span>ID {Math.round(example.identity_score * 100)}%</span></div>
              <p>{example.multimodal_caption}</p>
              {example.warnings.map((warning) => <small key={warning}>{warning}</small>)}
            </article>
          );
        })}
        {!examples.length ? <p className="dataset-empty">No ID-LoRA contract compiled yet.</p> : null}
      </section>
      <section className="id-lora-export">
        <div><PackageOpen size={16} /><span><strong>Portable AV Package</strong><small>LTX-2.3 zero-shot references · evaluation-gated</small></span></div>
        <input aria-label="ID-LoRA output folder" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="/path/to/id-lora-package" />
        {isTauri() ? <button type="button" onClick={chooseOutput} disabled={busy} title="Choose output folder"><FolderOpen size={14} /></button> : null}
        <button className="primary-action" type="button" onClick={exportPackage} disabled={!manifest || manifest.status !== "ready" || !outputDir.trim() || busy}>Export Package</button>
      </section>
      {manifest?.export_path ? <RunPodBundleConsole engine={engine} sourceExportPath={manifest.export_path} modality="audio_visual" triggerToken={projects.find((project) => project.id === manifest.project_id)?.intent.trigger_token ?? ""} fingerprint={manifest.fingerprint} trainingTargetProfileId={manifest.target_profile_id ?? "runpod_id_lora_ltx23_inference"} onRunChanged={() => setRunRevision((value) => value + 1)} /> : null}
      {!guided && projectId ? <IdLoraAcceptance engine={engine} projectId={projectId} refreshToken={runRevision} /> : null}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
