import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { CurateSearchTab } from "./CurateSearchTab";
import type { EngineClient } from "../lib/api";
import type { MediaItem, ProcessingJob } from "../lib/types";

const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: isTauriMock,
}));

describe("CurateSearchTab", () => {
  type CurateSearchEngine = Pick<
    EngineClient,
    | "assetUrl"
    | "createProcessingJob"
    | "getProcessingJob"
    | "listProcessingJobs"
    | "processProcessingJob"
  >;

  const mediaItems: MediaItem[] = [
    {
      id: "media_portrait",
      raw_path: "/tmp/vault/raw/portrait.png",
      media_type: "image",
      width: 768,
      height: 1024,
      status: "new",
      metadata_json: {
        original_path: "/Volumes/Training/MarySue/portrait.png",
      },
    },
    {
      id: "media_voice",
      raw_path: "/tmp/vault/raw/voice.m4a",
      media_type: "audio",
      duration: 12.4,
      status: "new",
    },
    {
      id: "media_video",
      raw_path: "/tmp/vault/raw/video.mp4",
      media_type: "video",
      duration: 42,
      status: "new",
    },
  ];

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("searches imported media by path and metadata", async () => {
    const user = userEvent.setup();
    const engine = engineStub();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Search media"), "MarySue");

    expect(screen.getByText("portrait.png")).toBeInTheDocument();
    expect(screen.queryByText("voice.m4a")).not.toBeInTheDocument();
    expect(screen.getByText("1 visible")).toBeInTheDocument();
  });

  it("filters by media type and tracks selected dataset items", async () => {
    const user = userEvent.setup();
    const assetUrl = vi.fn((path: string) => `/asset/${path}`);
    const engine = engineStub({ assetUrl });

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Media type"), "audio");

    expect(screen.queryByText("portrait.png")).not.toBeInTheDocument();
    expect(screen.getByText("voice.m4a")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select for Identify: voice.m4a"));

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(assetUrl).toHaveBeenCalledWith("/tmp/vault/raw/portrait.png");
  });

  it("sends selected images to Identify and leaves voice out", async () => {
    const user = userEvent.setup();
    const onSendToIdentify = vi.fn();
    const engine = engineStub();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={onSendToIdentify}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText("Select for Identify: portrait.png"));
    await user.click(screen.getByLabelText("Select for Identify: voice.m4a"));
    await user.click(screen.getByRole("button", { name: "Send to Identify" }));

    expect(onSendToIdentify).toHaveBeenCalledWith([mediaItems[0]]);
    expect(screen.getByText("Sent 1 image candidate to Identify.")).toBeInTheDocument();
  });

  it("launches video breakdown jobs and emits generated derivative media", async () => {
    const user = userEvent.setup();
    const generatedItems: MediaItem[] = [
      {
        id: "media_frame_1",
        raw_path: "/tmp/vault/derived/video/frame-0001.png",
        media_type: "image",
        width: 1920,
        height: 1080,
        status: "new",
      },
      {
        id: "media_audio_1",
        raw_path: "/tmp/vault/derived/video/audio.wav",
        media_type: "audio",
        duration: 42,
        status: "new",
      },
    ];
    const engine = engineStub({
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      createProcessingJob: vi.fn().mockResolvedValue({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: true,
          extract_audio: true,
        },
        status: "queued",
        progress_message: "Queued",
        errors: [],
        derived_media_items: [],
        created_at: "2026-07-09T00:00:00Z",
      }),
      getProcessingJob: vi.fn().mockResolvedValue({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: true,
          extract_audio: true,
        },
        status: "complete",
        progress_message: "Generated derivatives",
        errors: [],
        derived_media_items: generatedItems,
        created_at: "2026-07-09T00:00:00Z",
        completed_at: "2026-07-09T00:00:01Z",
      }),
    });
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    await user.click(screen.getByLabelText("Select for Breakdown: video.mp4"));
    await user.click(screen.getByRole("button", { name: "Break Down Selected Videos" }));

    await waitFor(() =>
      expect(engine.createProcessingJob).toHaveBeenCalledWith({
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: true,
          extract_audio: true,
        },
      }),
    );
    expect(engine.getProcessingJob).toHaveBeenCalledWith("processing_1");
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(generatedItems);
    expect(screen.getByText("Generated 2 derivative media items.")).toBeInTheDocument();
  });

  it("reuses existing non-terminal breakdown jobs for the same selected videos", async () => {
    const user = userEvent.setup();
    const generatedItems: MediaItem[] = [
      {
        id: "media_frame_reused",
        raw_path: "/tmp/vault/derived/video/frame-reused.png",
        media_type: "image",
        width: 1920,
        height: 1080,
        status: "new",
      },
    ];
    const engine = engineStub({
      listProcessingJobs: vi.fn().mockResolvedValue([
        processingJob({
          id: "processing_existing",
          source_media_item_ids: ["media_video"],
          status: "running",
        }),
      ]),
      processProcessingJob: vi
        .fn()
        .mockResolvedValue(processingJob({ id: "processing_existing", status: "running" })),
      getProcessingJob: vi.fn().mockResolvedValue(
        processingJob({
          id: "processing_existing",
          status: "complete",
          derived_media_items: generatedItems,
        }),
      ),
    });
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    await user.click(screen.getByLabelText("Select for Breakdown: video.mp4"));
    await user.click(screen.getByRole("button", { name: "Break Down Selected Videos" }));

    await waitFor(() => expect(engine.listProcessingJobs).toHaveBeenCalledOnce());
    expect(engine.createProcessingJob).not.toHaveBeenCalled();
    expect(engine.processProcessingJob).toHaveBeenCalledWith("processing_existing");
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(generatedItems);
  });

  it("polls queued and running video breakdown jobs until generated media are available", async () => {
    vi.useFakeTimers();
    const generatedItems: MediaItem[] = [
      {
        id: "media_frame_polled",
        raw_path: "/tmp/vault/derived/video/frame-polled.png",
        media_type: "image",
        width: 1920,
        height: 1080,
        status: "new",
      },
    ];
    const engine = engineStub({
      createProcessingJob: vi.fn().mockResolvedValue(processingJob({ status: "queued" })),
      getProcessingJob: vi
        .fn()
        .mockResolvedValueOnce(processingJob({ status: "queued" }))
        .mockResolvedValueOnce(
          processingJob({ status: "running", progress_message: "Extracting frames" }),
        )
        .mockResolvedValueOnce(
          processingJob({
            status: "complete",
            progress_message: "Generated derivatives",
            derived_media_items: generatedItems,
          }),
        ),
    });
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    fireEvent.click(screen.getByLabelText("Select for Breakdown: video.mp4"));
    fireEvent.click(screen.getByRole("button", { name: "Break Down Selected Videos" }));

    await act(flushPromises);
    expect(engine.getProcessingJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(engine.getProcessingJob).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await flushPromises();
    });
    expect(engine.getProcessingJob).toHaveBeenCalledTimes(3);
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(generatedItems);
    expect(screen.getByText("Generated 1 derivative media item.")).toBeInTheDocument();
  });

  it("keeps polling video breakdown jobs beyond the first few queued checks", async () => {
    vi.useFakeTimers();
    const generatedItems: MediaItem[] = [
      {
        id: "media_frame_delayed",
        raw_path: "/tmp/vault/derived/video/frame-delayed.png",
        media_type: "image",
        width: 1920,
        height: 1080,
        status: "new",
      },
    ];
    const getProcessingJob = vi.fn();
    for (let index = 0; index < 6; index += 1) {
      getProcessingJob.mockResolvedValueOnce(
        processingJob({
          status: index % 2 === 0 ? "queued" : "running",
          progress_message: "Still processing",
        }),
      );
    }
    getProcessingJob.mockResolvedValueOnce(
      processingJob({
        status: "complete",
        progress_message: "Generated derivatives",
        derived_media_items: generatedItems,
      }),
    );
    const engine = engineStub({
      createProcessingJob: vi.fn().mockResolvedValue(processingJob({ status: "queued" })),
      getProcessingJob,
    });
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    fireEvent.click(screen.getByLabelText("Select for Breakdown: video.mp4"));
    fireEvent.click(screen.getByRole("button", { name: "Break Down Selected Videos" }));

    await act(flushPromises);
    expect(getProcessingJob).toHaveBeenCalledTimes(1);

    for (let index = 0; index < 6; index += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
        await flushPromises();
      });
    }

    expect(getProcessingJob).toHaveBeenCalledTimes(7);
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(generatedItems);
    expect(screen.getByText("Generated 1 derivative media item.")).toBeInTheDocument();
  });

  it("ignores repeated breakdown clicks while a processing job is in flight", async () => {
    const user = userEvent.setup();
    let resolveCreatedJob: (job: ProcessingJob) => void = () => {};
    const createdJobPromise = new Promise<ProcessingJob>((resolve) => {
      resolveCreatedJob = resolve;
    });
    const engine = engineStub({
      createProcessingJob: vi.fn(() => createdJobPromise),
      getProcessingJob: vi
        .fn()
        .mockResolvedValue(processingJob({ status: "complete", derived_media_items: [] })),
    });

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText("Select for Breakdown: video.mp4"));
    const breakdownButton = screen.getByRole("button", { name: "Break Down Selected Videos" });

    await user.click(breakdownButton);
    await user.click(breakdownButton);

    expect(engine.createProcessingJob).toHaveBeenCalledTimes(1);
    expect(breakdownButton).toBeDisabled();

    resolveCreatedJob(processingJob({ status: "queued" }));
    await waitFor(() => expect(engine.getProcessingJob).toHaveBeenCalledWith("processing_1"));
  });

  it("preserves Curate search state when switching workspace tabs", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(true);
    window.localStorage.clear();
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: ["candidate_poster", "candidate_voice"],
      reviewed_candidate_ids: ["candidate_poster", "candidate_voice"],
      candidate_count: 2,
      selected_count: 2,
      imported_count: 2,
      deferred_count: 0,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [
        {
          id: "media_curate_portrait",
          raw_path: "/tmp/vault/raw/curate-portrait.png",
          media_type: "image",
          width: 768,
          height: 1024,
          status: "new",
        },
        {
          id: "media_curate_voice",
          raw_path: "/tmp/vault/raw/curate-voice.m4a",
          media_type: "audio",
          duration: 12.4,
          status: "new",
        },
      ],
      created_at: "2026-07-09T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [completedJob],
      }),
    );

    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Curate" }));
    expect(await screen.findByText("curate-portrait.png")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search media"), "portrait");
    expect(screen.queryByText("curate-voice.m4a")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Identify" }));
    await user.click(screen.getByRole("tab", { name: "Curate" }));

    expect(screen.getByLabelText("Search media")).toHaveValue("portrait");
    expect(screen.getByText("curate-portrait.png")).toBeInTheDocument();
    expect(screen.queryByText("curate-voice.m4a")).not.toBeInTheDocument();
  });

  function engineStub(overrides: Partial<CurateSearchEngine> = {}): CurateSearchEngine {
    return {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      createProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job")),
      getProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job detail")),
      processProcessingJob: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected processing job process")),
      ...overrides,
    };
  }

  function processingJob(overrides: Partial<ProcessingJob> = {}): ProcessingJob {
    return {
      id: "processing_1",
      job_type: "video_breakdown",
      source_media_item_ids: ["media_video"],
      options: {
        generate_frames: true,
        extract_audio: true,
      },
      status: "queued",
      progress_message: "Queued",
      errors: [],
      derived_media_items: [],
      created_at: "2026-07-09T00:00:00Z",
      ...overrides,
    };
  }

  async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
  }
});
