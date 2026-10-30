import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TrainingCostEstimate } from "../lib/types";
import { TrainingEstimatePanel } from "./TrainingEstimatePanel";

describe("TrainingEstimatePanel", () => {
  it("shows runtime, rate, cost, confidence, and the pricing source", async () => {
    const estimateTraining = vi.fn().mockResolvedValue(estimate());

    render(
      <TrainingEstimatePanel
        engine={{ estimateTraining }}
        provider="runcomfy"
        profileId="runcomfy_flux1_dev_character"
        gpuType="ADA_80_PLUS"
        pricingTier="pro"
        configFile={"train:\n  steps: 2000\n"}
        datasetItemCount={35}
      />,
    );

    expect(await screen.findByText("1h 42m")).toBeInTheDocument();
    expect(screen.getByText("$4.49/hr")).toBeInTheDocument();
    expect(screen.getByText("$7.63")).toBeInTheDocument();
    expect(screen.getByText("low confidence")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pricing snapshot 2026-07-16" })).toHaveAttribute(
      "href",
      "https://www.runcomfy.com/pricing",
    );
    await waitFor(() => expect(estimateTraining).toHaveBeenCalledWith({
      provider: "runcomfy",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      gpu_type: "ADA_80_PLUS",
      pricing_tier: "pro",
      config_file: "train:\n  steps: 2000",
      dataset_item_count: 35,
      hourly_rate_usd: undefined,
    }));
  });

  it("reports an unavailable estimate without exposing a launch credential", async () => {
    const estimateTraining = vi.fn().mockResolvedValue({
      ...estimate(),
      available: false,
      duration_hours: null,
      cost_usd: null,
      warnings: ["No H100 duration baseline is defined."],
    });

    render(
      <TrainingEstimatePanel
        engine={{ estimateTraining }}
        provider="runpod"
        profileId="unsupported-target"
        gpuType="NVIDIA H100 80GB HBM3"
        pricingTier="flex"
      />,
    );

    expect(await screen.findByText("No H100 duration baseline is defined.")).toBeInTheDocument();
  });
});

function estimate(): TrainingCostEstimate {
  return {
    schema_version: "lorasuite.training-estimate.v1",
    available: true,
    provider: "runcomfy",
    training_target_profile_id: "runcomfy_flux1_dev_character",
    training_target_label: "FLUX.1 Dev Character",
    gpu_type: "ADA_80_PLUS",
    gpu_family: "h100",
    pricing_tier: "pro",
    step_count: 2000,
    dataset_item_count: 35,
    duration_hours: { low: 1, expected: 1.7, high: 3 },
    hourly_rate_usd: 4.49,
    cost_usd: { low: 4.49, expected: 7.63, high: 13.47 },
    confidence: "low",
    historical_run_count: 0,
    duration_basis: "Engineering baseline.",
    pricing_basis: "RunComfy Trainer pricing snapshot.",
    pricing_source_url: "https://www.runcomfy.com/pricing",
    pricing_snapshot_date: "2026-07-16",
    assumptions: ["No provider queue time is included."],
    warnings: ["This is a planning estimate, not a provider quote."],
  };
}
