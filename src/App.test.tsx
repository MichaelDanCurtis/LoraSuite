import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: isTauriMock,
}));

describe("App", () => {
  beforeEach(() => {
    isTauriMock.mockReturnValue(true);
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the four workspace tabs", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "Data Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Curate" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Identify" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Train" })).toBeInTheDocument();
  });

  it("switches workspace tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Curate" }));

    expect(screen.getByRole("heading", { name: "Curate" })).toBeInTheDocument();
    expect(screen.getByText("PhotoMapAI-derived media triage workspace")).toBeInTheDocument();
  });

  it("reloads completed ingress media into Curate and sends selected images to Identify", async () => {
    const user = userEvent.setup();
    const importedImage = {
      id: "media_imported_portrait",
      raw_path: "/tmp/vault/raw/imported-portrait.png",
      media_type: "image",
      width: 768,
      height: 1024,
      status: "new",
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: ["candidate_poster"],
      reviewed_candidate_ids: ["candidate_poster"],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 1,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [importedImage],
      created_at: "2026-07-08T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [completedJob],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Curate" }));

    expect(await screen.findByText("imported-portrait.png")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select for Identify: imported-portrait.png"));
    await user.click(screen.getByRole("button", { name: "Send to Identify" }));
    await user.click(screen.getByRole("tab", { name: "Identify" }));

    expect(screen.getByRole("heading", { name: "Identify" })).toBeInTheDocument();
    expect(screen.getByText("imported-portrait.png")).toBeInTheDocument();
    expect(screen.getByText("1 target candidate")).toBeInTheDocument();
  });

  it("keeps ingress candidates when switching away from data ingress", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "scan_1",
        candidates: [
          {
            id: "candidate_persisted_image",
            source_kind: "instagram",
            source_locator: "https://www.instagram.com/p/persisted/",
            display_name: "persisted candidate",
            media_type: "image",
            thumbnail_path: "/tmp/vault/previews/social/persisted.jpg",
            status: "ready",
            selected: true,
          },
        ],
        errors: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/",
    );
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(await screen.findByText("persisted candidate")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Curate" }));
    expect(screen.getByRole("heading", { name: "Curate" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data Ingest" }));

    expect(screen.getByText("persisted candidate")).toBeInTheDocument();
  });

  it("shows RunComfy export controls", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Train" }));

    expect(screen.getByLabelText("Frame paths")).toBeInTheDocument();
    expect(screen.getByLabelText("Output folder")).toBeInTheDocument();
    expect(screen.getByLabelText("Caption template")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create RunComfy Image Export" }),
    ).toBeInTheDocument();
  });

  it("shows local ingress candidate review controls", () => {
    render(<App />);

    expect(screen.getByRole("button", { name: "Import Media" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose Destination" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tile" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "List" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gallery" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm Ingest" })).toBeDisabled();
  });

  it("shows instagram source controls with advanced fallbacks hidden by default", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));

    expect(screen.getByLabelText("Instagram URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Browser cookies")).toBeInTheDocument();
    const scanTarget = screen.getByRole("group", { name: "Scan target" });
    expect(within(scanTarget).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Scan Instagram" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Instagram helper payload")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Manual path fallback")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));

    expect(screen.getByLabelText("Instagram helper payload")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Scan Instagram Helper Payload" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load Helper Candidates" })).toBeInTheDocument();
    expect(screen.getByLabelText("Manual path fallback")).toBeInTheDocument();
  });

  it("switches local ingress review modes", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Gallery" }));
    expect(screen.getByRole("button", { name: "Gallery" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
