import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectHome } from "./ProjectHome";

describe("ProjectHome", () => {
  it("summarizes the active project contract and continues its recommended lane", async () => {
    const user = userEvent.setup();
    const lane = {
      id: "video",
      label: "MiniMax H3",
      state: "ready",
      phase: "compile",
      summary: "Reviewed clips can be paired with optional references.",
      action_label: "Choose H3 references",
      target_mode: "video",
      target_workspace: "train",
      counts: {},
      blockers: [],
      warnings: [],
    };
    const project = {
      id: "project_1",
      name: "Mary",
      intent: {
        target_type: "character",
        subject_name: "Mary",
        requested_outputs: ["video"],
        training_target_profile_ids: { video: "comfyui_minimax_h3_ref2va" },
        trigger_token: "",
        description: "",
        learned_attributes: [],
        controllable_attributes: [],
        excluded_attributes: [],
      },
      candidate_media_item_ids: [],
      observations: {},
      health: { accepted_count: 12, anchor_count: 2 },
      created_at: "2026-08-08T00:00:00Z",
      updated_at: "2026-08-08T00:00:00Z",
    };
    const engine = {
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      listTrainingTargets: vi.fn().mockResolvedValue([{
        profile_id: "comfyui_minimax_h3_ref2va",
        label: "MiniMax H3 Reference-to-Video with Audio",
        provider: "comfyui",
        output_format: "generated_video",
        warnings: [],
        recipe: {
          workflow_kind: "inference",
          dataset: {
            allowed_image_extensions: [".png"],
            allowed_video_extensions: [".mp4"],
            allowed_audio_extensions: [".wav"],
          },
        },
      }]),
      getTrainingWorkflow: vi.fn().mockResolvedValue({
        project_id: project.id,
        project_name: project.name,
        recommended_lane: "video",
        recommendation: "MiniMax H3: Choose H3 references",
        complete_count: 0,
        lanes: [lane],
        updated_at: "2026-08-08T00:00:00Z",
      }),
    };
    const onContinue = vi.fn();

    render(<ProjectHome engine={engine as never} activeProjectId={project.id} onProjectChange={vi.fn()} onContinue={onContinue} />);
    await user.click(screen.getByRole("button", { name: "Project Home" }));

    expect(await screen.findByText("MiniMax H3 Reference-to-Video with Audio")).toBeInTheDocument();
    expect(screen.getByText("Reference-only")).toBeInTheDocument();
    expect(screen.getByText("images + video + audio")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(onContinue).toHaveBeenCalledWith(lane);
  });
});
