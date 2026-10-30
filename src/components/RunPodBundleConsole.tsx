import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Ban, Box, Check, Clock3, Database, Download, FolderOpen, KeyRound, PackageOpen, RefreshCw, Rocket, ShieldAlert, ShieldCheck, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { ProviderSmokeRun, RunPodBundle, RunPodBundleUploadJob, RunPodInfrastructureProfile, RunPodModelBootstrapRun, RunPodModality, RunPodPreflightReport, RunPodTrainingRun } from "../lib/types";
import { openCredentialVault } from "../lib/credentials";
import { useCredentialStatus } from "../lib/useCredentialStatus";
import { RunPodInfrastructureSetup } from "./RunPodInfrastructureSetup";
import { TrainingEstimatePanel } from "./TrainingEstimatePanel";

type RunPodEngine = Pick<
  EngineClient,
  | "createRunPodBundle"
  | "listRunPodInfrastructureProfiles"
  | "provisionRunPodInfrastructure"
  | "listRunPodModelBootstrapRuns"
  | "getRunPodModelBootstrapRun"
  | "createRunPodModelBootstrapRun"
  | "refreshRunPodModelBootstrapRun"
  | "cancelRunPodModelBootstrapRun"
  | "listRunPodBundles"
  | "listRunPodBundleUploadJobs"
  | "getRunPodBundleUploadJob"
  | "createRunPodBundleUploadJob"
  | "resumeRunPodBundleUploadJob"
  | "listRunPodPreflightReports"
  | "createRunPodPreflightReport"
  | "listRunPodTrainingRuns"
  | "getRunPodTrainingRun"
  | "createRunPodTrainingRun"
  | "refreshRunPodTrainingRun"
  | "cancelRunPodTrainingRun"
  | "downloadRunPodTrainingArtifacts"
  | "registerRunPodTrainingArtifacts"
  | "listProviderSmokeRuns"
  | "createRunPodProviderSmokeRun"
  | "estimateTraining"
>;

interface RunPodBundleConsoleProps {
  engine: RunPodEngine;
  sourceExportPath: string;
  modality: RunPodModality;
  triggerToken: string;
  fingerprint: string;
  trainingTargetProfileId?: string;
  onArtifactsRegistered?: () => void;
  onRunChanged?: (run: RunPodTrainingRun) => void;
}

