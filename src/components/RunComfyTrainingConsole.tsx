import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Ban, CloudCog, Download, FolderOpen, KeyRound, PackageCheck, Play, RefreshCw, Rocket, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { ComfyEvaluationReport, ComfyInstallation, ComfyRuntimeStatus, DatasetSnapshot, ModelArtifactRecord, ProviderSmokeRun, TrainingRun, TrainingTargetProfile, VideoDatasetSnapshot } from "../lib/types";
import { openCredentialVault } from "../lib/credentials";
import { useCredentialStatus } from "../lib/useCredentialStatus";
import { TrainingEstimatePanel } from "./TrainingEstimatePanel";
import { TrainingSettingsPanel } from "./TrainingSettingsPanel";

type TrainingEngine = Pick<
  EngineClient,
  | "listTrainingRuns"
  | "getTrainingRun"
  | "createTrainingRun"
  | "refreshTrainingRun"
  | "resumeTrainingRun"
  | "cancelTrainingRun"
  | "listModelArtifacts"
  | "registerTrainingArtifacts"
  | "listComfyInstallations"
  | "installModelArtifact"
  | "listProviderSmokeRuns"
  | "createRunComfyProviderSmokeRun"
  | "estimateTraining"
> & Partial<Pick<
  EngineClient,
  | "assetUrl"
  | "previewModelArtifactComfyHandoff"
  | "listComfyEvaluationReports"
  | "getComfyRuntimeStatus"
>>;

interface RunComfyTrainingConsoleProps {
  engine: TrainingEngine;
  snapshot: DatasetSnapshot | VideoDatasetSnapshot;
  targetProfile?: TrainingTargetProfile;
}

const ACTIVE_STATUSES = new Set([
  "queued",
  "uploading",
  "dataset_ready",
  "in_queue",
  "running",
  "downloading",
]);

