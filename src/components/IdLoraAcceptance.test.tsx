import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { IdLoraEvaluationRun, RunPodTrainingRun } from "../lib/types";
import { IdLoraAcceptance } from "./IdLoraAcceptance";

describe("IdLoraAcceptance", () => {
  it("starts acceptance for a downloaded zero-shot RunPod output", async () => {
    const user = userEvent.setup();
    const createIdLoraEvaluation = vi.fn().mockResolvedValue(evaluation("queued"));
    const engine = {
      assetUrl: (path: string) => path,
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([inferenceRun()]),
      listIdLoraEvaluations: vi.fn().mockResolvedValue([]),
      getIdLoraEvaluation: vi.fn(),
      createIdLoraEvaluation,
      getSyncNetCapability: vi.fn().mockResolvedValue({ configured: false, ready: false, mode: "unconfigured", problems: ["setup required"], setup: [] }),
    };
    render(<IdLoraAcceptance engine={engine} projectId="project-1" />);

    await screen.findByText("Zero-shot output ready");
    await user.click(screen.getByRole("button", { name: "Evaluate Outputs" }));

    await waitFor(() => expect(createIdLoraEvaluation).toHaveBeenCalledWith("runpod-id-lora-1"));
    expect(screen.getByText("ID-LoRA acceptance is running in the background.")).toBeInTheDocument();
  });

  it("renders certified face, voice, transcript, and sync evidence", async () => {
    const completed = evaluation("complete");
    completed.summary = {
      case_count: 1, passed_count: 1, failed_count: 0, blocked_count: 0,
      average_identity: 0.82, average_speaker_similarity: 0.78, average_transcript_similarity: 0.91,
      average_stability: 0.76, screening_ready: true, release_ready: true, warnings: [],
    };
    completed.cases = {
      id_lora_01: {
        id: "id_lora_01", output_name: "id_lora_01", prompt: "[SPEECH]: Hello.", expected_transcript: "Hello.",
        video_path: "/vault/id_lora_01.mp4", passed: true, blocked: false, certified: true, reasons: [], checks: {}, certified_checks: {},
        metrics: {
          visual_quality: 0.8, temporal_stability: 0.76, motion_score: 0.5, subject_coverage: 0.9,
          identity_similarity: 0.82, identity_frame_coverage: 0.9, audio_quality: 0.8, speaker_similarity: 0.78,
          transcript_similarity: 0.91, av_sync_proxy: 0.7, syncnet_lse_c: 4.2, syncnet_lse_d: 7, syncnet_offset_frames: 1,
          duration_seconds: 5, analyzer_notes: [],
        },
      },
    };
    const engine = {
      assetUrl: (path: string) => `asset:${path}`,
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([inferenceRun()]),
      listIdLoraEvaluations: vi.fn().mockResolvedValue([completed]),
      getIdLoraEvaluation: vi.fn(),
      createIdLoraEvaluation: vi.fn(),
      getSyncNetCapability: vi.fn().mockResolvedValue({ configured: true, ready: true, mode: "canonical", problems: [], setup: [] }),
    };
    render(<IdLoraAcceptance engine={engine} projectId="project-1" />);

    expect(await screen.findByText("Certified release ready")).toBeInTheDocument();
    expect(screen.getByText("SyncNet ready")).toBeInTheDocument();
    expect(screen.getAllByText("82%").length).toBeGreaterThan(0);
    expect(screen.getByText("certified")).toBeInTheDocument();
  });
});

function inferenceRun(): RunPodTrainingRun {
  return {
    id: "runpod-id-lora-1", provider: "runpod", bundle_path: "/tmp/bundle", bundle_fingerprint: "fingerprint",
    modality: "audio_visual", training_target_profile_id: "runpod_id_lora_ltx23_inference", action: "run_id_lora",
    endpoint_id: "endpoint", provider_job_id: "job-1", project_id: "project-1", status: "completed", progress_message: "complete",
    artifacts: [
      { kind: "contract", name: "inference_contract.json", local_path: "/tmp/contract.json" },
      { kind: "sample", name: "id_lora_01.mp4", local_path: "/tmp/id_lora_01.mp4" },
    ],
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function evaluation(status: IdLoraEvaluationRun["status"]): IdLoraEvaluationRun {
  return {
    id: "id-eval-1", project_id: "project-1", runpod_run_id: "runpod-id-lora-1", contract_path: "/vault/contract.json",
    video_paths: {}, status, cases: {},
    summary: { case_count: 0, passed_count: 0, failed_count: 0, blocked_count: 0, average_stability: 0, screening_ready: false, release_ready: false, warnings: [] },
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}
