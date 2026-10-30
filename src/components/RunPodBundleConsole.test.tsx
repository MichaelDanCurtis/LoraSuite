import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunPodBundle, RunPodBundleUploadJob, RunPodModelBootstrapRun, RunPodPreflightReport, RunPodTrainingRun, TrainingCostEstimate } from "../lib/types";
import { RunPodBundleConsole } from "./RunPodBundleConsole";

const { isTauriMock } = vi.hoisted(() => ({ isTauriMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

function bootstrapEngineMethods() {
  return {
    listRunPodModelBootstrapRuns: vi.fn().mockResolvedValue([]),
    getRunPodModelBootstrapRun: vi.fn(),
    createRunPodModelBootstrapRun: vi.fn(),
    refreshRunPodModelBootstrapRun: vi.fn(),
    cancelRunPodModelBootstrapRun: vi.fn(),
  };
}

describe("RunPodBundleConsole", () => {
  beforeEach(() => isTauriMock.mockReturnValue(false));


  it.each([
    ["running", "Cancellation requested; waiting for RunPod confirmation"],
    ["in_queue", "RunPod cancellation not confirmed; refresh or cancel to retry"],
    ["completed", "Training completed with 1 artifact(s)"],
    ["canceled", "RunPod training canceled"],
  ] as const)("reports the provider cancellation outcome when the job is %s", async (status, message) => {
    const user = userEvent.setup();
    const result: RunPodTrainingRun = { ...runpodRun(), status, progress_message: message };
    const engine = {
      createRunPodBundle: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([{ ...bundle(), available: true }]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([completedUpload()]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([]),
      createRunPodPreflightReport: vi.fn().mockResolvedValue(preflightReport()),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([runpodRun()]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn().mockResolvedValue(runpodRun()),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn().mockResolvedValue(result),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
    };
    const { container } = render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);
    await user.click(await screen.findByRole("button", { name: "Cancel RunPod job" }));
    await waitFor(() => expect(container.querySelector(".runpod-console > .status-line")).toHaveTextContent(message));
    expect(engine.cancelRunPodTrainingRun).toHaveBeenCalledWith("runpod-run-1", undefined);
    expect(container.querySelector(".runpod-console > .status-line")).not.toHaveTextContent("RunPod job job-1 canceled.");
    if (status === "running" || status === "in_queue") {
      expect(screen.getByRole("button", { name: "Cancel RunPod job" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Refresh RunPod job" })).toBeEnabled();
    } else {
      expect(screen.queryByRole("button", { name: "Cancel RunPod job" })).not.toBeInTheDocument();
    }
  });

  it("creates a network-volume-ready modality bundle", async () => {
    const user = userEvent.setup();
    const createRunPodBundle = vi.fn().mockResolvedValue(bundle());
    const engine = {
      createRunPodBundle,
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([completedUpload()]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([]),
      createRunPodPreflightReport: vi.fn().mockResolvedValue(preflightReport()),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn().mockResolvedValue(runpodRun()),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
    };
    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);

    expect(screen.getByLabelText("Connect RunPod")).toHaveTextContent("API key needed");
    expect(screen.getByRole("button", { name: "Save RunPod API key" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("RunPod image bundle folder"), "/tmp/runpod-image");
    await user.type(screen.getByLabelText("RunPod image endpoint ID"), "endpoint-1");
    await user.click(screen.getByRole("button", { name: "Export RunPod" }));

    await waitFor(() => expect(createRunPodBundle).toHaveBeenCalledWith({
      source_export_path: "/tmp/image-export",
      output_path: "/tmp/runpod-image",
      modality: "image",
      trigger_token: "person_token",
      fingerprint: "abcdef",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      remote_root: "/workspace/lorasuite",
      endpoint_id: "endpoint-1",
    }));
    expect(screen.getByText("Trainer-ready")).toBeInTheDocument();
    expect(screen.getByText("/tmp/runpod-image-runpod.zip")).toBeInTheDocument();
    await user.type(screen.getByLabelText("RunPod image API key"), "session-key");
    expect(screen.getByRole("button", { name: "Start RunPod" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Verify Endpoint" }));
    await waitFor(() => expect(engine.createRunPodPreflightReport).toHaveBeenCalledWith({
      bundle_path: "/tmp/runpod-image",
      endpoint_id: "endpoint-1",
      api_token: "session-key",
    }));
    expect(screen.getByText("Endpoint ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start RunPod" }));
    await waitFor(() => expect(engine.createRunPodTrainingRun).toHaveBeenCalledWith({
      bundle_path: "/tmp/runpod-image",
      endpoint_id: "endpoint-1",
      api_token: "session-key",
    }));
    expect(screen.getByText("Waiting for a RunPod worker")).toBeInTheDocument();
  });

  it("installs the allowlisted Fish Speech models through the asynchronous RunPod controller", async () => {
    const user = userEvent.setup();
    const createRunPodModelBootstrapRun = vi.fn().mockResolvedValue(completedBootstrap());
    const engine = {
      createRunPodBundle: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      createRunPodModelBootstrapRun,
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
    };

    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/voice-export" modality="voice" triggerToken="person_voice" fingerprint="voice-fingerprint" trainingTargetProfileId="runpod_fish_speech_s2_voice_lora" />);

    const endpointField = screen.getByLabelText("RunPod voice endpoint ID");
    const installer = screen.getByRole("region", { name: "RunPod required model installation" });
    expect(endpointField.compareDocumentPosition(installer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.type(endpointField, "endpoint-fish");
    await user.type(screen.getByLabelText("RunPod infrastructure API key"), "session-key");
    await user.click(screen.getByRole("button", { name: "Install Models" }));

    await waitFor(() => expect(createRunPodModelBootstrapRun).toHaveBeenCalledWith({
      endpoint_id: "endpoint-fish",
      training_target_profile_id: "runpod_fish_speech_s2_voice_lora",
      api_token: "session-key",
    }));
    expect(screen.getByRole("button", { name: "Models Ready" })).toBeDisabled();
    expect(screen.getAllByText("Required models are installed.")).toHaveLength(2);
  });

  it("registers fully downloaded RunPod outputs for evaluation", async () => {
    const user = userEvent.setup();
    const completed = runpodRun();
    completed.status = "completed";
    completed.progress_message = "Training completed with 1 artifact(s)";
    completed.artifacts = [{
      kind: "checkpoint",
      name: "person.safetensors",
      local_path: "/tmp/artifacts/person.safetensors",
      size_bytes: 42,
      sha256: "abc",
    }];
    const registerRunPodTrainingArtifacts = vi.fn().mockResolvedValue([{ id: "artifact-1" }]);
    const engine = {
      createRunPodBundle: vi.fn().mockResolvedValue(bundle()),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([completedUpload()]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([preflightReport()]),
      createRunPodPreflightReport: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([completed]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts,
    };
    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);

    await user.type(screen.getByLabelText("RunPod image bundle folder"), "/tmp/runpod-image");
    await user.click(screen.getByRole("button", { name: "Export RunPod" }));
    await screen.findByTitle("Register RunPod artifacts");
    await user.click(screen.getByTitle("Register RunPod artifacts"));

    await waitFor(() => expect(registerRunPodTrainingArtifacts).toHaveBeenCalledWith("runpod-run-1"));
    expect(screen.getByText("Registered 1 model artifact for evaluation.")).toBeInTheDocument();
  });

  it("uploads the exported bundle without retaining S3 credentials", async () => {
    const user = userEvent.setup();
    const createRunPodBundleUploadJob = vi.fn().mockResolvedValue(uploadJob());
    const engine = {
      createRunPodBundle: vi.fn().mockResolvedValue(bundle()),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob,
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
    };
    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);
    await user.type(screen.getByLabelText("RunPod image bundle folder"), "/tmp/runpod-image");
    await user.click(screen.getByRole("button", { name: "Export RunPod" }));
    await user.type(screen.getByLabelText("RunPod network volume ID"), "volume-1");
    await user.type(screen.getByLabelText("RunPod S3 endpoint"), "https://s3.example/");
    await user.type(screen.getByLabelText("RunPod datacenter"), "US-CA-2");
    await user.type(screen.getByLabelText("RunPod S3 access key"), "access-key");
    await user.type(screen.getByLabelText("RunPod S3 secret key"), "secret-key");
    await user.click(screen.getByRole("button", { name: "Upload Bundle" }));

    await waitFor(() => expect(createRunPodBundleUploadJob).toHaveBeenCalledWith({
      bundle_path: "/tmp/runpod-image", volume_id: "volume-1", s3_endpoint: "https://s3.example/", datacenter: "US-CA-2",
      access_key: "access-key", secret_key: "secret-key",
    }));
    expect(screen.getByLabelText("RunPod S3 access key")).toHaveValue("");
    expect(screen.getByLabelText("RunPod S3 secret key")).toHaveValue("");
    expect(screen.getByText("4/4 files · 100 B/100 B")).toBeInTheDocument();
  });

  it("restores a persisted bundle, upload, endpoint, and provider state after refresh", async () => {
    const engine = {
      createRunPodBundle: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([bundle()]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([completedUpload()]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([preflightReport()]),
      createRunPodPreflightReport: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
    };

    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);

    expect(await screen.findByText("Trainer-ready")).toBeInTheDocument();
    expect(screen.getByLabelText("RunPod image bundle folder")).toHaveValue("/tmp/runpod-image");
    expect(screen.getByLabelText("RunPod image endpoint ID")).toHaveValue("endpoint-1");
    expect(screen.getByText("Network volume · bundle uploaded")).toBeInTheDocument();
    expect(screen.getByText("Restored provider-ready RunPod bundle.")).toBeInTheDocument();
  });

  it("uses the verified endpoint GPU and selected billing mode for its estimate", async () => {
    const user = userEvent.setup();
    const estimateTraining = vi.fn().mockResolvedValue(runpodEstimate());
    const engine = {
      createRunPodBundle: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([bundle()]),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      ...bootstrapEngineMethods(),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([completedUpload()]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([preflightReport()]),
      createRunPodPreflightReport: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
      estimateTraining,
    };

    render(<RunPodBundleConsole engine={engine} sourceExportPath="/tmp/image-export" modality="image" triggerToken="person_token" fingerprint="abcdef" trainingTargetProfileId="runcomfy_flux1_dev_character" />);

    await screen.findByText("$13.65");
    await user.selectOptions(screen.getByLabelText("RunPod pricing plan"), "active");
    await waitFor(() => expect(estimateTraining).toHaveBeenLastCalledWith(expect.objectContaining({
      provider: "runpod",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      gpu_type: "NVIDIA H100 80GB HBM3",
      pricing_tier: "active",
    })));
  });
});

function bundle(): RunPodBundle {
  return {
    id: "bundle-1", provider: "runpod", modality: "image", fingerprint: "abcdef", source_export_path: "/tmp/image-export",
    output_path: "/tmp/runpod-image", archive_path: "/tmp/runpod-image-runpod.zip",
    manifest_path: "/tmp/runpod-image/bundle_manifest.json", input_path: "/tmp/runpod-image/runpod_input.json",
    config_path: "/tmp/runpod-image/config/train.yaml", serverless_config_path: "/tmp/runpod-image/config/serverless_train.yaml",
    pod_template_path: "/tmp/runpod-image/pod_template.json",
    pod_launcher_path: "/tmp/runpod-image/launch_pod.sh", trainer_launcher_path: "/tmp/runpod-image/train_ai_toolkit.sh",
    remote_root: "/workspace/lorasuite/image-abcdef",
    remote_dataset_path: "/workspace/lorasuite/image-abcdef/dataset/images",
    serverless_root: "/runpod-volume/lorasuite/image-abcdef",
    serverless_dataset_path: "/runpod-volume/lorasuite/image-abcdef/dataset/images",
    training_target_profile_id: "runcomfy_flux1_dev_character", ready: true, available: true, warnings: [], created_at: "2026-07-12T00:00:00Z",
  };
}

function preflightReport(): RunPodPreflightReport {
  return {
    id: "preflight-1", provider: "runpod", bundle_path: "/tmp/runpod-image", bundle_fingerprint: "abcdef",
    training_target_profile_id: "runcomfy_flux1_dev_character", endpoint_id: "endpoint-1", worker_contract_version: 1,
    ready: true, volume_root: "/runpod-volume", platform: "Linux", python_version: "3.12.9",
    gpu: { available: true, name: "NVIDIA H100 80GB HBM3", memory_gb: 80, driver_version: "575.10" },
    checks: [{ id: "network_volume", passed: true, detail: "mounted" }, { id: "gpu", passed: true, detail: "H100 ready" }],
    checked_at: "2026-07-12T00:00:00Z",
  };
}

function completedBootstrap(): RunPodModelBootstrapRun {
  return {
    id: "bootstrap-1",
    provider: "runpod",
    training_target_profile_id: "runpod_fish_speech_s2_voice_lora",
    endpoint_id: "endpoint-fish",
    provider_job_id: "provider-bootstrap-1",
    status: "completed",
    progress_message: "Required models are installed.",
    required_paths: ["/runpod-volume/models/fish-speech-s2"],
    manifest_path: "/runpod-volume/models/.lorasuite/runpod_fish_speech_s2_voice_lora.json",
    reused: false,
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:01:00Z",
    completed_at: "2026-07-12T00:01:00Z",
  };
}

function completedUpload() {
  return {
    id: "upload-1", provider: "runpod" as const, bundle_path: "/tmp/runpod-image", bundle_fingerprint: "abcdef",
    training_target_profile_id: "runcomfy_flux1_dev_character", volume_id: "volume-1", endpoint_url: "https://s3.example/",
    datacenter: "US-CA-2", remote_prefix: "lorasuite/image-abcdef", status: "complete" as const,
    files_total: 4, files_uploaded: 4, bytes_total: 1024, bytes_uploaded: 1024,
    created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function uploadJob(): RunPodBundleUploadJob {
  return {
    id: "upload-1", provider: "runpod", bundle_path: "/tmp/runpod-image", bundle_fingerprint: "abcdef",
    training_target_profile_id: "runcomfy_flux1_dev_character", volume_id: "volume-1", endpoint_url: "https://s3.example/",
    datacenter: "US-CA-2", remote_prefix: "lorasuite/image-abcdef", status: "complete", files_total: 4, files_uploaded: 4,
    bytes_total: 100, bytes_uploaded: 100, created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function runpodRun(): RunPodTrainingRun {
  return {
    id: "runpod-run-1", provider: "runpod", bundle_path: "/tmp/runpod-image", bundle_fingerprint: "abcdef",
    modality: "image", training_target_profile_id: "runcomfy_flux1_dev_character", action: "train_lora", endpoint_id: "endpoint-1",
    provider_job_id: "job-1", snapshot_id: "snapshot-1", project_id: "project-1", status: "in_queue",
    progress_message: "Waiting for a RunPod worker", artifacts: [], created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z",
  };
}

function runpodEstimate(): TrainingCostEstimate {
  return {
    schema_version: "lorasuite.training-estimate.v1",
    available: true,
    provider: "runpod",
    training_target_profile_id: "runcomfy_flux1_dev_character",
    training_target_label: "FLUX.1 Dev Character",
    gpu_type: "NVIDIA H100 80GB HBM3",
    gpu_family: "h100",
    pricing_tier: "flex",
    step_count: 2000,
    duration_hours: { low: 2, expected: 3, high: 4 },
    hourly_rate_usd: 4.55,
    cost_usd: { low: 9.1, expected: 13.65, high: 18.2 },
    confidence: "medium",
    historical_run_count: 2,
    duration_basis: "Measured completed runs.",
    pricing_basis: "RunPod Serverless pricing snapshot.",
    pricing_source_url: "https://www.runpod.io/pricing",
    pricing_snapshot_date: "2026-07-16",
    assumptions: [],
    warnings: [],
  };
}
