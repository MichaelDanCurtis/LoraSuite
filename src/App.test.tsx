import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("shows the four workspace tabs", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "Data Ingress" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Curate / Search" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Video Review" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Exports" })).toBeInTheDocument();
  });

  it("switches workspace tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Curate / Search" }));

    expect(screen.getByRole("heading", { name: "Curate / Search" })).toBeInTheDocument();
    expect(screen.getByText("PhotoMapAI-derived curation workspace")).toBeInTheDocument();
  });

  it("shows segment intent guidance in video review", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Video Review" }));
    await user.click(screen.getByLabelText("Use for image training"));
    await user.click(screen.getByLabelText("Use for voice training / cloning"));

    expect(screen.getByText("Extract sparse keyframes from stable visual ranges.")).toBeInTheDocument();
    expect(screen.getByText("Prefer clean speech with one speaker and low noise.")).toBeInTheDocument();
  });
});
