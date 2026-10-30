import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GuidedErrorBoundary } from "./GuidedErrorBoundary";

function Broken(): never { throw new Error("Failed to fetch dynamically imported module: /TrainTab.tsx"); }
beforeEach(() => { vi.spyOn(console, "error").mockImplementation(() => {}); });
afterEach(() => vi.restoreAllMocks());

it("returns to a usable project after a workspace failure", async () => {
  function Journey() {
    const [stage, setStage] = useState("build");
    return <GuidedErrorBoundary resetKey={stage} onBack={() => setStage("create")} onReload={vi.fn()} onOpenStudio={vi.fn()}>
      {stage === "build" ? <Broken /> : <h1>Project home</h1>}
    </GuidedErrorBoundary>;
  }
  render(<Journey />);
  expect(screen.getByRole("alert")).toHaveTextContent("This workspace couldn’t load");
  await userEvent.click(screen.getByRole("button", { name: "Back to project" }));
  expect(screen.getByRole("heading", { name: "Project home" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("resets a failed boundary when navigation changes from outside it", () => {
  const props = { onBack: vi.fn(), onReload: vi.fn(), onOpenStudio: vi.fn() };
  const view = render(<GuidedErrorBoundary {...props} resetKey="old:build"><Broken /></GuidedErrorBoundary>);
  view.rerender(<GuidedErrorBoundary {...props} resetKey="new:create"><h1>Another project</h1></GuidedErrorBoundary>);
  expect(screen.getByRole("heading", { name: "Another project" })).toBeVisible();
});

it("offers a full reload to clear a rejected lazy import", async () => {
  const reload = vi.fn();
  render(<GuidedErrorBoundary resetKey="build" onBack={vi.fn()} onReload={reload} onOpenStudio={vi.fn()}><Broken /></GuidedErrorBoundary>);
  await userEvent.click(screen.getByRole("button", { name: "Reload workspace" }));
  expect(reload).toHaveBeenCalledOnce();
});
