import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CharacterProject, IdLoraManifest, MediaItem } from "../lib/types";
import { IdLoraCompiler } from "./IdLoraCompiler";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("IdLoraCompiler", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));

  it("exports a ready synchronized AV contract with the pinned zero-shot RunPod target", async () => {
    const user = userEvent.setup();
    const manifest = readyManifest();
    const engine = {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listVaultMedia: vi.fn().mockResolvedValue([video]),
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listIdLoraManifests: vi.fn().mockResolvedValue([manifest]),
      compileIdLoraManifest: vi.fn().mockResolvedValue(manifest),
      exportIdLoraManifest: vi.fn().mockResolvedValue({
        manifest: { ...manifest, export_path: "/tmp/id-lora" },
        package: {
          id: "export-id-lora",
          export_type: "id_lora_av",
          output_path: "/tmp/id-lora",
          source_segment_ids: [],
          status: "complete",
        },
      }),
      createRunPodBundle: vi.fn(),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      listRunPodModelBootstrapRuns: vi.fn().mockResolvedValue([]),
      getRunPodModelBootstrapRun: vi.fn(),
      createRunPodModelBootstrapRun: vi.fn(),
      refreshRunPodModelBootstrapRun: vi.fn(),
      cancelRunPodModelBootstrapRun: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([]),
      createRunPodPreflightReport: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
      listIdLoraEvaluations: vi.fn().mockResolvedValue([]),
      getIdLoraEvaluation: vi.fn(),
      createIdLoraEvaluation: vi.fn(),
      getSyncNetCapability: vi.fn().mockResolvedValue({ configured: false, ready: false, mode: "unconfigured", problems: ["setup required"], setup: [] }),
    };
    render(<IdLoraCompiler engine={engine} />);

    expect(await screen.findByText("ID-LoRA LTX-2.3 Zero-Shot Character")).toBeInTheDocument();
    expect(screen.getByText("Inference recipe v1 · 100% preflight")).toBeInTheDocument();
    expect(screen.getAllByText("Synced AV")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Start Training" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("ID-LoRA output folder"), "/tmp/id-lora");
    await user.click(screen.getByRole("button", { name: "Export Package" }));

    await waitFor(() => expect(engine.exportIdLoraManifest).toHaveBeenCalledWith("id-lora-1", "/tmp/id-lora"));
    expect(screen.getByText("ID-LoRA package exported: /tmp/id-lora")).toBeInTheDocument();
    expect(screen.getByText("ID-LoRA LTX-2.3 · zero-shot HQ")).toBeInTheDocument();
  });
});

const project = {
  id: "project-1",
  name: "Character",
  intent: { target_type: "character", subject_name: "Person", trigger_token: "person_token", description: "", learned_attributes: [], controllable_attributes: [], excluded_attributes: [] },
  candidate_media_item_ids: [], observations: {}, crop_recipes: {},
  health: { candidate_count: 0, accepted_count: 0, review_count: 0, rejected_count: 0, anchor_count: 0, effective_observation_count: 0, source_count: 0, largest_source_share: 0, average_quality: 0, average_diversity: 0, view_counts: {}, analyzer: "test", warnings: [] },
  created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
} as CharacterProject;

const video: MediaItem = { id: "video-1", source_id: "source-1", raw_path: "/tmp/video.mp4", media_type: "video", duration: 4 };

function readyManifest(): IdLoraManifest {
  return {
    id: "id-lora-1", project_id: project.id, video_snapshot_id: "video-snapshot-1", video_fingerprint: "video-fingerprint",
    target_profile_id: "runpod_id_lora_ltx23_inference", target_label: "ID-LoRA LTX-2.3 Zero-Shot", workflow_kind: "inference", status: "ready",
    examples: {
      example1: {
        id: "example1", video_dataset_item_id: "video-record-1", video_media_item_id: video.id, video_source_media_item_id: "source-1",
        video_start_seconds: 0, video_end_seconds: 4, visual_caption: "person in motion", voice_segment_id: "voice-1", audio_media_item_id: "audio-1",
        audio_source_media_item_id: "source-1", audio_start_seconds: 1, audio_end_seconds: 3, transcript: "Hello.",
        multimodal_caption: "[VISUAL] person in motion [SPEECH] Hello. [SOUNDS] unverified", pairing_kind: "synchronized_av", split: "train",
        identity_score: 0.9, speaker_similarity: 0.92, warnings: [],
      },
    },
    voice_references: {
      voice1: { voice_segment_id: "voice-1", audio_media_item_id: "audio-1", audio_source_media_item_id: "source-1", transcript: "Hello.", split: "train", speaker_similarity: 0.92, quality_score: 0.86 },
    },
    balance: {
      visual_example_count: 1, synchronized_pair_count: 1, visual_only_count: 0, voice_reference_count: 1, train_count: 1, validation_count: 1, source_count: 2, warnings: [],
      recipe_compliance: {
        recipe_id: "id_lora_ltx23_zero_shot_character", recipe_version: 1, recipe_label: "ID-LoRA LTX-2.3 Zero-Shot Character",
        status: "ready", score: 1, blocker_count: 0, warning_count: 0,
        checks: [{ check_id: "workflow-kind", label: "Workflow kind", passed: true, severity: "blocker", detail: "Inference recipe.", current: "inference", target: "inference" }],
      },
    },
    fingerprint: "id-fingerprint", export_path: null, created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}
