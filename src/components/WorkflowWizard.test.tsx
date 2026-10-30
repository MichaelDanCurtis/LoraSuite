import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TrainingWorkflowLane } from "../lib/types";
import { WorkflowWizard } from "./WorkflowWizard";

describe("WorkflowWizard", () => {
  it("inspects evidence and navigates to the first incomplete stage", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const engine = wizardEngine();
    render(<WorkflowWizard engine={engine} target="image" activeTab="ingest" mediaItems={[image]} onTargetChange={vi.fn()} onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    const dialog = screen.getByRole("dialog", { name: "LoRA workflow wizard" });
    await waitFor(() => expect(engine.getCurationHandoff).toHaveBeenCalled());
    await waitFor(() => expect(within(dialog).getAllByText("No accepted identity images.")).toHaveLength(2));
    await user.click(within(dialog).getByRole("button", { name: "Review identity candidates" }));

    expect(onNavigate).toHaveBeenCalledWith("identify");
  });

  it("switches the persisted workflow intent through the output selector", async () => {
    const user = userEvent.setup();
    const onTargetChange = vi.fn();
    render(<WorkflowWizard engine={wizardEngine()} target="image" activeTab="ingest" mediaItems={[]} onTargetChange={onTargetChange} onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    await user.click(within(screen.getByRole("group", { name: "LoRA output type" })).getByRole("button", { name: "Video" }));

    expect(onTargetChange).toHaveBeenCalledWith("video");
  });

  it("shows the backend-planned action for the selected LoRA lane", async () => {
    const user = userEvent.setup();
    render(<WorkflowWizard engine={wizardEngine()} target="voice" activeTab="train" mediaItems={[image]} onTargetChange={vi.fn()} onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));

    const dialog = screen.getByRole("dialog", { name: "LoRA workflow wizard" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Run audio quality gate" })).toBeInTheDocument());
    expect(within(dialog).getByText("Verify Speaker")).toBeInTheDocument();
    expect(within(dialog).getByText("working · quality")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("segments: 3")).toBeInTheDocument();
    expect(within(dialog).getByText("RunPod")).toBeInTheDocument();
    expect(within(dialog).getByText("Create RunPod bundle")).toBeInTheDocument();
  });

  it("shows blockers and preserves certified completion language", async () => {
    const user = userEvent.setup();
    const engine = wizardEngine();
    const workflow = await engine.getTrainingWorkflow("project-1");
    engine.getTrainingWorkflow.mockResolvedValue({
      ...workflow,
      lanes: workflow.lanes.map((lane: TrainingWorkflowLane) => lane.id === "id_lora" ? {
        ...lane,
        state: "complete" as const,
        phase: "certified",
        summary: "Appearance, voice, transcript, motion, and certified sync gates passed.",
        action_label: "Review certified ID-LoRA",
        counts: { evaluation_passed: 4 },
        blockers: [],
        warnings: ["Generic adapter was evaluated without per-person retraining."],
      } : lane),
    });
    render(<WorkflowWizard engine={engine} target="id_lora" activeTab="train" mediaItems={[]} onTargetChange={vi.fn()} onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    const dialog = screen.getByRole("dialog", { name: "LoRA workflow wizard" });
    await waitFor(() => expect(within(dialog).getByText("complete · certified")).toBeInTheDocument());
    expect(within(dialog).getAllByText("Appearance, voice, transcript, motion, and certified sync gates passed.")).toHaveLength(2);
    expect(within(dialog).getByText("Generic adapter was evaluated without per-person retraining.")).toBeInTheDocument();
  });

  it("treats a completed provider handoff as proof of prior workflow stages", async () => {
    const user = userEvent.setup();
    const engine = wizardEngine();
    engine.getTrainingWorkflow.mockResolvedValue({
      ...(await engine.getTrainingWorkflow("project-1")),
      complete_count: 1,
      lanes: (await engine.getTrainingWorkflow("project-1")).lanes.map((lane: TrainingWorkflowLane) => lane.id === "image" ? { ...lane, state: "complete" as const, phase: "handoff", summary: "Provider handoff ready.", action_label: "Open provider handoff" } : lane),
    });
    render(<WorkflowWizard engine={engine} target="image" activeTab="ingest" mediaItems={[]} onTargetChange={vi.fn()} onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Open workflow wizard" })).toHaveTextContent("4/4"));
    expect(within(screen.getByRole("dialog", { name: "LoRA workflow wizard" })).getByRole("button", { name: "Open provider handoff" })).toBeInTheDocument();
  });

  it("routes planner prerequisites to the workspace that can resolve them", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<WorkflowWizard engine={wizardEngine()} target="video" activeTab="train" mediaItems={[image]} onTargetChange={vi.fn()} onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    const dialog = screen.getByRole("dialog", { name: "LoRA workflow wizard" });
    const action = await within(dialog).findByRole("button", { name: "Curate video clips" });
    await user.click(action);

    expect(onNavigate).toHaveBeenCalledWith("curate");
  });

  it("opens provider readiness actions in the matching Train lane", async () => {
    const user = userEvent.setup();
    const onTargetChange = vi.fn();
    const onNavigate = vi.fn();
    render(<WorkflowWizard engine={wizardEngine()} target="image" activeTab="ingest" mediaItems={[image]} onTargetChange={onTargetChange} onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    const dialog = screen.getByRole("dialog", { name: "LoRA workflow wizard" });
    const providerAction = await within(dialog).findByRole("button", { name: "RunComfy: Launch RunComfy training" });
    await user.click(providerAction);

    expect(onTargetChange).toHaveBeenCalledWith("image");
    expect(onNavigate).toHaveBeenCalledWith("train");
    expect(screen.queryByRole("dialog", { name: "LoRA workflow wizard" })).not.toBeInTheDocument();
  });

  it("routes ID-LoRA video prerequisites directly into the Video Dataset compiler", async () => {
    const user = userEvent.setup();
    const onTargetChange = vi.fn();
    const onNavigate = vi.fn();
    render(<WorkflowWizard engine={wizardEngine()} target="id_lora" activeTab="ingest" mediaItems={[image]} onTargetChange={onTargetChange} onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    const action = await within(screen.getByRole("dialog", { name: "LoRA workflow wizard" })).findByRole("button", { name: "Finish video dataset" });
    await user.click(action);

    expect(onTargetChange).toHaveBeenCalledWith("video");
    expect(onNavigate).toHaveBeenCalledWith("train");
  });

  it("inspects and changes the explicitly active character project", async () => {
    const user = userEvent.setup();
    const engine = wizardEngine();
    engine.listCharacterProjects.mockResolvedValue([
      { id: "project-1", name: "First Character", health: { anchor_count: 0 } },
      { id: "project-2", name: "Second Character", health: { anchor_count: 1 } },
    ]);
    const onProjectChange = vi.fn();
    render(<WorkflowWizard engine={engine} target="image" activeTab="train" mediaItems={[image]} activeProjectId="project-2" onProjectChange={onProjectChange} onTargetChange={vi.fn()} onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Open workflow wizard" }));
    await waitFor(() => expect(engine.getTrainingWorkflow).toHaveBeenCalledWith("project-2"));
    expect(screen.getByLabelText("Workflow character project")).toHaveValue("project-2");
    await user.selectOptions(screen.getByLabelText("Workflow character project"), "project-1");

    expect(onProjectChange).toHaveBeenCalledWith("project-1");
  });
});

function wizardEngine() {
  return {
    getCurationHandoff: vi.fn().mockResolvedValue({ items: [{ media_item_id: image.id, lane: "image", review_status: "accepted" }], updated_at: "2026-07-12T00:00:00Z" }),
    listCharacterProjects: vi.fn().mockResolvedValue([{ id: "project-1", health: { anchor_count: 0 } }]),
    listDatasetSnapshots: vi.fn().mockResolvedValue([]),
    listVideoDatasetSnapshots: vi.fn().mockResolvedValue([]),
    getVoiceIdentityProfile: vi.fn().mockResolvedValue({ anchor_media_item_ids: [] }),
    getVoiceDataset: vi.fn().mockResolvedValue({ export_path: null }),
    listIdLoraManifests: vi.fn().mockResolvedValue([]),
    getTrainingWorkflow: vi.fn().mockResolvedValue({
      project_id: "project-1",
      project_name: "Character",
      recommended_lane: "voice",
      recommendation: "Voice Dataset: Run audio quality gate",
      complete_count: 0,
      updated_at: "2026-07-12T00:00:00Z",
      lanes: [
        { id: "image", label: "Image LoRA", state: "blocked", phase: "identity", summary: "No accepted identity images.", action_label: "Review identity candidates", target_mode: "image", target_workspace: "identify", counts: {}, blockers: [], warnings: [] },
        { id: "video", label: "Video LoRA", state: "blocked", phase: "curate", summary: "No clips.", action_label: "Curate video clips", target_mode: "video", target_workspace: "curate", counts: {}, blockers: [], warnings: [] },
        { id: "voice", label: "Voice Dataset", state: "working", phase: "quality", summary: "3 segments still need the audio quality gate.", action_label: "Run audio quality gate", target_mode: "voice", target_workspace: "train", counts: { segments: 3 }, blockers: [], warnings: [] },
        { id: "id_lora", label: "ID-LoRA", state: "blocked", phase: "video", summary: "Video required.", action_label: "Finish video dataset", target_mode: "video", target_workspace: "train", counts: {}, blockers: [], warnings: [] },
        { id: "evaluate", label: "Evaluate", state: "blocked", phase: "artifact", summary: "Artifact required.", action_label: "Train or register a model", target_mode: "evaluate", target_workspace: "train", counts: {}, blockers: [], warnings: [] },
      ],
    }),
    getProviderReadiness: vi.fn().mockResolvedValue({
      project_id: "project-1", ready_count: 0, total_count: 6,
      items: [
        { lane: "image", provider: "runcomfy", profile_id: "image-profile", state: "dataset_ready", summary: "Image export ready.", action_label: "Launch RunComfy training", blockers: [], warnings: [] },
        { lane: "image", provider: "runpod", profile_id: "image-profile", state: "dataset_ready", summary: "Image export ready.", action_label: "Create RunPod bundle", blockers: [], warnings: [] },
        { lane: "video", provider: "runcomfy", profile_id: "video-profile", state: "blocked", summary: "Video export needed.", action_label: "Export video dataset", blockers: [], warnings: [] },
        { lane: "video", provider: "runpod", profile_id: "video-profile", state: "blocked", summary: "Video export needed.", action_label: "Export video dataset", blockers: [], warnings: [] },
        { lane: "voice", provider: "runpod", profile_id: "voice-profile", state: "dataset_ready", summary: "Voice export ready.", action_label: "Create RunPod bundle", blockers: [], warnings: [] },
        { lane: "id_lora", provider: "runpod", profile_id: "id-profile", state: "blocked", summary: "ID export needed.", action_label: "Export ID-LoRA package", blockers: [], warnings: [] },
      ],
    }),
  };
}

const image = { id: "image-1", media_type: "image" as const, status: "new" as const };
