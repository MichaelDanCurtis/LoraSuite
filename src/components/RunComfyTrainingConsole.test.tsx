import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ComfyRuntimeStatus, DatasetSnapshot, ModelArtifactRecord, ProviderSmokeRun, TrainingCostEstimate, TrainingRun, TrainingTargetProfile } from "../lib/types";
import { RunComfyTrainingConsole } from "./RunComfyTrainingConsole";

describe("RunComfyTrainingConsole", () => {
  it("submits session-only credentials and shows the persisted run", async () => {
    const user = userEvent.setup();
    const run = trainingRun();
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn().mockResolvedValue(run),
      createTrainingRun: vi.fn().mockResolvedValue(run),
      refreshTrainingRun: vi.fn().mockResolvedValue(run),
      resumeTrainingRun: vi.fn().mockResolvedValue(run),
      cancelTrainingRun: vi.fn().mockResolvedValue({ ...run, status: "canceled" }),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn().mockResolvedValue([]),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
    };
    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    expect(screen.getByLabelText("Connect RunComfy")).toHaveTextContent("API token needed");
    expect(screen.getByRole("button", { name: "Save RunComfy token" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("RunComfy API token"), "secret-token");
    await user.click(screen.getByText("AI Toolkit YAML"));
    fireEvent.change(screen.getByLabelText("AI Toolkit YAML"), {
      target: { value: "folder_path: /app/ai-toolkit/datasets/{dataset_name}" },
    });
    await user.click(screen.getByRole("button", { name: "Start Training" }));

    await waitFor(() => expect(engine.createTrainingRun).toHaveBeenCalledWith({
      snapshot_id: "snapshot-1",
      config_file: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
      gpu_type: "ADA_80_PLUS",
      api_token: "secret-token",
    }));
    expect(screen.getByLabelText("RunComfy API token")).toHaveValue("");
    expect(screen.getByText("Training queued")).toBeInTheDocument();
  });

  it("registers a completed checkpoint and installs it into a discovered ComfyUI root", async () => {
    const user = userEvent.setup();
    const completed = { ...trainingRun(), status: "completed" as const, artifact_dir: "/vault/artifacts" };
    const artifact = modelArtifact();
    const installed = {
      ...artifact,
      installed_paths: ["/tmp/ComfyUI/models/loras/person.safetensors"],
      workflow_paths: ["/tmp/ComfyUI/user/default/workflows/LoraSuite/person-flux-evaluation.json"],
      handoff_paths: ["/tmp/ComfyUI/models/loras/person.safetensors.lorasuite-handoff.json"],
      comfy_installations: [{
        root: "/tmp/ComfyUI",
        checkpoint_path: "/tmp/ComfyUI/models/loras/person.safetensors",
        handoff_path: "/tmp/ComfyUI/models/loras/person.safetensors.lorasuite-handoff.json",
        extension_path: "/tmp/ComfyUI/custom_nodes/LoraSuite",
        extension_version: "0.1.0",
        compatibility_status: "ready" as const,
        workflow_paths: ["/tmp/ComfyUI/user/default/workflows/LoraSuite/person-flux-evaluation.json"],
        runnable_workflow_count: 1,
        installed_at: "2026-07-16T00:00:00Z",
      }],
    };
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([completed]),
      getTrainingRun: vi.fn().mockResolvedValue(completed),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn().mockResolvedValue([artifact]),
      listComfyInstallations: vi.fn().mockResolvedValue([{ root: "/tmp/ComfyUI", label: "ComfyUI", models_path: "/tmp/ComfyUI/models", workflows_path: "/tmp/ComfyUI/user/default/workflows" }]),
      getComfyRuntimeStatus: vi.fn().mockResolvedValue(comfyRuntime({ restart_required: true })),
      installModelArtifact: vi.fn().mockResolvedValue(installed),
      listComfyEvaluationReports: vi.fn().mockResolvedValue([{
        id: "report-1",
        artifact_id: "artifact-1",
        project_id: "project-1",
        checkpoint_sha256: "1234567890abcdef",
        workflow_id: "workflow-1",
        verdict: "pass",
        rating: 5,
        prompt: "person_token, portrait",
        output_paths: [],
        notes: "",
        metrics: {},
        created_at: "2026-07-16T00:00:00Z",
      }]),
    };
    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    const validate = await screen.findByTitle("Validate and register artifacts");
    await user.click(validate);
    expect(await screen.findByRole("region", { name: "Model artifact registry" })).toHaveTextContent("person.safetensors");
    expect(screen.getByText(/revision of artifact-v1/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Install" }));

    expect(engine.installModelArtifact).toHaveBeenCalledWith("artifact-1", "/tmp/ComfyUI");
    expect(await screen.findByText("Installed: /tmp/ComfyUI/models/loras/person.safetensors")).toBeInTheDocument();
    expect(screen.getByText(/ready · 1 runnable · 1 report/)).toBeInTheDocument();
    expect(screen.getByText("Restart required")).toBeInTheDocument();
    expect(screen.getByText(/Restart ComfyUI to load 4 LoraSuite nodes/)).toBeInTheDocument();
  });

  it("shows automatically exported checkpoint samples while training is running", async () => {
    const running = {
      ...trainingRun(),
      status: "running" as const,
      progress_current: 500,
      progress_total: 2000,
      progress_percent: 25,
      progress_message: "Training on RunComfy · 2 preview artifacts exported",
      artifact_dir: "/vault/training_artifacts/training-run-1",
      artifacts: [
        {
          kind: "checkpoint",
          name: "person_00000500.safetensors",
          remote_url: "https://example.test/person_00000500.safetensors",
          local_path: "/vault/training_artifacts/training-run-1/checkpoint/person_00000500.safetensors",
          step: 500,
        },
        {
          kind: "sample",
          name: "person_00000500.png",
          remote_url: "https://example.test/person_00000500.png",
          local_path: "/vault/training_artifacts/training-run-1/sample/person_00000500.png",
          step: 500,
          prompt: "person_token portrait",
          sample_index: 0,
        },
      ],
    };
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([running]),
      getTrainingRun: vi.fn().mockResolvedValue(running),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
      assetUrl: vi.fn((path: string) => `/assets/file?path=${encodeURIComponent(path)}`),
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    const previews = await screen.findByRole("region", { name: "Live training previews for training-run-1" });
    expect(previews).toHaveTextContent("Latest step 500 · 1 checkpoint");
    expect(previews).toHaveTextContent("Step 500");
    expect(screen.getByAltText("Training sample at step 500")).toHaveAttribute(
      "src",
      expect.stringContaining("/assets/file?path="),
    );
  });

  it("distinguishes loaded ComfyUI nodes from an installed node pack awaiting restart", async () => {
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn(),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([modelArtifact()]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([{ root: "/tmp/ComfyUI", label: "ComfyUI", models_path: "/tmp/ComfyUI/models", workflows_path: "/tmp/ComfyUI/user/default/workflows" }]),
      getComfyRuntimeStatus: vi.fn().mockResolvedValue(comfyRuntime()),
      installModelArtifact: vi.fn(),
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    expect(await screen.findByText("Nodes loaded")).toBeInTheDocument();
    expect(engine.getComfyRuntimeStatus).toHaveBeenCalledWith("/tmp/ComfyUI");
  });

  it("ignores stale provider evidence and unlocks training only for the exact dataset and config", async () => {
    const user = userEvent.setup();
    const profile = trainingTarget();
    const exactConfig = profile.config_template;
    const stale = smokeRun({ source_fingerprint: "old-fingerprint", config_file: exactConfig });
    const current = smokeRun({ source_fingerprint: "abc123", config_file: exactConfig, ready: true });
    const engine = {
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
      listProviderSmokeRuns: vi.fn().mockResolvedValue([stale]),
      createRunComfyProviderSmokeRun: vi.fn().mockResolvedValue(current),
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} targetProfile={profile} />);

    await waitFor(() => expect(engine.listProviderSmokeRuns).toHaveBeenCalled());
    expect(screen.queryByText("Provider contract failed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Training" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Smoke Test" }));
    expect(await screen.findByText("Provider contract passed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Training" })).toBeEnabled();
  });

  it("resumes a stopped run from its existing RunComfy checkpoint", async () => {
    const user = userEvent.setup();
    const stopped = {
      ...trainingRun(),
      status: "stopped" as const,
      provider_job_id: "job-1",
      progress_current: 250,
      progress_total: 1000,
      progress_percent: 25,
      progress_message: "Training stopped at 250 of 1000 steps; resume from the latest RunComfy checkpoint",
    };
    const resumed = { ...stopped, status: "in_queue" as const, progress_message: "Training resumed; waiting for RunComfy GPU" };
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([stopped]),
      getTrainingRun: vi.fn().mockResolvedValue(resumed),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn().mockResolvedValue(resumed),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    const resume = await screen.findByTitle("Resume training from checkpoint");
    await user.type(screen.getByLabelText("RunComfy API token"), "resume-secret");
    await user.click(resume);

    expect(engine.resumeTrainingRun).toHaveBeenCalledWith(stopped.id, "resume-secret");
    expect(screen.getByLabelText("RunComfy API token")).toHaveValue("");
    expect(await screen.findByText("Training resumed; waiting for RunComfy GPU")).toBeInTheDocument();
  });

  it("retries a failed run from its persisted upload state", async () => {
    const user = userEvent.setup();
    const failed = {
      ...trainingRun(),
      status: "failed" as const,
      provider_job_id: null,
      progress_current: 1,
      progress_total: 2,
      progress_percent: 50,
      progress_message: "Training run failed",
      error: "connection interrupted",
    };
    const retrying = {
      ...failed,
      status: "uploading" as const,
      progress_message: "Retrying the persisted RunComfy run",
      error: null,
    };
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([failed]),
      getTrainingRun: vi.fn().mockResolvedValue(retrying),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn().mockResolvedValue(retrying),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} />);

    await user.type(screen.getByLabelText("RunComfy API token"), "retry-secret");
    await user.click(await screen.findByTitle("Retry persisted RunComfy run"));

    expect(engine.refreshTrainingRun).toHaveBeenCalledWith(failed.id, "retry-secret");
    expect(screen.getByLabelText("RunComfy API token")).toHaveValue("");
    expect(await screen.findByText("Retrying the persisted RunComfy run")).toBeInTheDocument();
  });

  it("recalculates the planning estimate when the RunComfy GPU or plan changes", async () => {
    const user = userEvent.setup();
    const estimateTraining = vi.fn().mockResolvedValue(trainingEstimate());
    const engine = {
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
      estimateTraining,
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} targetProfile={trainingTarget()} />);

    await screen.findByText("$7.63");
    await user.selectOptions(screen.getByLabelText("RunComfy GPU"), "HOPPER_141");
    await user.selectOptions(screen.getByLabelText("RunComfy pricing plan"), "pro");

    await waitFor(() => expect(estimateTraining).toHaveBeenLastCalledWith(expect.objectContaining({
      provider: "runcomfy",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      gpu_type: "HOPPER_141",
      pricing_tier: "pro",
    })));
  });

  it("submits settings through the exact YAML that was estimated and smoke tested", async () => {
    const user = userEvent.setup();
    const profile = structuredTrainingTarget();
    const initialSmoke = smokeRun({ config_file: profile.config_template, ready: true });
    const estimateTraining = vi.fn().mockResolvedValue(trainingEstimate());
    const createRunComfyProviderSmokeRun = vi.fn().mockImplementation(async (request) => smokeRun({
      config_file: request.config_file,
      ready: true,
    }));
    const engine = {
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn(),
      createTrainingRun: vi.fn().mockResolvedValue(trainingRun()),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
      listProviderSmokeRuns: vi.fn().mockResolvedValue([initialSmoke]),
      createRunComfyProviderSmokeRun,
      estimateTraining,
    };

    render(<RunComfyTrainingConsole engine={engine} snapshot={snapshot()} targetProfile={profile} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Start Training" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Training steps"), { target: { value: "3000" } });

    expect(screen.getByRole("button", { name: "Start Training" })).toBeDisabled();
    expect(screen.getByText("Training settings changed. Run the provider smoke test before submission.")).toBeInTheDocument();
    await waitFor(() => expect(estimateTraining).toHaveBeenLastCalledWith(expect.objectContaining({
      config_file: expect.stringContaining("steps: 3000"),
    })));

    await user.click(screen.getByRole("button", { name: "Smoke Test" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start Training" })).toBeEnabled());
    expect(createRunComfyProviderSmokeRun).toHaveBeenCalledWith(expect.objectContaining({
      config_file: expect.stringContaining("steps: 3000"),
    }));

    await user.click(screen.getByRole("button", { name: "Start Training" }));
    expect(engine.createTrainingRun).toHaveBeenCalledWith(expect.objectContaining({
      config_file: expect.stringContaining("steps: 3000"),
    }));
  });
});

function trainingTarget(): TrainingTargetProfile {
  return {
    profile_id: "runcomfy_flux1_dev_character",
    label: "FLUX.1 Dev Character",
    provider: "runcomfy",
    trainer: "ai_toolkit",
    modality: "image",
    model_family: "flux1",
    base_model: "black-forest-labs/FLUX.1-dev",
    compiler_version: "image-pairs-v1",
    resolution_buckets: [512, 768, 1024],
    caption_format: "paired_txt",
    output_format: "safetensors_lora",
    description: "Character LoRA",
    ready: true,
    config_template: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
    warnings: [],
  };
}

function structuredTrainingTarget(): TrainingTargetProfile {
  return {
    ...trainingTarget(),
    profile_id: "runcomfy_krea2_character",
    label: "KREA 2 Character",
    model_family: "krea2",
    base_model: "krea/Krea-2-Raw",
    config_template: `---
job: extension
config:
  name: person-krea2-v1
  process:
    - type: diffusion_trainer
      network:
        type: lora
        linear: 32
        linear_alpha: 32
      save:
        save_every: 250
      datasets:
        - folder_path: /app/ai-toolkit/datasets/{dataset_name}
      train:
        steps: 2000
        lr: 0.0001
      model:
        name_or_path: krea/Krea-2-Raw
        arch: krea2
`,
  };
}

function smokeRun(overrides: Partial<ProviderSmokeRun> = {}): ProviderSmokeRun {
  return {
    id: "smoke-1",
    provider: "runcomfy",
    modality: "image",
    training_target_profile_id: "runcomfy_flux1_dev_character",
    project_id: "project-1",
    source_export_path: "/tmp/dataset",
    source_fingerprint: "abc123",
    config_file: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
    status: "complete",
    ready: false,
    checks: [{ id: "profile", passed: false, detail: "stale" }],
    created_at: "2026-07-12T00:00:00Z",
    completed_at: "2026-07-12T00:00:00Z",
    ...overrides,
  };
}

function snapshot(): DatasetSnapshot {
  return {
    id: "snapshot-1",
    project_id: "project-1",
    project_name: "Character",
    version: 1,
    status: "exported",
    intent: {
      target_type: "character",
      subject_name: "Person",
      trigger_token: "person_token",
      description: "",
      learned_attributes: ["identity"],
      controllable_attributes: [],
      excluded_attributes: [],
    },
    items: {},
    balance: {
      total_count: 1,
      approved_count: 1,
      review_count: 0,
      excluded_count: 0,
      source_count: 1,
      cropped_count: 0,
      average_quality: 0.9,
      average_diversity: 0.8,
      view_counts: {},
      crop_counts: {},
      warnings: [],
    },
    fingerprint: "abc123",
    export_path: "/tmp/dataset",
    created_at: "2026-07-11T00:00:00Z",
    updated_at: "2026-07-11T00:00:00Z",
  };
}

function trainingRun(): TrainingRun {
  return {
    id: "training-run-1",
    provider: "runcomfy",
    snapshot_id: "snapshot-1",
    dataset_fingerprint: "abc123",
    config_digest: "config123",
    config_file: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
    gpu_type: "ADA_80_PLUS",
    status: "in_queue",
    dataset_id: "dataset-1",
    dataset_name: "lorasuite-abc123",
    provider_job_id: "job-1",
    progress_current: 0,
    progress_total: 0,
    progress_percent: 0,
    progress_message: "Training queued",
    export_path: "/tmp/dataset",
    artifacts: [],
    created_at: "2026-07-11T00:00:00Z",
    updated_at: "2026-07-11T00:00:00Z",
  };
}

function modelArtifact(): ModelArtifactRecord {
  return {
    id: "artifact-1",
    training_run_id: "training-run-1",
    snapshot_id: "snapshot-1",
    dataset_fingerprint: "abc123",
    parent_snapshot_id: "snapshot-v1",
    parent_dataset_fingerprint: "fingerprint-v1",
    improvement_request_id: "improvement-v2",
    parent_artifact_id: "artifact-v1",
    parent_checkpoint_sha256: "checkpoint-v1-sha",
    checkpoint_name: "person.safetensors",
    checkpoint_path: "/vault/artifacts/person.safetensors",
    checkpoint_sha256: "1234567890abcdef",
    checkpoint_size_bytes: 1024,
    sample_paths: ["/vault/artifacts/sample.png"],
    trigger_token: "person_token",
    modality: "image",
    model_family: "flux1",
    evaluation: {
      status: "ready",
      checkpoint_valid: true,
      provenance_valid: true,
      config_present: true,
      sample_count: 1,
      tensor_count: 16,
      parameter_count: 1200000,
      warnings: [],
      evaluated_at: "2026-07-11T00:00:00Z",
    },
    installed_paths: [],
    workflow_paths: [],
    created_at: "2026-07-11T00:00:00Z",
    updated_at: "2026-07-11T00:00:00Z",
  };
}

function trainingEstimate(): TrainingCostEstimate {
  return {
    schema_version: "lorasuite.training-estimate.v1",
    available: true,
    provider: "runcomfy",
    training_target_profile_id: "runcomfy_flux1_dev_character",
    training_target_label: "FLUX.1 Dev Character",
    gpu_type: "ADA_80_PLUS",
    gpu_family: "h100",
    pricing_tier: "pay_as_you_go",
    step_count: 2000,
    dataset_item_count: 1,
    duration_hours: { low: 1, expected: 1.7, high: 3 },
    hourly_rate_usd: 4.49,
    cost_usd: { low: 4.49, expected: 7.63, high: 13.47 },
    confidence: "low",
    historical_run_count: 0,
    duration_basis: "Engineering baseline.",
    pricing_basis: "RunComfy pricing snapshot.",
    pricing_source_url: "https://www.runcomfy.com/pricing",
    pricing_snapshot_date: "2026-07-16",
    assumptions: [],
    warnings: [],
  };
}

function comfyRuntime(overrides: Partial<ComfyRuntimeStatus> = {}): ComfyRuntimeStatus {
  const required = [
    "LoraSuiteArtifactInfo",
    "LoraSuiteArtifactLoader",
    "LoraSuiteArtifactLoaderModelOnly",
    "LoraSuiteEvaluationReport",
  ];
  return {
    root: "/tmp/ComfyUI",
    base_url: "http://127.0.0.1:8188",
    reachable: true,
    extension_installed: true,
    extension_version: "0.1.0",
    required_nodes: required,
    loaded_nodes: required,
    missing_nodes: [],
    restart_required: false,
    checked_at: "2026-07-16T00:00:00Z",
    ...overrides,
    ...(overrides.restart_required ? { loaded_nodes: [], missing_nodes: required } : {}),
  };
}
