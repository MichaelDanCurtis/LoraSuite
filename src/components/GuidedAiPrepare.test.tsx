import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GuidedAiPrepare } from "./GuidedAiPrepare";
import type { EngineClient } from "../lib/api";
import type { MediaItem, ProcessingJob } from "../lib/types";

const mediaItems: MediaItem[] = [
  { id: "keep", raw_path: "/vault/keep.jpg", media_type: "image", status: "new" },
  { id: "review", raw_path: "/vault/review.jpg", media_type: "image", status: "new" },
  { id: "reject", raw_path: "/vault/reject.jpg", media_type: "image", status: "new" },
];

function analysisJob(status: ProcessingJob["status"]): ProcessingJob {
  return {
    id: "analysis",
    job_type: "curation_analysis",
    source_media_item_ids: mediaItems.map((item) => item.id),
    options: {},
    status,
    progress_message: status === "complete" ? "Curation analysis complete" : "Queued",
    errors: [],
    derived_media_items: [],
    curation_analyses: status === "complete" ? [
      { media_item_id: "keep", media_type: "image", recommendation: "keep", confidence: 0.96, reasons: ["Strong identity evidence"], warnings: [], analyzer: "fixture", analyzed_at: "2026-07-19T00:00:00Z" },
      { media_item_id: "review", media_type: "image", recommendation: "review", confidence: 0.62, reasons: ["Face is partially obscured"], warnings: ["Confirm subject identity"], analyzer: "fixture", analyzed_at: "2026-07-19T00:00:00Z" },
      { media_item_id: "reject", media_type: "image", recommendation: "reject", confidence: 0.91, reasons: ["No usable subject evidence"], warnings: [], analyzer: "fixture", analyzed_at: "2026-07-19T00:00:00Z" },
    ] : [],
    created_at: "2026-07-19T00:00:00Z",
  };
}

function engineStub() {
  return {
    assetUrl: (path: string) => path,
    createCurationAnalysisJob: vi.fn().mockResolvedValue(analysisJob("queued")),
    getProcessingJob: vi.fn().mockResolvedValue(analysisJob("complete")),
    addCurationHandoff: vi.fn().mockResolvedValue({ items: [], updated_at: "2026-07-19T00:00:00Z" }),
  } as unknown as EngineClient;
}

