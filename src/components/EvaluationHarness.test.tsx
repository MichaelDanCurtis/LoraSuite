import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkCaseDefinition, BenchmarkGenerationRun, BenchmarkRun, BenchmarkWorkspace, CharacterProject, ModelArtifactRecord } from "../lib/types";
import { EvaluationHarness } from "./EvaluationHarness";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("EvaluationHarness", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));

  it("shows the fixed file contract and queues a background comparison", async () => {
    const user = userEvent.setup();
    const queued = run("queued");
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ backend: "opencv-sface", model_version: "test", installed: true, ready: true, download_size_bytes: 0, message: "ready" }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ backend: "speaker", model_version: "test", installed: false, ready: false, download_size_bytes: 0, message: "needed" }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn().mockResolvedValue(queued),
      createBenchmarkRun: vi.fn().mockResolvedValue(queued),
      reviewBenchmarkCase: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${path}`),
    };
    render(<EvaluationHarness engine={engine} />);

    expect(await screen.findByText("identity_closeup.mp4")).toBeInTheDocument();
    expect(screen.getByText("Face ready")).toBeInTheDocument();
    expect(screen.getByText("Voice needed")).toBeInTheDocument();
    expect(screen.getByText("person_token, close-up portrait")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Baseline video folder"), "/tmp/base");
    await user.type(screen.getByLabelText("LoRA video folder"), "/tmp/lora");
    await user.click(screen.getByRole("button", { name: "Run Evaluation" }));

    await waitFor(() => expect(engine.createBenchmarkRun).toHaveBeenCalledWith({
      project_id: project.id,
      baseline_dir: "/tmp/base",
      lora_dir: "/tmp/lora",
      artifact_id: undefined,
    }));
    expect(screen.getByText("Scoring generated videos...")).toBeInTheDocument();
  });

  it("prepares matched baseline and LoRA folders before generation", async () => {
    const user = userEvent.setup();
    const workspace: BenchmarkWorkspace = {
      project_id: project.id,
      root: "/tmp/evaluation",
      baseline_dir: "/tmp/evaluation/baseline",
      lora_dir: "/tmp/evaluation/lora",
      contract_path: "/tmp/evaluation/evaluation_contract.json",
      cases: suite,
    };
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ backend: "opencv-sface", model_version: "test", installed: true, ready: true, download_size_bytes: 0, message: "ready" }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ backend: "speaker", model_version: "test", installed: true, ready: true, download_size_bytes: 0, message: "ready" }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn().mockResolvedValue(workspace),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${path}`),
    };
    render(<EvaluationHarness engine={engine} />);

    await user.type(await screen.findByLabelText("Evaluation workspace folder"), "/tmp/evaluation");
    await user.click(screen.getByRole("button", { name: "Prepare Folders" }));

    await waitFor(() => expect(engine.prepareBenchmarkWorkspace).toHaveBeenCalledWith(project.id, "/tmp/evaluation"));
    expect(screen.getByLabelText("Baseline video folder")).toHaveValue("/tmp/evaluation/baseline");
    expect(screen.getByLabelText("LoRA video folder")).toHaveValue("/tmp/evaluation/lora");
    expect(screen.getByText(/evaluation_contract\.json/)).toBeInTheDocument();
  });

  it("queues the full matched RunComfy generation suite without retaining the token", async () => {
    const user = userEvent.setup();
    const generated = generationRun();
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn().mockResolvedValue(generated),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${path}`),
    };
    render(<EvaluationHarness engine={engine} />);

    await user.type(await screen.findByLabelText("Evaluation workspace folder"), "/tmp/evaluation");
    await user.type(screen.getByLabelText("RunComfy video model ID"), "provider/video-model");
    await user.type(screen.getByLabelText("RunComfy LoRA asset"), "person.safetensors");
    await user.type(screen.getByLabelText("RunComfy benchmark API token"), "session-secret");
    await user.click(screen.getByRole("button", { name: "Generate Suite" }));

    await waitFor(() => expect(engine.createBenchmarkGenerationRun).toHaveBeenCalledWith({
      project_id: project.id,
      workspace_root: "/tmp/evaluation",
      model_id: "provider/video-model",
      lora_path: "person.safetensors",
      artifact_id: undefined,
      baseline_payload: { prompt: "$PROMPT", seed: "$SEED" },
      lora_payload: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } },
      seed_base: 424242,
      auto_evaluate: true,
      api_token: "session-secret",
    }));
    expect(screen.getByLabelText("RunComfy benchmark API token")).toHaveValue("");
    expect(screen.getByText("Generating matched clips")).toBeInTheDocument();
  });

  it("queues the matched suite through RunPod with its nested input contract", async () => {
    const user = userEvent.setup();
    const generated = { ...generationRun(), provider: "runpod_serverless", endpoint_id: "endpoint-video-1", model_id: "endpoint-video-1" };
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn().mockResolvedValue(generated),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${path}`),
    };
    render(<EvaluationHarness engine={engine} />);

    await user.click(await screen.findByRole("button", { name: "RunPod" }));
    await user.type(screen.getByLabelText("Evaluation workspace folder"), "/tmp/evaluation");
    await user.type(screen.getByLabelText("RunPod benchmark endpoint ID"), "endpoint-video-1");
    await user.type(screen.getByLabelText("RunPod LoRA asset"), "https://assets.test/person.safetensors");
    await user.type(screen.getByLabelText("RunPod benchmark API token"), "runpod-secret");
    await user.click(screen.getByRole("button", { name: "Generate Suite" }));

    await waitFor(() => expect(engine.createRunPodBenchmarkGenerationRun).toHaveBeenCalledWith({
      project_id: project.id,
      workspace_root: "/tmp/evaluation",
      endpoint_id: "endpoint-video-1",
      lora_path: "https://assets.test/person.safetensors",
      artifact_id: undefined,
      baseline_payload: { input: { prompt: "$PROMPT", seed: "$SEED" } },
      lora_payload: { input: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } } },
      seed_base: 424242,
      auto_evaluate: true,
      api_token: "runpod-secret",
    }));
    expect(screen.getByLabelText("RunPod benchmark API token")).toHaveValue("");
  });

  it("offers only artifacts for the active character and shows durable acceptance", async () => {
    const otherProject = { ...project, id: "project-2", name: "Other Character" };
    const ownArtifact = artifact("artifact-1", project.id, "person.safetensors", "certified");
    const otherArtifact = artifact("artifact-2", otherProject.id, "other.safetensors", "not_evaluated");
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project, otherProject]),
      listModelArtifacts: vi.fn().mockResolvedValue([ownArtifact, otherArtifact]),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${path}`),
    };

    render(<EvaluationHarness engine={engine} activeProjectId={project.id} />);

    const select = await screen.findByLabelText("Evaluation model artifact");
    expect(select).toHaveTextContent("person.safetensors · certified");
    expect(select).not.toHaveTextContent("other.safetensors");
    expect(await screen.findByText("Release certified")).toBeInTheDocument();
  });

  it("plays the durable baseline pair and records human review", async () => {
    const user = userEvent.setup();
    const completed = reviewedRun();
    const accepted = {
      ...completed,
      cases: { identity_closeup: { ...completed.cases.identity_closeup, review_decision: "accepted" as const, review_note: "Identity stays stable" } },
      summary: { ...completed.summary, human_review_ready: true, release_ready: true, review_pending_count: 0, review_accepted_count: 1 },
    };
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady),
      getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([completed]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn().mockResolvedValue(accepted),
      assetUrl: vi.fn((path: string) => `http://engine/assets?path=${encodeURIComponent(path)}`),
    };
    render(<EvaluationHarness engine={engine} activeProjectId={project.id} />);

    expect(await screen.findByText("Human Review Required")).toBeInTheDocument();
    expect(screen.getByLabelText("Close-up identity baseline video")).toHaveAttribute("src", expect.stringContaining("baseline.mp4"));
    await user.type(screen.getByLabelText("Human review note"), "Identity stays stable");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => expect(engine.reviewBenchmarkCase).toHaveBeenCalledWith("benchmark-review", "identity_closeup", "accepted", "Identity stays stable"));
    expect(await screen.findByText("Certified Release Ready")).toBeInTheDocument();
  });

  it("regenerates only the active matched case from a linked cloud run", async () => {
    const user = userEvent.setup();
    const completed = reviewedRun();
    const source = { ...generationRun(), status: "completed" as const, benchmark_run_id: completed.id, progress_current: 8 };
    const retry = { ...source, id: "generation-retry", parent_run_id: source.id, case_ids: ["identity_closeup"], status: "queued" as const, progress_current: 6 };
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]), listModelArtifacts: vi.fn().mockResolvedValue([]),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: true }), getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: true }),
      getSyncNetCapability: vi.fn().mockResolvedValue(syncNetReady), getBenchmarkSuite: vi.fn().mockResolvedValue(suite),
      prepareBenchmarkWorkspace: vi.fn(), listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([source]),
      getBenchmarkGenerationRun: vi.fn(), retryBenchmarkGenerationRun: vi.fn().mockResolvedValue(retry),
      createBenchmarkGenerationRun: vi.fn(), createRunPodBenchmarkGenerationRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([completed]), getBenchmarkRun: vi.fn(), createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(), assetUrl: vi.fn((path: string) => `http://engine/assets?path=${encodeURIComponent(path)}`),
    };
    render(<EvaluationHarness engine={engine} activeProjectId={project.id} />);

    await user.click(await screen.findByRole("button", { name: "Regenerate Pair" }));

    await waitFor(() => expect(engine.retryBenchmarkGenerationRun).toHaveBeenCalledWith(source.id, ["identity_closeup"], undefined));
    expect(screen.getByText("Targeted regeneration is running. The other benchmark outputs were reused.")).toBeInTheDocument();
  });
});

