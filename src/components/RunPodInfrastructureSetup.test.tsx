import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RunPodInfrastructureProfile } from "../lib/types";
import { RunPodInfrastructureSetup } from "./RunPodInfrastructureSetup";

function profile(overrides: Partial<RunPodInfrastructureProfile> = {}): RunPodInfrastructureProfile {
  return {
    id: "infra-1",
    provider: "runpod",
    name: "LoraSuite Training",
    image_name: "docker.io/example/lorasuite-worker:sha-123",
    data_center_id: "US-KS-2",
    network_volume_id: "volume-1",
    network_volume_name: "lorasuite-models",
    network_volume_size_gb: 500,
    template_id: "template-1",
    template_name: "LoraSuite Serverless Worker",
    container_disk_gb: 50,
    endpoint_id: "endpoint-1",
    endpoint_name: "LoraSuite Training",
    gpu_type_ids: ["NVIDIA H100 80GB HBM3"],
    workers_min: 0,
    workers_max: 1,
    idle_timeout_seconds: 5,
    execution_timeout_ms: 86_400_000,
    status: "ready",
    progress_message: "ready",
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:00:00Z",
    ...overrides,
  };
}

describe("RunPodInfrastructureSetup", () => {
  it("restores a ready profile into the shared RunPod console", async () => {
    const onProfile = vi.fn();
    const engine = {
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([profile()]),
      provisionRunPodInfrastructure: vi.fn(),
    };

    render(<RunPodInfrastructureSetup engine={engine} apiToken="" onApiTokenChange={vi.fn()} onProfile={onProfile} />);

    await waitFor(() => expect(onProfile).toHaveBeenCalledWith(expect.objectContaining({ endpoint_id: "endpoint-1", network_volume_id: "volume-1" })));
    expect(screen.getByText("LoraSuite Training ready")).toBeInTheDocument();
  });

  it("provisions the complete stack and clears the Hugging Face token", async () => {
    const user = userEvent.setup();
    const ready = profile();
    const onProfile = vi.fn();
    const engine = {
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn().mockResolvedValue(ready),
    };

    render(<RunPodInfrastructureSetup engine={engine} apiToken="runpod-secret" onApiTokenChange={vi.fn()} onProfile={onProfile} />);
    await user.type(screen.getByLabelText("RunPod worker image"), "docker.io/example/lorasuite-worker:sha-123");
    await user.type(screen.getByLabelText("RunPod Hugging Face token"), "hf-secret");
    await user.click(screen.getByRole("button", { name: "Provision RunPod" }));

    await waitFor(() => expect(engine.provisionRunPodInfrastructure).toHaveBeenCalledWith(expect.objectContaining({
      image_name: "docker.io/example/lorasuite-worker:sha-123",
      data_center_id: "US-KS-2",
      runtime_environment: { HF_TOKEN: "hf-secret" },
      api_token: "runpod-secret",
    })));
    await waitFor(() => expect(onProfile).toHaveBeenCalledWith(ready));
    expect(screen.getByLabelText("RunPod Hugging Face token")).toHaveValue("");
  });
});
