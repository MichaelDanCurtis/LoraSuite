import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./components/TrainTab", () => ({ TrainTab: () => { throw new Error("Failed to fetch dynamically imported module: /TrainTab.tsx"); } }));
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

it.each(["Back to project", "LoraSuite home"])("escapes a failed Build screen using %s without changing the selected project", async (button) => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  localStorage.setItem("lorasuite:workspace:v1", JSON.stringify({ active_project_id: "existing-project", target: "image", stage: "build", experience: "guided" }));
  render(<App />);
  await screen.findByRole("button", { name: "Back to project" });
  await userEvent.click(screen.getByRole("button", { name: button }));
  expect(await screen.findByRole("heading", { name: "What do you want to create?" })).toBeVisible();
  const saved = JSON.parse(localStorage.getItem("lorasuite:workspace:v1")!);
  expect(saved.active_project_id).toBe("existing-project");
  expect(saved.stage).toBe("create");
  expect(screen.queryByText("This workspace couldn’t load")).not.toBeInTheDocument();
});
