import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CharacterProject, MediaItem, VideoDatasetSnapshot } from "../lib/types";
import { VideoDatasetCompiler } from "./VideoDatasetCompiler";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("VideoDatasetCompiler", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));

  it("persists a video recipe across Guided and Advanced remounts", async () => {
    const user = userEvent.setup();
    let savedProject = project;
    const updateCharacterProject = vi.fn(async (_id, patch) => { savedProject = { ...savedProject, ...patch }; return savedProject; });
    const engine = {
      assetUrl: (path: string) => path,
      listCharacterProjects: vi.fn(async () => [savedProject]), updateCharacterProject,
      listVideoDatasetCandidates: vi.fn().mockResolvedValue([]), listVideoDatasetSnapshots: vi.fn().mockResolvedValue([]),
      listVaultMedia: vi.fn().mockResolvedValue([]), getCurationHandoff: vi.fn().mockResolvedValue({ items: [] }),
      listTrainingTargets: vi.fn().mockResolvedValue([wanTarget, { ...wanTarget, profile_id: "comfyui_minimax_h3_ref2va", label: "H3 reference" }]),
    } as unknown as ComponentProps<typeof VideoDatasetCompiler>["engine"];
    const view = render(<VideoDatasetCompiler engine={engine} activeProjectId={project.id} guided />);
    const selector = await screen.findByLabelText("Video target");
    await waitFor(() => expect(screen.getByRole("option", { name: "H3 reference" })).toBeInTheDocument());
    await user.selectOptions(selector, "comfyui_minimax_h3_ref2va");
    await waitFor(() => expect(updateCharacterProject).toHaveBeenCalledWith(project.id, expect.objectContaining({ intent: expect.objectContaining({ training_target_profile_ids: expect.objectContaining({ video: "comfyui_minimax_h3_ref2va" }) }) })));
    view.unmount();
    render(<VideoDatasetCompiler engine={engine} activeProjectId={project.id} />);
    await waitFor(() => expect(screen.getByLabelText("Video target")).toHaveValue("comfyui_minimax_h3_ref2va"));
  });

  it("approves, freezes, and exports a reviewed video snapshot", async () => {
    const user = userEvent.setup();
    const draft = snapshot();
    const approved = snapshot({
      items: { clip_record: { ...draft.items.clip_record, status: "approved" } },
      balance: {
        ...draft.balance,
        approved_count: 1,
        review_count: 0,
        recipe_compliance: {
          recipe_id: "wan22_14b_t2v_character",
          recipe_version: 1,
          recipe_label: "WAN 2.2 14B T2V Character Video",
          status: "review",
          score: 0.8,
          blocker_count: 0,
          warning_count: 1,
          checks: [{
            check_id: "approved-clips",
            label: "Approved clips",
            passed: false,
            severity: "warning",
            detail: "Approve at least 8 clips for the WAN baseline.",
            current: 1,
            target: 8,
          }],
        },
      },
    });
    const frozen = snapshot({
      ...approved,
      status: "frozen",
      fingerprint: "a".repeat(64),
      items: { clip_record: { ...approved.items.clip_record, split: "train" } },
      balance: { ...approved.balance, train_count: 1 },
    });
    const exported = snapshot({ ...frozen, status: "exported", export_path: "/tmp/video-dataset" });
    const engine = {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listVideoDatasetCandidates: vi.fn().mockResolvedValue([candidate]),
      listVideoDatasetSnapshots: vi.fn().mockResolvedValue([draft]),
      listVaultMedia: vi.fn().mockResolvedValue([]),
      getCurationHandoff: vi.fn().mockResolvedValue({ items: [], updated_at: "2026-07-12T00:00:00Z" }),
      compileVideoDataset: vi.fn().mockResolvedValue(draft),
      updateVideoDatasetItem: vi.fn().mockResolvedValue(draft),
      bulkUpdateVideoDataset: vi.fn().mockResolvedValue(approved),
      freezeVideoDataset: vi.fn().mockResolvedValue(frozen),
      exportVideoDataset: vi.fn().mockResolvedValue({
        snapshot: exported,
        package: {
          id: "export_video_1",
          export_type: "ai_toolkit_video",
          output_path: "/tmp/video-dataset",
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
      listTrainingTargets: vi.fn().mockResolvedValue([wanTarget]),
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn(),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
    };

    render(<VideoDatasetCompiler engine={engine} />);

    expect(await screen.findByText("Video Dataset Compiler")).toBeInTheDocument();
    expect(screen.getByText("1 accepted clip ready.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve All" }));
    expect(engine.bulkUpdateVideoDataset).toHaveBeenCalledWith("video_snapshot_1", "approved");
    expect(await screen.findByText("Recipe v1 · 80% preflight")).toBeInTheDocument();
    expect(screen.getByText("Approve at least 8 clips for the WAN baseline.")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Freeze" }));
    expect(engine.freezeVideoDataset).toHaveBeenCalledWith("video_snapshot_1");

    await user.type(screen.getByLabelText("Video output folder"), "/tmp/video-dataset");
    await user.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(engine.exportVideoDataset).toHaveBeenCalledWith("video_snapshot_1", "/tmp/video-dataset"));
    expect(screen.getByText("Video export complete: /tmp/video-dataset")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "RunComfy cloud training" })).toBeInTheDocument();
    await user.click(screen.getByText("AI Toolkit YAML"));
    expect((screen.getByLabelText("AI Toolkit YAML") as HTMLTextAreaElement).value).toContain("num_frames: 41");
  });

  it("adds only explicitly selected reviewed H3 image and voice references", async () => {
    const user = userEvent.setup();
    const image = { id: "identity_image", raw_path: "/tmp/identity.png", media_type: "image" as const };
    const audio = { id: "confirmed_voice", raw_path: "/tmp/voice.wav", media_type: "audio" as const };
    const h3Project = {
      ...project,
      intent: {
        ...project.intent,
        requested_outputs: ["video" as const],
        training_target_profile_ids: { video: "comfyui_minimax_h3_ref2va" },
      },
      observations: {
        identity_image: {
          media_item_id: image.id,
          review_status: "accepted" as const,
          decision_source: "user" as const,
          view: "face" as const,
          is_anchor: false,
          quality_score: 1,
          diversity_score: 1,
          face_count: 1,
          face_area: 0.5,
          body_coverage: 0.5,
          aesthetic_score: 1,
          reasons: [],
          warnings: [],
          analyzer: "test",
          updated_at: "2026-07-12T00:00:00Z",
        },
      },
    };
    const compiled = snapshot({
      target_profile_id: "comfyui_minimax_h3_ref2va",
      target_label: "MiniMax H3 Reference-to-Video with Audio",
      reference_image_media_item_ids: [image.id],
      reference_audio_media_item_ids: [audio.id],
    });
    const engine = {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listCharacterProjects: vi.fn().mockResolvedValue([h3Project]),
      listVideoDatasetCandidates: vi.fn().mockResolvedValue([candidate]),
      listVideoDatasetSnapshots: vi.fn().mockResolvedValue([]),
      listVaultMedia: vi.fn().mockResolvedValue([image, audio]),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [{ media_item_id: audio.id, lane: "audio", project_id: h3Project.id, requested_output: "video", review_status: "accepted", speaker_confirmation: "human_override", updated_at: "2026-07-12T00:00:00Z" }],
        updated_at: "2026-07-12T00:00:00Z",
      }),
      listTrainingTargets: vi.fn().mockResolvedValue([{
        ...wanTarget,
        profile_id: "comfyui_minimax_h3_ref2va",
        label: "MiniMax H3 Reference-to-Video with Audio",
        model_family: "minimax_h3_ref2va",
        recipe: { workflow_kind: "inference" },
      }]),
      compileVideoDataset: vi.fn().mockResolvedValue(compiled),
    };

    render(<VideoDatasetCompiler engine={engine as never} />);

    expect(await screen.findByText("MiniMax H3 standalone references")).toBeInTheDocument();
    await user.click(await screen.findByLabelText(`Include image reference ${image.id}`));
    await user.click(await screen.findByLabelText(`Include audio reference ${audio.id}`));
    await user.click(screen.getByRole("button", { name: "Build Draft" }));
    await waitFor(() => expect(engine.compileVideoDataset).toHaveBeenCalledWith(
      h3Project.id,
      [candidate.id],
      "comfyui_minimax_h3_ref2va",
      [image.id],
      [audio.id],
    ));
  });
});