const suite: BenchmarkCaseDefinition[] = [{
  id: "identity_closeup",
  label: "Close-up identity",
  filename: "identity_closeup.mp4",
  prompt: "{trigger}, close-up portrait",
  audio_required: false,
}];

const syncNetReady = { configured: true, ready: true, mode: "canonical" as const, problems: [], setup: [] };

const project = {
  id: "project-1", name: "Character",
  intent: { target_type: "character", subject_name: "Person", trigger_token: "person_token", description: "", learned_attributes: [], controllable_attributes: [], excluded_attributes: [] },
  candidate_media_item_ids: [], observations: {}, crop_recipes: {},
  health: { candidate_count: 0, accepted_count: 0, review_count: 0, rejected_count: 0, anchor_count: 0, effective_observation_count: 0, source_count: 0, largest_source_share: 0, average_quality: 0, average_diversity: 0, view_counts: {}, analyzer: "test", warnings: [] },
  created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
} as CharacterProject;

function run(status: BenchmarkRun["status"]): BenchmarkRun {
  return {
    id: "benchmark-1", project_id: project.id, baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", status, cases: {},
    summary: { passed_count: 0, failed_count: 0, blocked_count: 0, average_lora_stability: 0, average_lora_motion: 0, screening_ready: false, automated_release_ready: false, human_review_ready: false, release_ready: false, review_pending_count: 0, review_accepted_count: 0, review_rejected_count: 0, validation_level: "screening", warnings: [] },
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function reviewedRun(): BenchmarkRun {
  const metrics = { visual_quality: 0.8, temporal_stability: 0.76, motion_score: 0.24, subject_coverage: 0.82, identity_similarity: 0.78, identity_frame_coverage: 0.9, duration_seconds: 4, analyzer_notes: [] };
  return {
    ...run("complete"),
    id: "benchmark-review",
    cases: {
      identity_closeup: {
        definition: suite[0], baseline_path: "/vault/benchmark_inputs/baseline.mp4", lora_path: "/vault/benchmark_inputs/lora.mp4",
        baseline: { ...metrics, identity_similarity: 0.42 }, lora: metrics, passed: true, blocked: false,
        checks: { identity_similarity: true }, certified_checks: { syncnet_lse_c: true }, reasons: [], review_decision: "pending", review_note: "",
      },
    },
    summary: { passed_count: 1, failed_count: 0, blocked_count: 0, average_lora_stability: 0.76, average_lora_motion: 0.24, screening_ready: true, automated_release_ready: true, human_review_ready: false, release_ready: false, review_pending_count: 1, review_accepted_count: 0, review_rejected_count: 0, validation_level: "screening", warnings: ["Human review pending"] },
  };
}

function generationRun(): BenchmarkGenerationRun {
  return {
    id: "generation-1", provider: "runcomfy_model_api", project_id: project.id,
    model_id: "provider/video-model", lora_path: "person.safetensors", workspace_root: "/tmp/evaluation",
    baseline_dir: "/tmp/evaluation/baseline", lora_dir: "/tmp/evaluation/lora",
    baseline_payload: {}, lora_payload: {}, seed_base: 424242, auto_evaluate: true, status: "running",
    progress_current: 0, progress_total: 8, progress_message: "Generating matched clips", items: [],
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function artifact(id: string, projectId: string, checkpointName: string, status: NonNullable<ModelArtifactRecord["acceptance"]>["status"]): ModelArtifactRecord {
  return {
    id,
    project_id: projectId,
    training_run_id: `training-${id}`,
    snapshot_id: `snapshot-${id}`,
    dataset_fingerprint: `fingerprint-${id}`,
    checkpoint_name: checkpointName,
    checkpoint_path: `/tmp/${checkpointName}`,
    checkpoint_sha256: "abc123",
    checkpoint_size_bytes: 1024,
    sample_paths: [],
    trigger_token: "person_token",
    modality: "video",
    model_family: "wan22_14b_t2v",
    evaluation: { status: "ready", checkpoint_valid: true, provenance_valid: true, config_present: true, sample_count: 0, tensor_count: 1, parameter_count: 1, warnings: [], evaluated_at: "2026-07-12T00:00:00Z" },
    acceptance: { status, screening_ready: status === "screening_passed" || status === "certified", release_ready: status === "certified", passed_count: status === "certified" ? 4 : 0, failed_count: 0, blocked_count: 0, warnings: [] },
    installed_paths: [],
    workflow_paths: [],
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:00:00Z",
  };
}
