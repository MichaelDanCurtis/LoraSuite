import { Clock3, DollarSign, Gauge } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type {
  TrainingCostEstimate,
  TrainingEstimateRequest,
} from "../lib/types";

interface TrainingEstimatePanelProps {
  engine: Pick<EngineClient, "estimateTraining">;
  provider: "runcomfy" | "runpod";
  profileId?: string;
  gpuType: string;
  pricingTier: string;
  configFile?: string;
  datasetItemCount?: number;
  hourlyRateUsd?: number;
}

export function TrainingEstimatePanel({
  engine,
  provider,
  profileId,
  gpuType,
  pricingTier,
  configFile,
  datasetItemCount,
  hourlyRateUsd,
}: TrainingEstimatePanelProps) {
  const [estimate, setEstimate] = useState<TrainingCostEstimate | null>(null);
  const [error, setError] = useState("");
  const request = useMemo<TrainingEstimateRequest | null>(() => (
    profileId
      ? {
          provider,
          training_target_profile_id: profileId,
          gpu_type: gpuType,
          pricing_tier: pricingTier,
          config_file: configFile?.trim() || undefined,
          dataset_item_count: datasetItemCount,
          hourly_rate_usd: hourlyRateUsd,
        }
      : null
  ), [
    configFile,
    datasetItemCount,
    gpuType,
    hourlyRateUsd,
    pricingTier,
    profileId,
    provider,
  ]);

  useEffect(() => {
    if (!request || !engine.estimateTraining) {
      setEstimate(null);
      setError("");
      return;
    }
    let disposed = false;
    const timer = window.setTimeout(() => {
      engine.estimateTraining?.(request)
        .then((value) => {
          if (disposed) return;
          setEstimate(value);
          setError("");
        })
        .catch((reason) => {
          if (disposed) return;
          setEstimate(null);
          setError(errorMessage(reason));
        });
    }, 250);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [engine, request]);

  if (!profileId || !engine.estimateTraining) return null;

  return (
    <section
      className={`training-estimate ${estimate?.available ? "available" : "unavailable"}`}
      aria-label={`${provider === "runcomfy" ? "RunComfy" : "RunPod"} training estimate`}
    >
      <header>
        <Gauge size={15} aria-hidden="true" />
        <span>
          <strong>Planning estimate</strong>
          <small>{estimate ? `${estimate.confidence} confidence` : error || "Calculating..."}</small>
        </span>
      </header>
      {estimate?.available && estimate.duration_hours ? (
        <>
          <dl>
            <div>
              <dt><Clock3 size={12} /> Runtime</dt>
              <dd>{formatHours(estimate.duration_hours.expected)}</dd>
              <small>{formatHours(estimate.duration_hours.low)}-{formatHours(estimate.duration_hours.high)}</small>
            </div>
            <div>
              <dt><DollarSign size={12} /> Rate</dt>
              <dd>{estimate.hourly_rate_usd == null ? "Unknown" : `$${estimate.hourly_rate_usd.toFixed(2)}/hr`}</dd>
              <small>{humanizeTier(estimate.pricing_tier)}</small>
            </div>
            <div>
              <dt><DollarSign size={12} /> Expected</dt>
              <dd>{estimate.cost_usd ? formatMoney(estimate.cost_usd.expected) : "Unknown"}</dd>
              <small>{estimate.cost_usd ? `${formatMoney(estimate.cost_usd.low)}-${formatMoney(estimate.cost_usd.high)}` : "Enter a rate to calculate"}</small>
            </div>
          </dl>
          <details>
            <summary>
              {estimate.historical_run_count
                ? `${estimate.historical_run_count} measured run${estimate.historical_run_count === 1 ? "" : "s"}`
                : `${estimate.step_count ?? "Configured"} steps · assumptions`}
            </summary>
            <p>{estimate.duration_basis}</p>
            <ul>{estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
            {estimate.warnings.map((warning) => <p key={warning} className="warning">{warning}</p>)}
            {estimate.pricing_source_url ? (
              <a href={estimate.pricing_source_url} target="_blank" rel="noreferrer">
                Pricing snapshot {estimate.pricing_snapshot_date}
              </a>
            ) : <small>{estimate.pricing_basis}</small>}
          </details>
        </>
      ) : (
        <p>{error || estimate?.warnings[0] || "Calculating provider runtime and cost..."}</p>
      )}
    </section>
  );
}

function formatHours(value: number): string {
  if (value < 1) return `${Math.max(1, Math.round(value * 60))}m`;
  const hours = Math.floor(value);
  const minutes = Math.round((value - hours) * 60);
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

function formatMoney(value: number): string {
  return `$${value.toFixed(2)}`;
}

function humanizeTier(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
