import { Activity, Check, Cloud, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { CloudProviderDescriptor, CloudRunRecord } from "../lib/types";


type CloudOverviewEngine = Pick<EngineClient, "listCloudProviders" | "listCloudRuns">;

interface CloudProviderOverviewProps {
  engine: CloudOverviewEngine;
  projectId?: string;
}

export function CloudProviderOverview({ engine, projectId }: CloudProviderOverviewProps) {
  const [providers, setProviders] = useState<CloudProviderDescriptor[]>([]);
  const [runs, setRuns] = useState<CloudRunRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("Cloud contract not inspected.");

  async function refresh() {
    if (!engine.listCloudProviders || !engine.listCloudRuns || loading) return;
    setLoading(true);
    try {
      const [providerPayload, runPayload] = await Promise.all([
        engine.listCloudProviders(),
        engine.listCloudRuns(projectId),
      ]);
      setProviders(providerPayload);
      setRuns(runPayload);
      setStatus(`Cloud contract ready · ${runPayload.length} recorded run${runPayload.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setStatus(`Cloud contract error: ${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [engine, projectId]);

  const activeRuns = useMemo(
    () => runs.filter((run) => ["queued", "preparing", "running", "paused", "retrieving"].includes(run.state)),
    [runs],
  );
  const recentRuns = runs.slice(0, 5);
  if (!engine.listCloudProviders || !engine.listCloudRuns) return null;

  return (
    <details className="cloud-provider-overview">
      <summary>
        <Cloud size={15} aria-hidden="true" />
        <span>
          <strong>Cloud handoff</strong>
          <small>{providers.length ? `${providers.length} provider contracts` : "Inspect provider contracts"}</small>
        </span>
        <em>{activeRuns.length ? `${activeRuns.length} active` : runs.length ? `${runs.length} recorded` : "No runs"}</em>
      </summary>
      <div className="cloud-provider-overview-body">
        <div className="cloud-provider-contracts">
          {providers.map((provider) => {
            const nativeCount = provider.features.filter((feature) => feature.support === "native").length;
            const incompleteCount = provider.features.filter((feature) => feature.support === "partial" || feature.support === "unavailable").length;
            return (
              <section key={provider.id}>
                <header>
                  <span><ShieldCheck size={14} /><strong>{provider.label}</strong></span>
                  <small>{provider.contract_version}</small>
                </header>
                <p>{provider.modalities.join(" · ")} · {provider.target_profile_ids.length} executable target{provider.target_profile_ids.length === 1 ? "" : "s"}</p>
                <div>
                  <span><Check size={12} /> {nativeCount} native</span>
                  <span className={incompleteCount ? "warning" : ""}><TriangleAlert size={12} /> {incompleteCount} limited</span>
                </div>
              </section>
            );
          })}
        </div>
        <div className="cloud-run-overview">
          <header>
            <span><Activity size={14} /><strong>Recent provider runs</strong></span>
            <button type="button" title="Refresh cloud provider state" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={loading ? "spin" : ""} size={13} />
            </button>
          </header>
          {recentRuns.length ? recentRuns.map((run) => (
            <div className={`cloud-run-row ${run.state}`} key={`${run.provider}:${run.id}`}>
              <span><strong>{run.provider === "runcomfy" ? "RunComfy" : "RunPod"}</strong><small>{run.training_target_profile_id || run.modality || "Provider run"}</small></span>
              <span><strong>{run.state}</strong><small>{run.progress.message}</small></span>
              <em>{run.artifact_count ? `${run.local_artifact_count}/${run.artifact_count} local` : run.progress.percent ? `${Math.round(run.progress.percent)}%` : "—"}</em>
            </div>
          )) : <p className="cloud-run-empty">No provider runs are recorded for this project.</p>}
        </div>
        <p className="status-line" aria-live="polite">{status}</p>
      </div>
    </details>
  );
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
