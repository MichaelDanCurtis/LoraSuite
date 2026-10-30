import { Check, CircleAlert, RefreshCw, Trophy } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { ArtifactReleaseCandidate } from "../lib/types";

type ReleaseEngine = Pick<EngineClient, "listModelReleaseCandidates" | "selectModelRelease">;

export function ReleaseCandidatePanel({
  engine,
  projectId,
  mode,
  onSelected,
}: {
  engine: ReleaseEngine;
  projectId: string;
  mode: "image" | "audio_visual";
  onSelected?(): void;
}) {
  const [candidates, setCandidates] = useState<ArtifactReleaseCandidate[]>([]);
  const [busyId, setBusyId] = useState("");
  const [status, setStatus] = useState("Loading release candidates...");

  const reload = useCallback(async () => {
    if (!projectId) {
      setCandidates([]);
      setStatus("Choose a character project to compare checkpoints.");
      return;
    }
    try {
      const payload = await engine.listModelReleaseCandidates(projectId);
      const filtered = payload.filter((candidate) => mode === "image"
        ? candidate.artifact.modality === "image"
        : candidate.artifact.modality === "video" || candidate.artifact.modality === "audio_visual");
      setCandidates(filtered);
      setStatus(filtered.length ? "Ranked from persisted acceptance evidence." : "No registered checkpoints for this evaluation mode yet.");
    } catch (error) {
      setStatus(`Release candidate error: ${errorMessage(error)}`);
    }
  }, [engine, mode, projectId]);

  useEffect(() => {
    reload();
    const timer = window.setInterval(reload, 5_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const selected = useMemo(() => candidates.find((candidate) => candidate.selected), [candidates]);

  async function select(candidate: ArtifactReleaseCandidate) {
    if (!candidate.eligible || busyId) return;
    setBusyId(candidate.artifact.id);
    setStatus(`Selecting ${candidate.artifact.checkpoint_name}...`);
    try {
      await engine.selectModelRelease(candidate.artifact.id);
      await reload();
      setStatus(`${candidate.artifact.checkpoint_name} is the selected release checkpoint.`);
      onSelected?.();
    } catch (error) {
      setStatus(`Release selection error: ${errorMessage(error)}`);
    } finally {
      setBusyId("");
    }
  }

  return <section className="release-candidate-panel" aria-label="Release candidate ranking">
    <header>
      <div><Trophy size={16} /><span><strong>Release Candidate</strong><small>{selected ? selected.artifact.checkpoint_name : "No checkpoint selected"}</small></span></div>
      <button type="button" title="Refresh release candidates" onClick={reload}><RefreshCw size={14} /></button>
    </header>
    {candidates.length ? <div className="release-candidate-list">{candidates.map((candidate) => <article className={`${candidate.selected ? "selected" : ""} ${candidate.eligible ? "eligible" : "blocked"}`} key={candidate.artifact.id}>
      <span className="release-rank">#{candidate.rank}</span>
      <div className="release-name"><strong>{candidate.artifact.checkpoint_name}</strong><small>{candidate.artifact.model_family} · {candidate.artifact.modality}</small></div>
      <div className="release-score"><strong>{candidate.score.toFixed(1)}</strong><small>score</small></div>
      <dl><Metric label="Identity" value={candidate.metrics.identity_similarity} /><Metric label="Stability" value={candidate.metrics.temporal_stability} /><Metric label="Voice" value={candidate.metrics.speaker_similarity} /><Metric label="Sync" value={candidate.metrics.av_sync_proxy} /></dl>
      {candidate.selected
        ? <span className="release-selected"><Check size={13} /> Selected</span>
        : <button type="button" disabled={!candidate.eligible || Boolean(busyId)} title={candidate.reasons.join(" ")} onClick={() => select(candidate)}>{candidate.eligible ? "Select Release" : <><CircleAlert size={13} /> Not Ready</>}</button>}
    </article>)}</div> : null}
    <p className="status-line" aria-live="polite">{status}</p>
  </section>;
}

function Metric({ label, value }: { label: string; value?: number }) {
  return <div><dt>{label}</dt><dd>{value == null ? "--" : `${Math.round(value * 100)}%`}</dd></div>;
}

function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
