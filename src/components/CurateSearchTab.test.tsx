import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CurateSearchTab } from "./CurateSearchTab";
import type { EngineClient } from "../lib/api";
import type { MediaItem } from "../lib/types";

describe("CurateSearchTab", () => {
  type CurateSearchEngine = Pick<
    EngineClient,
    "assetUrl" | "createProcessingJob" | "getProcessingJob"
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

  function engineStub(overrides: Partial<CurateSearchEngine> = {}): CurateSearchEngine {
    return {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      createProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job")),
      getProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job detail")),
      ...overrides,
    };
  }
});
