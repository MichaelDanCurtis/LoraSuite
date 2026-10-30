import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, CircleAlert, FlaskConical, FolderOpen, Play, RefreshCw, ShieldCheck, Volume2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { ModelArtifactRecord, VoiceArtifactEvaluationRun } from "../lib/types";

type VoiceEvaluationEngine = Pick<
  EngineClient,
  | "assetUrl"
  | "listModelArtifacts"
  | "listVoiceArtifactEvaluations"
  | "getVoiceArtifactEvaluation"
  | "getRecommendedVoiceArtifactEvaluation"
  | "createVoiceArtifactEvaluation"
  | "selectVoiceArtifactEvaluation"
>;

export function VoiceArtifactEvaluator({ engine, projectId, refreshToken = 0 }: { engine: VoiceEvaluationEngine; projectId: string; refreshToken?: number }) {
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [artifactId, setArtifactId] = useState("");
  const [samplesDir, setSamplesDir] = useState("");
  const [runs, setRuns] = useState<VoiceArtifactEvaluationRun[]>([]);
  const [recommended, setRecommended] = useState<VoiceArtifactEvaluationRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Register a trained Fish Speech checkpoint, then render evaluation phrases.");

  async function reload() {
    if (!projectId) return;
    const [artifactPayload, runPayload, recommendation] = await Promise.all([
      engine.listModelArtifacts(projectId),
      engine.listVoiceArtifactEvaluations(projectId),
      engine.getRecommendedVoiceArtifactEvaluation(projectId),
    ]);
    const available = artifactPayload.filter((item) => item.modality === "voice");
    setArtifacts(available);
    setArtifactId((current) => available.some((item) => item.id === current) ? current : available[0]?.id ?? "");
    setRuns(runPayload);
    setRecommended(recommendation);
    const firstSample = available.flatMap((item) => item.sample_paths)[0];
    if (firstSample) setSamplesDir((current) => current || parentPath(firstSample));
  }

  useEffect(() => {
    reload().catch((error) => setStatus(`Voice evaluation error: ${errorMessage(error)}`));
  }, [engine, projectId, refreshToken]);

  const activeIds = useMemo(() => runs.filter((run) => run.status === "queued" || run.status === "running").map((run) => run.id), [runs]);
  useEffect(() => {
    if (!activeIds.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeIds.map((id) => engine.getVoiceArtifactEvaluation(id)));
      setRuns((existing) => existing.map((run) => {
        const update = updates[activeIds.indexOf(run.id)];
        return update?.status === "fulfilled" ? update.value : run;
      }));
      if (updates.some((update) => update.status === "fulfilled" && update.value.status === "complete")) {
        setRecommended(await engine.getRecommendedVoiceArtifactEvaluation(projectId));
      }
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [activeIds.join("|"), engine, projectId]);

  async function chooseSamples() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose rendered voice evaluation samples" });
      if (typeof selected === "string") setSamplesDir(selected);
    } catch (error) {
      setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function start() {
    if (!projectId || !artifactId || !samplesDir.trim() || busy) return;
    setBusy(true);
    setStatus("Queueing speaker, transcript, and signal-quality evaluation...");
    try {
      const run = await engine.createVoiceArtifactEvaluation({ project_id: projectId, artifact_id: artifactId, samples_dir: samplesDir.trim() });
      setRuns((existing) => [run, ...existing]);
      setStatus("Voice checkpoint evaluation is running in the background.");
    } catch (error) {
      setStatus(`Voice evaluation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function selectRun(runId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const selected = await engine.selectVoiceArtifactEvaluation(runId);
      setRuns((existing) => existing.map((run) => ({ ...run, selected_for_release: run.id === selected.id })));
      setStatus(`${selected.checkpoint_name} selected as the release checkpoint.`);
    } catch (error) {
      setStatus(`Voice selection error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="voice-evaluation" aria-label="Voice checkpoint evaluation">
      <header>
        <div><FlaskConical size={18} /><span><strong>Voice Acceptance</strong><small>Speaker identity · transcript · signal quality</small></span></div>
        {recommended ? <div className="voice-evaluation-recommended"><ShieldCheck size={14} /><span><small>Earliest passing</small><strong>{recommended.checkpoint_name}</strong></span></div> : null}
      </header>
      <div className="voice-evaluation-launch">
        <label>Checkpoint<select aria-label="Voice evaluation checkpoint" value={artifactId} onChange={(event) => { const id = event.target.value; setArtifactId(id); const sample = artifacts.find((item) => item.id === id)?.sample_paths[0]; if (sample) setSamplesDir(parentPath(sample)); }}><option value="">No registered voice checkpoint</option>{artifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.checkpoint_name}</option>)}</select></label>
        <label>Rendered phrases<input aria-label="Voice evaluation samples folder" value={samplesDir} onChange={(event) => setSamplesDir(event.target.value)} placeholder="Folder of WAV + matching TXT or LAB files" /></label>
        {isTauri() ? <button type="button" title="Choose voice evaluation samples" onClick={chooseSamples}><FolderOpen size={14} /></button> : null}
        <button className="primary-action" type="button" onClick={start} disabled={!artifactId || !samplesDir.trim() || busy}><Play size={14} /> Evaluate</button>
      </div>
      {runs.length ? <div className="voice-evaluation-runs">{runs.map((run) => <VoiceRun key={run.id} run={run} assetUrl={engine.assetUrl} busy={busy} recommended={recommended?.id === run.id} onSelect={() => selectRun(run.id)} />)}</div> : <p className="dataset-empty">No trained voice checkpoint evaluations yet.</p>}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function VoiceRun({ run, assetUrl, busy, recommended, onSelect }: { run: VoiceArtifactEvaluationRun; assetUrl(path: string): string; busy: boolean; recommended: boolean; onSelect(): void }) {
  const active = run.status === "queued" || run.status === "running";
  return <article className={`voice-evaluation-run ${run.summary.screening_ready ? "ready" : run.status}`}>
    <header>
      <span>{active ? <RefreshCw className="spin" size={14} /> : run.summary.screening_ready ? <Check size={15} /> : <CircleAlert size={15} />}<strong>{run.checkpoint_name}</strong>{run.checkpoint_step != null ? <small>step {run.checkpoint_step}</small> : null}</span>
      <dl><Metric label="Passed" value={`${run.summary.passed_count}/${run.summary.sample_count}`} /><Metric label="Speaker" value={percent(run.summary.average_speaker_similarity)} /><Metric label="Transcript" value={percent(run.summary.average_transcript_similarity)} /><Metric label="Signal" value={percent(run.summary.average_quality)} /></dl>
      {run.selected_for_release ? <span className="voice-release-selected"><ShieldCheck size={13} /> Release</span> : run.summary.screening_ready ? <button type="button" onClick={onSelect} disabled={busy}>{recommended ? "Select earliest" : "Select"}</button> : null}
    </header>
    {run.error ? <p className="voice-evaluation-error"><X size={13} /> {run.error}</p> : null}
    {Object.values(run.samples).length ? <details><summary>{Object.values(run.samples).length} rendered phrase results</summary><div className="voice-evaluation-samples">{Object.values(run.samples).map((sample) => <article key={sample.id} className={sample.passed ? "passed" : sample.blocked ? "blocked" : "failed"}>
      <div><Volume2 size={13} /><strong>{fileName(sample.audio_path)}</strong><span>{sample.passed ? "pass" : sample.blocked ? "blocked" : "fail"}</span></div>
      <audio controls preload="none" src={assetUrl(sample.audio_path)} />
      <p><small>Expected</small>{sample.expected_transcript}</p>
      <p><small>Heard</small>{sample.actual_transcript || "Transcription unavailable"}</p>
      <dl><Metric label="Voice" value={percent(sample.speaker_similarity)} /><Metric label="Words" value={percent(sample.transcript_similarity)} /><Metric label="Quality" value={percent(sample.quality_score)} /><Metric label="SNR" value={sample.snr_db == null ? "--" : `${sample.snr_db.toFixed(1)} dB`} /></dl>
    </article>)}</div></details> : null}
    {run.summary.warnings.map((warning) => <p className="voice-evaluation-warning" key={warning}>{warning}</p>)}
  </article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function percent(value?: number | null) { return value == null ? "--" : `${Math.round(value * 100)}%`; }
function fileName(path: string) { return path.split(/[\\/]/).pop() || path; }
function parentPath(path: string) { const parts = path.split(/[\\/]/); parts.pop(); return parts.join("/") || "/"; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
