import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ArtifactReleaseCandidate, ModelArtifactRecord } from "../lib/types";
import { ReleaseCandidatePanel } from "./ReleaseCandidatePanel";

describe("ReleaseCandidatePanel", () => {
  it("ranks certified checkpoints and persists the selected release", async () => {
    const user = userEvent.setup();
    const ready = candidate("artifact-best", "best.safetensors", 91.4, true);
    const blocked = candidate("artifact-review", "review.safetensors", 96.2, false);
    const selected = { ...ready, selected: true, artifact: { ...ready.artifact, selected_for_release: true } };
    const listModelReleaseCandidates = vi.fn()
      .mockResolvedValueOnce([ready, blocked])
      .mockResolvedValue([selected, blocked]);
    const engine = {
      listModelReleaseCandidates,
      selectModelRelease: vi.fn().mockResolvedValue(selected.artifact),
    };
    const onSelected = vi.fn();

    render(<ReleaseCandidatePanel engine={engine} projectId="project-1" mode="audio_visual" onSelected={onSelected} />);

    expect(await screen.findByText("best.safetensors")).toBeInTheDocument();
    expect(screen.getByText("91.4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not Ready" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Select Release" }));

    await waitFor(() => expect(engine.selectModelRelease).toHaveBeenCalledWith("artifact-best"));
    expect(await screen.findByText("Selected")).toBeInTheDocument();
    expect(onSelected).toHaveBeenCalled();
  });

  it("filters image and audio-visual candidates into their own workspaces", async () => {
    const image = candidate("image-1", "image.safetensors", 80, true, "image");
    const video = candidate("video-1", "video.safetensors", 82, true, "video");
    const engine = { listModelReleaseCandidates: vi.fn().mockResolvedValue([image, video]), selectModelRelease: vi.fn() };

    render(<ReleaseCandidatePanel engine={engine} projectId="project-1" mode="image" />);

    expect(await screen.findByText("image.safetensors")).toBeInTheDocument();
    expect(screen.queryByText("video.safetensors")).not.toBeInTheDocument();
  });
});

function candidate(id: string, name: string, score: number, eligible: boolean, modality: ModelArtifactRecord["modality"] = "video"): ArtifactReleaseCandidate {
  return {
    rank: 1,
    score,
    eligible,
    selected: false,
    metrics: { identity_similarity: 0.86, temporal_stability: 0.8 },
    reasons: eligible ? [] : ["acceptance gates are incomplete"],
    artifact: {
      id,
      project_id: "project-1",
      training_run_id: `run-${id}`,
      snapshot_id: "snapshot-1",
      dataset_fingerprint: "fingerprint-1",
      checkpoint_name: name,
      checkpoint_path: `/tmp/${name}`,
      checkpoint_sha256: id,
      checkpoint_size_bytes: 1024,
      sample_paths: [],
      trigger_token: "person_token",
      modality,
      model_family: modality === "image" ? "flux1" : "wan22_14b_t2v",
      evaluation: { status: "ready", checkpoint_valid: true, provenance_valid: true, config_present: true, sample_count: 0, tensor_count: 1, parameter_count: 1, warnings: [], evaluated_at: "2026-07-12T00:00:00Z" },
      acceptance: { status: eligible ? "certified" : "screening_passed", screening_ready: true, release_ready: eligible, passed_count: 4, failed_count: 0, blocked_count: 0, warnings: [] },
      installed_paths: [],
      workflow_paths: [],
      created_at: "2026-07-12T00:00:00Z",
      updated_at: "2026-07-12T00:00:00Z",
    },
  };
}