describe("GuidedAiPrepare", () => {
  beforeEach(() => window.localStorage.clear());
  it("runs the whole AI batch before presenting one compact decision checkpoint", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const onComplete = vi.fn();
    render(
      <GuidedAiPrepare
        engine={engine}
        mediaItems={mediaItems}
        target="image"
        activeProjectId="project-1"
        onComplete={onComplete}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Let AI prepare 3 items" }));

    expect(await screen.findByRole("heading", { name: "Your first pass is ready" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 ready" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 need you" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 excluded" })).toBeInTheDocument();
    expect(engine.createCurationAnalysisJob).toHaveBeenCalledWith(["keep", "review", "reject"]);

    await user.click(screen.getByRole("button", { name: "1 need you" }));
    const dialog = screen.getByRole("dialog", { name: "1 uncertain items" });
    const decision = within(dialog).getByRole("article");
    expect(within(decision).getByText("Face is partially obscured")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Skip all" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use all" }));

    expect(screen.getByRole("button", { name: "0 need you" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "2 ready" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue with 2 selected" }));
    expect(engine.addCurationHandoff).toHaveBeenCalledWith(
      ["keep", "review"],
      "project-1",
      "image",
    );
    expect(onComplete).toHaveBeenCalledWith([mediaItems[0], mediaItems[1]]);
  });

  it("restores completed preparation and manual choices without another analysis", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const props = { engine, mediaItems, target: "image" as const, activeProjectId: "project-1", onComplete: vi.fn(), onMediaItemsGenerated: vi.fn() };
    const view = render(<GuidedAiPrepare {...props} />);
    await user.click(screen.getByRole("button", { name: "Let AI prepare 3 items" }));
    await user.click(await screen.findByRole("button", { name: "1 need you" }));
    await user.click(screen.getByRole("button", { name: "Use all" }));
    view.unmount();
    render(<GuidedAiPrepare {...props} />);
    expect(await screen.findByRole("button", { name: "Continue with 2 selected" })).toBeEnabled();
    expect(engine.createCurationAnalysisJob).toHaveBeenCalledTimes(1);
  });

  it("loads the shared preparation on a client with no browser draft", async () => {
    const engine = engineStub();
    engine.getPreparationCheckpoint = vi.fn().mockResolvedValue({ checkpoint: {
      sourceItems: mediaItems, preparedItems: mediaItems,
      evidence: analysisJob("complete").curation_analyses, includedIds: ["keep", "review"], analysisJobId: "analysis",
    } });
    engine.savePreparationCheckpoint = vi.fn().mockResolvedValue({ checkpoint: null });
    render(<GuidedAiPrepare engine={engine} mediaItems={mediaItems} target="image" activeProjectId="project-1" onComplete={vi.fn()} onMediaItemsGenerated={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Continue with 2 selected" })).toBeEnabled();
    expect(engine.getPreparationCheckpoint).toHaveBeenCalledWith("project-1", "image");
    expect(engine.createCurationAnalysisJob).not.toHaveBeenCalled();
  });

  it("reconnects to a queued analysis after remount instead of submitting it twice", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    let finish!: (job: ProcessingJob) => void;
    vi.mocked(engine.getProcessingJob).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const props = { engine, mediaItems, target: "image" as const, activeProjectId: "project-1", onComplete: vi.fn(), onMediaItemsGenerated: vi.fn() };
    const view = render(<GuidedAiPrepare {...props} />);
    await user.click(screen.getByRole("button", { name: "Let AI prepare 3 items" }));
    await waitFor(() => expect(engine.getProcessingJob).toHaveBeenCalled());
    view.unmount();
    render(<GuidedAiPrepare {...props} />);
    expect(await screen.findByRole("heading", { name: "Your first pass is ready" })).toBeInTheDocument();
    await act(async () => finish(analysisJob("complete")));
    expect(engine.createCurationAnalysisJob).toHaveBeenCalledTimes(1);
  });

  it("does not show another project's results when switching projects mid-analysis", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    let finish!: (job: ProcessingJob) => void;
    vi.mocked(engine.getProcessingJob).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const props = { engine, mediaItems, target: "image" as const, onComplete: vi.fn(), onMediaItemsGenerated: vi.fn() };
    const view = render(<GuidedAiPrepare {...props} activeProjectId="project-1" />);
    await user.click(screen.getByRole("button", { name: "Let AI prepare 3 items" }));
    view.rerender(<GuidedAiPrepare {...props} activeProjectId="project-2" />);
    await act(async () => finish(analysisJob("complete")));
    expect(screen.getByRole("button", { name: "Let AI prepare 3 items" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your first pass is ready" })).not.toBeInTheDocument();
    expect(props.onComplete).not.toHaveBeenCalled();
  });

  it("routes missing analyzer output to human review instead of silently dropping it", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.getProcessingJob).mockResolvedValue({
      ...analysisJob("complete"),
      curation_analyses: [analysisJob("complete").curation_analyses![0]],
    });
    render(
      <GuidedAiPrepare
        engine={engine}
        mediaItems={mediaItems}
        target="image"
        activeProjectId="project-1"
        onComplete={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Let AI prepare 3 items" }));

    expect(await screen.findByRole("button", { name: "2 need you" })).toBeInTheDocument();
  });

  it("materializes selected video keyframes for an image workflow", async () => {
    const user = userEvent.setup();
    const video: MediaItem = {
      id: "source-video",
      raw_path: "/vault/source.mp4",
      media_type: "video",
      status: "new",
    };
    const frame: MediaItem = {
      id: "frame-1",
      raw_path: "/vault/frame.png",
      media_type: "image",
      status: "new",
      metadata_json: {
        source_media_item_id: video.id,
        derivative_type: "video_frame",
        analysis_frame_id: "frame-choice",
      },
    };
    const staleFrameFromEarlierPass: MediaItem = {
      id: "stale-frame",
      raw_path: "/vault/stale-frame.png",
      media_type: "image",
      status: "new",
      metadata_json: {
        source_media_item_id: video.id,
        derivative_type: "video_frame",
        analysis_frame_id: "stale-frame-choice",
      },
    };
    const duplicateFrame: MediaItem = {
      id: "duplicate-frame-1",
      raw_path: "/vault/duplicate-frame.png",
      media_type: "image",
      status: "new",
      metadata_json: {
        source_media_item_id: video.id,
        derivative_type: "video_frame",
        analysis_frame_id: "duplicate-frame-choice",
      },
    };
    const breakdown: ProcessingJob = {
      id: "breakdown",
      job_type: "video_breakdown",
      source_media_item_ids: [video.id],
      options: {},
      status: "complete",
      progress_message: "Video breakdown complete",
      errors: [],
      derived_media_items: [],
      video_analyses: [{
        source_media_item_id: video.id,
        duration_seconds: 2,
        sample_fps: 4,
        analyzer: "fixture",
        frames: [{
          id: "frame-choice",
          source_media_item_id: video.id,
          timestamp_seconds: 1,
          thumbnail_path: "/vault/thumb.png",
          width: 64,
          height: 96,
          decision: "keeper",
          scores: {
            overall: 0.9,
            sharpness: 0.9,
            exposure: 0.9,
            stability: 0.9,
            detail: 0.9,
            face_quality: 0.9,
            face_area: 0.2,
            body_coverage: 0.6,
            scene_change: 0,
          },
          reasons: ["strong keyframe"],
        }, {
          id: "duplicate-frame-choice",
          source_media_item_id: video.id,
          timestamp_seconds: 1.25,
          thumbnail_path: "/vault/duplicate-thumb.png",
          width: 64,
          height: 96,
          decision: "duplicate",
          scores: {
            overall: 0.85,
            sharpness: 0.9,
            exposure: 0.9,
            stability: 0.9,
            detail: 0.9,
            face_quality: 0.9,
            face_area: 0.2,
            body_coverage: 0.6,
            scene_change: 0,
          },
          reasons: ["near duplicate"],
        }],
        stable_ranges: [],
        clip_proposals: [],
      }],
      created_at: "2026-07-19T00:00:00Z",
    };
    const committed = { ...breakdown, derived_media_items: [frame, duplicateFrame] };
    const analyzed: ProcessingJob = {
      ...analysisJob("complete"),
      source_media_item_ids: [frame.id],
      curation_analyses: [{
        media_item_id: frame.id,
        media_type: "image",
        recommendation: "keep",
        confidence: 0.95,
        reasons: ["strong identity frame"],
        warnings: [],
        analyzer: "fixture",
        analyzed_at: "2026-07-19T00:00:00Z",
      }],
    };
    const engine = {
      ...engineStub(),
      createProcessingJob: vi.fn().mockResolvedValue({ ...breakdown, status: "queued" }),
      commitVideoBreakdown: vi.fn().mockResolvedValue(committed),
      createCurationAnalysisJob: vi.fn().mockResolvedValue({ ...analyzed, status: "queued" }),
      getProcessingJob: vi.fn().mockImplementation((jobId: string) =>
        Promise.resolve(jobId === "breakdown" ? breakdown : analyzed)),
    } as unknown as EngineClient;
    const onMediaItemsGenerated = vi.fn();

    render(
      <GuidedAiPrepare
        engine={engine}
        mediaItems={[video, staleFrameFromEarlierPass]}
        target="image"
        activeProjectId="project-1"
        onComplete={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Let AI prepare 1 item" }));

    expect(await screen.findByRole("heading", { name: "Your first pass is ready" })).toBeInTheDocument();
    expect(engine.createProcessingJob).toHaveBeenCalledWith(expect.objectContaining({
      options: expect.objectContaining({ generate_frames: true, extract_audio: false }),
    }));
    expect(engine.commitVideoBreakdown).toHaveBeenCalledWith("breakdown", {
      frame_ids: ["frame-choice"],
      clips: [],
    });
    expect(engine.createCurationAnalysisJob).toHaveBeenCalledWith(["frame-1"]);
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([frame]);
  });
});
