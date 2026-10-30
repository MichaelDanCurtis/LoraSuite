import { Check, CircleAlert, FlaskConical, Play, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { IdLoraEvaluationRun, RunPodTrainingRun, SyncNetCapability } from "../lib/types";

type IdLoraAcceptanceEngine = Pick<
  EngineClient,
  "assetUrl" | "listRunPodTrainingRuns" | "listIdLoraEvaluations" | "getIdLoraEvaluation" | "createIdLoraEvaluation" | "getSyncNetCapability"
>;

export function IdLoraAcceptance({ engine, projectId, refreshToken = 0 }: { engine: IdLoraAcceptanceEngine; projectId: string; refreshToken?: number }) {
  const [inferenceRuns, setInferenceRuns] = useState<RunPodTrainingRun[]>([]);
  const [runs, setRuns] = useState<IdLoraEvaluationRun[]>([]);
  const [syncNet, setSyncNet] = useState<SyncNetCapability | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Download a completed zero-shot run to begin AV acceptance.");

  async function reload() {
    const [runpod, evaluations, capability] = await Promise.all([
      engine.listRunPodTrainingRuns(),
      engine.listIdLoraEvaluations(projectId),
      engine.getSyncNetCapability(),
    ]);
    setInferenceRuns(runpod.filter((run) => run.project_id === projectId && run.action === "run_id_lora"));
    setRuns(evaluations);
    setSyncNet(capability);
  }

  useEffect(() => {
    reload().catch((error) => setStatus(`ID-LoRA acceptance error: ${errorMessage(error)}`));
  }, [engine, projectId, refreshToken]);

  const evaluatedRunIds = useMemo(() => new Set(runs.map((run) => run.runpod_run_id)), [runs]);
  const readyRuns = inferenceRuns.filter((run) =>
    run.status === "completed"
    && run.artifacts.some((artifact) => artifact.kind === "contract" && artifact.local_path)
    && run.artifacts.some((artifact) => artifact.kind === "sample" && artifact.local_path?.toLowerCase().endsWith(".mp4"))
    && !evaluatedRunIds.has(run.id)
  );
  const activeIds = useMemo(() => runs.filter((run) => run.status === "queued" || run.status === "running").map((run) => run.id), [runs]);

  useEffect(() => {
    if (!activeIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeIds.map((id) => engine.getIdLoraEvaluation(id)));
      setRuns((existing) => existing.map((run) => {
        const update = updates[activeIds.indexOf(run.id)];
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeIds.join("|"), engine]);

  async function start(runpodRunId: string) {
    if (busy) return;
    setBusy(true);
    setStatus("Snapshotting outputs and starting identity, voice, transcript, motion, and sync checks...");
    try {
      const run = await engine.createIdLoraEvaluation(runpodRunId);
      setRuns((existing) => [run, ...existing]);
      setStatus("ID-LoRA acceptance is running in the background.");
    } catch (error) {
      setStatus(`ID-LoRA acceptance error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return <section className="id-lora-acceptance" aria-label="ID-LoRA acceptance">
    <header>
      <div><FlaskConical size={18} /><span><strong>ID-LoRA Acceptance</strong><small>Face · voice · transcript · motion · certified sync</small></span></div>
      <span className={`id-lora-syncnet-status ${syncNet?.ready ? "ready" : "blocked"}`} title={syncNet?.problems.join(" ")}>SyncNet {syncNet?.ready ? "ready" : "setup"}</span>
      <button type="button" title="Refresh ID-LoRA runs" onClick={() => reload()} disabled={busy}><RefreshCw size={14} /></button>
    </header>
    {readyRuns.map((run) => <div className="id-lora-ready-run" key={run.id}><span><strong>Zero-shot output ready</strong><small>{run.provider_job_id ?? run.id}</small></span><button className="primary-action" type="button" onClick={() => start(run.id)} disabled={busy}><Play size={14} /> Evaluate Outputs</button></div>)}
    {runs.length ? <div className="id-lora-evaluation-runs">{runs.map((run) => <EvaluationRun key={run.id} run={run} assetUrl={engine.assetUrl} />)}</div> : <p className="dataset-empty">No ID-LoRA acceptance runs yet.</p>}
    <p className="status-line" aria-live="polite">{status}</p>
  </section>;
}

function EvaluationRun({ run, assetUrl }: { run: IdLoraEvaluationRun; assetUrl(path: string): string }) {
  const active = run.status === "queued" || run.status === "running";
  const tone = run.summary.release_ready ? "certified" : run.summary.screening_ready ? "screening" : run.status;
  return <article className={`id-lora-evaluation-run ${tone}`}>
    <header>
      <span>{active ? <RefreshCw className="spin" size={14} /> : run.summary.release_ready ? <ShieldCheck size={15} /> : run.summary.screening_ready ? <Check size={15} /> : <CircleAlert size={15} />}<strong>{run.summary.release_ready ? "Certified release ready" : run.summary.screening_ready ? "Local screening passed" : run.status.replace("_", " ")}</strong></span>
      <dl><Metric label="Passed" value={`${run.summary.passed_count}/${run.summary.case_count}`} /><Metric label="Face" value={percent(run.summary.average_identity)} /><Metric label="Voice" value={percent(run.summary.average_speaker_similarity)} /><Metric label="Words" value={percent(run.summary.average_transcript_similarity)} /><Metric label="Stability" value={percent(run.summary.average_stability)} /></dl>
    </header>
    {run.error ? <p className="id-lora-evaluation-error"><X size={13} /> {run.error}</p> : null}
    {Object.values(run.cases).length ? <div className="id-lora-evaluation-cases">{Object.values(run.cases).map((item) => <article key={item.id} className={item.certified ? "certified" : item.passed ? "passed" : item.blocked ? "blocked" : "failed"}>
      <video src={assetUrl(item.video_path)} controls preload="metadata" />
      <div><strong>{item.output_name}</strong><span>{item.certified ? "certified" : item.passed ? "screening pass" : item.blocked ? "blocked" : "failed"}</span></div>
      <p>{item.prompt}</p>
      <dl><Metric label="Face" value={percent(item.metrics.identity_similarity)} /><Metric label="Voice" value={percent(item.metrics.speaker_similarity)} /><Metric label="Words" value={percent(item.metrics.transcript_similarity)} /><Metric label="Sync" value={item.metrics.syncnet_lse_c == null ? "--" : item.metrics.syncnet_lse_c.toFixed(1)} /></dl>
      {item.reasons.length ? <small>{item.reasons.join(" · ")}</small> : null}
    </article>)}</div> : null}
    {run.summary.warnings.map((warning) => <p className="id-lora-evaluation-warning" key={warning}>{warning}</p>)}
  </article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function percent(value?: number | null) { return value == null ? "--" : `${Math.round(value * 100)}%`; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
