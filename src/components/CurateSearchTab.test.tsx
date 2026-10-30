import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { CurateSearchTab } from "./CurateSearchTab";
import type { EngineClient } from "../lib/api";
import type { CurationAnalysisEvidence, MediaItem, ProcessingJob } from "../lib/types";

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
    | "rotateVaultImage"
    | "createProcessingJob"
    | "getProcessingJob"
    | "listProcessingJobs"
    | "processProcessingJob"
    | "updateVideoKeepers"
    | "commitVideoBreakdown"
    | "addCurationHandoff"
    | "rejectCurationMedia"
    | "restoreCurationAudio"
    | "createCurationAnalysisJob"
    | "getAudioCleaningRecipe"
    | "previewAudioCleaning"
    | "renderAudioCleaning"
    | "getAudioSeparationStatus"
    | "installAudioSeparationModel"
    | "createAudioCleaningJob"
  > & Partial<Pick<EngineClient, "listExactDuplicateClusters">>;

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

    await user.click(screen.getByRole("button", { name: "Open media search" }));
    await user.type(screen.getByLabelText("Search media"), "MarySue");

    expect(screen.getByRole("article", { name: "portrait.png" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "voice.m4a" })).not.toBeInTheDocument();
    expect(screen.getByText("1 visible")).toBeInTheDocument();
  });

  it("persists clockwise rotation for sideways image candidates", async () => {
    const user = userEvent.setup();
    const rotatedItem: MediaItem = {
      ...mediaItems[0],
      raw_path: "/tmp/vault/raw/portrait-rotated.png",
      width: 1024,
      height: 768,
      metadata_json: { rotation_degrees: 90, orientation_corrected: true },
    };
    const rotateVaultImage = vi.fn().mockResolvedValue(rotatedItem);
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub({ rotateVaultImage })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Images1" }));
    await user.click(screen.getByRole("button", { name: "Rotate Clockwise: portrait.png" }));

    expect(rotateVaultImage).toHaveBeenCalledWith("media_portrait", 90);
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([rotatedItem]);
    expect(screen.getByText("Rotated portrait.png clockwise.")).toBeInTheDocument();
  });

  it("removes exact content duplicates from counts and candidate cards", async () => {
    const user = userEvent.setup();
    const duplicateItems: MediaItem[] = [
      { ...mediaItems[0], sha256: "same-image-content" },
      {
        ...mediaItems[0],
        id: "media_portrait_duplicate",
        sha256: "same-image-content",
      },
    ];

    render(
      <CurateSearchTab
        mediaItems={duplicateItems}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Images/ }));

    expect(screen.getAllByRole("article", { name: "portrait.png" })).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Images1/ })).toBeInTheDocument();
  });

  it("shows retained provenance for exact duplicates", async () => {
    const user = userEvent.setup();
    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub({
          listExactDuplicateClusters: vi.fn().mockResolvedValue([
            {
              id: "duplicate_same",
              media_type: "image",
              sha256: "same",
              canonical_media_item_id: "media_portrait",
              canonical_raw_path: "/tmp/vault/raw/portrait.png",
              duplicate_count: 1,
              media_item_ids: ["media_portrait"],
              source_bundle_keys: ["instagram:post:one", "instagram:post:two"],
              original_paths: ["/imports/one.png", "/imports/two.png"],
              origins: [],
            },
          ]),
        })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Duplicates (1)" }));

    expect(screen.getByRole("dialog", { name: "Exact Duplicates" })).toBeInTheDocument();
    expect(screen.getByText("/imports/one.png")).toBeInTheDocument();
    expect(screen.getByText("2 source bundles retained")).toBeInTheDocument();
  });

  it("loads large media libraries in bounded render pages", async () => {
    const user = userEvent.setup();
    const largeLibrary: MediaItem[] = Array.from({ length: 100 }, (_, index) => ({
      id: `media_${index}`,
      raw_path: `/tmp/vault/raw/image-${index}.png`,
      media_type: "image",
      sha256: `digest-${index}`,
      width: 768,
      height: 1024,
      metadata_json: { display_name: `image-${index}.png` },
    }));
    render(
      <CurateSearchTab
        mediaItems={largeLibrary}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Images100" }));

    expect(screen.getAllByRole("article")).toHaveLength(84);
    expect(screen.getByText("84 of 100 loaded")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load 16 more" }));
    expect(screen.getAllByRole("article")).toHaveLength(100);
  });

  it("opens image candidates in an expanded preview", async () => {
    const user = userEvent.setup();
    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Images/ }));
    await user.click(screen.getByRole("button", { name: "Expand preview: portrait.png" }));

    expect(screen.getByRole("dialog", { name: "Expanded preview: portrait.png" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close expanded preview" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("switches curation lanes and tracks selected dataset items", async () => {
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

    await user.click(screen.getByRole("tab", { name: /Audio/ }));

    expect(screen.queryByText("portrait.png")).not.toBeInTheDocument();
    expect(screen.getByText("voice.m4a")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select for Identify: voice.m4a"));

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(assetUrl).toHaveBeenCalledWith("/tmp/vault/raw/portrait.png");
  });

  it("reviews one audio track with honest signal evidence and explicit decisions", async () => {
    const user = userEvent.setup();
    const evidence: CurationAnalysisEvidence = {
      ...curationEvidence("media_voice", "audio", "review"),
      active_audio_ratio: 0.64,
      clipping_ratio: 0.01,
      transcript: "This is a useful voice sample.",
      language: "en",
      speech_duration_ratio: 0.35,
      transcript_confidence: 0.91,
      word_count: 6,
      speaker_count: 1,
      reasons: ["speaker ownership and speech content require verification"],
    };
    const existingAnalysis = processingJob({
      id: "processing_audio_existing",
      job_type: "curation_analysis",
      status: "complete",
      source_media_item_ids: ["media_voice"],
      curation_analyses: [evidence],
    });
    const refreshedAnalysis = processingJob({
      id: "processing_audio_new",
      job_type: "curation_analysis",
      status: "complete",
      source_media_item_ids: ["media_voice"],
      curation_analyses: [evidence],
    });
    const createCurationAnalysisJob = vi.fn().mockResolvedValue(
      processingJob({
        id: "processing_audio_new",
        job_type: "curation_analysis",
        source_media_item_ids: ["media_voice"],
      }),
    );
    const getProcessingJob = vi.fn().mockResolvedValue(refreshedAnalysis);
    const rejectCurationMedia = vi.fn().mockResolvedValue([]);
    const cleaningRecipe = {
      media_item_id: "media_voice",
      high_pass_hz: 80,
      low_pass_hz: 14000,
      noise_floor_db: -55,
      noise_reduction_db: 6,
      gate_threshold_db: -55,
      presence_gain_db: 0,
      normalize: true,
      isolate_voice: false,
    };
    const previewAudioCleaning = vi.fn().mockResolvedValue({
      recipe: cleaningRecipe,
      preview_path: "/tmp/vault/derivatives/audio_cleaning/preview.wav",
      recipe_digest: "clean123",
      separation_available: false,
      isolation_applied: false,
      warnings: [],
    });
    const renderedAudioItem: MediaItem = {
      id: "media_voice_clean",
      raw_path: "/tmp/vault/derivatives/audio_cleaning/clean.wav",
      media_type: "audio",
      status: "new",
    };
    const renderAudioCleaning = vi.fn().mockResolvedValue({
      recipe: cleaningRecipe,
      preview_path: "/tmp/vault/derivatives/audio_cleaning/preview.wav",
      recipe_digest: "clean123",
      separation_available: false,
      isolation_applied: false,
      warnings: [],
      rendered_media_item: renderedAudioItem,
    });
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub({
          listProcessingJobs: vi.fn().mockResolvedValue([existingAnalysis]),
          createCurationAnalysisJob,
          getProcessingJob,
          rejectCurationMedia,
          getAudioCleaningRecipe: vi.fn().mockResolvedValue(cleaningRecipe),
          previewAudioCleaning,
          renderAudioCleaning,
        })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    await user.click(screen.getByRole("button", { name: "Open audio review: voice.m4a" }));

    expect(screen.getByRole("region", { name: "Audio review: voice.m4a" })).toBeInTheDocument();
    expect(screen.getByText("6 words detected")).toBeInTheDocument();
    expect(screen.getByText("This is a useful voice sample.")).toBeInTheDocument();
    expect(screen.getByText(/91% transcript confidence/)).toBeInTheDocument();
    expect(screen.getByText("64%")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(screen.getByText("36%")).toBeInTheDocument();
    expect(screen.getByText("1%")).toBeInTheDocument();
    expect(screen.getByText(/intended speaker still requires/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Recipe ready/)).toBeInTheDocument());
    expect(await screen.findByText("UVR vocal isolation is ready")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Isolate voice" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(previewAudioCleaning).toHaveBeenCalledWith("media_voice", cleaningRecipe));
    expect(screen.getByRole("button", { name: "B Processed" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Render Derivative" }));
    await waitFor(() => expect(renderAudioCleaning).toHaveBeenCalledWith("media_voice", cleaningRecipe));
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([renderedAudioItem]);

    await user.click(screen.getByRole("button", { name: "Analyze Track" }));
    await waitFor(() => expect(createCurationAnalysisJob).toHaveBeenCalledWith(["media_voice"]));
    expect(getProcessingJob).toHaveBeenCalledWith("processing_audio_new");

    await user.click(screen.getByRole("button", { name: "Keep for Identify" }));
    expect(screen.getByRole("button", { name: "Selected" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(rejectCurationMedia).toHaveBeenCalledWith(["media_voice"]));
    expect(screen.queryByRole("region", { name: "Audio review: voice.m4a" })).not.toBeInTheDocument();
  });

  it("isolates and cleans selected audio as one persistent batch job", async () => {
    const user = userEvent.setup();
    const cleanedAudio: MediaItem = {
      id: "media_voice_clean",
      raw_path: "/tmp/vault/derivatives/audio_cleaning/clean.wav",
      media_type: "audio",
      status: "new",
      metadata_json: {
        derivative_type: "audio_clean",
        source_media_item_id: "media_voice",
        voice_isolation_applied: true,
      },
    };
    const queued = processingJob({
      id: "processing_audio_clean",
      job_type: "audio_cleaning",
      source_media_item_ids: ["media_voice"],
      progress_message: "Queued",
    });
    const completed = processingJob({
      ...queued,
      status: "complete",
      progress_message: "Voice preparation complete: 1 prepared",
      derived_media_items: [cleanedAudio],
    });
    const createAudioCleaningJob = vi.fn().mockResolvedValue(queued);
    const getProcessingJob = vi.fn().mockResolvedValue(completed);
    const onMediaItemsGenerated = vi.fn();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub({ createAudioCleaningJob, getProcessingJob })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    await user.click(screen.getByRole("button", { name: "Select All" }));
    const isolateButton = await screen.findByRole("button", { name: "Isolate & Clean (1)" });
    await waitFor(() => expect(isolateButton).toBeEnabled());
    await user.click(isolateButton);

    await waitFor(() => expect(createAudioCleaningJob).toHaveBeenCalledWith(["media_voice"], true));
    expect(getProcessingJob).toHaveBeenCalledWith("processing_audio_clean");
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([cleanedAudio]);
    expect(screen.getByText("Generated 1 derivative media item.")).toBeInTheDocument();
  });

  it("scrubs video and audio with the scroll wheel", async () => {
    const user = userEvent.setup();
    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    const video = screen.getByRole("article", { name: "video.mp4" }).querySelector("video");
    expect(video).not.toBeNull();
    if (!video) throw new Error("Expected video preview");
    Object.defineProperty(video, "duration", { configurable: true, value: 42 });
    video.currentTime = 10;
    fireEvent.wheel(video, { deltaMode: 0, deltaY: 90 });
    expect(video.currentTime).toBe(12);
    expect(screen.getByText("0:12")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    const audioPreview = screen
      .getByRole("article", { name: "voice.m4a" })
      .querySelector<HTMLElement>(".audio-preview");
    const audio = audioPreview?.querySelector("audio") ?? null;
    expect(audioPreview).not.toBeNull();
    expect(audio).not.toBeNull();
    if (!audioPreview || !audio) throw new Error("Expected audio preview");
    Object.defineProperty(audio, "duration", { configurable: true, value: 12.4 });
    audio.currentTime = 10;
    fireEvent.wheel(audioPreview, { deltaMode: 0, deltaY: -90 });
    expect(audio.currentTime).toBe(8);
    expect(screen.getByText("0:08")).toBeInTheDocument();
  });

  it("selects and deselects all visible videos for breakdown", async () => {
    const user = userEvent.setup();
    const secondVideo: MediaItem = {
      ...mediaItems[2],
      id: "media_video_second",
      raw_path: "/tmp/vault/raw/video-second.mp4",
    };
    render(
      <CurateSearchTab
        mediaItems={[...mediaItems, secondVideo]}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    await user.click(screen.getByRole("button", { name: "Select All Videos to Prepare" }));
    expect(screen.getByLabelText("Select to Prepare: video.mp4")).toBeChecked();
    expect(screen.getByLabelText("Select to Prepare: video-second.mp4")).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Deselect All Videos" }));
    expect(screen.getByLabelText("Select to Prepare: video.mp4")).not.toBeChecked();
    expect(screen.getByLabelText("Select to Prepare: video-second.mp4")).not.toBeChecked();
  });

  it("uses AI recommendations to select video breakdown candidates", async () => {
    const user = userEvent.setup();
    const secondVideo: MediaItem = {
      ...mediaItems[2],
      id: "media_video_reject",
      raw_path: "/tmp/vault/raw/video-reject.mp4",
    };
    const analysis = processingJob({
      id: "processing_ai_video",
      job_type: "curation_analysis",
      status: "complete",
      curation_analyses: [
        curationEvidence("media_video", "video", "review"),
        curationEvidence("media_video_reject", "video", "reject"),
      ],
    });
    render(
      <CurateSearchTab
        mediaItems={[...mediaItems, secondVideo]}
        engine={engineStub({ listProcessingJobs: vi.fn().mockResolvedValue([analysis]) })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    await user.click(await screen.findByRole("button", { name: "Select AI Video Picks" }));

    expect(screen.getByLabelText("Select to Prepare: video.mp4")).toBeChecked();
    expect(screen.getByLabelText("Select to Prepare: video-reject.mp4")).not.toBeChecked();
  });

  it("stages AI decisions for review before committing or sending them", async () => {
    const user = userEvent.setup();
    const onSendToIdentify = vi.fn();
    const rejectCurationMedia = vi.fn().mockResolvedValue([]);
    const analysis = processingJob({
      id: "processing_ai_stage",
      job_type: "curation_analysis",
      status: "complete",
      curation_analyses: [
        curationEvidence("media_portrait", "image", "keep"),
        curationEvidence("media_voice", "audio", "reject"),
        curationEvidence("media_video", "video", "review"),
      ],
    });
    const engine = engineStub({
      listProcessingJobs: vi.fn().mockResolvedValue([analysis]),
      rejectCurationMedia,
    });
    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        activeProjectId="project-1"
        workflowTarget="id_lora"
        onSendToIdentify={onSendToIdentify}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Stage AI Picks" }));
    expect(rejectCurationMedia).not.toHaveBeenCalled();
    expect(engine.addCurationHandoff).not.toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: /Images/ }));
    await user.click(screen.getByLabelText("Stage Reject: portrait.png"));
    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    await user.click(screen.getByLabelText("Stage Keep: voice.m4a"));
    await user.click(screen.getByRole("button", { name: /Commit AI Picks/ }));

    expect(rejectCurationMedia).toHaveBeenCalledWith(["media_portrait"]);
    expect(engine.addCurationHandoff).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Verify Identity" }));
    await user.click(screen.getByRole("button", { name: "Start Identity Verification" }));
    expect(onSendToIdentify).toHaveBeenCalledWith([mediaItems[1]]);
  });

  it("excludes reused Instagram audio from source counts and the Audio lane", async () => {
    const user = userEvent.setup();
    const onMediaItemsGenerated = vi.fn();
    const restoreCurationAudio = vi.fn().mockResolvedValue([]);
    const reusedAudio: MediaItem = {
      id: "media_reused_audio",
      raw_path: "/tmp/vault/raw/trending-sound.m4a",
      media_type: "audio",
      metadata_json: {
        audio_original: false,
        audio_kind: "reused_or_music",
        source_bundle_key: "instagram:reused",
      },
    };
    render(
      <CurateSearchTab
        mediaItems={[...mediaItems, reusedAudio]}
        engine={engineStub({ restoreCurationAudio })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={onMediaItemsGenerated}
      />,
    );

    expect(screen.getByRole("tab", { name: /Audio/ })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "trending-sound.m4a" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    expect(screen.getByText("voice.m4a")).toBeInTheDocument();
    expect(screen.queryByText("trending-sound.m4a")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show rejected audio (1)" }));
    expect(screen.queryByText("voice.m4a")).not.toBeInTheDocument();
    expect(screen.getByText("trending-sound.m4a")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Restore Audio: trending-sound.m4a"));
    expect(restoreCurationAudio).toHaveBeenCalledWith(["media_reused_audio"]);
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([]);
    expect(screen.getByText("Restored audio after user review.")).toBeInTheDocument();
  });

  it("uses a parent video poster as the audio thumbnail", async () => {
    const user = userEvent.setup();
    const sourceBundleKey = "instagram:poster-audio";
    const bundledItems: MediaItem[] = [
      {
        ...mediaItems[0],
        metadata_json: {
          source_bundle_key: sourceBundleKey,
          asset_role: "video_poster",
        },
      },
      {
        ...mediaItems[1],
        metadata_json: { source_bundle_key: sourceBundleKey },
      },
      {
        ...mediaItems[2],
        metadata_json: { source_bundle_key: sourceBundleKey },
      },
    ];

    render(
      <CurateSearchTab
        mediaItems={bundledItems}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    const audioCard = screen.getByRole("article", { name: "voice.m4a" });
    expect(audioCard.querySelector("img")).toHaveAttribute(
      "src",
      "/asset//tmp/vault/raw/portrait.png",
    );
  });

  it("persists and sends selected image and audio candidates to Identify", async () => {
    const user = userEvent.setup();
    const onSendToIdentify = vi.fn();
    const engine = engineStub();

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        activeProjectId="project-1"
        workflowTarget="id_lora"
        onSendToIdentify={onSendToIdentify}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Images/ }));
    await user.click(screen.getByLabelText("Select for Identify: portrait.png"));
    await user.click(screen.getByRole("tab", { name: /Audio/ }));
    await user.click(screen.getByLabelText("Select for Identify: voice.m4a"));
    await user.click(screen.getByRole("button", { name: "Verify Identity" }));
    expect(screen.getByRole("dialog", { name: "Identity Verification" })).toBeInTheDocument();
    expect(screen.getByText("2 prepared candidates")).toBeInTheDocument();
    expect(screen.getByText("Video Subject")).toBeInTheDocument();
    expect(screen.getByText("Speaker")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start Identity Verification" }));

    expect(engine.addCurationHandoff).toHaveBeenCalledWith(
      ["media_portrait", "media_voice"],
      "project-1",
      "id_lora",
    );
    expect(onSendToIdentify).toHaveBeenCalledWith([mediaItems[0], mediaItems[1]]);
    expect(screen.getByText("Started identity verification for 2 prepared candidates.")).toBeInTheDocument();
  });

  it("quickly rejects one source lane and removes it from the active workspace", async () => {
    const user = userEvent.setup();
    const onMediaItemsRejected = vi.fn();
    const rejectCurationMedia = vi.fn().mockResolvedValue([
      { ...mediaItems[0], status: "ignored" },
    ]);

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engineStub({ rejectCurationMedia })}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
        onMediaItemsRejected={onMediaItemsRejected}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reject images" }));

    expect(rejectCurationMedia).toHaveBeenCalledWith(["media_portrait"]);
    expect(onMediaItemsRejected).toHaveBeenCalledWith(["media_portrait"]);
    expect(screen.getByText("Rejected 1 image candidate.")).toBeInTheDocument();
  });

  it("switches bundle previews and starts video or audio playback on hover", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const bundledItems = mediaItems.map((item) => ({
      ...item,
      metadata_json: {
        ...item.metadata_json,
        source_bundle_key: "instagram:hover-preview",
        display_name: "Hover preview",
      },
    }));

    render(
      <CurateSearchTab
        mediaItems={bundledItems}
        engine={engineStub()}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    const card = screen.getByRole("article", { name: "Hover preview" });
    fireEvent.mouseEnter(card);
    fireEvent.mouseEnter(screen.getByRole("button", { name: "Video 1" }));
    await waitFor(() => expect(card.querySelector("video")).toBeInTheDocument());
    expect(play).toHaveBeenCalledTimes(1);

    fireEvent.mouseEnter(screen.getByRole("button", { name: "Audio 1" }));
    await waitFor(() => expect(card.querySelector("audio")).toBeInTheDocument());
    expect(play).toHaveBeenCalledTimes(2);
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
      rotateVaultImage: vi.fn().mockRejectedValue(new Error("Unexpected image rotation")),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      createProcessingJob: vi.fn().mockResolvedValue({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: true,
          extract_audio: true,
          intelligent_selection: true,
          frames_per_second: 4,
          max_frame_count: 24,
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

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    await user.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    await user.click(screen.getByRole("button", { name: "Prepare Selected Videos" }));

    await waitFor(() =>
      expect(engine.createProcessingJob).toHaveBeenCalledWith({
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: true,
          extract_audio: true,
          intelligent_selection: true,
          frames_per_second: 4,
          max_frame_count: 24,
        },
      }),
    );
    expect(engine.getProcessingJob).toHaveBeenCalledWith("processing_1");
    expect(onMediaItemsGenerated).toHaveBeenCalledWith(generatedItems);
    expect(
      screen.getByText("1 audio track ready. Open Audio to analyze, isolate, and clean the voice."),
    ).toBeInTheDocument();
  });

  it("extracts only audio for a voice workflow and opens the audio lane", async () => {
    const user = userEvent.setup();
    const generatedAudio: MediaItem = {
      id: "media_audio_extracted",
      raw_path: "/tmp/vault/derived/video/audio.wav",
      media_type: "audio",
      duration: 42,
      status: "new",
      metadata_json: { derivative_type: "audio_clip" },
    };
    const engine = engineStub({
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      createProcessingJob: vi.fn().mockResolvedValue(
        processingJob({
          options: {
            generate_frames: false,
            extract_audio: true,
            intelligent_selection: false,
            frames_per_second: 4,
            max_frame_count: 24,
          },
        }),
      ),
      getProcessingJob: vi.fn().mockResolvedValue(
        processingJob({
          status: "complete",
          derived_media_items: [generatedAudio],
          options: { generate_frames: false, extract_audio: true },
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
        workflowTarget="voice"
        initialView="video"
      />,
    );

    expect(screen.getByRole("heading", { name: "Prepare Voice Samples" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Voice sample workflow" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Frames & clips" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Audio tracks" })).toBeChecked();

    await user.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    await user.click(screen.getByRole("button", { name: "Prepare Selected Videos" }));

    await waitFor(() =>
      expect(engine.createProcessingJob).toHaveBeenCalledWith({
        job_type: "video_breakdown",
        source_media_item_ids: ["media_video"],
        options: {
          generate_frames: false,
          extract_audio: true,
          intelligent_selection: false,
          frames_per_second: 4,
          max_frame_count: 24,
        },
      }),
    );
    expect(onMediaItemsGenerated).toHaveBeenCalledWith([generatedAudio]);
    expect(screen.getByRole("tab", { name: /Audio/ })).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByText("1 audio track ready. Open Audio to analyze, isolate, and clean the voice."),
    ).toBeInTheDocument();
  });

  it("runs local AI analysis for all media and presents recommendations", async () => {
    const user = userEvent.setup();
    const completedAnalysis: ProcessingJob = {
      id: "processing_ai_1",
      job_type: "curation_analysis",
      source_media_item_ids: mediaItems.map((item) => item.id),
      options: {},
      status: "complete",
      progress_message: "Curation analysis complete",
      errors: [],
      derived_media_items: [],
      curation_analyses: [
        {
          media_item_id: "media_portrait",
          media_type: "image",
          recommendation: "keep",
          confidence: 0.88,
          quality_score: 0.81,
          face_count: 1,
          face_area: 0.12,
          body_coverage: 0.44,
          pose_coverage: 0.67,
          aesthetic_score: 0.73,
          reasons: ["one usable face with sufficient visual quality"],
          warnings: [],
          analyzer: "apple-vision-dataset-v1",
          analyzed_at: "2026-07-10T00:00:00Z",
        },
      ],
      created_at: "2026-07-10T00:00:00Z",
      completed_at: "2026-07-10T00:00:01Z",
    };
    const createCurationAnalysisJob = vi.fn().mockResolvedValue({
      ...completedAnalysis,
      status: "queued",
      curation_analyses: [],
    });
    const engine = engineStub({
      createCurationAnalysisJob,
      getProcessingJob: vi.fn().mockResolvedValue(completedAnalysis),
    });

    render(
      <CurateSearchTab
        mediaItems={mediaItems}
        engine={engine}
        onSendToIdentify={vi.fn()}
        onMediaItemsGenerated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "AI Analyze All" }));
    await waitFor(() =>
      expect(createCurationAnalysisJob).toHaveBeenCalledWith(mediaItems.map((item) => item.id)),
    );
    expect(screen.getByText("AI review complete: 1 keep, 0 review, 0 reject.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Images/ }));
    expect(screen.getByText("keep")).toBeInTheDocument();
    expect(screen.getByText("one usable face with sufficient visual quality")).toBeInTheDocument();
    expect(screen.getByText("Q 81%")).toBeInTheDocument();
    expect(screen.getByText("Faces 1")).toBeInTheDocument();
    expect(screen.getByText("Pose 67%")).toBeInTheDocument();
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

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    await user.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    await user.click(screen.getByRole("button", { name: "Prepare Selected Videos" }));

    await waitFor(() => expect(engine.listProcessingJobs).toHaveBeenCalled());
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

    fireEvent.click(screen.getByRole("tab", { name: /Video/ }));
    fireEvent.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    fireEvent.click(screen.getByRole("button", { name: "Prepare Selected Videos" }));

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
    expect(
      screen.getByText(
        "Generated 1 derivative media item. No audio track was extracted; check that the source video contains audio.",
      ),
    ).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("tab", { name: /Video/ }));
    fireEvent.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    fireEvent.click(screen.getByRole("button", { name: "Prepare Selected Videos" }));

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
    expect(
      screen.getByText(
        "Generated 1 derivative media item. No audio track was extracted; check that the source video contains audio.",
      ),
    ).toBeInTheDocument();
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

    await user.click(screen.getByRole("tab", { name: /Video/ }));
    await user.click(screen.getByLabelText("Select to Prepare: video.mp4"));
    const breakdownButton = screen.getByRole("button", { name: "Prepare Selected Videos" });

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
    window.localStorage.setItem("lorasuite:experience:v1", "studio");
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      options: { project_id: "job_1" },
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

    await user.click(screen.getByRole("tab", { name: "Prepare" }));
    await user.click(await screen.findByRole("tab", { name: /Images/ }));
    expect(await within(screen.getByLabelText("Curate search results")).findByText("curate-portrait.png")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open media search" }));
    await user.type(screen.getByLabelText("Search media"), "portrait");
    expect(within(screen.getByLabelText("Curate search results")).queryByText("curate-voice.m4a")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Verify Identity" }));
    await user.click(screen.getByRole("tab", { name: "Prepare" }));

    expect(screen.getByLabelText("Search media")).toHaveValue("portrait");
    expect(within(screen.getByLabelText("Curate search results")).getByText("curate-portrait.png")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Curate search results")).queryByText("curate-voice.m4a")).not.toBeInTheDocument();
  });

  function engineStub(overrides: Partial<CurateSearchEngine> = {}): CurateSearchEngine {
    return {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      rotateVaultImage: vi.fn().mockRejectedValue(new Error("Unexpected image rotation")),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      createProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job")),
      getProcessingJob: vi.fn().mockRejectedValue(new Error("Unexpected processing job detail")),
      processProcessingJob: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected processing job process")),
      updateVideoKeepers: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected keeper update")),
      commitVideoBreakdown: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected breakdown commit")),
      addCurationHandoff: vi.fn().mockResolvedValue({
        items: [],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      rejectCurationMedia: vi.fn().mockResolvedValue([]),
      restoreCurationAudio: vi.fn().mockResolvedValue([]),
      createCurationAnalysisJob: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected curation analysis job")),
      getAudioCleaningRecipe: vi.fn().mockResolvedValue({
        media_item_id: "media_voice",
        high_pass_hz: 80,
        low_pass_hz: 14000,
        noise_floor_db: -55,
        noise_reduction_db: 6,
        gate_threshold_db: -55,
        presence_gain_db: 0,
        normalize: true,
        isolate_voice: false,
      }),
      previewAudioCleaning: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected audio cleaning preview")),
      renderAudioCleaning: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected audio cleaning render")),
      getAudioSeparationStatus: vi.fn().mockResolvedValue({
        backend: "audio-separator-uvr-mdx",
        model_name: "UVR-MDX-NET-Inst_HQ_3.onnx",
        model_sha256: "test",
        download_size_bytes: 66_759_214,
        runtime_installed: true,
        model_installed: true,
        ready: true,
        message: "UVR vocal isolation is ready",
      }),
      installAudioSeparationModel: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected audio separation install")),
      createAudioCleaningJob: vi
        .fn()
        .mockRejectedValue(new Error("Unexpected audio cleaning job")),
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

  function curationEvidence(
    mediaItemId: string,
    mediaType: MediaItem["media_type"],
    recommendation: CurationAnalysisEvidence["recommendation"],
  ): CurationAnalysisEvidence {
    return {
      media_item_id: mediaItemId,
      media_type: mediaType,
      recommendation,
      confidence: 0.8,
      reasons: [`AI recommends ${recommendation}`],
      warnings: [],
      analyzer: "test-curator-v1",
      analyzed_at: "2026-07-10T00:00:00Z",
    };
  }

  async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
  }
});