export function RunComfyTrainingConsole({ engine, snapshot, targetProfile }: RunComfyTrainingConsoleProps) {
  const smokeSupported = typeof engine.listProviderSmokeRuns === "function" && typeof engine.createRunComfyProviderSmokeRun === "function";
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [evaluationReports, setEvaluationReports] = useState<ComfyEvaluationReport[]>([]);
  const [installations, setInstallations] = useState<ComfyInstallation[]>([]);
  const [comfyRoot, setComfyRoot] = useState("");
  const [comfyRuntime, setComfyRuntime] = useState<ComfyRuntimeStatus | null>(null);
  const [apiToken, setApiToken] = useState("");
  const [gpuType, setGpuType] = useState<"ADA_80_PLUS" | "HOPPER_141">("ADA_80_PLUS");
  const [pricingTier, setPricingTier] = useState<"pay_as_you_go" | "pro">("pay_as_you_go");
  const [configFile, setConfigFile] = useState(() => targetConfig(snapshot, targetProfile));
  const [smokeRun, setSmokeRun] = useState<ProviderSmokeRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready to submit the exported dataset.");
  const storedApiCredential = useCredentialStatus("runcomfy_api");
  const hasApiCredential = Boolean(storedApiCredential || apiToken.trim());
  const defaultConfigFile = useMemo(
    () => targetConfig(snapshot, targetProfile),
    [snapshot, targetProfile],
  );

  useEffect(() => {
    let disposed = false;
    const expectedConfig = targetConfig(snapshot, targetProfile);
    Promise.all([
      engine.listTrainingRuns(snapshot.id),
      engine.listModelArtifacts(snapshot.id),
      engine.listComfyInstallations(),
      engine.listProviderSmokeRuns ? engine.listProviderSmokeRuns({ projectId: snapshot.project_id, provider: "runcomfy", trainingTargetProfileId: targetProfile?.profile_id }) : Promise.resolve([]),
      engine.listComfyEvaluationReports ? engine.listComfyEvaluationReports({ projectId: snapshot.project_id }) : Promise.resolve([]),
    ])
      .then(([runPayload, artifactPayload, installationPayload, smokePayload, reportPayload]) => {
        if (disposed) return;
        setRuns(Array.isArray(runPayload) ? runPayload : []);
        setArtifacts(Array.isArray(artifactPayload) ? artifactPayload : []);
        const availableInstallations = Array.isArray(installationPayload) ? installationPayload : [];
        setInstallations(availableInstallations);
        setComfyRoot((current) => current || availableInstallations[0]?.root || "");
        setSmokeRun(smokePayload.find((run) => (
          run.source_export_path === snapshot.export_path
          && run.source_fingerprint === snapshot.fingerprint
          && run.config_file === expectedConfig
        )) ?? null);
        setEvaluationReports(Array.isArray(reportPayload) ? reportPayload : []);
      })
      .catch((error) => {
        if (!disposed) setStatus(`Training jobs unavailable: ${errorMessage(error)}`);
      });
    return () => {
      disposed = true;
    };
  }, [engine, snapshot.id, targetProfile?.profile_id]);

  useEffect(() => {
    setConfigFile(targetConfig(snapshot, targetProfile));
    setSmokeRun(null);
  }, [snapshot.id, targetProfile?.profile_id]);

  useEffect(() => {
    if (!engine.getComfyRuntimeStatus || !comfyRoot.trim()) {
      setComfyRuntime(null);
      return;
    }
    let disposed = false;
    const timer = window.setTimeout(() => {
      engine.getComfyRuntimeStatus?.(comfyRoot.trim())
        .then((runtime) => {
          if (!disposed) setComfyRuntime(runtime);
        })
        .catch((error) => {
          if (!disposed) {
            setComfyRuntime({
              root: comfyRoot.trim(),
              base_url: "http://127.0.0.1:8188",
              reachable: false,
              extension_installed: false,
              required_nodes: [],
              loaded_nodes: [],
              missing_nodes: [],
              restart_required: false,
              error: errorMessage(error),
              checked_at: new Date().toISOString(),
            });
          }
        });
    }, 250);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [comfyRoot, engine]);

  async function refreshComfyRuntime(root = comfyRoot.trim()) {
    if (!engine.getComfyRuntimeStatus || !root) return null;
    try {
      const runtime = await engine.getComfyRuntimeStatus(root);
      setComfyRuntime(runtime);
      return runtime;
    } catch (error) {
      const runtime: ComfyRuntimeStatus = {
        root,
        base_url: "http://127.0.0.1:8188",
        reachable: false,
        extension_installed: false,
        required_nodes: [],
        loaded_nodes: [],
        missing_nodes: [],
        restart_required: false,
        error: errorMessage(error),
        checked_at: new Date().toISOString(),
      };
      setComfyRuntime(runtime);
      return runtime;
    }
  }

  async function smokeTest() {
    if (busy || !snapshot.export_path || !targetProfile?.profile_id || !configFile.trim() || !engine.createRunComfyProviderSmokeRun) return;
    setBusy(true);
    setStatus("Validating dataset pairs, checksums, YAML, and the AI Toolkit contract...");
    try {
      const run = await engine.createRunComfyProviderSmokeRun({
        project_id: snapshot.project_id,
        source_export_path: snapshot.export_path,
        training_target_profile_id: targetProfile.profile_id,
        config_file: configFile,
      });
      setSmokeRun(run);
      setStatus(run.ready ? "Provider smoke passed. This exact dataset and configuration can be submitted." : "Provider smoke failed. Review the failed contract checks.");
    } catch (error) {
      setStatus(`Provider smoke error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const activeRunIds = useMemo(
    () => runs.filter((run) => ACTIVE_STATUSES.has(run.status)).map((run) => run.id),
    [runs],
  );

  useEffect(() => {
    if (!activeRunIds.length) return;
    let disposed = false;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(activeRunIds.map((runId) => engine.getTrainingRun(runId)));
      if (disposed) return;
      setRuns((existing) => existing.map((run) => {
        const index = activeRunIds.indexOf(run.id);
        const update = index >= 0 ? updates[index] : null;
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 2_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeRunIds.join("|"), engine]);

  async function startTraining() {
    if (busy || !configFile.trim()) return;
    setBusy(true);
    setStatus("Creating the RunComfy dataset and training job...");
    try {
      const run = await engine.createTrainingRun({
        snapshot_id: snapshot.id,
        config_file: configFile.trim(),
        gpu_type: gpuType,
        api_token: apiToken.trim() || undefined,
      });
      upsertRun(run);
      setApiToken("");
      setStatus(`Training run ${shortId(run.id)} queued.`);
    } catch (error) {
      setStatus(`Training error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function changeTrainingConfig(nextConfig: string) {
    setConfigFile(nextConfig);
    setSmokeRun(null);
    setStatus("Training settings changed. Run the provider smoke test before submission.");
  }

  async function reconnect(runId: string) {
    if (busy) return;
    setBusy(true);
    setStatus("Reconnecting to the RunComfy job...");
    try {
      const run = await engine.refreshTrainingRun(runId, apiToken.trim() || undefined);
      upsertRun(run);
      setApiToken("");
      setStatus(`Monitoring ${shortId(run.id)}.`);
    } catch (error) {
      setStatus(`Reconnect error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(runId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const run = await engine.cancelTrainingRun(runId, apiToken.trim() || undefined);
      upsertRun(run);
      setApiToken("");
      setStatus(`Training run ${shortId(run.id)} canceled.`);
    } catch (error) {
      setStatus(`Cancel error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function resume(runId: string) {
    if (busy) return;
    setBusy(true);
    setStatus("Resuming the RunComfy job from its latest checkpoint...");
    try {
      const run = await engine.resumeTrainingRun(runId, apiToken.trim() || undefined);
      upsertRun(run);
      setApiToken("");
      setStatus(`Resuming ${shortId(run.id)}.`);
    } catch (error) {
      setStatus(`Resume error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function registerArtifacts(runId: string) {
    if (busy) return;
    setBusy(true);
    setStatus("Validating checkpoints and training provenance...");
    try {
      const records = await engine.registerTrainingArtifacts(runId);
      setArtifacts((existing) => [
        ...records,
        ...existing.filter((artifact) => !records.some((record) => record.id === artifact.id)),
      ]);
      setStatus(`${records.length} checkpoint${records.length === 1 ? "" : "s"} registered and validated.`);
    } catch (error) {
      setStatus(`Artifact validation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseComfyRoot() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose ComfyUI folder" });
      if (typeof selected === "string") setComfyRoot(selected);
    } catch (error) {
      setStatus(`ComfyUI folder error: ${errorMessage(error)}`);
    }
  }

  async function installArtifact(artifactId: string) {
    if (busy || !comfyRoot.trim()) return;
    setBusy(true);
    setStatus("Installing LoRA and starter workflow into ComfyUI...");
    try {
      const installed = await engine.installModelArtifact(artifactId, comfyRoot.trim());
      setArtifacts((existing) => existing.map((artifact) => artifact.id === installed.id ? installed : artifact));
      const state = installed.comfy_installations?.find((candidate) => candidate.root === comfyRoot.trim());
      const runtime = await refreshComfyRuntime(comfyRoot.trim());
      const runtimeMessage = !runtime
        ? ""
        : runtime.reachable && !runtime.missing_nodes.length
          ? " LoraSuite nodes are loaded."
          : runtime.restart_required
            ? ` Restart ComfyUI to load ${runtime.missing_nodes.length} LoraSuite node${runtime.missing_nodes.length === 1 ? "" : "s"}.`
            : runtime.error
              ? ` Runtime status unavailable: ${runtime.error}`
              : "";
      setStatus(state
        ? `Installed ${installed.checkpoint_name}; compatibility ${state.compatibility_status}, ${state.runnable_workflow_count} runnable workflow${state.runnable_workflow_count === 1 ? "" : "s"}.${runtimeMessage}`
        : `Installed ${installed.checkpoint_name} and its LoraSuite handoff.${runtimeMessage}`);
    } catch (error) {
      setStatus(`ComfyUI install error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function upsertRun(run: TrainingRun) {
    setRuns((existing) => [run, ...existing.filter((candidate) => candidate.id !== run.id)]);
  }

  return (
    <section className="training-console" aria-label="RunComfy cloud training">
      <header>
        <div><CloudCog size={18} /><span><strong>Cloud Training</strong><small>{snapshotTargetLabel(snapshot, targetProfile)}</small></span></div>
        <span className="training-security"><ShieldCheck size={13} /> {storedApiCredential ? "System credential store" : "Session-only token"}</span>
      </header>
      <section className="provider-ease-guide" aria-label="Connect RunComfy">
        <header>
          <span>1</span>
          <div>
            <strong>Connect RunComfy</strong>
            <small>RunComfy is the managed option. It handles the training environment, upload, monitoring, and checkpoint return.</small>
          </div>
          <i className={hasApiCredential ? "connected" : "needed"}>
            {hasApiCredential ? <ShieldCheck size={13} /> : <KeyRound size={13} />}
            {hasApiCredential ? "Connected" : "API token needed"}
          </i>
        </header>
        <div>
          <button type="button" onClick={() => openCredentialVault("runcomfy_api")}>
            <KeyRound size={14} />
            {storedApiCredential ? "Manage saved token" : "Save RunComfy token"}
          </button>
          <small>You can also paste a temporary token below. LoraSuite never asks for your RunComfy password.</small>
        </div>
      </section>
      <div className="provider-step-heading">
        <span>2</span>
        <div><strong>Choose speed and review the estimate</strong><small>H100 is the sensible default. H200 is faster and typically costs more.</small></div>
      </div>
      <div className="training-launch-row">
        <label>Temporary API token<input aria-label="RunComfy API token" type="password" autoComplete="off" value={apiToken} onChange={(event) => setApiToken(event.target.value)} placeholder={storedApiCredential ? "Stored securely or enter an override" : "Paste a token for this session"} /></label>
        <label>GPU<select aria-label="RunComfy GPU" value={gpuType} onChange={(event) => setGpuType(event.target.value as typeof gpuType)}><option value="ADA_80_PLUS">H100</option><option value="HOPPER_141">H200</option></select></label>
        <label>Plan<select aria-label="RunComfy pricing plan" value={pricingTier} onChange={(event) => setPricingTier(event.target.value as typeof pricingTier)}><option value="pay_as_you_go">Pay as you go</option><option value="pro">Pro</option></select></label>
        {smokeSupported ? <button type="button" onClick={smokeTest} disabled={busy || !snapshot.export_path || !configFile.trim()}><ShieldCheck size={15} /> Smoke Test</button> : null}
        <button className="primary-action" type="button" onClick={startTraining} disabled={busy || !configFile.trim() || (smokeSupported && !smokeRun?.ready)}><Rocket size={15} /> Start Training</button>
      </div>
      <TrainingSettingsPanel
        configFile={configFile}
        defaultConfigFile={defaultConfigFile}
        disabled={busy}
        onChange={changeTrainingConfig}
        onError={(message) => setStatus(`Training settings error: ${message}`)}
      />
      <TrainingEstimatePanel
        engine={engine}
        provider="runcomfy"
        profileId={targetProfile?.profile_id ?? snapshotTrainingTarget(snapshot)}
        gpuType={gpuType}
        pricingTier={pricingTier}
        configFile={configFile}
        datasetItemCount={snapshot.balance.approved_count}
      />
      {smokeRun ? <div className={`provider-smoke-result ${smokeRun.ready ? "ready" : "blocked"}`}>
        {smokeRun.ready ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
        <span><strong>{smokeRun.ready ? "Provider contract passed" : "Provider contract failed"}</strong><small>{smokeRun.checks.filter((check) => check.passed).length}/{smokeRun.checks.length} checks · {new Date(smokeRun.completed_at).toLocaleString()}</small></span>
        <div>{smokeRun.checks.map((check) => <i key={check.id} className={check.passed ? "passed" : "failed"} title={`${check.id}: ${check.detail}`} />)}</div>
      </div> : null}
      <details className="training-config">
        <summary>AI Toolkit YAML</summary>
        <textarea aria-label="AI Toolkit YAML" rows={10} value={configFile} onChange={(event) => changeTrainingConfig(event.target.value)} placeholder={'Paste the RunComfy AI Toolkit YAML. Keep {dataset_name} in the dataset folder path.'} />
      </details>
      {runs.length ? (
        <div className="training-run-list">
          {runs.map((run) => (
            <article key={run.id} className={`training-run ${run.status}`}>
              <div className="training-run-state"><i /><span><strong>{trainingStatus(run)}</strong><small>{run.progress_message}</small></span></div>
              <progress max={100} value={run.progress_percent} />
              <dl><div><dt>Dataset</dt><dd>{run.dataset_name ?? "pending"}</dd></div><div><dt>Job</dt><dd>{run.provider_job_id ? shortId(run.provider_job_id) : "pending"}</dd></div><div><dt>Artifacts</dt><dd>{run.artifacts.length}</dd></div></dl>
              <div className="training-run-actions">
                {run.artifact_dir ? <span title={run.artifact_dir}><Download size={13} /> Downloaded</span> : null}
                {run.status === "completed" ? <button type="button" onClick={() => registerArtifacts(run.id)} disabled={busy} title="Validate and register artifacts"><PackageCheck size={14} /></button> : null}
                {run.status === "stopped" ? <button type="button" onClick={() => resume(run.id)} disabled={busy} title="Resume training from checkpoint"><Play size={14} /></button> : null}
                {run.status === "failed" ? <button type="button" onClick={() => reconnect(run.id)} disabled={busy} title="Retry persisted RunComfy run"><RefreshCw size={14} /></button> : null}
                {ACTIVE_STATUSES.has(run.status) ? <button type="button" onClick={() => reconnect(run.id)} disabled={busy} title="Reconnect monitoring"><RefreshCw size={14} /></button> : null}
                {ACTIVE_STATUSES.has(run.status) && run.provider_job_id ? <button type="button" onClick={() => cancel(run.id)} disabled={busy} title="Cancel training"><Ban size={14} /></button> : null}
              </div>
              <LiveTrainingArtifacts run={run} assetUrl={engine.assetUrl} />
              {run.error ? <p>{run.error}</p> : null}
            </article>
          ))}
        </div>
      ) : <p className="training-empty">No cloud training runs for this dataset version.</p>}
      {artifacts.length ? (
        <section className="model-registry" aria-label="Model artifact registry">
          <header>
            <strong>Model Registry</strong>
            <label>
              ComfyUI
              <input aria-label="ComfyUI root" list="comfy-installations" value={comfyRoot} onChange={(event) => setComfyRoot(event.target.value)} placeholder="/path/to/ComfyUI" />
              <datalist id="comfy-installations">{installations.map((installation) => <option key={installation.root} value={installation.root}>{installation.label}</option>)}</datalist>
            </label>
            <div className="comfy-runtime-controls">
              <span className={`comfy-runtime-state ${comfyRuntimeClass(comfyRuntime)}`} title={comfyRuntimeDetail(comfyRuntime)}>
                {comfyRuntimeIcon(comfyRuntime)}
                {comfyRuntimeLabel(comfyRuntime)}
              </span>
              {engine.getComfyRuntimeStatus ? <button type="button" onClick={() => refreshComfyRuntime()} disabled={busy || !comfyRoot.trim()} title="Refresh ComfyUI runtime status"><RefreshCw size={14} /></button> : null}
              {isTauri() ? <button type="button" onClick={chooseComfyRoot} disabled={busy} title="Choose ComfyUI folder"><FolderOpen size={14} /></button> : null}
            </div>
          </header>
          <div className="model-artifact-list">
            {artifacts.map((artifact) => (
              <article key={artifact.id} className={`model-artifact ${artifact.evaluation.status}`}>
                {(() => {
                  const installation = artifact.comfy_installations?.find((candidate) => candidate.root === comfyRoot.trim())
                    ?? artifact.comfy_installations?.[0];
                  const reportCount = evaluationReports.filter((report) => report.artifact_id === artifact.id).length;
                  return <>
                <span className="artifact-state"><i /><strong>{artifact.checkpoint_name}</strong><small>{artifact.evaluation.status}{artifact.parent_artifact_id ? ` · revision of ${shortId(artifact.parent_artifact_id)}` : ""}</small></span>
                <dl><div><dt>Parameters</dt><dd>{formatParameters(artifact.evaluation.parameter_count)}</dd></div><div><dt>Samples</dt><dd>{artifact.evaluation.sample_count}</dd></div><div><dt>SHA-256</dt><dd title={artifact.checkpoint_sha256}>{artifact.checkpoint_sha256.slice(0, 12)}</dd></div></dl>
                <button className="primary-action" type="button" onClick={() => installArtifact(artifact.id)} disabled={busy || !comfyRoot.trim() || artifact.evaluation.status === "failed"}><Download size={14} /> {artifact.installed_paths.length ? "Reinstall" : "Install"}</button>
                {artifact.evaluation.warnings.length ? <p>{artifact.evaluation.warnings.join(" ")}</p> : null}
                {artifact.installed_paths.length ? <small className="installed-path" title={artifact.installed_paths[0]}>Installed: {artifact.installed_paths[0]}</small> : null}
                {installation ? <small className={`comfy-handoff-state ${installation.compatibility_status}`}>
                  <ShieldCheck size={12} /> {installation.compatibility_status} · {installation.runnable_workflow_count} runnable · {reportCount} report{reportCount === 1 ? "" : "s"}
                </small> : null}
                  </>;
                })()}
              </article>
            ))}
          </div>
        </section>
      ) : null}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function LiveTrainingArtifacts({
  run,
  assetUrl,
}: {
  run: TrainingRun;
  assetUrl?: (path: string) => string;
}) {
  const samples = run.artifacts
    .filter((artifact) => artifact.kind === "sample" && artifact.local_path)
    .sort((left, right) => (right.step ?? 0) - (left.step ?? 0))
    .slice(0, 4);
  const checkpoints = run.artifacts.filter(
    (artifact) => artifact.kind === "checkpoint" && artifact.local_path,
  );
  const showWaitingState = run.status === "running" && samples.length === 0 && checkpoints.length === 0;
  if (!samples.length && !checkpoints.length && !showWaitingState) return null;
  const latestStep = Math.max(
    run.progress_current,
    ...samples.map((artifact) => artifact.step ?? 0),
    ...checkpoints.map((artifact) => artifact.step ?? 0),
  );

  return (
    <section className="training-live-artifacts" aria-label={`Live training previews for ${shortId(run.id)}`}>
      <header>
        <span>
          <strong>Live training previews</strong>
          <small>LoraSuite automatically exports new samples and checkpoints while this run trains.</small>
        </span>
        <span>
          {latestStep > 0 ? `Latest step ${latestStep}` : "Waiting for first save"}
          {checkpoints.length ? ` · ${checkpoints.length} checkpoint${checkpoints.length === 1 ? "" : "s"}` : ""}
        </span>
      </header>
      {samples.length && assetUrl ? (
        <div className="training-live-samples">
          {samples.map((artifact) => {
            const source = assetUrl(artifact.local_path as string);
            return (
              <a
                key={artifact.remote_url}
                href={source}
                target="_blank"
                rel="noreferrer"
                title={artifact.prompt || `Training sample${artifact.step ? ` at step ${artifact.step}` : ""}`}
              >
                <img src={source} alt={`Training sample${artifact.step ? ` at step ${artifact.step}` : ""}`} />
                <span>{artifact.step ? `Step ${artifact.step}` : artifact.name}</span>
              </a>
            );
          })}
        </div>
      ) : (
        <p>{samples.length ? "Preview files are exported; reopen this run in the desktop app to view them." : "The first saved sample will appear here automatically."}</p>
      )}
    </section>
  );
}

function trainingStatus(run: TrainingRun): string {
  if (run.status === "uploading" && run.progress_total) {
    return `Uploading ${run.progress_current} / ${run.progress_total}`;
  }
  if (run.status === "running" && run.progress_total) {
    return `Training ${run.progress_current} / ${run.progress_total}`;
  }
  return run.status.replace("_", " ");
}

function shortId(value: string): string {
  return value.length > 16 ? value.slice(-12) : value;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatParameters(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function comfyRuntimeClass(runtime: ComfyRuntimeStatus | null): string {
  if (!runtime) return "unknown";
  if (!runtime.reachable) return "offline";
  if (runtime.required_nodes.length > 0 && !runtime.missing_nodes.length) return "ready";
  if (!runtime.extension_installed) return "missing";
  if (runtime.restart_required) return "restart";
  return "missing";
}

function comfyRuntimeLabel(runtime: ComfyRuntimeStatus | null): string {
  if (!runtime) return "Runtime unchecked";
  if (!runtime.reachable) return "Runtime offline";
  if (runtime.required_nodes.length > 0 && !runtime.missing_nodes.length) return "Nodes loaded";
  if (!runtime.extension_installed) return "Nodes not installed";
  if (runtime.restart_required) return "Restart required";
  return "Nodes incomplete";
}

function comfyRuntimeDetail(runtime: ComfyRuntimeStatus | null): string {
  if (!runtime) return "Select a ComfyUI root to inspect its live node registry.";
  if (runtime.error) return runtime.error;
  if (runtime.missing_nodes.length) return `Missing: ${runtime.missing_nodes.join(", ")}`;
  return `${runtime.loaded_nodes.length} required LoraSuite nodes are active at ${runtime.base_url}.`;
}

function comfyRuntimeIcon(runtime: ComfyRuntimeStatus | null) {
  return runtime?.reachable && runtime.extension_installed && !runtime.missing_nodes.length
    ? <ShieldCheck size={13} />
    : <ShieldAlert size={13} />;
}

function snapshotTrainingTarget(
  snapshot: DatasetSnapshot | VideoDatasetSnapshot,
): string | undefined {
  return "target_profile_id" in snapshot
    ? snapshot.target_profile_id
    : snapshot.training_target?.profile_id;
}

function targetConfig(snapshot: DatasetSnapshot | VideoDatasetSnapshot, profile?: TrainingTargetProfile): string {
  if (!profile?.config_template) return "";
  const token = yamlText(("intent" in snapshot ? snapshot.intent.trigger_token : snapshot.trigger_token) || "character_token");
  const subject = ("intent" in snapshot ? snapshot.intent.subject_name : snapshot.project_name).trim() || "character";
  const jobName = `${slug(subject)}-${profile.model_family}-v${snapshot.version}`;
  const samplePrompt = yamlText(profile.modality === "video"
    ? `${token}, ${subject}, natural character motion, consistent identity, cinematic video`
    : `${token}, ${subject}, character portrait, natural expression, detailed photograph`);
  return profile.config_template
    .replaceAll("{job_name}", jobName)
    .replaceAll("{trigger_token}", token)
    .replaceAll("{sample_prompt}", samplePrompt);
}

function snapshotTargetLabel(snapshot: DatasetSnapshot | VideoDatasetSnapshot, profile?: TrainingTargetProfile): string {
  if ("training_target" in snapshot && snapshot.training_target?.label) return snapshot.training_target.label;
  if ("target_label" in snapshot && snapshot.target_label) return snapshot.target_label;
  return profile?.label ?? "RunComfy Trainer API";
}

function yamlText(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"').replaceAll("\n", " ");
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "character";
}
