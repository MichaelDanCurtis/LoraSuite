import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CloudProviderOverview } from "./CloudProviderOverview";


describe("CloudProviderOverview", () => {
  it("summarizes provider capability truth and normalized project runs", async () => {
    const engine = {
      listCloudProviders: vi.fn().mockResolvedValue([
        {
          id: "runpod",
          label: "RunPod Serverless",
          contract_version: "lorasuite.cloud-provider.v1",
          auth_environment_variables: ["RUNPOD_API_KEY"],
          target_profile_ids: ["runcomfy_flux1_dev_character"],
          modalities: ["image"],
          actions: ["train_lora"],
          gpu_families: ["NVIDIA H100 80GB HBM3"],
          billing_models: ["flex"],
          documentation_urls: [],
          pricing_snapshot_date: "2026-07-16",
          features: [
            { id: "immutable_config", label: "Immutable config", support: "native", detail: "Verified." },
            { id: "checkpoint_resume", label: "Resume", support: "unavailable", detail: "Unavailable." },
          ],
          warnings: [],
        },
      ]),
      listCloudRuns: vi.fn().mockResolvedValue([
        {
          id: "run-1",
          provider: "runpod",
          project_id: "project-1",
          training_target_profile_id: "runcomfy_flux1_dev_character",
          modality: "image",
          operation: "train",
          state: "running",
          provider_status: "running",
          progress: { current: 100, total: 2000, percent: 5, message: "Training on RunPod" },
          dataset_fingerprint: "fingerprint",
          config_digest: "digest",
          artifact_count: 0,
          local_artifact_count: 0,
          checksum_artifact_count: 0,
          registered_artifact_count: 0,
          available_actions: ["refresh", "cancel"],
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
      ]),
    };

    render(<CloudProviderOverview engine={engine} projectId="project-1" />);

    await waitFor(() => expect(screen.getByText("1 provider contracts")).toBeInTheDocument());
    expect(screen.getByText("1 active")).toBeInTheDocument();
    expect(engine.listCloudRuns).toHaveBeenCalledWith("project-1");
  });
});