export function RunPodBundleConsole({
  engine,
  sourceExportPath,
  modality,
  triggerToken,
  fingerprint,
  trainingTargetProfileId,
  onArtifactsRegistered,
  onRunChanged,
}: RunPodBundleConsoleProps) {
  const smokeSupported = typeof engine.listProviderSmokeRuns === "function" && typeof engine.createRunPodProviderSmokeRun === "function";
  const targetLabel = trainingTargetProfileId === "runpod_id_lora_ltx23_inference"
    ? "ID-LoRA LTX-2.3 · zero-shot HQ"
    : trainingTargetProfileId === "runpod_id_lora_ltx23"
      ? "ID-LoRA LTX-2.3 · research contract"
      : trainingTargetProfileId === "runpod_fish_speech_s2_voice_lora"
        ? "Fish Speech S2 · voice LoRA"
        : "Network volume · Pod or Serverless worker";
  const [outputPath, setOutputPath] = useState("");
  const [remoteRoot, setRemoteRoot] = useState("/workspace/lorasuite");
  const [endpointId, setEndpointId] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [artifactOutput, setArtifactOutput] = useState("");
  const [volumeId, setVolumeId] = useState("");
  const [s3Endpoint, setS3Endpoint] = useState("");
  const [datacenter, setDatacenter] = useState("");
  const [s3AccessKey, setS3AccessKey] = useState("");
  const [s3SecretKey, setS3SecretKey] = useState("");
  const [bundle, setBundle] = useState<RunPodBundle | null>(null);
  const [smokeRun, setSmokeRun] = useState<ProviderSmokeRun | null>(null);
  const [uploadJob, setUploadJob] = useState<RunPodBundleUploadJob | null>(null);
  const [volumeConfigOpen, setVolumeConfigOpen] = useState(true);
  const [preflight, setPreflight] = useState<RunPodPreflightReport | null>(null);
  const [bootstrapRun, setBootstrapRun] = useState<RunPodModelBootstrapRun | null>(null);
  const [runs, setRuns] = useState<RunPodTrainingRun[]>([]);
  const [estimateGpuType, setEstimateGpuType] = useState("NVIDIA H100 80GB HBM3");
  const [pricingTier, setPricingTier] = useState<"flex" | "active">("flex");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Create a network-volume-ready RunPod handoff.");
  const storedApiCredential = useCredentialStatus("runpod_api");
  const hasApiCredential = Boolean(apiToken.trim() || storedApiCredential);
  const activeRunIds = useMemo(
    () => runs.filter((run) => ["queued", "in_queue", "running"].includes(run.status)).map((run) => run.id),
    [runs],
  );
  const preflightReady = !!(
    bundle
    && preflight?.ready
    && preflight.bundle_path === bundle.output_path
    && preflight.bundle_fingerprint === fingerprint
    && preflight.endpoint_id === endpointId.trim()
  );
  const uploadReady = !!(
    bundle
    && uploadJob?.status === "complete"
    && uploadJob.bundle_path === bundle.output_path
    && uploadJob.bundle_fingerprint === fingerprint
  );
  const requiresModelBootstrap = trainingTargetProfileId === "runpod_fish_speech_s2_voice_lora" || trainingTargetProfileId === "runpod_id_lora_ltx23_inference";

  function applyInfrastructure(profile: RunPodInfrastructureProfile) {
    setEndpointId(profile.endpoint_id ?? "");
    setVolumeId(profile.network_volume_id ?? "");
    setDatacenter(profile.data_center_id);
    setS3Endpoint(`https://s3api-${profile.data_center_id.toLowerCase()}.runpod.io/`);
    setEstimateGpuType(profile.gpu_type_ids[0] ?? "NVIDIA H100 80GB HBM3");
    setPricingTier(profile.workers_min > 0 ? "active" : "flex");
    setStatus("RunPod infrastructure loaded. Create or upload the bundle next.");
  }

  useEffect(() => {
    let disposed = false;
    engine.listRunPodBundles(sourceExportPath, trainingTargetProfileId)
      .then(async (bundles) => {
        const restored = bundles.find((candidate) => candidate.available && candidate.fingerprint === fingerprint);
        if (!restored || disposed) return;
        const [existingRuns, reports, uploads, smokeRuns] = await Promise.all([
          engine.listRunPodTrainingRuns(restored.output_path),
          engine.listRunPodPreflightReports(restored.output_path),
          engine.listRunPodBundleUploadJobs(restored.output_path),
          engine.listProviderSmokeRuns ? engine.listProviderSmokeRuns({ bundleId: restored.id, provider: "runpod" }) : Promise.resolve([]),
        ]);
        if (disposed) return;
        const restoredEndpoint = existingRuns[0]?.endpoint_id ?? reports[0]?.endpoint_id ?? "";
        setBundle(restored);
        setOutputPath(restored.output_path);
        setArtifactOutput(`${restored.output_path}-artifacts`);
        setRuns(existingRuns);
        setEndpointId(restoredEndpoint);
        const restoredPreflight = reports.find((report) => report.endpoint_id === restoredEndpoint) ?? reports[0] ?? null;
        setPreflight(restoredPreflight);
        if (restoredPreflight?.gpu.name) setEstimateGpuType(restoredPreflight.gpu.name);
        setUploadJob(uploads[0] ?? null);
        setSmokeRun(smokeRuns[0] ?? null);
        setVolumeConfigOpen(uploads[0]?.status !== "complete");
        if (uploads[0]) {
          setVolumeId(uploads[0].volume_id);
          setS3Endpoint(uploads[0].endpoint_url);
          setDatacenter(uploads[0].datacenter);
        }
        setStatus(restored.ready ? "Restored provider-ready RunPod bundle." : "Restored RunPod bundle with unresolved worker requirements.");
      })
      .catch((error) => {
        if (!disposed) setStatus(`RunPod bundle registry error: ${errorMessage(error)}`);
      });
    return () => { disposed = true; };
  }, [engine, sourceExportPath, trainingTargetProfileId, fingerprint]);

  useEffect(() => {
    if (!requiresModelBootstrap || !endpointId.trim()) return;
    let disposed = false;
    engine.listRunPodModelBootstrapRuns(endpointId.trim(), trainingTargetProfileId)
      .then((items) => { if (!disposed) setBootstrapRun(items[0] ?? null); })
      .catch((error) => { if (!disposed) setStatus(`Model bootstrap registry error: ${errorMessage(error)}`); });
    return () => { disposed = true; };
  }, [engine, endpointId, requiresModelBootstrap, trainingTargetProfileId]);

  useEffect(() => {
    if (!activeRunIds.length || !hasApiCredential) return;
    let disposed = false;
    const timer = window.setInterval(async () => {
      const updates = await Promise.allSettled(
        activeRunIds.map((runId) => engine.refreshRunPodTrainingRun(runId, apiToken.trim())),
      );
      if (disposed) return;
      setRuns((existing) => existing.map((run) => {
        const index = activeRunIds.indexOf(run.id);
        const update = index >= 0 ? updates[index] : null;
        return update?.status === "fulfilled" ? update.value : run;
      }));
    }, 5_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeRunIds.join("|"), apiToken, engine, hasApiCredential]);

  useEffect(() => {
    if (!bootstrapRun || !["queued", "in_queue", "running"].includes(bootstrapRun.status) || !hasApiCredential) return;
    let disposed = false;
    const timer = window.setInterval(async () => {
      try {
        const update = await engine.refreshRunPodModelBootstrapRun(bootstrapRun.id, apiToken.trim());
        if (disposed) return;
        setBootstrapRun(update);
        if (update.status === "completed") {
          setPreflight(null);
          setStatus("Required models are ready. Verify the endpoint against the current bundle.");
        } else if (["failed", "timed_out"].includes(update.status)) {
          setStatus(`Model bootstrap failed: ${update.error ?? update.progress_message}`);
        } else {
          setStatus(update.progress_message);
        }
      } catch (error) {
        if (!disposed) setStatus(`Model bootstrap monitor error: ${errorMessage(error)}`);
      }
    }, 5_000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [bootstrapRun?.id, bootstrapRun?.status, apiToken, engine, hasApiCredential]);

  useEffect(() => {
    if (!uploadJob || !["queued", "running"].includes(uploadJob.status)) return;
    let disposed = false;
    const timer = window.setInterval(async () => {
      try {
        const update = await engine.getRunPodBundleUploadJob(uploadJob.id);
        if (disposed) return;
        setUploadJob(update);
        if (update.status === "complete") setStatus("Bundle upload complete. Verify the endpoint next.");
        if (update.status === "failed") setStatus(`RunPod bundle upload failed: ${update.error ?? "Unknown upload error"}`);
      } catch (error) {
        if (!disposed) setStatus(`RunPod upload monitor error: ${errorMessage(error)}`);
      }
    }, 1_500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [uploadJob?.id, uploadJob?.status, engine]);

  async function chooseOutput() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose RunPod bundle destination" });
      if (typeof selected === "string") setOutputPath(selected);
    } catch (error) {
      setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function createBundle() {
    if (!outputPath.trim() || !remoteRoot.trim() || busy) return;
    setBusy(true);
    setStatus("Packaging dataset, trainer config, upload command, and Serverless input...");
    try {
      const result = await engine.createRunPodBundle({
        source_export_path: sourceExportPath,
        output_path: outputPath.trim(),
        modality,
        trigger_token: triggerToken,
        fingerprint,
        training_target_profile_id: trainingTargetProfileId,
        remote_root: remoteRoot.trim(),
        endpoint_id: endpointId.trim() || undefined,
      });
      setBundle(result);
      setSmokeRun(null);
      setArtifactOutput((current) => current || `${result.output_path}-artifacts`);
      const [existingRuns, reports, uploads] = await Promise.all([
        engine.listRunPodTrainingRuns(result.output_path),
        engine.listRunPodPreflightReports(result.output_path, endpointId.trim() || undefined),
        engine.listRunPodBundleUploadJobs(result.output_path),
      ]);
      setRuns(existingRuns);
      setPreflight(reports[0] ?? null);
      setUploadJob(uploads[0] ?? null);
      setVolumeConfigOpen(uploads[0]?.status !== "complete");
      setStatus(result.ready ? "Bundle ready. Upload it to the network volume, then verify the endpoint." : "RunPod data bundle ready; custom worker implementation is still required.");
    } catch (error) {
      setStatus(`RunPod bundle error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function smokeTestBundle(target = bundle) {
    if (!target || busy || !engine.createRunPodProviderSmokeRun) return;
    setBusy(true);
    setStatus("Executing the packaged worker contract against a local network-volume layout...");
    try {
      const run = await engine.createRunPodProviderSmokeRun(target.id);
      setSmokeRun(run);
      setStatus(run.ready ? "Provider smoke passed. The bundle is safe to upload." : `Provider smoke failed: ${run.error ?? "review the failed checks"}`);
    } catch (error) {
      setStatus(`Provider smoke error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function installRequiredModels() {
    if (!requiresModelBootstrap || !trainingTargetProfileId || !endpointId.trim() || !hasApiCredential || busy) return;
    setBusy(true);
    setStatus("Starting persistent model installation on the RunPod network volume...");
    try {
      const run = await engine.createRunPodModelBootstrapRun({
        endpoint_id: endpointId.trim(),
        training_target_profile_id: trainingTargetProfileId,
        api_token: apiToken.trim(),
      });
      setBootstrapRun(run);
      setStatus(run.progress_message);
    } catch (error) {
      setStatus(`Model bootstrap error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function cancelModelBootstrap() {
    if (!bootstrapRun || !hasApiCredential || busy) return;
    setBusy(true);
    try {
      const run = await engine.cancelRunPodModelBootstrapRun(bootstrapRun.id, apiToken.trim());
      setBootstrapRun(run);
      setStatus(run.progress_message);
    } catch (error) {
      setStatus(`Model bootstrap cancel error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseArtifactOutput() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose RunPod artifact destination" });
      if (typeof selected === "string") setArtifactOutput(selected);
    } catch (error) {
      setStatus(`Artifact folder error: ${errorMessage(error)}`);
    }
  }

  function upsertRun(run: RunPodTrainingRun) {
    setRuns((existing) => [run, ...existing.filter((candidate) => candidate.id !== run.id)]);
    onRunChanged?.(run);
  }

  async function uploadBundle() {
    if (!bundle?.ready || busy || !volumeId.trim() || !s3Endpoint.trim() || !datacenter.trim()) return;
    setBusy(true);
    setStatus(uploadJob?.status === "failed" ? "Resuming network-volume upload..." : "Queueing network-volume upload...");
    try {
      const job = uploadJob?.status === "failed"
        ? await engine.resumeRunPodBundleUploadJob(uploadJob.id, s3AccessKey.trim() || undefined, s3SecretKey.trim() || undefined)
        : await engine.createRunPodBundleUploadJob({
          bundle_path: bundle.output_path,
          volume_id: volumeId.trim(),
          s3_endpoint: s3Endpoint.trim(),
          datacenter: datacenter.trim(),
          access_key: s3AccessKey.trim() || undefined,
          secret_key: s3SecretKey.trim() || undefined,
        });
      setUploadJob(job);
      setS3AccessKey("");
      setS3SecretKey("");
      setStatus(job.status === "complete" ? "Bundle is already present on the network volume." : "Bundle upload is running in the background.");
    } catch (error) {
      setStatus(`RunPod bundle upload error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function verifyEndpoint() {
    if (!bundle?.ready || !uploadReady || !endpointId.trim() || busy) return;
    setBusy(true);
    setStatus("Checking worker contract, network volume, bundle, models, commands, environment, and GPU...");
    try {
      const report = await engine.createRunPodPreflightReport({
        bundle_path: bundle.output_path,
        endpoint_id: endpointId.trim(),
        api_token: apiToken.trim() || undefined,
      });
      setPreflight(report);
      if (report.gpu.name) setEstimateGpuType(report.gpu.name);
      setStatus(report.ready ? "Endpoint verified. Training can start." : "Endpoint verification found requirements that must be fixed.");
    } catch (error) {
      setPreflight(null);
      setStatus(`RunPod endpoint verification error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function startRun() {
    if (!bundle?.ready || !endpointId.trim() || !preflightReady || busy) return;
    setBusy(true);
    setStatus(trainingTargetProfileId === "runpod_id_lora_ltx23_inference" ? "Submitting zero-shot inference to RunPod Serverless..." : "Submitting the training contract to RunPod Serverless...");
    try {
      const run = await engine.createRunPodTrainingRun({
        bundle_path: bundle.output_path,
        endpoint_id: endpointId.trim(),
        api_token: apiToken.trim() || undefined,
      });
      upsertRun(run);
      setStatus(`RunPod job ${shortId(run.provider_job_id ?? run.id)} queued.`);
    } catch (error) {
      setStatus(`RunPod launch error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function refreshRun(runId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const run = await engine.refreshRunPodTrainingRun(runId, apiToken.trim() || undefined);
      upsertRun(run);
      setStatus(`RunPod job ${shortId(run.provider_job_id ?? run.id)} refreshed.`);
    } catch (error) {
      setStatus(`RunPod refresh error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun(runId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const run = await engine.cancelRunPodTrainingRun(runId, apiToken.trim() || undefined);
      upsertRun(run);
      setStatus(`RunPod job ${shortId(run.provider_job_id ?? run.id)} canceled.`);
    } catch (error) {
      setStatus(`RunPod cancel error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function downloadArtifacts(runId: string) {
    if (busy || !artifactOutput.trim() || !volumeId.trim() || !s3Endpoint.trim() || !datacenter.trim()) return;
    setBusy(true);
    setStatus("Downloading and verifying RunPod artifacts...");
    try {
      const run = await engine.downloadRunPodTrainingArtifacts(runId, {
        output_dir: artifactOutput.trim(),
        volume_id: volumeId.trim(),
        s3_endpoint: s3Endpoint.trim(),
        datacenter: datacenter.trim(),
        access_key: s3AccessKey.trim() || undefined,
        secret_key: s3SecretKey.trim() || undefined,
      });
      upsertRun(run);
      setS3AccessKey("");
      setS3SecretKey("");
      setStatus(`Downloaded ${run.artifacts.length} verified RunPod artifact${run.artifacts.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setStatus(`RunPod download error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function registerArtifacts(runId: string) {
    if (busy) return;
    setBusy(true);
    setStatus("Validating provenance and registering RunPod outputs...");
    try {
      const records = await engine.registerRunPodTrainingArtifacts(runId);
      onArtifactsRegistered?.();
      setStatus(`Registered ${records.length} model artifact${records.length === 1 ? "" : "s"} for evaluation.`);
    } catch (error) {
      setStatus(`RunPod registration error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="runpod-console" aria-label="RunPod training bundle">
      <div className="runpod-title"><Box size={18} /><span><strong>RunPod</strong><small>{targetLabel}</small></span></div>
      <section className="provider-ease-guide runpod-provider-guide" aria-label="Connect RunPod">
        <header>
          <span>1</span>
          <div>
            <strong>Connect your RunPod account</strong>
            <small>RunPod is the advanced option for an existing account, custom worker, endpoint, and network volume.</small>
          </div>
          <i className={hasApiCredential ? "connected" : "needed"}>
            {hasApiCredential ? <ShieldCheck size={13} /> : <KeyRound size={13} />}
            {hasApiCredential ? "Connected" : "API key needed"}
          </i>
        </header>
        <div>
          <button type="button" onClick={() => openCredentialVault("runpod_api")}>
            <KeyRound size={14} />
            {storedApiCredential ? "Manage saved key" : "Save RunPod API key"}
          </button>
          <small>LoraSuite uses an API key, not your RunPod password. New users should generally choose RunComfy.</small>
        </div>
        <ol>
          <li className={hasApiCredential ? "complete" : ""}><span>1</span>Connect</li>
          <li><span>2</span>Provision or restore infrastructure</li>
          <li className={bundle?.ready ? "complete" : ""}><span>3</span>Build and upload</li>
          <li className={preflightReady ? "complete" : ""}><span>4</span>Verify and start</li>
        </ol>
      </section>
      <RunPodInfrastructureSetup engine={engine} apiToken={apiToken} apiCredentialAvailable={hasApiCredential} onApiTokenChange={setApiToken} onProfile={applyInfrastructure} />
      <label>Bundle folder<input aria-label={`RunPod ${modality} bundle folder`} value={outputPath} onChange={(event) => setOutputPath(event.target.value)} placeholder="/path/to/runpod-bundle" /></label>
      {isTauri() ? <button type="button" onClick={chooseOutput} title="Choose RunPod bundle folder"><FolderOpen size={14} /></button> : null}
      <label>Remote root<input aria-label={`RunPod ${modality} remote root`} value={remoteRoot} onChange={(event) => setRemoteRoot(event.target.value)} /></label>
      <label>Endpoint<input aria-label={`RunPod ${modality} endpoint ID`} value={endpointId} onChange={(event) => setEndpointId(event.target.value)} placeholder="Optional Serverless endpoint" /></label>
      <button className="primary-action" type="button" onClick={createBundle} disabled={!outputPath.trim() || !remoteRoot.trim() || busy}><PackageOpen size={14} /> Export RunPod</button>
      {requiresModelBootstrap ? <section className={`runpod-model-bootstrap ${bootstrapRun?.status ?? "pending"}`} aria-label="RunPod required model installation">
        <div><Download size={14} /><span><strong>Required Models</strong><small>{trainingTargetProfileId === "runpod_id_lora_ltx23_inference" ? "LTX-2.3 · Gemma · ID-LoRA · approximately 80 GB" : "Fish Speech S2-Pro · approximately 11 GB"}</small></span></div>
        <span className="runpod-model-state">{bootstrapRun?.status.replaceAll("_", " ") ?? "not installed"}</span>
        <button type="button" onClick={() => void installRequiredModels()} disabled={busy || !endpointId.trim() || !hasApiCredential || Boolean(bootstrapRun && ["queued", "in_queue", "running", "completed"].includes(bootstrapRun.status))} title={!endpointId.trim() ? "Choose or enter a RunPod endpoint first" : !hasApiCredential ? "Enter or save the RunPod API key" : "Install pinned models on the endpoint network volume"}><Download size={13} />{bootstrapRun?.status === "completed" ? "Models Ready" : bootstrapRun && ["failed", "canceled", "timed_out"].includes(bootstrapRun.status) ? "Retry Install" : "Install Models"}</button>
        {bootstrapRun && ["queued", "in_queue", "running"].includes(bootstrapRun.status) ? <button type="button" title="Cancel model installation" onClick={() => void cancelModelBootstrap()} disabled={busy || !hasApiCredential}><Ban size={13} /></button> : null}
        <small>{bootstrapRun?.error ?? bootstrapRun?.progress_message ?? "Downloads resume through the pinned RunPod worker contract."}</small>
      </section> : null}
      {bundle ? <div className={`runpod-result ${bundle.ready ? "ready" : "blocked"}`}>{bundle.ready ? <Check size={14} /> : <ShieldAlert size={14} />}<span><strong>{bundle.ready ? "Trainer-ready" : "Worker required"}</strong><small>{bundle.archive_path}</small></span></div> : null}
      {bundle?.ready && smokeSupported ? <button type="button" onClick={() => void smokeTestBundle()} disabled={busy}><ShieldCheck size={14} /> Smoke Test</button> : null}
      {smokeRun ? <div className={`provider-smoke-result ${smokeRun.ready ? "ready" : "blocked"}`}>
        {smokeRun.ready ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
        <span><strong>{smokeRun.ready ? "Worker contract passed" : "Worker contract failed"}</strong><small>{smokeRun.checks.filter((check) => check.passed).length}/{smokeRun.checks.length} checks · {new Date(smokeRun.completed_at).toLocaleString()}</small></span>
        <div>{smokeRun.checks.map((check) => <i key={check.id} className={check.passed ? "passed" : "failed"} title={`${check.id}: ${check.detail}`} />)}</div>
      </div> : null}
      {bundle?.warnings.map((warning) => <p className="runpod-warning" key={warning}>{warning}</p>)}
      {bundle?.ready ? <div className="runpod-launch-row">
        <label>API key<input aria-label={`RunPod ${modality} API key`} type="password" autoComplete="off" value={apiToken} onChange={(event) => setApiToken(event.target.value)} placeholder={storedApiCredential ? "Stored securely or enter an override" : "Session key or RUNPOD_API_KEY"} /></label>
        <label>Billing<select aria-label="RunPod pricing plan" value={pricingTier} onChange={(event) => setPricingTier(event.target.value as typeof pricingTier)}><option value="flex">Flex workers</option><option value="active">Active workers</option></select></label>
        <button type="button" onClick={verifyEndpoint} disabled={busy || !uploadReady || !endpointId.trim()} title={uploadReady ? "Verify RunPod endpoint" : "Upload the bundle before endpoint verification"}><ShieldCheck size={14} /> Verify Endpoint</button>
        <button className="primary-action" type="button" onClick={startRun} disabled={busy || !preflightReady}><Rocket size={14} /> Start RunPod</button>
        <small>{storedApiCredential ? "Using the system credential store" : "Unsaved keys stay in memory only"}</small>
      </div> : null}
      {bundle?.ready ? <TrainingEstimatePanel
        engine={engine}
        provider="runpod"
        profileId={trainingTargetProfileId}
        gpuType={estimateGpuType}
        pricingTier={pricingTier}
      /> : null}
      {preflight && bundle ? <div className={`runpod-preflight ${preflightReady ? "ready" : "blocked"}`}>
        <header>{preflightReady ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}<span><strong>{preflightReady ? "Endpoint ready" : "Endpoint needs attention"}</strong><small>{preflight.gpu.available ? `${preflight.gpu.name} · ${preflight.gpu.memory_gb} GB` : "GPU unavailable"}</small></span></header>
        <div>{preflight.checks.map((check) => <span className={check.passed ? "passed" : "failed"} key={check.id} title={check.detail}>{check.passed ? <Check size={11} /> : <ShieldAlert size={11} />}{preflightLabel(check.id)}</span>)}</div>
        <small>Checked {new Date(preflight.checked_at).toLocaleString()}</small>
      </div> : null}
      {bundle?.ready ? <details className="runpod-download-config" open={volumeConfigOpen} onToggle={(event) => setVolumeConfigOpen(event.currentTarget.open)}>
        <summary>Network volume · {uploadReady ? "bundle uploaded" : uploadJob?.status ?? "upload required"}</summary>
        <div>
          {runs.some((run) => run.status === "completed" && run.artifacts.some((artifact) => !artifact.local_path)) ? <label>Download to<input aria-label={`RunPod ${modality} artifact folder`} value={artifactOutput} onChange={(event) => setArtifactOutput(event.target.value)} /></label> : null}
          {isTauri() && runs.some((run) => run.status === "completed" && run.artifacts.some((artifact) => !artifact.local_path)) ? <button type="button" onClick={chooseArtifactOutput} title="Choose artifact folder"><FolderOpen size={13} /></button> : null}
          <label>Volume ID<input aria-label="RunPod network volume ID" value={volumeId} onChange={(event) => setVolumeId(event.target.value)} /></label>
          <label>S3 endpoint<input aria-label="RunPod S3 endpoint" value={s3Endpoint} onChange={(event) => setS3Endpoint(event.target.value)} placeholder="https://s3api-us-ca-2.runpod.io/" /></label>
          <label>Datacenter<input aria-label="RunPod datacenter" value={datacenter} onChange={(event) => setDatacenter(event.target.value)} placeholder="US-CA-2" /></label>
          <label>Access key<input aria-label="RunPod S3 access key" value={s3AccessKey} onChange={(event) => setS3AccessKey(event.target.value)} placeholder="AWS_ACCESS_KEY_ID" /></label>
          <label>Secret<input aria-label="RunPod S3 secret key" type="password" autoComplete="off" value={s3SecretKey} onChange={(event) => setS3SecretKey(event.target.value)} placeholder="AWS_SECRET_ACCESS_KEY" /></label>
          <button className="runpod-upload-button" type="button" onClick={uploadBundle} disabled={busy || (smokeSupported && !smokeRun?.ready) || uploadReady || uploadJob?.status === "running" || uploadJob?.status === "queued" || !volumeId.trim() || !s3Endpoint.trim() || !datacenter.trim()} title={!smokeSupported || smokeRun?.ready ? "Upload bundle" : "Pass the local provider smoke test before uploading"}><Upload size={13} /> {uploadJob?.status === "failed" ? "Resume Upload" : uploadReady ? "Uploaded" : "Upload Bundle"}</button>
        </div>
        {uploadJob ? <div className={`runpod-upload-progress ${uploadJob.status}`}><progress max={Math.max(uploadJob.files_total, 1)} value={uploadJob.files_uploaded} /><span>{uploadJob.files_uploaded}/{uploadJob.files_total} files · {formatBytes(uploadJob.bytes_uploaded)}/{formatBytes(uploadJob.bytes_total)}</span>{uploadJob.current_file ? <small>{uploadJob.current_file}</small> : null}{uploadJob.error ? <small>{uploadJob.error}</small> : null}</div> : null}
      </details> : null}
      {runs.length ? <div className="runpod-run-list" aria-label="RunPod training runs">
        {runs.map((run) => <article key={run.id} className={`runpod-run ${run.status}`}>
          <div><i /><span><strong>{run.status.replace("_", " ")}</strong><small>{run.progress_message}</small></span></div>
          <dl>
            <div><dt>Job</dt><dd>{shortId(run.provider_job_id ?? "pending")}</dd></div>
            <div><dt><Clock3 size={11} /> Runtime</dt><dd>{formatRuntime(run.execution_time_ms)}</dd></div>
            <div><dt>Artifacts</dt><dd>{run.artifacts.length}</dd></div>
          </dl>
          <div className="runpod-run-actions">
            {run.status === "completed" && run.artifacts.some((artifact) => !artifact.local_path) ? <button type="button" title="Download RunPod artifacts" onClick={() => downloadArtifacts(run.id)} disabled={busy || !artifactOutput.trim() || !volumeId.trim() || !s3Endpoint.trim() || !datacenter.trim()}><Download size={13} /></button> : null}
            {run.action === "train_lora" && run.status === "completed" && run.artifacts.length > 0 && run.artifacts.every((artifact) => artifact.local_path) ? <button type="button" title="Register RunPod artifacts" onClick={() => registerArtifacts(run.id)} disabled={busy}><Database size={13} /></button> : null}
            {!["completed", "failed", "canceled", "timed_out"].includes(run.status) ? <button type="button" title="Refresh RunPod job" onClick={() => refreshRun(run.id)} disabled={busy}><RefreshCw size={13} /></button> : null}
            {!["completed", "failed", "canceled", "timed_out"].includes(run.status) ? <button type="button" title="Cancel RunPod job" onClick={() => cancelRun(run.id)} disabled={busy}><Ban size={13} /></button> : null}
          </div>
          {run.artifacts.map((artifact) => <p key={`${artifact.kind}:${artifact.name}`} title={artifact.volume_path ?? artifact.remote_url ?? undefined}><strong>{artifact.kind}</strong> {artifact.name}</p>)}
          {run.error ? <p className="runpod-warning">{run.error}</p> : null}
        </article>)}
      </div> : null}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }

function shortId(value: string): string { return value.length > 14 ? value.slice(-12) : value; }

function formatRuntime(milliseconds?: number | null): string {
  if (milliseconds == null) return "--";
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function preflightLabel(value: string): string {
  const [, detail] = value.split(":", 2);
  return (detail || value).replaceAll("_", " ");
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