const project: CharacterProject = {
  id: "character_project_1",
  name: "Mary Character",
  intent: {
    target_type: "character",
    subject_name: "Mary",
    trigger_token: "example_person",
    description: "",
    learned_attributes: ["identity"],
    controllable_attributes: ["motion"],
    excluded_attributes: ["background"],
  },
  candidate_media_item_ids: [],
  observations: {},
  crop_recipes: {},
  health: {
    candidate_count: 0,
    accepted_count: 0,
    review_count: 0,
    rejected_count: 0,
    anchor_count: 0,
    effective_observation_count: 0,
    source_count: 0,
    largest_source_share: 0,
    average_quality: 0,
    average_diversity: 0,
    view_counts: {},
    analyzer: "test",
    warnings: [],
  },
  created_at: "2026-07-12T00:00:00Z",
  updated_at: "2026-07-12T00:00:00Z",
};

const candidate: MediaItem = {
  id: "video_clip_1",
  source_id: "instagram_source",
  raw_path: "/tmp/video.mp4",
  media_type: "video",
  duration: 8,
  width: 720,
  height: 1280,
};

function snapshot(overrides: Partial<VideoDatasetSnapshot> = {}): VideoDatasetSnapshot {
  return {
    id: "video_snapshot_1",
    project_id: project.id,
    project_name: project.name,
    version: 1,
    status: "draft",
    trigger_token: "example_person",
    target_profile_id: "runcomfy_wan22_14b_t2v_character",
    target_label: "WAN 2.2 14B T2V Character Video",
    items: {
      clip_record: {
        id: "clip_record",
        media_item_id: candidate.id,
        source_media_item_id: "source_video_1",
        caption: "example_person, person in motion",
        status: "needs_review",
        split: "unassigned",
        duration_seconds: 8,
        width: 720,
        height: 1280,
        fps: 30,
        quality_score: 0.84,
        identity_score: 0.92,
        stability_score: 0.78,
        motion_score: 0.71,
        created_at: "2026-07-12T00:00:00Z",
        updated_at: "2026-07-12T00:00:00Z",
      },
    },
    balance: {
      total_count: 1,
      approved_count: 0,
      review_count: 1,
      excluded_count: 0,
      source_count: 0,
      total_duration_seconds: 0,
      train_count: 0,
      validation_count: 0,
      average_quality: 0,
      average_identity: 0,
      warnings: [],
    },
    fingerprint: null,
    export_path: null,
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:00:00Z",
    frozen_at: null,
    ...overrides,
  };
}

const wanTarget = {
  profile_id: "runcomfy_wan22_14b_t2v_character",
  label: "WAN 2.2 14B T2V Character Video",
  provider: "runcomfy",
  trainer: "ai_toolkit",
  modality: "video" as const,
  model_family: "wan22_14b_t2v",
  base_model: "ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
  compiler_version: "video-pairs-v1",
  resolution_buckets: [480],
  caption_format: "paired_txt",
  output_format: "safetensors_lora",
  description: "WAN video target",
  ready: true,
  config_template: "folder_path: /app/ai-toolkit/datasets/{dataset_name}\nnum_frames: 41\narch: wan22_14b\nname: {job_name}\nprompt: {sample_prompt}",
  warnings: [],
};
