import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { loadVaultMediaProgressively } from "./App";
import { createEngineClient } from "./lib/api";

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
    window.localStorage.setItem("lorasuite:experience:v1", "studio");
  });

  it("opens in guided mode for a new user and preserves Advanced Consoles", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem("lorasuite:experience:v1");
    render(<App />);

    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Living Identity" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /H3 native/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced Consoles" }));
    expect(screen.getByRole("tab", { name: "Data Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guided Mode" })).toBeInTheDocument();
  });

  it("keeps an unavailable recipe catalog on Create and preserves source navigation", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem("lorasuite:experience:v1");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Engine offline")));
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    expect(await screen.findByText(/Choose a compatible model recipe before continuing/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sources" }));
    expect(screen.getByRole("heading", { name: "Give me everything you have" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add local media" }));
    expect(screen.getByRole("dialog", { name: "Local Media" })).toBeInTheDocument();
  });

  it("keeps setup controls in Settings and tools", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem("lorasuite:experience:v1");
    render(<App />);
    expect(screen.getByRole("button", { name: "Credentials" }).closest("details")).not.toHaveAttribute("open");
    await user.click(screen.getByText("Settings & tools"));
    expect(screen.getByRole("button", { name: "Credentials" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Support" })).toBeVisible();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the four workspace tabs", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "Data Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Prepare" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Verify Identity" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Build & Train" })).toBeInTheDocument();
  });

  it("uses the brand to return home from Advanced and later guided steps", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getByRole("tab", { name: "Data Ingest" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "LoraSuite home" }));
    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Sources" }));
    expect(screen.getByRole("heading", { name: "Give me everything you have" })).toBeVisible();
    screen.getByRole("button", { name: "LoraSuite home" }).focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "LoraSuite home" }));
    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeVisible();
  });

  it("returns a saved experimental workspace to Guided without deleting saved scene preferences", () => {
    window.localStorage.setItem("lorasuite:experience:v1", "h3");
    window.localStorage.setItem("lorasuite:h3-scene:v1", "saved-scene");
    window.localStorage.setItem("lorasuite:h3-editor:v1", "advanced");
    render(<App />);
    expect(screen.getByRole("heading", { name: "What do you want to create?" })).toBeInTheDocument();
    expect(window.localStorage.getItem("lorasuite:experience:v1")).toBe("guided");
    expect(window.localStorage.getItem("lorasuite:h3-scene:v1")).toBe("saved-scene");
    expect(window.localStorage.getItem("lorasuite:h3-editor:v1")).toBe("advanced");
    expect(screen.queryByRole("button", { name: /Experimental|H3 native/ })).not.toBeInTheDocument();
  });

  it("labels speaker verification clearly for a voice workflow", () => {
    window.localStorage.setItem("lorasuite:workflow-target:v1", "voice");
    render(<App />);

    expect(screen.getByRole("tab", { name: "Verify Speaker" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Verify Identity" })).not.toBeInTheDocument();
  });

  it("switches workspace tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Prepare" }));

    expect(await screen.findByRole("heading", { name: "Prepare Media" })).toBeInTheDocument();
    expect(screen.getByText("Images, video clips, frames, and voice tracks")).toBeInTheDocument();
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
      options: { project_id: "job_1" },
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

    await user.click(screen.getByRole("tab", { name: "Prepare" }));
    await user.click(await screen.findByRole("tab", { name: /Images/ }));
    expect((await screen.findAllByText("imported-portrait.png")).length).toBeGreaterThan(0);

    await user.click(screen.getByLabelText("Select for Identify: imported-portrait.png"));
    await user.click(screen.getByRole("button", { name: "Finish Curation" }));
    await user.click(screen.getByRole("button", { name: "Start Identity Verification" }));

    expect(await screen.findByRole("heading", { name: "Face Identity" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Verify Identity" })).toHaveAttribute("aria-selected", "true");
    expect((await screen.findAllByText("imported-portrait.png")).length).toBeGreaterThan(0);
    expect(
      within(screen.getByLabelText("Dataset health")).getByText("Candidates"),
    ).toBeInTheDocument();
  });

  it("keeps ingress candidates when switching away from data ingress", async () => {
    const user = userEvent.setup();
    const scanResult = {
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
      };
    const fetchMock = vi.fn().mockImplementation(async (input: string, init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => input.endsWith("/ingress/social-acquisitions") && init?.method === "POST"
        ? {
            id: "social_1",
            request: {
              provider: "instagram",
              url: "https://www.instagram.com/marysuecurtis/",
              browser: "chrome",
            },
            request_fingerprint: "fingerprint",
            status: "complete",
            attempt: 1,
            max_attempts: 3,
            progress_message: "Retrieved 1 candidate record",
            cancel_requested: false,
            result: scanResult,
            created_at: "2026-07-16T00:00:00Z",
            updated_at: "2026-07-16T00:00:01Z",
          }
        : [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/",
    );
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(await screen.findByText("persisted candidate")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Prepare" }));
    expect(await screen.findByRole("heading", { name: "Prepare Media" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data Ingest" }));

    expect(screen.getByText("persisted candidate")).toBeInTheDocument();
  });

  it("shows the persistent dataset compiler and RunComfy handoff", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Build & Train" }));

    expect(await screen.findByRole("heading", { name: "Dataset Compiler" })).toBeInTheDocument();
    expect(screen.getByLabelText("Project")).toBeInTheDocument();
    expect(screen.getByLabelText("Output folder")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export Dataset" }),
    ).toBeInTheDocument();
  });

  it("opens the Train compiler selected by the persisted workflow target", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("lorasuite:workflow-target:v1", "video");
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Build & Train" }));

    expect(await screen.findByRole("tab", { name: "Video Dataset" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Video Dataset Compiler")).toBeInTheDocument();
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
    expect(screen.queryByLabelText("Local media paths")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));

    expect(screen.getByLabelText("Instagram helper payload")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Scan Instagram Helper Payload" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load Helper Candidates" })).toBeInTheDocument();
    expect(screen.getByLabelText("Local media paths")).toBeInTheDocument();
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

describe("loadVaultMediaProgressively", () => {
  it("publishes the first snapshot page before hydrating the remainder", async () => {
    const firstItems = [{ id: "media_1", media_type: "image" as const }];
    const nextItems = [{ id: "media_2", media_type: "video" as const }];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: firstItems, offset: 0, limit: 250, total: 2, has_more: true, next_offset: 1, snapshot: "stable" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: nextItems, offset: 1, limit: 250, total: 2, has_more: false, next_offset: null, snapshot: "stable" }),
      });
    const firstPage = vi.fn();
    const nextPage = vi.fn();

    const result = await loadVaultMediaProgressively(createEngineClient("http://engine.test", fetchMock), {
      canceled: () => false,
      onFirstPage: firstPage,
      onNextPage: nextPage,
    });

    expect(firstPage).toHaveBeenCalledWith(firstItems);
    expect(nextPage).toHaveBeenCalledWith(nextItems);
    expect(result).toEqual([...firstItems, ...nextItems]);
    expect(fetchMock.mock.calls[1]?.[0]).toContain("snapshot=stable");
  });

  it("restarts once when the vault snapshot changes between pages", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [{ id: "old", media_type: "image" }], offset: 0, limit: 250, total: 2, has_more: true, next_offset: 1, snapshot: "old" }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: "Vault media changed while this page set was loading; restart from the first page." }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [{ id: "new", media_type: "image" }], offset: 0, limit: 250, total: 1, has_more: false, next_offset: null, snapshot: "new" }),
      });
    const firstPage = vi.fn();

    const result = await loadVaultMediaProgressively(createEngineClient("http://engine.test", fetchMock), {
      canceled: () => false,
      onFirstPage: firstPage,
      onNextPage: vi.fn(),
    });

    expect(firstPage).toHaveBeenNthCalledWith(1, [{ id: "old", media_type: "image" }]);
    expect(firstPage).toHaveBeenNthCalledWith(2, [{ id: "new", media_type: "image" }]);
    expect(result).toEqual([{ id: "new", media_type: "image" }]);
  });
});
