import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, CircleAlert, CloudCog, FlaskConical, FolderOpen, Play, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { resolveCredential } from "../lib/credentials";
import { projectOptionLabel } from "../lib/projects";
import type { BenchmarkCaseDefinition, BenchmarkGenerationRun, BenchmarkRun, CharacterProject, IdentityRuntimeStatus, ModelArtifactRecord, SyncNetCapability } from "../lib/types";

export type EvaluationEngine = Pick<
  EngineClient,
  "listCharacterProjects" | "listModelArtifacts" | "getIdentityStatus" | "getVoiceIdentityStatus" | "getSyncNetCapability" | "getBenchmarkSuite" | "prepareBenchmarkWorkspace" | "listBenchmarkGenerationRuns" | "getBenchmarkGenerationRun" | "retryBenchmarkGenerationRun" | "createBenchmarkGenerationRun" | "createRunPodBenchmarkGenerationRun" | "listBenchmarkRuns" | "getBenchmarkRun" | "createBenchmarkRun" | "reviewBenchmarkCase" | "assetUrl"
>;

type GenerationProvider = "runcomfy_model_api" | "runpod_serverless";

export function EvaluationHarness({ engine, activeProjectId = "", onProjectChange }: { engine: EvaluationEngine; activeProjectId?: string; onProjectChange?(projectId: string): void }) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [artifactId, setArtifactId] = useState("");
  const [suite, setSuite] = useState<BenchmarkCaseDefinition[]>([]);
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [generationRuns, setGenerationRuns] = useState<BenchmarkGenerationRun[]>([]);
  const [identityStatus, setIdentityStatus] = useState<IdentityRuntimeStatus | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<IdentityRuntimeStatus | null>(null);
  const [syncNetStatus, setSyncNetStatus] = useState<SyncNetCapability | null>(null);
  const [baselineDir, setBaselineDir] = useState("");
  const [loraDir, setLoraDir] = useState("");
  const [workspaceDir, setWorkspaceDir] = useState("");
  const [generationProvider, setGenerationProvider] = useState<GenerationProvider>("runcomfy_model_api");
  const [modelId, setModelId] = useState("");
  const [endpointId, setEndpointId] = useState("");
  const [loraPath, setLoraPath] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [seedBase, setSeedBase] = useState(424242);
  const [autoEvaluate, setAutoEvaluate] = useState(true);
  const [baselinePayload, setBaselinePayload] = useState('{"prompt":"$PROMPT","seed":"$SEED"}');
  const [loraPayload, setLoraPayload] = useState('{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading evaluation contract...");

  useEffect(() => {
    if (generationProvider === "runpod_serverless") {
      setBaselinePayload('{"input":{"prompt":"$PROMPT","seed":"$SEED"}}');
      setLoraPayload('{"input":{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}}');
    } else {
      setBaselinePayload('{"prompt":"$PROMPT","seed":"$SEED"}');
      setLoraPayload('{"prompt":"$PROMPT","seed":"$SEED","lora":{"path":"$LORA_PATH"}}');
    }
  }, [generationProvider]);

  useEffect(() => {
    let disposed = false;
    Promise.all([
      engine.listCharacterProjects(),
      engine.listModelArtifacts(),
      engine.getIdentityStatus(),
      engine.getVoiceIdentityStatus(),
      engine.getSyncNetCapability(),
      engine.getBenchmarkSuite(),
      engine.listBenchmarkGenerationRuns(undefined, "audio_visual"),
      engine.listBenchmarkRuns(),
    ]).then(([projectPayload, artifactPayload, identityPayload, voicePayload, syncNetPayload, suitePayload, generationPayload, runPayload]) => {
      if (disposed) return;
      const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
      setProjects(availableProjects);
      const initialProjectId = availableProjects.find((project) => project.id === activeProjectId)?.id ?? availableProjects[0]?.id ?? "";
      setProjectId(initialProjectId);
      if (initialProjectId && initialProjectId !== activeProjectId) onProjectChange?.(initialProjectId);
      const videoArtifacts = (Array.isArray(artifactPayload) ? artifactPayload : []).filter((item) => item.modality === "video" || item.modality === "audio_visual");
      setArtifacts(videoArtifacts);
      setIdentityStatus(identityPayload);
      setVoiceStatus(voicePayload);
      setSyncNetStatus(syncNetPayload);
      setSuite(Array.isArray(suitePayload) ? suitePayload : []);
      setGenerationRuns(Array.isArray(generationPayload) ? generationPayload : []);
      setRuns(Array.isArray(runPayload) ? runPayload : []);
      setStatus("Generate the named baseline and LoRA videos, then run the comparison.");
    }).catch((error) => setStatus(`Evaluation error: ${errorMessage(error)}`));
    return () => { disposed = true; };
  }, [engine, activeProjectId]);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([engine.listBenchmarkRuns(projectId), engine.listBenchmarkGenerationRuns(projectId, "audio_visual")])
      .then(([runPayload, generationPayload]) => {
        setRuns(Array.isArray(runPayload) ? runPayload : []);
        setGenerationRuns(Array.isArray(generationPayload) ? generationPayload : []);
      })
      .catch((error) => setStatus(`Evaluation error: ${errorMessage(error)}`));
  }, [engine, projectId]);

  useEffect(() => {
    const artifact = artifacts.find((item) => item.id === artifactId);
    if (artifact) setLoraPath(artifact.checkpoint_name);
  }, [artifactId, artifacts]);

  const projectArtifacts = useMemo(
    () => artifacts.filter((item) => !item.project_id || item.project_id === projectId),
    [artifacts, projectId],
  );
  useEffect(() => {
    if (projectArtifacts.some((item) => item.id === artifactId)) return;
    setArtifactId(projectArtifacts[0]?.id ?? "");
  }, [artifactId, projectArtifacts]);

  const activeIds = useMemo(() => runs.filter((run) => run.status === "queued" || run.status === "running").map((run) => run.id), [runs]);
  useEffect(() => {
    if (!activeIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeIds.map((id) => engine.getBenchmarkRun(id)));
      if (updates.some((update) => update.status === "fulfilled" && update.value.status === "complete")) {
        const artifactPayload = await engine.listModelArtifacts();
        setArtifacts((Array.isArray(artifactPayload) ? artifactPayload : []).filter((item) => item.modality === "video" || item.modality === "audio_visual"));
      }
      setRuns((existing) => existing.map((run) => {
        const index = activeIds.indexOf(run.id);
        const update = updates[index];
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeIds.join("|"), engine]);

  const activeGenerationIds = useMemo(() => generationRuns.filter((run) => run.status !== "completed" && run.status !== "failed").map((run) => run.id), [generationRuns]);
  useEffect(() => {
    if (!activeGenerationIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeGenerationIds.map((id) => engine.getBenchmarkGenerationRun(id)));
      const completed = updates.find((update) => update.status === "fulfilled" && update.value.status === "completed");
      if (completed?.status === "fulfilled") {
        setBaselineDir(completed.value.baseline_dir);
        setLoraDir(completed.value.lora_dir);
        setStatus(completed.value.benchmark_run_id ? "Cloud generation and acceptance evaluation are complete." : "Cloud benchmark clips are ready. Run the acceptance evaluation.");
        if (completed.value.benchmark_run_id) {
          const refreshed = await engine.listBenchmarkRuns(projectId);
          setRuns(Array.isArray(refreshed) ? refreshed : []);
          const artifactPayload = await engine.listModelArtifacts();
          setArtifacts((Array.isArray(artifactPayload) ? artifactPayload : []).filter((item) => item.modality === "video" || item.modality === "audio_visual"));
        }
      }
      setGenerationRuns((existing) => existing.map((run) => {
        const index = activeGenerationIds.indexOf(run.id);
        const update = updates[index];
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeGenerationIds.join("|"), engine, projectId]);

  const project = projects.find((item) => item.id === projectId);
  const artifact = projectArtifacts.find((item) => item.id === artifactId) ?? null;
  const latest = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;

  async function chooseDirectory(target: "workspace" | "baseline" | "lora") {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: `Choose ${target} evaluation folder` });
      if (typeof selected === "string") {
        if (target === "workspace") setWorkspaceDir(selected);
        else if (target === "baseline") setBaselineDir(selected);
        else setLoraDir(selected);
      }
    } catch (error) {
      setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function prepareWorkspace() {
    if (!projectId || !workspaceDir.trim() || busy) return;
    setBusy(true);
    setStatus("Preparing reproducible baseline and LoRA evaluation folders...");
    try {
      const workspace = await engine.prepareBenchmarkWorkspace(projectId, workspaceDir.trim());
      setBaselineDir(workspace.baseline_dir);
      setLoraDir(workspace.lora_dir);
      setStatus(`Evaluation contract ready: ${workspace.contract_path}`);
    } catch (error) {
      setStatus(`Workspace preparation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!projectId || !baselineDir.trim() || !loraDir.trim() || busy) return;
    setBusy(true);
    setStatus("Queueing baseline versus LoRA evaluation...");
    try {
      const run = await engine.createBenchmarkRun({
        project_id: projectId,
        baseline_dir: baselineDir.trim(),
        lora_dir: loraDir.trim(),
        artifact_id: artifactId || undefined,
      });
      setRuns((existing) => [run, ...existing.filter((item) => item.id !== run.id)]);
      setStatus("Evaluation running in the background.");
    } catch (error) {
      setStatus(`Evaluation start error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function generateSuite() {
    const providerTarget = generationProvider === "runpod_serverless" ? endpointId.trim() : modelId.trim();
    if (!projectId || !workspaceDir.trim() || !providerTarget || !loraPath.trim() || busy) return;
    setBusy(true);
    setStatus(`Queueing eight matched ${generationProvider === "runpod_serverless" ? "RunPod Serverless" : "RunComfy Model API"} clips...`);
    try {
      const parsedBaseline = parsePayload(baselinePayload, "Baseline");
      const parsedLora = parsePayload(loraPayload, "LoRA");
      const common = {
        project_id: projectId,
        workspace_root: workspaceDir.trim(),
        lora_path: loraPath.trim(),
        artifact_id: artifactId || undefined,
        baseline_payload: parsedBaseline,
        lora_payload: parsedLora,
        seed_base: seedBase,
        auto_evaluate: autoEvaluate,
        api_token: apiToken.trim() || undefined,
      };
      const run = generationProvider === "runpod_serverless"
        ? await engine.createRunPodBenchmarkGenerationRun({ ...common, endpoint_id: endpointId.trim() })
        : await engine.createBenchmarkGenerationRun({ ...common, model_id: modelId.trim() });
      setGenerationRuns((existing) => [run, ...existing.filter((item) => item.id !== run.id)]);
      setApiToken("");
      setBaselineDir(run.baseline_dir);
      setLoraDir(run.lora_dir);
      setStatus("Cloud generation is running in the background.");
    } catch (error) {
      setStatus(`Cloud generation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function reviewCase(runId: string, caseId: string, decision: "pending" | "accepted" | "rejected", note: string) {
    setStatus(decision === "pending" ? "Resetting human review decision..." : `Saving ${decision} review decision...`);
    try {
      const updated = await engine.reviewBenchmarkCase(runId, caseId, decision, note);
      setRuns((existing) => existing.map((run) => run.id === updated.id ? updated : run));
      setStatus(updated.summary.release_ready ? "Automated checks and human review passed. This artifact is release ready." : "Human review decision saved.");
      if (updated.artifact_id) {
        const artifactPayload = await engine.listModelArtifacts();
        setArtifacts((Array.isArray(artifactPayload) ? artifactPayload : []).filter((item) => item.modality === "video" || item.modality === "audio_visual"));
      }
    } catch (error) {
      setStatus(`Review error: ${errorMessage(error)}`);
      throw error;
    }
  }

  async function retryCase(runId: string, caseId: string) {
    const source = generationRuns.find((run) => run.benchmark_run_id === runId);
    if (!source) {
      setStatus("This evaluation was created from local folders, so no cloud generation run is available to retry.");
      return;
    }
    setStatus(`Queueing a matched baseline and LoRA retry for ${caseId.replaceAll("_", " ")}...`);
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
      setStatus("Targeted regeneration is running. The other benchmark outputs were reused.");
    } catch (error) {
      setStatus(`Targeted regeneration error: ${errorMessage(error)}`);
    }
  }

  return (
    <section className="workspace-section benchmark-workspace">
      <header className="benchmark-header">
        <div><FlaskConical size={19} /><span><strong>LoRA Acceptance Harness</strong><small>Baseline versus trained output · fixed reproducible suite</small></span></div>
        <label>Project<select value={projectId} onChange={(event) => { setProjectId(event.target.value); onProjectChange?.(event.target.value); }}>{projects.map((item) => <option key={item.id} value={item.id}>{projectOptionLabel(item)}</option>)}</select></label>
        <label>Artifact<select aria-label="Evaluation model artifact" value={artifactId} onChange={(event) => setArtifactId(event.target.value)}><option value="">Unregistered / external</option>{projectArtifacts.map((item) => <option key={item.id} value={item.id}>{item.checkpoint_name} · {acceptanceLabel(item.acceptance?.status)}</option>)}</select></label>
        <div className="benchmark-preflight"><span className={identityStatus?.ready ? "ready" : "blocked"}>Face {identityStatus?.ready ? "ready" : "needed"}</span><span className={voiceStatus?.ready ? "ready" : "blocked"}>Voice {voiceStatus?.ready ? "ready" : "needed"}</span><span className={syncNetStatus?.ready ? "ready" : "blocked"} title={syncNetStatus?.problems.join(" ")}>SyncNet {syncNetStatus?.ready ? "ready" : "setup"}</span>{artifact ? <span className={artifact.acceptance?.release_ready ? "ready" : "blocked"}>Release {acceptanceLabel(artifact.acceptance?.status)}</span> : null}</div>
        <button className="primary-action" type="button" onClick={start} disabled={!projectId || !baselineDir.trim() || !loraDir.trim() || busy}><Play size={14} /> Run Evaluation</button>
      </header>
      <section className="benchmark-prepare">
        <label>Evaluation workspace<input aria-label="Evaluation workspace folder" value={workspaceDir} onChange={(event) => setWorkspaceDir(event.target.value)} placeholder="/path/to/evaluation-workspace" /></label>
        {isTauri() ? <button type="button" title="Choose evaluation workspace" onClick={() => chooseDirectory("workspace")}><FolderOpen size={14} /></button> : null}
        <button type="button" onClick={prepareWorkspace} disabled={!projectId || !workspaceDir.trim() || busy}>Prepare Folders</button>
      </section>
      <section className="benchmark-cloud" aria-label="Cloud benchmark generation">
        <div><CloudCog size={17} /><span><strong>Generate Matched Suite</strong><small>{generationProvider === "runpod_serverless" ? "RunPod Serverless" : "RunComfy Model API"} · secure store or session override</small></span></div>
        <div className="benchmark-provider" role="group" aria-label="Benchmark generation provider"><button type="button" className={generationProvider === "runcomfy_model_api" ? "active" : ""} onClick={() => setGenerationProvider("runcomfy_model_api")}>RunComfy</button><button type="button" className={generationProvider === "runpod_serverless" ? "active" : ""} onClick={() => setGenerationProvider("runpod_serverless")}>RunPod</button></div>
        {generationProvider === "runpod_serverless"
          ? <label>Endpoint ID<input aria-label="RunPod benchmark endpoint ID" value={endpointId} onChange={(event) => setEndpointId(event.target.value)} placeholder="serverless-endpoint-id" /></label>
          : <label>Model ID<input aria-label="RunComfy video model ID" value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="provider/video-model-id" /></label>}
        <label>LoRA asset<input aria-label={`${generationProvider === "runpod_serverless" ? "RunPod" : "RunComfy"} LoRA asset`} value={loraPath} onChange={(event) => setLoraPath(event.target.value)} placeholder="trained-lora.safetensors or public URL" /></label>
        <label>Seed<input aria-label="Benchmark seed" type="number" value={seedBase} onChange={(event) => setSeedBase(Number(event.target.value) || 0)} /></label>
        <label>API token<input aria-label={`${generationProvider === "runpod_serverless" ? "RunPod" : "RunComfy"} benchmark API token`} type="password" autoComplete="off" value={apiToken} onChange={(event) => setApiToken(event.target.value)} placeholder={generationProvider === "runpod_serverless" ? "Session key or RUNPOD_API_KEY" : "Session token or RUNCOMFY_TOKEN"} /></label>
        <label className="benchmark-auto"><input aria-label="Evaluate automatically" type="checkbox" checked={autoEvaluate} onChange={(event) => setAutoEvaluate(event.target.checked)} /> Auto evaluate</label>
        <button className="primary-action" type="button" onClick={generateSuite} disabled={!projectId || !workspaceDir.trim() || !(generationProvider === "runpod_serverless" ? endpointId.trim() : modelId.trim()) || !loraPath.trim() || busy}><CloudCog size={14} /> Generate Suite</button>
        <details className="benchmark-payloads"><summary>Model payloads</summary><div><label>Baseline JSON<textarea aria-label="Baseline generation payload" rows={4} value={baselinePayload} onChange={(event) => setBaselinePayload(event.target.value)} /></label><label>LoRA JSON<textarea aria-label="LoRA generation payload" rows={4} value={loraPayload} onChange={(event) => setLoraPayload(event.target.value)} /></label></div></details>
      </section>
      {generationRuns[0] ? <GenerationProgress run={generationRuns[0]} /> : null}
      <section className="benchmark-paths">
        <label>Base model folder<input aria-label="Baseline video folder" value={baselineDir} onChange={(event) => setBaselineDir(event.target.value)} placeholder="/path/to/baseline-videos" /></label>
        {isTauri() ? <button type="button" title="Choose baseline folder" onClick={() => chooseDirectory("baseline")}><FolderOpen size={14} /></button> : null}
        <label>LoRA folder<input aria-label="LoRA video folder" value={loraDir} onChange={(event) => setLoraDir(event.target.value)} placeholder="/path/to/lora-videos" /></label>
        {isTauri() ? <button type="button" title="Choose LoRA folder" onClick={() => chooseDirectory("lora")}><FolderOpen size={14} /></button> : null}
      </section>
      <section className="benchmark-suite" aria-label="Evaluation video contract">
        {suite.map((definition) => (
          <article key={definition.id}>
            <span><strong>{definition.label}</strong><code>{definition.filename}</code></span>
            <p>{definition.prompt.replace("{trigger}", project?.intent.trigger_token || "trigger_token")}</p>
            {definition.expected_transcript ? <small>Speech: “{definition.expected_transcript}”</small> : null}
          </article>
        ))}
      </section>
      {runs.length ? <div className="benchmark-history"><label>Evaluation history<select aria-label="Audio-visual evaluation history" value={latest?.id ?? ""} onChange={(event) => setSelectedRunId(event.target.value)}>{runs.map((run) => <option value={run.id} key={run.id}>{historyLabel(run)}</option>)}</select></label><span>{runs.length} persisted run{runs.length === 1 ? "" : "s"}</span></div> : null}
      {latest ? <BenchmarkResult run={latest} assetUrl={engine.assetUrl} onReview={reviewCase} onRetry={generationRuns.some((run) => run.benchmark_run_id === latest.id) ? retryCase : undefined} /> : <p className="dataset-empty benchmark-empty">No evaluation runs yet.</p>}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function BenchmarkResult({ run, assetUrl, onReview, onRetry }: { run: BenchmarkRun; assetUrl(path: string): string; onReview(runId: string, caseId: string, decision: "pending" | "accepted" | "rejected", note: string): Promise<void>; onRetry?(runId: string, caseId: string): Promise<void> }) {
  const results = Object.values(run.cases);
  const [activeCaseId, setActiveCaseId] = useState(results.find((item) => item.review_decision === "pending")?.definition.id ?? results[0]?.definition.id ?? "");
  const active = results.find((item) => item.definition.id === activeCaseId) ?? results[0];
  const [note, setNote] = useState(active?.review_note ?? "");
  const [reviewBusy, setReviewBusy] = useState(false);
  useEffect(() => { setNote(active?.review_note ?? ""); }, [active?.definition.id, active?.review_note]);
  if (run.status === "queued" || run.status === "running") return <div className="benchmark-running"><RefreshCw size={15} /> Scoring generated videos...</div>;
  if (run.status === "failed") return <div className="benchmark-failed"><X size={15} /> {run.error || "Evaluation failed"}</div>;
  async function decide(decision: "pending" | "accepted" | "rejected") {
    if (!active || reviewBusy) return;
    setReviewBusy(true);
    try {
      await onReview(run.id, active.definition.id, decision, note);
      if (decision !== "pending") {
        const next = results.find((item) => item.definition.id !== active.definition.id && item.review_decision === "pending");
        if (next) setActiveCaseId(next.definition.id);
      }
    } finally {
      setReviewBusy(false);
    }
  }
  return (
    <section className={`benchmark-result ${run.summary.screening_ready ? "ready" : "review"}`} aria-label="Benchmark result">
      <header>
        <span>{run.summary.release_ready ? <Check size={17} /> : <CircleAlert size={17} />}<strong>{run.summary.release_ready ? "Certified Release Ready" : run.summary.automated_release_ready ? "Human Review Required" : run.summary.screening_ready ? "Screening Passed" : run.summary.blocked_count ? "Metrics Blocked" : "Evaluation Failed"}</strong></span>
        <dl><Metric label="Passed" value={run.summary.passed_count} /><Metric label="Failed" value={run.summary.failed_count} /><Metric label="Pending review" value={run.summary.review_pending_count} /><Metric label="Accepted" value={run.summary.review_accepted_count} /><Metric label="Identity gain" value={percent(run.summary.identity_gain)} /><Metric label="Speaker" value={percent(run.summary.average_speaker_similarity)} /></dl>
      </header>
      <div className="benchmark-review-tabs" role="tablist" aria-label="Evaluation cases">{results.map((result) => <button type="button" role="tab" aria-selected={active?.definition.id === result.definition.id} className={result.review_decision} onClick={() => setActiveCaseId(result.definition.id)} key={result.definition.id}>{result.definition.label}<small>{result.review_decision}</small></button>)}</div>
      {active ? <div className="benchmark-paired-review">
        <div className="benchmark-video-pair">
          <figure><figcaption>Base model</figcaption><video aria-label={`${active.definition.label} baseline video`} src={assetUrl(active.baseline_path)} controls preload="metadata" /></figure>
          <figure><figcaption>Trained LoRA</figcaption><video aria-label={`${active.definition.label} LoRA video`} src={assetUrl(active.lora_path)} controls preload="metadata" /></figure>
        </div>
        <aside className={`benchmark-review-decision ${active.review_decision}`}>
          <div><strong>{active.definition.label}</strong><span>{active.passed ? "automated pass" : active.blocked ? "metrics blocked" : "automated fail"}</span></div>
          <dl><Metric label="Identity" value={percent(active.lora.identity_similarity)} /><Metric label="Stability" value={percent(active.lora.temporal_stability)} /><Metric label="Motion" value={percent(active.lora.motion_score)} /><Metric label="Coverage" value={percent(active.lora.subject_coverage)} />{active.definition.audio_required ? <><Metric label="Speaker" value={percent(active.lora.speaker_similarity)} /><Metric label="Transcript" value={percent(active.lora.transcript_similarity)} /><Metric label="SyncNet LSE-C" value={active.lora.syncnet_lse_c == null ? "--" : active.lora.syncnet_lse_c.toFixed(1)} /></> : null}</dl>
          {active.reasons.length ? <small>{active.reasons.join(" ")}</small> : null}
          <label>Reviewer note<textarea aria-label="Human review note" rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional reason, artifact, or regeneration instruction" /></label>
          <div className="benchmark-review-actions"><button type="button" className="approve" disabled={reviewBusy} onClick={() => decide("accepted")}><Check size={14} /> Accept</button><button type="button" className="reject" disabled={reviewBusy} onClick={() => decide("rejected")}><X size={14} /> Reject</button><button type="button" disabled={reviewBusy || active.review_decision === "pending"} onClick={() => decide("pending")}><RefreshCw size={14} /> Reset</button>{onRetry ? <button type="button" className="retry" disabled={reviewBusy} onClick={() => onRetry(run.id, active.definition.id)}><RefreshCw size={14} /> Regenerate Pair</button> : null}</div>
        </aside>
      </div> : null}
      {run.summary.warnings.length ? <p className="benchmark-warning">{run.summary.warnings.join(" ")}</p> : null}
    </section>
  );
}

function GenerationProgress({ run }: { run: BenchmarkGenerationRun }) {
  const target = run.provider === "runpod_serverless" ? `RunPod · ${run.endpoint_id || run.model_id}` : `RunComfy · ${run.model_id}`;
  return <section className={`benchmark-generation ${run.status}`} aria-label="Benchmark generation progress"><span>{run.status === "failed" ? <X size={15} /> : run.status === "completed" ? <Check size={15} /> : <RefreshCw size={15} />}<strong>{run.progress_message}</strong></span><progress max={Math.max(1, run.progress_total)} value={run.progress_current} /><small>{run.progress_current}/{run.progress_total} · {target}{run.benchmark_run_id ? " · evaluation linked" : ""}</small>{run.error || run.evaluation_error ? <p>{run.error || run.evaluation_error}</p> : null}</section>;
}

function Metric({ label, value }: { label: string; value: string | number }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function percent(value?: number | null): string { return value == null ? "--" : `${Math.round(value * 100)}%`; }
function acceptanceLabel(status?: string): string {
  if (!status || status === "not_evaluated") return "not evaluated";
  return status.replaceAll("_", " ");
}
function historyLabel(run: BenchmarkRun) {
  const state = run.summary.release_ready ? "release ready" : run.status === "complete" ? `${run.summary.passed_count} pass / ${run.summary.failed_count} fail` : run.status;
  return `${new Date(run.created_at).toLocaleString()} · ${state}`;
}
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function parsePayload(value: string, label: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("must be a JSON object");
    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(`${label} payload is invalid: ${errorMessage(error)}`);
  }
}
