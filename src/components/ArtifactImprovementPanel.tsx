import {
  ArrowRight,
  Check,
  CircleAlert,
  GitBranch,
  GitCompareArrows,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type {
  ArtifactComparison,
  DatasetRevisionRecord,
  ImprovementRequest,
  ModelArtifactRecord,
} from "../lib/types";

type ImprovementEngine = Pick<EngineClient, "listModelArtifacts"> & Partial<Pick<
  EngineClient,
  | "listArtifactComparisons"
  | "createArtifactComparison"
  | "listImprovementRequests"
  | "createImprovementRequest"
  | "decideImprovementRequest"
  | "listDatasetRevisions"
  | "materializeDatasetRevision"
>>;

export function ArtifactImprovementPanel({
  engine,
  projectId,
  mode,
  onOpenRevision,
}: {
  engine: ImprovementEngine;
  projectId: string;
  mode: "image" | "audio_visual";
  onOpenRevision?(modality: DatasetRevisionRecord["modality"]): void;
}) {
  const supported = Boolean(
    engine.listArtifactComparisons
    && engine.createArtifactComparison
    && engine.listImprovementRequests
    && engine.createImprovementRequest
    && engine.decideImprovementRequest,
  );
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [comparisons, setComparisons] = useState<ArtifactComparison[]>([]);
  const [requests, setRequests] = useState<ImprovementRequest[]>([]);
  const [revisions, setRevisions] = useState<DatasetRevisionRecord[]>([]);
  const [candidateId, setCandidateId] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [decisionNote, setDecisionNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Choose an evaluated artifact to compare.");

  const reload = useCallback(async () => {
    if (!projectId || !supported) {
      setArtifacts([]);
      setComparisons([]);
      setRequests([]);
      setRevisions([]);
      return;
    }
    try {
      const [artifactPayload, comparisonPayload, requestPayload, revisionPayload] = await Promise.all([
        engine.listModelArtifacts(),
        engine.listArtifactComparisons!({ projectId, benchmarkKind: mode }),
        engine.listImprovementRequests!({ projectId }),
        engine.listDatasetRevisions?.(projectId) ?? Promise.resolve([]),
      ]);
      const allowed = new Set(mode === "image" ? ["image"] : ["video", "audio_visual"]);
      const filtered = artifactPayload.filter(
        (artifact) => artifact.project_id === projectId && allowed.has(artifact.modality),
      );
      setArtifacts(filtered);
      setComparisons(comparisonPayload);
      setRequests(requestPayload);
      setRevisions(revisionPayload);
      setCandidateId((current) => (
        filtered.some((artifact) => artifact.id === current)
          ? current
          : filtered[0]?.id ?? ""
      ));
      setReferenceId((current) => {
        if (filtered.some((artifact) => artifact.id === current)) return current;
        const selected = filtered.find((artifact) => artifact.selected_for_release);
        return selected?.id ?? filtered[1]?.id ?? "";
      });
      setStatus(filtered.length
        ? "Compare against the base model or a prior evaluated artifact."
        : "No evaluated model artifacts are registered for this mode.");
    } catch (error) {
      setStatus(`Improvement loop error: ${errorMessage(error)}`);
    }
  }, [engine, mode, projectId, supported]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (referenceId === candidateId) {
      setReferenceId(artifacts.find((artifact) => artifact.id !== candidateId)?.id ?? "");
    }
  }, [artifacts, candidateId, referenceId]);

  const latest = comparisons[0] ?? null;
  const activeRequest = useMemo(
    () => requests.find((request) => request.comparison_id === latest?.id) ?? null,
    [latest?.id, requests],
  );
  const activeRevision = useMemo(
    () => revisions.find(
      (revision) => revision.improvement_request_id === activeRequest?.id,
    ) ?? null,
    [activeRequest?.id, revisions],
  );

  async function compare() {
    if (!projectId || !candidateId || busy || !engine.createArtifactComparison) return;
    setBusy(true);
    setStatus("Comparing persisted benchmark evidence...");
    try {
      const comparison = await engine.createArtifactComparison({
        project_id: projectId,
        benchmark_kind: mode,
        candidate_artifact_id: candidateId,
        reference_artifact_id: referenceId || undefined,
      });
      setComparisons((existing) => [
        comparison,
        ...existing.filter((item) => item.id !== comparison.id),
      ]);
      setStatus(`Comparison complete: ${comparison.improved_count} improved, ${comparison.regressed_count} regressed.`);
    } catch (error) {
      setStatus(`Comparison error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function stagePlan() {
    if (!latest || busy || !engine.createImprovementRequest) return;
    setBusy(true);
    setStatus("Building an evidence-backed revision proposal...");
    try {
      const request = await engine.createImprovementRequest(latest.id);
      setRequests((existing) => [
        request,
        ...existing.filter((item) => item.id !== request.id),
      ]);
      setStatus("Draft improvement plan staged. Nothing has been changed.");
    } catch (error) {
      setStatus(`Improvement plan error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "approved" | "rejected") {
    if (!activeRequest || activeRequest.status !== "draft" || busy || !engine.decideImprovementRequest) return;
    setBusy(true);
    setStatus(`${decision === "approved" ? "Approving" : "Rejecting"} the staged plan...`);
    try {
      const updated = await engine.decideImprovementRequest(
        activeRequest.id,
        decision,
        decisionNote,
      );
      setRequests((existing) => existing.map((item) => item.id === updated.id ? updated : item));
      setDecisionNote("");
      setStatus(updated.status === "approved"
        ? "Improvement intent approved. The frozen dataset and settings remain unchanged."
        : "Improvement plan rejected. No project data was changed.");
    } catch (error) {
      setStatus(`Improvement decision error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function materializeRevision() {
    if (
      !activeRequest
      || activeRequest.status !== "approved"
      || activeRevision
      || busy
      || !engine.materializeDatasetRevision
    ) return;
    setBusy(true);
    setStatus("Creating a new editable revision from the frozen source...");
    try {
      const revision = await engine.materializeDatasetRevision(activeRequest.id);
      setRevisions((existing) => [
        revision,
        ...existing.filter((item) => item.id !== revision.id),
      ]);
      setStatus(
        `Revision v${revision.revision_version} created. Items, captions, and settings were copied unchanged for manual editing.`,
      );
    } catch (error) {
      setStatus(`Dataset revision error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!supported) return null;

  return <section className="artifact-improvement-panel" aria-label="Artifact improvement loop">
    <header>
      <div><GitCompareArrows size={17} /><span><strong>Revision Comparison</strong><small>Fixed-suite evidence · approval before change</small></span></div>
      <button type="button" title="Refresh comparisons" onClick={reload}><RefreshCw size={14} /></button>
    </header>
    <div className="artifact-comparison-controls">
      <label>Reference<select aria-label="Reference artifact" value={referenceId} onChange={(event) => setReferenceId(event.target.value)}>
        <option value="">Base model baseline</option>
        {artifacts.filter((artifact) => artifact.id !== candidateId).map((artifact) => <option value={artifact.id} key={artifact.id}>{artifactLabel(artifact)}</option>)}
      </select></label>
      <ArrowRight size={16} aria-hidden="true" />
      <label>Candidate<select aria-label="Candidate artifact" value={candidateId} onChange={(event) => setCandidateId(event.target.value)}>
        {artifacts.map((artifact) => <option value={artifact.id} key={artifact.id}>{artifactLabel(artifact)}</option>)}
      </select></label>
      <button className="primary-action" type="button" disabled={!candidateId || busy} onClick={compare}><GitCompareArrows size={14} /> Compare</button>
    </div>
    {latest ? <div className="artifact-comparison-result">
      <div className="comparison-summary">
        <span className={`comparability ${latest.comparability}`}>{comparabilityLabel(latest.comparability)}</span>
        <strong>{latest.reference?.checkpoint_name ?? "Base model"} <ArrowRight size={13} /> {latest.candidate.checkpoint_name}</strong>
        <dl>
          <Metric label="Improved" value={latest.improved_count} tone="improved" />
          <Metric label="Regressed" value={latest.regressed_count} tone="regressed" />
          <Metric label="Unchanged" value={latest.unchanged_count} />
          <Metric label="Comfy reports" value={latest.candidate_comfy.report_count} />
        </dl>
      </div>
      <div className="comparison-metrics">
        {latest.aggregate_metrics.filter((metric) => metric.verdict !== "unavailable").slice(0, 8).map((metric) => <div className={metric.verdict} key={metric.metric}>
          <span>{metricLabel(metric.metric)}</span>
          <strong>{signedPercent(metric.delta)}</strong>
        </div>)}
      </div>
      {latest.comparability_notes.length ? <p>{latest.comparability_notes.join(" ")}</p> : null}
      {!activeRequest ? <button type="button" onClick={stagePlan} disabled={busy}><Sparkles size={14} /> Stage Improvement Plan</button> : <ImprovementPlan request={activeRequest} revision={activeRevision} decisionNote={decisionNote} setDecisionNote={setDecisionNote} busy={busy} canMaterialize={Boolean(engine.materializeDatasetRevision)} decide={decide} materialize={materializeRevision} onOpenRevision={onOpenRevision} />}
    </div> : null}
    <p className="status-line" aria-live="polite">{status}</p>
  </section>;
}

function ImprovementPlan({
  request,
  revision,
  decisionNote,
  setDecisionNote,
  busy,
  canMaterialize,
  decide,
  materialize,
  onOpenRevision,
}: {
  request: ImprovementRequest;
  revision: DatasetRevisionRecord | null;
  decisionNote: string;
  setDecisionNote(value: string): void;
  busy: boolean;
  canMaterialize: boolean;
  decide(decision: "approved" | "rejected"): Promise<void>;
  materialize(): Promise<void>;
  onOpenRevision?(modality: DatasetRevisionRecord["modality"]): void;
}) {
  return <section className={`improvement-plan ${request.status}`} aria-label="Staged improvement plan">
    <header><span>{request.status === "approved" ? <Check size={14} /> : request.status === "rejected" ? <X size={14} /> : <CircleAlert size={14} />}<strong>{request.status === "draft" ? "Draft Revision Plan" : `${capitalize(request.status)} Plan`}</strong></span><small>No automatic mutations</small></header>
    <p>{request.summary}</p>
    <div>{request.actions.map((action) => <article key={action.id} className={action.priority}>
      <span>{action.priority}</span><strong>{action.title}</strong><p>{action.recommendation}</p>
    </article>)}</div>
    {request.status === "draft" ? <footer>
      <input aria-label="Improvement decision note" value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="Optional decision note" />
      <button type="button" disabled={busy} onClick={() => decide("rejected")}><X size={13} /> Reject</button>
      <button className="primary-action" type="button" disabled={busy} onClick={() => decide("approved")}><Check size={13} /> Approve Plan</button>
    </footer> : <footer className="improvement-plan-result">
      <span>{request.decision_note || (request.status === "approved" ? "Approved for a new editable dataset revision." : "Rejected without changing project data.")}</span>
      {request.status === "approved" && revision ? <>
        <strong>Revision v{revision.revision_version}</strong>
        {onOpenRevision ? <button className="primary-action" type="button" onClick={() => onOpenRevision(revision.modality)}><GitBranch size={13} /> Open {revision.modality === "image" ? "Image" : "Video"} Draft</button> : null}
      </> : request.status === "approved" && canMaterialize ? <button className="primary-action" type="button" disabled={busy} onClick={materialize}><GitBranch size={13} /> Create Revision Draft</button> : null}
    </footer>}
  </section>;
}

function Metric({ label, value, tone = "" }: { label: string; value: number; tone?: string }) {
  return <div className={tone}><dt>{label}</dt><dd>{value}</dd></div>;
}

function artifactLabel(artifact: ModelArtifactRecord) {
  return `${artifact.checkpoint_name} · ${artifact.checkpoint_sha256.slice(0, 8)}`;
}

function comparabilityLabel(value: ArtifactComparison["comparability"]) {
  return {
    exact_baseline: "Exact baseline",
    prompt_seed_matched: "Prompt + seed matched",
    case_matched: "Case matched",
    partial: "Partial evidence",
  }[value];
}

function metricLabel(value: string) {
  return value.replaceAll("_", " ");
}

function signedPercent(value?: number | null) {
  if (value == null) return "--";
  const percentage = Math.round(value * 100);
  return `${percentage > 0 ? "+" : ""}${percentage}%`;
}

function capitalize(value: string) {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
