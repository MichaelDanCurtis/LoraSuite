import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkGenerationRun, CharacterProject, ImageBenchmarkCaseDefinition, ImageBenchmarkRun, ModelArtifactRecord } from "../lib/types";
import { ImageEvaluationHarness } from "./ImageEvaluationHarness";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("ImageEvaluationHarness", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));

  it("queues twelve matched images through RunPod without retaining credentials", async () => {
    const user = userEvent.setup();
    const generated = generationRun();
    const engine = makeEngine({ createRunPodImageBenchmarkGenerationRun: vi.fn().mockResolvedValue(generated) });
    render(<ImageEvaluationHarness engine={engine} activeProjectId={project.id} />);

    await user.click(await screen.findByRole("button", { name: "RunPod" }));
    await user.type(screen.getByLabelText("Image evaluation workspace folder"), "/tmp/image-evaluation");
    await user.type(screen.getByLabelText("RunPod image benchmark endpoint ID"), "endpoint-image-1");
    await user.clear(screen.getByLabelText("RunPod image LoRA asset"));
    await user.type(screen.getByLabelText("RunPod image LoRA asset"), "https://assets.test/person.safetensors");
    await user.type(screen.getByLabelText("RunPod image benchmark API token"), "runpod-secret");
    await user.click(screen.getByRole("button", { name: "Generate Suite" }));

    await waitFor(() => expect(engine.createRunPodImageBenchmarkGenerationRun).toHaveBeenCalledWith({
      project_id: project.id,
      workspace_root: "/tmp/image-evaluation",
      endpoint_id: "endpoint-image-1",
      lora_path: "https://assets.test/person.safetensors",
      artifact_id: artifact.id,
      baseline_payload: { input: { prompt: "$PROMPT", seed: "$SEED" } },
      lora_payload: { input: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } } },
      seed_base: 424242,
      auto_evaluate: true,
      api_token: "runpod-secret",
    }));
    expect(screen.getByLabelText("RunPod image benchmark API token")).toHaveValue("");
  });

  it("shows baseline and LoRA evidence for a completed release gate", async () => {
    const engine = makeEngine({ listImageBenchmarkRuns: vi.fn().mockResolvedValue([completedRun()]) });
    render(<ImageEvaluationHarness engine={engine} activeProjectId={project.id} />);

    expect(await screen.findByText("Image LoRA Release Ready")).toBeInTheDocument();
    expect(screen.getByAltText("Neutral close-up baseline")).toHaveAttribute("src", "asset:///tmp/base/neutral_closeup.png");
    expect(screen.getByAltText("Neutral close-up LoRA")).toHaveAttribute("src", "asset:///tmp/lora/neutral_closeup.png");
    expect(screen.getByText("Identity").nextSibling).toHaveTextContent("76%");
  });
});

function makeEngine(overrides: Record<string, unknown> = {}) {
  return {
    assetUrl: (path: string) => `asset://${path}`,
    listCharacterProjects: vi.fn().mockResolvedValue([project]),
    listModelArtifacts: vi.fn().mockResolvedValue([artifact]),
    getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
    getImageBenchmarkSuite: vi.fn().mockResolvedValue(suite),
    prepareImageBenchmarkWorkspace: vi.fn(),
    listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
    getBenchmarkGenerationRun: vi.fn(),
    retryBenchmarkGenerationRun: vi.fn(),
    createImageBenchmarkGenerationRun: vi.fn(),
    createRunPodImageBenchmarkGenerationRun: vi.fn(),
    listImageBenchmarkRuns: vi.fn().mockResolvedValue([]),
    getImageBenchmarkRun: vi.fn(),
    createImageBenchmarkRun: vi.fn(),
    ...overrides,
  };
}

const project = {
  id: "project-1", name: "Character",
  intent: { target_type: "character", subject_name: "Person", trigger_token: "person_token", description: "", learned_attributes: [], controllable_attributes: [], excluded_attributes: [] },
  candidate_media_item_ids: [], observations: {}, crop_recipes: {},
  health: { candidate_count: 0, accepted_count: 0, review_count: 0, rejected_count: 0, anchor_count: 0, effective_observation_count: 0, source_count: 0, largest_source_share: 0, average_quality: 0, average_diversity: 0, view_counts: {}, analyzer: "test", warnings: [] },
  created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
} as CharacterProject;

const artifact = {
  id: "artifact-1", project_id: project.id, training_run_id: "run-1", snapshot_id: "snapshot-1", dataset_fingerprint: "fingerprint",
  checkpoint_name: "person.safetensors", checkpoint_path: "/tmp/person.safetensors", checkpoint_sha256: "abc", checkpoint_size_bytes: 100,
  sample_paths: [], trigger_token: "person_token", modality: "image", model_family: "flux1",
  evaluation: { status: "ready", checkpoint_valid: true, provenance_valid: true, config_present: true, sample_count: 0, tensor_count: 1, parameter_count: 1, warnings: [], evaluated_at: "2026-07-12T00:00:00Z" },
  acceptance: { status: "not_evaluated", screening_ready: false, release_ready: false, passed_count: 0, failed_count: 0, blocked_count: 0, warnings: [] },
  installed_paths: [], workflow_paths: [], created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
} as ModelArtifactRecord;

const suite: ImageBenchmarkCaseDefinition[] = [{ id: "neutral_closeup", label: "Neutral close-up", filename: "neutral_closeup.png", prompt: "{trigger}, neutral portrait", composition: "face" }];

function generationRun(): BenchmarkGenerationRun {
  return { id: "generation-1", provider: "runpod_serverless", benchmark_kind: "image", endpoint_id: "endpoint-image-1", project_id: project.id, model_id: "endpoint-image-1", lora_path: "person.safetensors", workspace_root: "/tmp/image-evaluation", baseline_dir: "/tmp/image-evaluation/baseline", lora_dir: "/tmp/image-evaluation/lora", baseline_payload: {}, lora_payload: {}, seed_base: 424242, auto_evaluate: true, status: "running", progress_current: 0, progress_total: 12, progress_message: "Generating matched images", items: [], created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z" };
}

function completedRun(): ImageBenchmarkRun {
  const metrics = { visual_quality: 0.8, aesthetic_score: 0.7, subject_coverage: 0.8, face_count: 1, face_area: 0.1, body_coverage: 0.3, pose_coverage: 0.6, identity_similarity: 0.76, analyzer_notes: [] };
  return { id: "image-benchmark-1", project_id: project.id, artifact_id: artifact.id, baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", status: "complete", cases: { neutral_closeup: { definition: suite[0], baseline_path: "/tmp/base/neutral_closeup.png", lora_path: "/tmp/lora/neutral_closeup.png", baseline: { ...metrics, identity_similarity: 0.3 }, lora: metrics, passed: true, blocked: false, checks: { identity_similarity: true }, reasons: [] } }, summary: { passed_count: 1, failed_count: 0, blocked_count: 0, identity_gain: 0.46, average_lora_identity: 0.76, average_visual_quality: 0.8, average_subject_coverage: 0.8, screening_ready: true, release_ready: true, warnings: [] }, created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z" };
}
