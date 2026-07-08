import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DataIngressTab } from "./DataIngressTab";
import type { EngineClient } from "../lib/api";
import type { IngressCandidate, IngressJob } from "../lib/types";

const { openMock } = vi.hoisted(() => ({
  openMock: vi.fn(),
}));
const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: openMock,
}));
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: isTauriMock,
}));

describe("DataIngressTab", () => {
  const instagramVideoCandidate: IngressCandidate = {
    id: "candidate_video",
    source_kind: "instagram",
    source_locator: "https://www.instagram.com/reel/example/",
    display_name: "example reel",
    media_type: "video",
    duration: 9.5,
    width: 720,
    height: 1280,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    poster_asset_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: false,
    metadata_json: {
      download_url: "https://cdninstagram.example/video.mp4",
    },
  };
  const instagramPosterCandidate: IngressCandidate = {
    id: "candidate_poster",
    source_kind: "instagram",
    source_locator: "/tmp/vault/previews/social/example.jpg",
    display_name: "example reel poster",
    media_type: "image",
    width: 720,
    height: 1280,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: true,
    metadata_json: {
      source_video_candidate_id: "candidate_video",
      local_import_path: "/tmp/vault/previews/social/example.jpg",
      asset_role: "video_poster",
    },
  };
  const instagramVoiceCandidate: IngressCandidate = {
    id: "candidate_voice",
    source_kind: "instagram",
    source_locator: "https://www.instagram.com/reel/example/#audio",
    display_name: "example reel voice",
    media_type: "audio",
    duration: 9.5,
    thumbnail_path: "/tmp/vault/previews/social/example.jpg",
    status: "ready",
    selected: false,
    metadata_json: {
      source_video_candidate_id: "candidate_video",
      download_url: "https://cdninstagram.example/video.mp4",
      asset_role: "video_audio",
    },
  };

  function engineWith(overrides: Partial<EngineClient> = {}): EngineClient {
    return {
      importLocal: vi.fn(),
      scanLocalIngress: vi.fn(),
      scanInstagramBrowserUrl: vi.fn(),
      scanInstagramHelperPayload: vi.fn(),
      listIngressCandidates: vi.fn(),
      createIngressJob: vi.fn(),
      listIngressJobs: vi.fn(),
      getIngressJob: vi.fn(),
      exportRunComfyImage: vi.fn(),
      assetUrl: vi.fn((path: string) => `http://engine.test/assets/file?path=${encodeURIComponent(path)}`),
      ...overrides,
    };
  }

  beforeEach(() => {
    openMock.mockReset();
    isTauriMock.mockReturnValue(true);
  });

  async function scanInstagramUrl(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));
  }

  it("groups Instagram reel poster candidates under separate image and video selectors", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(await screen.findByText("example reel")).toBeInTheDocument();
    expect(screen.queryByText("example reel poster")).not.toBeInTheDocument();
    expect(screen.queryByText("example reel voice")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Select as image: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();
  });

  it("renders compact review tiles with metadata over the image", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    const tile = screen.getByRole("article", { name: "example reel" });
    expect(within(tile).getByText("720x1280")).toHaveClass("thumb-meta");
    expect(within(tile).getAllByText("ready")[0]).toHaveClass("thumb-status");
    expect(within(tile).getByText("image")).toHaveClass("role-chip-label");
    expect(within(tile).getByText("video")).toHaveClass("role-chip-label");
    expect(within(tile).getByText("voice")).toHaveClass("role-chip-label");
    expect(within(tile).queryByText("Select as image")).not.toBeInTheDocument();
    expect(container.querySelector(".role-statuses")).toBeNull();
  });

  it("selects all image, video, or voice roles independently", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Images" }));

    expect(screen.getByLabelText("Select as image: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Videos" }));

    expect(screen.getByLabelText("Select as image: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    await user.click(screen.getByRole("button", { name: "Select All Voice" }));

    expect(screen.getByLabelText("Select as image: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as video: example reel")).not.toBeChecked();
    expect(screen.getByLabelText("Select as voice: example reel")).toBeChecked();
  });

  it("uses one Tauri local media picker for files and folders", async () => {
    const user = userEvent.setup();
    openMock.mockResolvedValue(["/tmp/portrait.png", "/tmp/session-folder"]);
    const scanLocalIngress = vi.fn().mockResolvedValue({
      id: "scan_local",
      candidates: [instagramPosterCandidate],
      errors: [],
    });
    const engine = engineWith({ scanLocalIngress });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Import Media" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Files" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Folder" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import Media" }));

    expect(openMock).toHaveBeenCalledWith({
      multiple: true,
      recursive: true,
      title: "Choose files or folders",
    });
    expect(scanLocalIngress).toHaveBeenCalledWith(["/tmp/portrait.png", "/tmp/session-folder"], true);
  });

  it("uses browser-safe local controls outside Tauri", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(false);
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Import Media" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose Destination" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Path Scan" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desktop Picker" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Desktop Only" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Path Scan" }));

    expect(screen.getByLabelText("Manual path fallback")).toBeInTheDocument();
    expect(openMock).not.toHaveBeenCalled();
  });

  it("selects the media destination with a folder picker", async () => {
    const user = userEvent.setup();
    openMock.mockResolvedValue("/Volumes/Training/MarySue");
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose Destination" }));

    expect(openMock).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: "Choose media destination",
      canCreateDirectories: true,
    });
    expect(screen.getByLabelText("Media destination")).toHaveValue("/Volumes/Training/MarySue");
  });

  it("sends the selected media destination with the ingress job", async () => {
    const user = userEvent.setup();
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
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
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    openMock.mockResolvedValue("/Volumes/Training/MarySue");
    await user.click(screen.getByRole("button", { name: "Choose Destination" }));
    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [instagramPosterCandidate.id],
      options: {
        destination_root: "/Volumes/Training/MarySue",
      },
    });
  });

  it("sends the selected Instagram scan limit to the engine", async () => {
    const user = userEvent.setup();
    const scanInstagramBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_1",
      candidates: [],
      errors: [],
    });
    const engine = engineWith({ scanInstagramBrowserUrl });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "8");
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(scanInstagramBrowserUrl).toHaveBeenCalledWith(
      "https://www.instagram.com/marysuecurtis/reels/",
      "chrome",
      8,
      undefined,
      "all",
    );
  });

  it("sends the selected Instagram scan target to the engine", async () => {
    const user = userEvent.setup();
    const scanInstagramBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_1",
      candidates: [],
      errors: [],
    });
    const engine = engineWith({ scanInstagramBrowserUrl });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/",
    );
    const scanTarget = screen.getByRole("group", { name: "Scan target" });
    expect(within(scanTarget).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(within(scanTarget).getByRole("button", { name: "Reels" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));

    expect(scanInstagramBrowserUrl).toHaveBeenCalledWith(
      "https://www.instagram.com/marysuecurtis/",
      "chrome",
      24,
      undefined,
      "reels",
    );
  });

  it("loads the next Instagram batch while preserving earlier review choices", async () => {
    const user = userEvent.setup();
    const firstBatchCandidate: IngressCandidate = {
      id: "candidate_first_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/FIRST/",
      display_name: "first batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/first.jpg",
      status: "ready",
      selected: true,
    };
    const secondBatchCandidate: IngressCandidate = {
      id: "candidate_second_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/p/SECOND/",
      display_name: "second batch image",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/second.jpg",
      status: "ready",
      selected: true,
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [secondBatchCandidate.id],
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
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const scanInstagramBrowserUrl = vi
      .fn()
      .mockResolvedValueOnce({
        id: "scan_1",
        candidates: [firstBatchCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: true,
          next_cursor: "cursor_2",
        },
      })
      .mockResolvedValueOnce({
        id: "scan_2",
        candidates: [secondBatchCandidate],
        errors: [],
        metadata_json: {
          has_next_batch: false,
        },
      });
    const createIngressJob = vi.fn().mockResolvedValue({
      ...completedJob,
      status: "queued",
      progress_message: "Queued",
    });
    const engine = engineWith({
      scanInstagramBrowserUrl,
      createIngressJob,
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.type(
      screen.getByLabelText("Instagram URL"),
      "https://www.instagram.com/marysuecurtis/reels/",
    );
    await user.clear(screen.getByLabelText("Scan limit"));
    await user.type(screen.getByLabelText("Scan limit"), "2");
    await user.click(screen.getByRole("button", { name: "Scan Instagram" }));
    await user.click(await screen.findByLabelText("Select as image: first batch image"));
    await user.click(screen.getByRole("button", { name: "Next Batch" }));

    expect(await screen.findByText("second batch image")).toBeInTheDocument();
    expect(screen.queryByText("first batch image")).not.toBeInTheDocument();
    expect(scanInstagramBrowserUrl).toHaveBeenLastCalledWith(
      "https://www.instagram.com/marysuecurtis/reels/",
      "chrome",
      2,
      "cursor_2",
      "all",
    );

    await user.click(screen.getByRole("button", { name: "Confirm Ingest" }));

    expect(createIngressJob).toHaveBeenCalledWith({
      source_kind: "instagram",
      candidate_ids: [secondBatchCandidate.id],
    });
  });

  it("opens a source preview for video candidates", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramVideoCandidate, instagramPosterCandidate, instagramVoiceCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "Preview video: example reel" }));

    expect(
      screen.getByRole("dialog", { name: "Video preview: example reel" }),
    ).toBeInTheDocument();
    expect(container.querySelector("iframe")?.getAttribute("src")).toBe(
      "https://www.instagram.com/reel/example/",
    );
  });

  it("renders delayed enlarged image previews for thumbnails", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);

    expect(screen.getByAltText("Enlarged preview for example reel poster")).toHaveClass(
      "hover-preview",
    );
  });

  it("keeps helper payload and manual path fallback behind advanced controls", async () => {
    const user = userEvent.setup();
    const engine = engineWith();

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));

    expect(screen.getByLabelText("Instagram URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Browser cookies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan Instagram" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Instagram helper payload")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Manual path fallback")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));

    expect(screen.getByLabelText("Instagram helper payload")).toBeInTheDocument();
    expect(screen.getByLabelText("Manual path fallback")).toBeInTheDocument();
  });

  it("includes thumbnails in list view", async () => {
    const user = userEvent.setup();
    const engine = engineWith({
      scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [instagramPosterCandidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await scanInstagramUrl(user);
    await user.click(screen.getByRole("button", { name: "List" }));

    const image = container.querySelector(".candidate-list img");
    expect(image).not.toBeNull();
    expect(image?.getAttribute("src")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fsocial%2Fexample.jpg",
    );
  });

  it("shows deferred original downloads in the ingress job table", async () => {
    const user = userEvent.setup();
    const candidate: IngressCandidate = {
      id: "candidate_video",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/reel/example/",
      display_name: "example reel",
      media_type: "video",
      duration: 9.5,
      status: "ready",
      selected: true,
      metadata_json: {
        download_url: "https://cdninstagram.example/video.mp4",
      },
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [candidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 0,
      deferred_count: 1,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; original downloads deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const engine: EngineClient = engineWith({
      scanInstagramBrowserUrl: vi.fn(),
      scanInstagramHelperPayload: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [candidate],
        errors: [],
      }),
      createIngressJob: vi.fn().mockResolvedValue({
        ...completedJob,
        status: "queued",
        progress_message: "Queued",
      }),
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
    });

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram Helper Payload" }));
    await user.click(await screen.findByRole("button", { name: "Confirm Ingest" }));

    const jobsTable = await screen.findByRole("table");
    expect(within(jobsTable).getByRole("columnheader", { name: "Deferred" })).toBeInTheDocument();
    expect(within(jobsTable).getAllByRole("cell", { name: "1" })).toHaveLength(2);
    expect(
      screen.getByText("Ingress complete; original downloads deferred: 0 imported, 1 deferred, 0 failed."),
    ).toBeInTheDocument();
  });

  it("renders scanned thumbnails through the engine asset endpoint", async () => {
    const user = userEvent.setup();
    const candidate: IngressCandidate = {
      id: "candidate_image",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/reel/example/#poster",
      display_name: "example poster",
      media_type: "image",
      thumbnail_path: "/tmp/vault/previews/social/poster.jpg",
      status: "ready",
      selected: true,
    };
    const engine: EngineClient = engineWith({
      scanInstagramHelperPayload: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [candidate],
        errors: [],
      }),
    });

    const { container } = render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.click(screen.getByRole("button", { name: "Advanced Fallbacks" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram Helper Payload" }));

    const image = container.querySelector("img");
    expect(image).not.toBeNull();
    expect(image?.getAttribute("src")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fsocial%2Fposter.jpg",
    );
    expect(engine.assetUrl).toHaveBeenCalledWith("/tmp/vault/previews/social/poster.jpg");
  });
});
