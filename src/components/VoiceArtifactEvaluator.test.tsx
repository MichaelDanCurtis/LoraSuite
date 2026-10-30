import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ModelArtifactRecord, VoiceArtifactEvaluationRun } from "../lib/types";
import { VoiceArtifactEvaluator } from "./VoiceArtifactEvaluator";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("VoiceArtifactEvaluator", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));

  it("queues rendered voice samples against a registered checkpoint", async () => {
    const user = userEvent.setup();
    const createVoiceArtifactEvaluation = vi.fn().mockResolvedValue(run("queued"));
    const engine = {
      assetUrl: (path: string) => path,
      listModelArtifacts: vi.fn().mockResolvedValue([artifact()]),
      listVoiceArtifactEvaluations: vi.fn().mockResolvedValue([]),
      getVoiceArtifactEvaluation: vi.fn(),
      getRecommendedVoiceArtifactEvaluation: vi.fn().mockResolvedValue(null),
      createVoiceArtifactEvaluation,
      selectVoiceArtifactEvaluation: vi.fn(),
    };
    render(<VoiceArtifactEvaluator engine={engine} projectId="project-1" />);

    await screen.findByRole("option", { name: "voice_step_250.ckpt" });
    await user.type(screen.getByLabelText("Voice evaluation samples folder"), "/tmp/rendered");
    await user.click(screen.getByRole("button", { name: "Evaluate" }));

    await waitFor(() => expect(createVoiceArtifactEvaluation).toHaveBeenCalledWith({
      project_id: "project-1",
      artifact_id: "artifact-1",
      samples_dir: "/tmp/rendered",
    }));
    expect(screen.getByText("Voice checkpoint evaluation is running in the background.")).toBeInTheDocument();
  });

  it("shows and selects the earliest passing checkpoint", async () => {
    const user = userEvent.setup();
    const passing = run("complete");
    passing.summary.screening_ready = true;
    passing.summary.sample_count = 3;
    passing.summary.passed_count = 3;
    const selected = { ...passing, selected_for_release: true };
    const selectVoiceArtifactEvaluation = vi.fn().mockResolvedValue(selected);
    const engine = {
      assetUrl: (path: string) => path,
      listModelArtifacts: vi.fn().mockResolvedValue([artifact()]),
      listVoiceArtifactEvaluations: vi.fn().mockResolvedValue([passing]),
      getVoiceArtifactEvaluation: vi.fn(),
      getRecommendedVoiceArtifactEvaluation: vi.fn().mockResolvedValue(passing),
      createVoiceArtifactEvaluation: vi.fn(),
      selectVoiceArtifactEvaluation,
    };
    render(<VoiceArtifactEvaluator engine={engine} projectId="project-1" />);

    await screen.findByText("Earliest passing");
    await user.click(screen.getByRole("button", { name: "Select earliest" }));

    await waitFor(() => expect(selectVoiceArtifactEvaluation).toHaveBeenCalledWith("voice-run-1"));
    expect(screen.getByText("Release")).toBeInTheDocument();
  });
});

function artifact(): ModelArtifactRecord {
  return {
    id: "artifact-1", training_run_id: "run-1", snapshot_id: "project-1", dataset_fingerprint: "fingerprint",
    checkpoint_name: "voice_step_250.ckpt", checkpoint_path: "/tmp/voice_step_250.ckpt", checkpoint_sha256: "sha", checkpoint_size_bytes: 42,
    sample_paths: [], trigger_token: "voice_person", base_model: "fishaudio/s2-pro", modality: "voice", model_family: "fish_speech_s2",
    evaluation: { status: "review", checkpoint_valid: true, provenance_valid: true, config_present: true, sample_count: 0, tensor_count: 0, parameter_count: 0, warnings: [], evaluated_at: "2026-07-12T00:00:00Z" },
    installed_paths: [], workflow_paths: [], created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function run(status: VoiceArtifactEvaluationRun["status"]): VoiceArtifactEvaluationRun {
  return {
    id: "voice-run-1", project_id: "project-1", artifact_id: "artifact-1", checkpoint_name: "voice_step_250.ckpt", checkpoint_step: 250,
    samples_dir: "/tmp/rendered", status, samples: {}, selected_for_release: false,
    summary: { sample_count: 0, passed_count: 0, failed_count: 0, blocked_count: 0, screening_ready: false, rank_score: 0, warnings: [] },
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}
