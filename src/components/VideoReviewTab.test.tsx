import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MediaItem, ProcessingJob, VideoBreakdownAnalysis } from "../lib/types";
import { VideoReviewTab } from "./VideoReviewTab";

describe("VideoReviewTab", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("replays real frame decisions and collapses discarded frames", async () => {
    vi.useFakeTimers();
    const analysis = videoAnalysis();

    render(
      <VideoReviewTab
        analysis={analysis}
        job={processingJob(analysis)}
        sourceItem={sourceVideo}
        engine={{ assetUrl, commitVideoBreakdown: vi.fn() }}
        onBack={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    expect(screen.getByText("Analyzing source frames")).toBeInTheDocument();
    for (let step = 0; step < 5; step += 1) {
      await act(async () => vi.advanceTimersByTimeAsync(1000));
    }

    expect(screen.getByText("1 strongest frames ready for review")).toBeInTheDocument();
    expect(screen.queryByTitle("0:01.0 · near duplicate")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show 1 collapsed frames from range 1" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show discarded" })).toBeInTheDocument();
  });

  it("promotes an overridden frame and returns reviewed keepers to Curate", async () => {
    const analysis = videoAnalysis();
    const promotedAnalysis = videoAnalysis();
    promotedAnalysis.frames[1] = {
      ...promotedAnalysis.frames[1],
      decision: "keeper",
      reasons: ["user selected"],
      output_media_item_id: "media_frame_2",
    };
    const derivedItems: MediaItem[] = [
      { id: "media_frame_1", media_type: "image", raw_path: "/vault/frame-1.png" },
      { id: "media_frame_2", media_type: "image", raw_path: "/vault/frame-2.png" },
    ];
    const updatedJob = processingJob(promotedAnalysis, derivedItems);
    const commitVideoBreakdown = vi.fn().mockResolvedValue(updatedJob);
    const onMediaItemsGenerated = vi.fn();

    render(
      <VideoReviewTab
        analysis={analysis}
        job={processingJob(analysis, derivedItems.slice(0, 1))}
        sourceItem={sourceVideo}
        engine={{ assetUrl, commitVideoBreakdown }}
        onBack={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    fireEvent.click(await screen.findByTitle("0:01.0 · near duplicate"));
    fireEvent.click(screen.getByRole("button", { name: "Commit Breakdown" }));

    await waitFor(() =>
      expect(commitVideoBreakdown).toHaveBeenCalledWith("processing_1", {
        frame_ids: ["analysis_frame_1", "analysis_frame_2"],
        clips: [],
      }),
    );
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(derivedItems);
    expect(screen.getByText("Committed 2 frames and 0 clips to Curate")).toBeInTheDocument();
  });

  it("limits automatic thumbnail loading for long analyses", async () => {
    vi.useFakeTimers();
    const analysis = longVideoAnalysis(204);
    const trackedAssetUrl = vi.fn((path: string) => `/asset/${path}`);

    render(
      <VideoReviewTab
        analysis={analysis}
        job={processingJob(analysis)}
        sourceItem={sourceVideo}
        engine={{ assetUrl: trackedAssetUrl, commitVideoBreakdown: vi.fn() }}
        onBack={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    for (let step = 0; step < 64; step += 1) {
      await act(async () => vi.advanceTimersByTimeAsync(100));
    }

    const requestedThumbnails = new Set(
      trackedAssetUrl.mock.calls
        .map(([path]) => path)
        .filter((path) => path.includes("analysis-long-")),
    );
    expect(requestedThumbnails.size).toBeLessThanOrEqual(48);
    expect(screen.getByText("12 strongest frames ready for review")).toBeInTheDocument();
    expect(screen.getByText("204 / 204")).toBeInTheDocument();
  });

  it("stages clip decisions and trim points before committing", async () => {
    const analysis = videoAnalysis();
    analysis.clip_proposals = [
      {
        id: "clip_1",
        source_media_item_id: "media_video",
        stable_range_ids: ["stable_1"],
        start_seconds: 0,
        end_seconds: 2,
        decision: "review",
        scores: {
          quality: 0.88,
          stability: 0.82,
          identity_coverage: 0.91,
          motion: 0.18,
          scene_change: 0.04,
          aesthetic: 0.8,
        },
        reasons: ["stable visual range"],
      },
    ];
    const updatedAnalysis = structuredClone(analysis);
    updatedAnalysis.clip_proposals![0] = {
      ...updatedAnalysis.clip_proposals![0],
      start_seconds: 0.2,
      end_seconds: 1.8,
      decision: "keep",
      output_media_item_id: "media_clip_1",
    };
    const derivedItems: MediaItem[] = [
      { id: "media_frame_1", media_type: "image", raw_path: "/vault/frame-1.png" },
      { id: "media_clip_1", media_type: "video", raw_path: "/vault/clip-1.mp4" },
    ];
    const commitVideoBreakdown = vi.fn().mockResolvedValue(
      processingJob(updatedAnalysis, derivedItems),
    );

    render(
      <VideoReviewTab
        analysis={analysis}
        job={processingJob(analysis, derivedItems.slice(0, 1))}
        sourceItem={sourceVideo}
        engine={{ assetUrl, commitVideoBreakdown }}
        onBack={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "In" }), {
      target: { value: "0.2" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Out" }), {
      target: { value: "1.8" },
    });
    fireEvent.click(screen.getByRole("button", { name: "keep" }));
    fireEvent.click(screen.getByRole("button", { name: "Commit Breakdown" }));

    await waitFor(() =>
      expect(commitVideoBreakdown).toHaveBeenCalledWith("processing_1", {
        frame_ids: ["analysis_frame_1"],
        clips: [
          {
            clip_id: "clip_1",
            start_seconds: 0.2,
            end_seconds: 1.8,
            decision: "keep",
          },
        ],
      }),
    );
    expect(screen.getByText("Committed 1 frames and 1 clips to Curate")).toBeInTheDocument();
  });
});

const sourceVideo: MediaItem = {
  id: "media_video",
  media_type: "video",
  raw_path: "/vault/source.mp4",
  duration: 8,
};

function assetUrl(path: string): string {
  return `/asset/${path}`;
}

function videoAnalysis(): VideoBreakdownAnalysis {
  return {
    source_media_item_id: "media_video",
    duration_seconds: 8,
    sample_fps: 1,
    analyzer: "apple-vision",
    stable_ranges: [
      {
        id: "stable_1",
        source_media_item_id: "media_video",
        start_seconds: 0,
        end_seconds: 2,
        scene_index: 0,
        frame_ids: ["analysis_frame_1", "analysis_frame_2"],
      },
    ],
    frames: [
      {
        id: "analysis_frame_1",
        source_media_item_id: "media_video",
        timestamp_seconds: 0,
        thumbnail_path: "/vault/analysis-1.jpg",
        width: 360,
        height: 640,
        decision: "keeper",
        scores: scores(0.91),
        reasons: ["clear face", "sharp detail"],
        stable_range_id: "stable_1",
        output_media_item_id: "media_frame_1",
      },
      {
        id: "analysis_frame_2",
        source_media_item_id: "media_video",
        timestamp_seconds: 1,
        thumbnail_path: "/vault/analysis-2.jpg",
        width: 360,
        height: 640,
        decision: "duplicate",
        scores: scores(0.86),
        reasons: ["near duplicate"],
        stable_range_id: "stable_1",
        duplicate_of_frame_id: "analysis_frame_1",
      },
    ],
  };
}

function longVideoAnalysis(frameCount: number): VideoBreakdownAnalysis {
  const frameIds = Array.from({ length: frameCount }, (_, index) => `long_frame_${index}`);
  return {
    source_media_item_id: "media_video",
    duration_seconds: frameCount,
    sample_fps: 1,
    analyzer: "apple-vision",
    stable_ranges: [
      {
        id: "stable_long",
        source_media_item_id: "media_video",
        start_seconds: 0,
        end_seconds: frameCount,
        scene_index: 0,
        frame_ids: frameIds,
      },
    ],
    frames: frameIds.map((id, index) => ({
      id,
      source_media_item_id: "media_video",
      timestamp_seconds: index,
      thumbnail_path: `/vault/analysis-long-${index}.jpg`,
      width: 360,
      height: 640,
      decision: index % 17 === 0 ? "keeper" : "duplicate",
      scores: scores(index % 17 === 0 ? 0.91 : 0.74),
      reasons: [index % 17 === 0 ? "clear face" : "near duplicate"],
      stable_range_id: "stable_long",
      ...(index % 17 === 0 ? { output_media_item_id: `media_long_${index}` } : {}),
    })),
  };
}

function scores(overall: number) {
  return {
    overall,
    sharpness: 0.9,
    exposure: 0.8,
    stability: 0.88,
    detail: 0.75,
    face_quality: 0.8,
    face_area: 0.14,
    body_coverage: 0.4,
    scene_change: 0.05,
  };
}

function processingJob(
  analysis: VideoBreakdownAnalysis,
  derived_media_items: MediaItem[] = [],
): ProcessingJob {
  return {
    id: "processing_1",
    job_type: "video_breakdown",
    source_media_item_ids: ["media_video"],
    options: { intelligent_selection: true },
    status: "complete",
    progress_message: "Complete",
    errors: [],
    derived_media_items,
    video_analyses: [analysis],
    created_at: "2026-07-09T00:00:00Z",
  };
}
