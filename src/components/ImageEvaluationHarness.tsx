import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, CircleAlert, CloudCog, FolderOpen, ImageIcon, Play, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { resolveCredential } from "../lib/credentials";
import { projectOptionLabel } from "../lib/projects";
import type { BenchmarkGenerationRun, CharacterProject, IdentityRuntimeStatus, ImageBenchmarkCaseDefinition, ImageBenchmarkRun, ModelArtifactRecord } from "../lib/types";

export type ImageEvaluationEngine = Pick<EngineClient,
  "assetUrl" | "listCharacterProjects" | "listModelArtifacts" | "getIdentityStatus" |
  "getImageBenchmarkSuite" | "prepareImageBenchmarkWorkspace" | "listBenchmarkGenerationRuns" |
  "getBenchmarkGenerationRun" | "retryBenchmarkGenerationRun" | "createImageBenchmarkGenerationRun" | "createRunPodImageBenchmarkGenerationRun" |
  "listImageBenchmarkRuns" | "getImageBenchmarkRun" | "createImageBenchmarkRun"
>;

type GenerationProvider = "runcomfy_model_api" | "runpod_serverless";

export function ImageEvaluationHarness({ engine, activeProjectId = "", onProjectChange }: { engine: ImageEvaluationEngine; activeProjectId?: string; onProjectChange?(projectId: string): void }) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [artifactId, setArtifactId] = useState("");
  const [suite, setSuite] = useState<ImageBenchmarkCaseDefinition[]>([]);
  const [runs, setRuns] = useState<ImageBenchmarkRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [generationRuns, setGenerationRuns] = useState<BenchmarkGenerationRun[]>([]);
  const [identityStatus, setIdentityStatus] = useState<IdentityRuntimeStatus | null>(null);
  const [workspaceDir, setWorkspaceDir] = useState("");
  const [baselineDir, setBaselineDir] = useState("");
  const [loraDir, setLoraDir] = useState("");
  const [provider, setProvider] = useState<GenerationProvider>("runcomfy_model_api");
  const [modelId, setModelId] = useState("");
  const [endpointId, setEndpointId] = useState("");
  const [loraPath, setLoraPath] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [seedBase, setSeedBase] = useState(424242);
  const [autoEvaluate, setAutoEvaluate] = useState(true);
  const [baselinePayload, setBaselinePayload] = useState('{"prompt":"$PROMPT","seed":"$SEED"}');
  const [loraPayload, setLoraPayload] = useState('{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading image acceptance contract...");

  useEffect(() => {
    if (provider === "runpod_serverless") {
      setBaselinePayload('{"input":{"prompt":"$PROMPT","seed":"$SEED"}}');
      setLoraPayload('{"input":{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}}');
    } else {
      setBaselinePayload('{"prompt":"$PROMPT","seed":"$SEED"}');
      setLoraPayload('{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}');
    }
  }, [provider]);

  useEffect(() => {
    let disposed = false;
    Promise.all([
      engine.listCharacterProjects(), engine.listModelArtifacts(), engine.getIdentityStatus(),
      engine.getImageBenchmarkSuite(), engine.listBenchmarkGenerationRuns(undefined, "image"), engine.listImageBenchmarkRuns(),
    ]).then(([projectPayload, artifactPayload, identityPayload, suitePayload, generationPayload, runPayload]) => {
      if (disposed) return;
      const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
      const initialProjectId = availableProjects.find((item) => item.id === activeProjectId)?.id ?? availableProjects[0]?.id ?? "";
      setProjects(availableProjects);
      setProjectId(initialProjectId);
      if (initialProjectId && initialProjectId !== activeProjectId) onProjectChange?.(initialProjectId);
      setArtifacts((Array.isArray(artifactPayload) ? artifactPayload : []).filter((item) => item.modality === "image"));
      setIdentityStatus(identityPayload);
      setSuite(Array.isArray(suitePayload) ? suitePayload : []);
      setGenerationRuns(Array.isArray(generationPayload) ? generationPayload : []);
      setRuns(Array.isArray(runPayload) ? runPayload : []);
      setStatus("Generate the matched still-image suite, then inspect identity and composition gates.");
    }).catch((error) => setStatus(`Image evaluation error: ${errorMessage(error)}`));
    return () => { disposed = true; };
  }, [engine, activeProjectId]);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([engine.listImageBenchmarkRuns(projectId), engine.listBenchmarkGenerationRuns(projectId, "image")])
      .then(([runPayload, generationPayload]) => {
        setRuns(Array.isArray(runPayload) ? runPayload : []);
        setGenerationRuns(Array.isArray(generationPayload) ? generationPayload : []);
      })
      .catch((error) => setStatus(`Image evaluation error: ${errorMessage(error)}`));
  }, [engine, projectId]);

  const projectArtifacts = useMemo(() => artifacts.filter((item) => !item.project_id || item.project_id === projectId), [artifacts, projectId]);
  useEffect(() => {
    if (projectArtifacts.some((item) => item.id === artifactId)) return;
    setArtifactId(projectArtifacts[0]?.id ?? "");
  }, [artifactId, projectArtifacts]);
  useEffect(() => {
    const artifact = projectArtifacts.find((item) => item.id === artifactId);
    if (artifact) setLoraPath(artifact.checkpoint_name);
  }, [artifactId, projectArtifacts]);

  const activeRunIds = useMemo(() => runs.filter((run) => run.status === "queued" || run.status === "running").map((run) => run.id), [runs]);
  useEffect(() => {
    if (!activeRunIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeRunIds.map((id) => engine.getImageBenchmarkRun(id)));
      setRuns((existing) => existing.map((run) => {
        const update = updates[activeRunIds.indexOf(run.id)];
        return update?.status === "fulfilled" ? update.value : run;
      }));
      if (updates.some((update) => update.status === "fulfilled" && update.value.status === "complete")) {
        setArtifacts((await engine.listModelArtifacts()).filter((item) => item.modality === "image"));
      }
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeRunIds.join("|"), engine]);

  const activeGenerationIds = useMemo(() => generationRuns.filter((run) => !["completed", "failed"].includes(run.status)).map((run) => run.id), [generationRuns]);
  useEffect(() => {
    if (!activeGenerationIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeGenerationIds.map((id) => engine.getBenchmarkGenerationRun(id)));
      const completed = updates.find((update) => update.status === "fulfilled" && update.value.status === "completed");
      if (completed?.status === "fulfilled") {
        setBaselineDir(completed.value.baseline_dir);
        setLoraDir(completed.value.lora_dir);
        setRuns(await engine.listImageBenchmarkRuns(projectId));
        setArtifacts((await engine.listModelArtifacts()).filter((item) => item.modality === "image"));
      }
      setGenerationRuns((existing) => existing.map((run) => {
        const update = updates[activeGenerationIds.indexOf(run.id)];
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeGenerationIds.join("|"), engine, projectId]);

  const project = projects.find((item) => item.id === projectId) ?? null;
  const artifact = projectArtifacts.find((item) => item.id === artifactId) ?? null;
  const latest = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;

  async function retryImageCase(runId: string, caseId: string) {
    const source = generationRuns.find((run) => run.benchmark_run_id === runId);
    if (!source) {
      setStatus("This image evaluation has no linked cloud generation run to retry.");
      return;
    }
    setStatus(`Queueing matched image retry for ${caseId.replaceAll("_", " ")}...`);
    try {
      const retry = await engine.retryBenchmarkGenerationRun(
        source.id,
        [caseId],
        await resolveCredential(
          source.provider === "runpod_serverless" ? "runpod_api" : "runcomfy_api",
          apiToken,
        ),
      );
      setGenerationRuns((existing) => [retry, ...existing.filter((run) => run.id !== retry.id)]);
      setApiToken("");
      setStatus("Targeted image regeneration is running; unchanged cases were reused.");
    } catch (error) {
      setStatus(`Targeted image regeneration error: ${errorMessage(error)}`);
    }
  }

  async function chooseDirectory(target: "workspace" | "baseline" | "lora") {
    if (!isTauri()) return;
    const selected = await open({ directory: true, multiple: false, title: `Choose ${target} image evaluation folder` });
    if (typeof selected !== "string") return;
    if (target === "workspace") setWorkspaceDir(selected);
    else if (target === "baseline") setBaselineDir(selected);
    else setLoraDir(selected);
  }

  async function prepareWorkspace() {
    if (!projectId || !workspaceDir.trim() || busy) return;
    setBusy(true);
    try {
      const workspace = await engine.prepareImageBenchmarkWorkspace(projectId, workspaceDir.trim());
      setBaselineDir(workspace.baseline_dir);
      setLoraDir(workspace.lora_dir);
      setStatus(`Image evaluation contract ready: ${workspace.contract_path}`);
    } catch (error) { setStatus(`Workspace error: ${errorMessage(error)}`); }
    finally { setBusy(false); }
  }

  async function startEvaluation() {
    if (!projectId || !baselineDir.trim() || !loraDir.trim() || busy) return;
    setBusy(true);
    try {
      const run = await engine.createImageBenchmarkRun({ project_id: projectId, baseline_dir: baselineDir.trim(), lora_dir: loraDir.trim(), artifact_id: artifactId || undefined });
      setRuns((existing) => [run, ...existing.filter((item) => item.id !== run.id)]);
      setStatus("Image acceptance scoring is running in the background.");
    } catch (error) { setStatus(`Evaluation error: ${errorMessage(error)}`); }
    finally { setBusy(false); }
  }

  async function generateSuite() {
    const target = provider === "runpod_serverless" ? endpointId.trim() : modelId.trim();
    if (!projectId || !workspaceDir.trim() || !target || !loraPath.trim() || busy) return;
    setBusy(true);
    try {
      const common = {
        project_id: projectId, workspace_root: workspaceDir.trim(), lora_path: loraPath.trim(), artifact_id: artifactId || undefined,
        baseline_payload: parsePayload(baselinePayload, "Baseline"), lora_payload: parsePayload(loraPayload, "LoRA"),
        seed_base: seedBase, auto_evaluate: autoEvaluate, api_token: apiToken.trim() || undefined,
      };
      const run = provider === "runpod_serverless"
        ? await engine.createRunPodImageBenchmarkGenerationRun({ ...common, endpoint_id: endpointId.trim() })
        : await engine.createImageBenchmarkGenerationRun({ ...common, model_id: modelId.trim() });
      setGenerationRuns((existing) => [run, ...existing.filter((item) => item.id !== run.id)]);
      setBaselineDir(run.baseline_dir);
      setLoraDir(run.lora_dir);
      setApiToken("");
      setStatus("Matched image generation is running in the background.");
    } catch (error) { setStatus(`Cloud generation error: ${errorMessage(error)}`); }
    finally { setBusy(false); }
  }

  return <section className="workspace-section benchmark-workspace image-benchmark-workspace">
    <header className="benchmark-header">
      <div><ImageIcon size={19} /><span><strong>Image LoRA Acceptance</strong><small>Matched identity, quality, composition, and disentanglement suite</small></span></div>
      <label>Project<select value={projectId} onChange={(event) => { setProjectId(event.target.value); onProjectChange?.(event.target.value); }}>{projects.map((item) => <option key={item.id} value={item.id}>{projectOptionLabel(item)}</option>)}</select></label>
      <label>Artifact<select aria-label="Image evaluation model artifact" value={artifactId} onChange={(event) => setArtifactId(event.target.value)}><option value="">External LoRA</option>{projectArtifacts.map((item) => <option key={item.id} value={item.id}>{item.checkpoint_name} · {acceptanceLabel(item.acceptance?.status)}</option>)}</select></label>
      <div className="benchmark-preflight"><span className={identityStatus?.ready ? "ready" : "blocked"}>Face {identityStatus?.ready ? "ready" : "needed"}</span>{artifact ? <span className={artifact.acceptance?.release_ready ? "ready" : "blocked"}>Release {acceptanceLabel(artifact.acceptance?.status)}</span> : null}</div>
      <button className="primary-action" type="button" onClick={startEvaluation} disabled={!projectId || !baselineDir.trim() || !loraDir.trim() || busy}><Play size={14} /> Run Evaluation</button>
    </header>
    <section className="benchmark-prepare"><label>Evaluation workspace<input aria-label="Image evaluation workspace folder" value={workspaceDir} onChange={(event) => setWorkspaceDir(event.target.value)} placeholder="/path/to/image-evaluation" /></label>{isTauri() ? <button type="button" title="Choose image evaluation workspace" onClick={() => chooseDirectory("workspace")}><FolderOpen size={14} /></button> : null}<button type="button" onClick={prepareWorkspace} disabled={!projectId || !workspaceDir.trim() || busy}>Prepare Folders</button></section>
    <section className="benchmark-cloud" aria-label="Image benchmark generation">
      <div><CloudCog size={17} /><span><strong>Generate Matched Images</strong><small>{provider === "runpod_serverless" ? "RunPod Serverless" : "RunComfy Model API"} · 12 outputs</small></span></div>
      <div className="benchmark-provider" role="group" aria-label="Image benchmark provider"><button type="button" className={provider === "runcomfy_model_api" ? "active" : ""} onClick={() => setProvider("runcomfy_model_api")}>RunComfy</button><button type="button" className={provider === "runpod_serverless" ? "active" : ""} onClick={() => setProvider("runpod_serverless")}>RunPod</button></div>
      {provider === "runpod_serverless" ? <label>Endpoint ID<input aria-label="RunPod image benchmark endpoint ID" value={endpointId} onChange={(event) => setEndpointId(event.target.value)} /></label> : <label>Model ID<input aria-label="RunComfy image model ID" value={modelId} onChange={(event) => setModelId(event.target.value)} /></label>}
      <label>LoRA asset<input aria-label={`${provider === "runpod_serverless" ? "RunPod" : "RunComfy"} image LoRA asset`} value={loraPath} onChange={(event) => setLoraPath(event.target.value)} /></label>
      <label>Seed<input aria-label="Image benchmark seed" type="number" value={seedBase} onChange={(event) => setSeedBase(Number(event.target.value) || 0)} /></label>
      <label>API token<input aria-label={`${provider === "runpod_serverless" ? "RunPod" : "RunComfy"} image benchmark API token`} type="password" autoComplete="off" value={apiToken} onChange={(event) => setApiToken(event.target.value)} /></label>
      <label className="benchmark-auto"><input aria-label="Evaluate images automatically" type="checkbox" checked={autoEvaluate} onChange={(event) => setAutoEvaluate(event.target.checked)} /> Auto evaluate</label>
      <button className="primary-action" type="button" onClick={generateSuite} disabled={!projectId || !workspaceDir.trim() || !(provider === "runpod_serverless" ? endpointId.trim() : modelId.trim()) || !loraPath.trim() || busy}><CloudCog size={14} /> Generate Suite</button>
      <details className="benchmark-payloads"><summary>Model payloads</summary><div><label>Baseline JSON<textarea aria-label="Image baseline generation payload" rows={4} value={baselinePayload} onChange={(event) => setBaselinePayload(event.target.value)} /></label><label>LoRA JSON<textarea aria-label="Image LoRA generation payload" rows={4} value={loraPayload} onChange={(event) => setLoraPayload(event.target.value)} /></label></div></details>
    </section>
    {generationRuns[0] ? <ImageGenerationProgress run={generationRuns[0]} /> : null}
    <section className="benchmark-paths"><label>Base image folder<input aria-label="Baseline image folder" value={baselineDir} onChange={(event) => setBaselineDir(event.target.value)} /></label>{isTauri() ? <button type="button" title="Choose baseline image folder" onClick={() => chooseDirectory("baseline")}><FolderOpen size={14} /></button> : null}<label>LoRA image folder<input aria-label="LoRA image folder" value={loraDir} onChange={(event) => setLoraDir(event.target.value)} /></label>{isTauri() ? <button type="button" title="Choose LoRA image folder" onClick={() => chooseDirectory("lora")}><FolderOpen size={14} /></button> : null}</section>
    <section className="benchmark-suite image-benchmark-suite" aria-label="Image evaluation contract">{suite.map((definition) => <article key={definition.id}><span><strong>{definition.label}</strong><code>{definition.filename}</code></span><p>{definition.prompt.replace("{trigger}", project?.intent.trigger_token || "trigger_token")}</p></article>)}</section>
    {runs.length ? <div className="benchmark-history"><label>Evaluation history<select aria-label="Image evaluation history" value={latest?.id ?? ""} onChange={(event) => setSelectedRunId(event.target.value)}>{runs.map((run) => <option value={run.id} key={run.id}>{imageHistoryLabel(run)}</option>)}</select></label><span>{runs.length} persisted run{runs.length === 1 ? "" : "s"}</span></div> : null}
    {latest ? <ImageBenchmarkResult run={latest} assetUrl={engine.assetUrl} onRetry={generationRuns.some((run) => run.benchmark_run_id === latest.id) ? retryImageCase : undefined} /> : <p className="dataset-empty benchmark-empty">No image evaluation runs yet.</p>}
    <p className="status-line" aria-live="polite">{status}</p>
  </section>;
}

function ImageBenchmarkResult({ run, assetUrl, onRetry }: { run: ImageBenchmarkRun; assetUrl(path: string): string; onRetry?(runId: string, caseId: string): Promise<void> }) {
  if (run.status === "queued" || run.status === "running") return <div className="benchmark-running"><RefreshCw size={15} /> Scoring matched images...</div>;
  if (run.status === "failed") return <div className="benchmark-failed"><X size={15} /> {run.error || "Image evaluation failed"}</div>;
  return <section className={`benchmark-result ${run.summary.release_ready ? "ready" : "review"}`} aria-label="Image benchmark result">
    <header><span>{run.summary.release_ready ? <Check size={17} /> : <CircleAlert size={17} />}<strong>{run.summary.release_ready ? "Image LoRA Release Ready" : run.summary.blocked_count ? "Identity Metrics Blocked" : "Image Evaluation Failed"}</strong></span><dl><Metric label="Passed" value={run.summary.passed_count} /><Metric label="Failed" value={run.summary.failed_count} /><Metric label="Blocked" value={run.summary.blocked_count} /><Metric label="Identity" value={percent(run.summary.average_lora_identity)} /><Metric label="Gain" value={percent(run.summary.identity_gain)} /><Metric label="Quality" value={percent(run.summary.average_visual_quality)} /></dl></header>
    <div className="image-benchmark-results">{Object.values(run.cases).map((result) => <article className={result.passed ? "passed" : result.blocked ? "blocked" : "failed"} key={result.definition.id}><header><strong>{result.definition.label}</strong><span>{result.passed ? "pass" : result.blocked ? "blocked" : "fail"}</span></header><div className="image-benchmark-comparison"><figure><img src={assetUrl(result.baseline_path)} alt={`${result.definition.label} baseline`} /><figcaption>Base · {percent(result.baseline.identity_similarity)}</figcaption></figure><figure><img src={assetUrl(result.lora_path)} alt={`${result.definition.label} LoRA`} /><figcaption>LoRA · {percent(result.lora.identity_similarity)}</figcaption></figure></div>{result.reasons.length ? <small>{result.reasons.join(" ")}</small> : null}{onRetry ? <button className="image-case-retry" type="button" onClick={() => onRetry(run.id, result.definition.id)}><RefreshCw size={13} /> Regenerate Pair</button> : null}</article>)}</div>
    {run.summary.warnings.length ? <p className="benchmark-warning">{run.summary.warnings.join(" ")}</p> : null}
  </section>;
}

function ImageGenerationProgress({ run }: { run: BenchmarkGenerationRun }) { return <section className={`benchmark-generation ${run.status}`} aria-label="Image benchmark generation progress"><span>{run.status === "failed" ? <X size={15} /> : run.status === "completed" ? <Check size={15} /> : <RefreshCw size={15} />}<strong>{run.progress_message}</strong></span><progress max={Math.max(1, run.progress_total)} value={run.progress_current} /><small>{run.progress_current}/{run.progress_total} · {run.provider === "runpod_serverless" ? "RunPod" : "RunComfy"}</small>{run.error || run.evaluation_error ? <p>{run.error || run.evaluation_error}</p> : null}</section>; }
function Metric({ label, value }: { label: string; value: string | number }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function percent(value?: number | null) { return value == null ? "--" : `${Math.round(value * 100)}%`; }
function acceptanceLabel(status?: string) { return !status || status === "not_evaluated" ? "not evaluated" : status.replaceAll("_", " "); }
function imageHistoryLabel(run: ImageBenchmarkRun) { return `${new Date(run.created_at).toLocaleString()} · ${run.summary.release_ready ? "release ready" : run.status === "complete" ? `${run.summary.passed_count} pass / ${run.summary.failed_count} fail` : run.status}`; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
function parsePayload(value: string, label: string): Record<string, unknown> { try { const parsed = JSON.parse(value) as unknown; if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("must be an object"); return parsed as Record<string, unknown>; } catch (error) { throw new Error(`${label} payload is invalid: ${errorMessage(error)}`); } }
