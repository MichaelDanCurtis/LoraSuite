import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GuidedCopilot } from "./GuidedCopilot";

describe("GuidedCopilot", () => {
  it("stays actionable and answers identity questions from workflow context", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <GuidedCopilot
        stage="verify"
        target="image"
        relevantMediaCount={42}
        identifyItemCount={18}
        hasProject
        evaluationReady={false}
        action={{ label: "Return to Prepare", onClick: onAction }}
      />,
    );

    expect(screen.getByLabelText("Ask AI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Ask AI" }));
    expect(screen.getByText(/checking identity across 18 prepared items/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Ask AI a question"), "How do I anchor the right person?");
    await user.click(screen.getByTitle("Send"));
    expect(screen.getByText(/click “Anchor this person.”/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Return to Prepare" }));
    expect(onAction).toHaveBeenCalledOnce();
  });

  it("starts as a compact launcher and expands only on request", async () => {
    const user = userEvent.setup();
    render(
      <GuidedCopilot
        stage="sources"
        target="video"
        relevantMediaCount={0}
        identifyItemCount={0}
        hasProject={false}
        evaluationReady={false}
      />,
    );

    const toggle = screen.getByRole("button", { name: "Open Ask AI" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.querySelector(".guided-copilot-launcher-icon")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ask AI a question")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle.querySelector(".guided-copilot-launcher-icon")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask AI a question")).toBeInTheDocument();
  });
});
