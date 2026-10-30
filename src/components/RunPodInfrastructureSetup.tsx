import { Check, CloudCog, HardDrive, RefreshCw, Server, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { RunPodInfrastructureProfile } from "../lib/types";

type InfrastructureEngine = Pick<EngineClient, "listRunPodInfrastructureProfiles" | "provisionRunPodInfrastructure">;

interface RunPodInfrastructureSetupProps {
  engine: InfrastructureEngine;
  apiToken: string;
  apiCredentialAvailable?: boolean;
  onApiTokenChange(value: string): void;
  onProfile(profile: RunPodInfrastructureProfile): void;
}

export function RunPodInfrastructureSetup({ engine, apiToken, apiCredentialAvailable, onApiTokenChange, onProfile }: RunPodInfrastructureSetupProps) {
  const [profiles, setProfiles] = useState<RunPodInfrastructureProfile[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [workerImage, setWorkerImage] = useState("");
  const [datacenter, setDatacenter] = useState("US-KS-2");
  const [gpuType, setGpuType] = useState("NVIDIA H100 80GB HBM3");
  const [volumeSize, setVolumeSize] = useState(500);
  const [volumeId, setVolumeId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [endpointId, setEndpointId] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Use an existing profile or provision the worker stack.");
  const hasApiCredential = apiCredentialAvailable ?? Boolean(apiToken.trim());

  useEffect(() => {
    let disposed = false;
    const listProfiles = (engine as Partial<InfrastructureEngine>).listRunPodInfrastructureProfiles;
    if (typeof listProfiles !== "function") return () => { disposed = true; };
    listProfiles.call(engine)
      .then((items) => {
        if (disposed) return;
        setProfiles(items);
        const ready = items.find((item) => item.status === "ready" && item.endpoint_id && item.network_volume_id);
        if (ready) {
          setSelectedId(ready.id);
          loadProfile(ready);
          onProfile(ready);
          setStatus("Restored provider-ready RunPod infrastructure.");
        }
      })
      .catch((error) => { if (!disposed) setStatus(`Infrastructure registry error: ${errorMessage(error)}`); });
    return () => { disposed = true; };
  }, [engine]);

  function loadProfile(profile: RunPodInfrastructureProfile) {
    setWorkerImage(profile.image_name);
    setDatacenter(profile.data_center_id);
    setGpuType(profile.gpu_type_ids[0] ?? "NVIDIA H100 80GB HBM3");
    setVolumeSize(profile.network_volume_size_gb);
    setVolumeId(profile.network_volume_id ?? "");
    setTemplateId(profile.template_id ?? "");
    setEndpointId(profile.endpoint_id ?? "");
  }

  function selectProfile(profileId: string) {
    setSelectedId(profileId);
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile) return;
    loadProfile(profile);
    if (profile.status === "ready") onProfile(profile);
    setStatus(profile.progress_message);
  }

  async function provision() {
    if (busy || !hasApiCredential || (!selectedId && (!workerImage.trim() || !datacenter.trim()))) return;
    const provisionInfrastructure = (engine as Partial<InfrastructureEngine>).provisionRunPodInfrastructure;
    if (typeof provisionInfrastructure !== "function") {
      setStatus("This engine does not expose RunPod infrastructure provisioning.");
      return;
    }
    setBusy(true);
    setStatus(selectedId ? "Resuming infrastructure provisioning..." : "Creating volume, template, and Serverless endpoint...");
    try {
      const profile = await provisionInfrastructure.call(engine, {
        profile_id: selectedId || undefined,
        image_name: workerImage.trim(),
        data_center_id: datacenter.trim(),
        network_volume_id: volumeId.trim() || undefined,
        template_id: templateId.trim() || undefined,
        endpoint_id: endpointId.trim() || undefined,
        network_volume_size_gb: volumeSize,
        gpu_type_ids: [gpuType],
        runtime_environment: hfToken.trim() ? { HF_TOKEN: hfToken.trim() } : {},
        api_token: apiToken.trim(),
      });
      setHfToken("");
      setProfiles((items) => [profile, ...items.filter((item) => item.id !== profile.id)]);
      setSelectedId(profile.id);
      loadProfile(profile);
      setStatus(profile.error || profile.progress_message);
      if (profile.status === "ready") onProfile(profile);
    } catch (error) {
      setHfToken("");
      setStatus(`Infrastructure provisioning error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const selected = profiles.find((item) => item.id === selectedId);
  const ready = selected?.status === "ready";

  return <details className="runpod-infrastructure" open={!ready}>
    <summary><CloudCog size={14} /><span><strong>RunPod Infrastructure</strong><small>{ready ? `${selected.endpoint_name} ready` : "Volume · worker · endpoint"}</small></span>{ready ? <Check size={13} /> : <ShieldAlert size={13} />}</summary>
    <div className="runpod-infrastructure-grid">
      {profiles.length ? <label>Saved profile<select aria-label="RunPod infrastructure profile" value={selectedId} onChange={(event) => selectProfile(event.target.value)}><option value="">New infrastructure</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.status}</option>)}</select></label> : null}
      <label className="runpod-worker-image"><Server size={13} /> Worker image<input aria-label="RunPod worker image" value={workerImage} onChange={(event) => setWorkerImage(event.target.value)} placeholder="docker.io/account/lorasuite-worker:sha" disabled={!!selectedId} /></label>
      <label>Datacenter<input aria-label="RunPod infrastructure datacenter" value={datacenter} onChange={(event) => setDatacenter(event.target.value.toUpperCase())} placeholder="US-KS-2" disabled={!!selectedId} /></label>
      <label>GPU<select aria-label="RunPod infrastructure GPU" value={gpuType} onChange={(event) => setGpuType(event.target.value)} disabled={!!selectedId}><option>NVIDIA H100 80GB HBM3</option><option>NVIDIA H200</option><option>NVIDIA A100 80GB PCIe</option></select></label>
      <label><HardDrive size={13} /> Volume GB<input aria-label="RunPod network volume size" type="number" min={1} max={4000} value={volumeSize} onChange={(event) => setVolumeSize(Number(event.target.value))} disabled={!!selectedId} /></label>
      <label>RunPod API key<input aria-label="RunPod infrastructure API key" type="password" autoComplete="off" value={apiToken} onChange={(event) => onApiTokenChange(event.target.value)} placeholder={apiCredentialAvailable && !apiToken.trim() ? "Stored securely" : "Session key"} /></label>
      <label>Hugging Face token<input aria-label="RunPod Hugging Face token" type="password" autoComplete="off" value={hfToken} onChange={(event) => setHfToken(event.target.value)} placeholder="Optional gated-model token" disabled={!!selectedId} /></label>
      <details className="runpod-existing-resources"><summary>Use existing resources</summary><div><label>Volume ID<input aria-label="Existing RunPod volume ID" value={volumeId} onChange={(event) => setVolumeId(event.target.value)} disabled={!!selectedId} /></label><label>Template ID<input aria-label="Existing RunPod template ID" value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={!!selectedId} /></label><label>Endpoint ID<input aria-label="Existing RunPod endpoint ID" value={endpointId} onChange={(event) => setEndpointId(event.target.value)} disabled={!!selectedId} /></label></div></details>
      <button className="primary-action runpod-provision" type="button" onClick={() => void provision()} disabled={busy || ready || !hasApiCredential || (!selectedId && (!workerImage.trim() || !datacenter.trim()))}>{busy ? <RefreshCw className="spin" size={14} /> : <CloudCog size={14} />}{selectedId ? "Resume Setup" : "Provision RunPod"}</button>
    </div>
    {selected ? <div className={`runpod-infrastructure-state ${selected.status}`}><span><HardDrive size={12} />{selected.network_volume_id || "volume pending"}</span><span><Server size={12} />{selected.template_id || "template pending"}</span><span><CloudCog size={12} />{selected.endpoint_id || "endpoint pending"}</span></div> : null}
    <p className="status-line" aria-live="polite">{status}</p>
  </details>;
}

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
