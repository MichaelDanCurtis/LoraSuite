import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GuidedExperience, GuidedProviderReadiness } from "./GuidedExperience";
import type { EngineClient } from "../lib/api";
import type { CharacterProject, IngressJob, MediaItem, PartnerQualificationReport, ProcessingJob, ProviderReadinessMatrix, SocialAcquisitionJob } from "../lib/types";

const importedImage: MediaItem = {
  id: "media_approved",
  raw_path: "/vault/raw/approved.jpg",
  media_type: "image",
  status: "new",
};

function projectFixture(
  id: string,
  name: string,
  subjectName: string,
  requestedOutputs: NonNullable<CharacterProject["intent"]["requested_outputs"]>,
): CharacterProject {
  return {
    id,
    name,
    intent: {
      subject_name: subjectName,
      requested_outputs: requestedOutputs,
      training_target_profile_ids: requestedOutputs.includes("voice")
        ? { voice: "runpod_fish_speech_s2_voice_lora" }
        : { image: "runcomfy_flux1_dev_character" },
      target_type: "character",
      trigger_token: "",
      description: "",
      learned_attributes: [],
      controllable_attributes: [],
      excluded_attributes: [],
    },
    candidate_media_item_ids: [],
    observations: {},
    crop_recipes: {},
    health: {
      candidate_count: 4,
      accepted_count: 3,
      review_count: 1,
      rejected_count: 0,
      anchor_count: 1,
      effective_observation_count: 4,
      source_count: 1,
      largest_source_share: 1,
      average_quality: 0.8,
      average_diversity: 0.7,
      view_counts: {},
      analyzer: "fixture",
      warnings: [],
    },
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-27T00:00:00Z",
  };
}

function engineStub() {
  let analysisIds: string[] = [];
  const audioDerivative: MediaItem = {
    id: "guided_audio",
    raw_path: "/vault/derivatives/guided_audio.wav",
    media_type: "audio",
    status: "new",
    metadata_json: { source_media_item_id: "media_approved", derivative_type: "audio_clip" },
  };
  const frameDerivative: MediaItem = {
    id: "guided_frame",
    raw_path: "/vault/derivatives/guided_frame.jpg",
    media_type: "image",
    status: "new",
    metadata_json: { source_media_item_id: "media_approved", derivative_type: "video_frame" },
  };
  const queuedProcessingJob = (id: string, jobType: ProcessingJob["job_type"]): ProcessingJob => ({
    id,
    job_type: jobType,
    source_media_item_ids: ["media_approved"],
    options: {},
    status: "queued",
    progress_message: "Queued",
    errors: [],
    derived_media_items: [],
    created_at: "2026-07-13T00:00:00Z",
  });
  const completeJob: IngressJob = {
    id: "job_guided",
    source_kind: "instagram",
    candidate_ids: ["poster_1"],
    candidate_count: 2,
    selected_count: 1,
    imported_count: 1,
    deferred_count: 1,
    skipped_count: 0,
    failed_count: 0,
    status: "complete",
    progress_message: "Ingress complete",
    errors: [],
    deferred_candidates: [],
    imported_media_items: [importedImage],
    created_at: "2026-07-13T00:00:00Z",
  };
  return {
    clearAllMedia: vi.fn().mockResolvedValue({
      status: "cleared",
      files_removed: 12,
      bytes_removed: 4096,
    }),
    scanInstagramBrowserUrl: vi.fn().mockResolvedValue({
      id: "scan_guided",
      errors: [],
      metadata_json: {},
      candidates: [
        {
          id: "video_1",
          source_kind: "instagram",
          source_locator: "https://instagram.com/reel/one",
          display_name: "One source post",
          media_type: "video",
          thumbnail_path: "/vault/previews/one.jpg",
          status: "ready",
          selected: true,
        },
        {
          id: "poster_1",
          source_kind: "instagram",
          source_locator: "https://instagram.com/reel/one",
          display_name: "One source post poster",
          media_type: "image",
          thumbnail_path: "/vault/previews/one.jpg",
          status: "ready",
          selected: true,
          metadata_json: { source_video_candidate_id: "video_1" },
        },
      ],
    }),
    analyzeIngressCandidates: vi.fn().mockResolvedValue({
      analyses: [
        {
          candidate_id: "video_1",
          recommendation: "review",
          confidence: 0.74,
          reasons: ["temporal evidence needs detailed analysis"],
          warnings: [],
          analyzer: "fixture",
        },
        {
          candidate_id: "poster_1",
          recommendation: "keep",
          confidence: 0.88,
          quality_score: 0.82,
          face_count: 1,
          reasons: ["strong person signal with sufficient visual quality"],
          warnings: [],
          analyzer: "fixture",
        },
      ],
      errors: [],
    }),
    ingressCandidateVideoPreviewUrl: vi.fn((candidateId: string) => `http://engine.test/ingress/candidates/${candidateId}/video-preview`),
    ingressCandidateThumbnailUrl: vi.fn((candidateId: string) => `http://engine.test/ingress/candidates/${candidateId}/thumbnail`),
    createIngressJob: vi.fn().mockResolvedValue(completeJob),
    getIngressJob: vi.fn().mockResolvedValue(completeJob),
    listTrainingTargets: vi.fn().mockResolvedValue([
      { profile_id: "runcomfy_flux1_dev_character", label: "FLUX.1 Dev Character", modality: "image" },
      { profile_id: "runcomfy_krea2_raw_character", label: "KREA 2 Character", modality: "image" },
      { profile_id: "runcomfy_qwen_image_character", label: "Qwen Image Character", modality: "image" },
      { profile_id: "runcomfy_wan22_14b_t2v_character", label: "WAN 2.2 14B T2V Character Video", modality: "video" },
      { profile_id: "comfyui_minimax_h3_ref2va", label: "MiniMax H3 Reference-to-Video", modality: "video" },
      { profile_id: "runpod_fish_speech_s2_voice_lora", label: "Fish Speech S2 Voice LoRA", modality: "voice" },
      { profile_id: "runpod_id_lora_ltx23_inference", label: "ID-LoRA LTX-2.3 Zero-Shot", modality: "audio_visual" },
    ]),
    listProcessingJobs: vi.fn().mockResolvedValue([]),
    createProcessingJob: vi.fn().mockResolvedValue(queuedProcessingJob("guided_breakdown", "video_breakdown")),
    createCurationAnalysisJob: vi.fn().mockImplementation((mediaItemIds: string[]) => {
      analysisIds = mediaItemIds;
      return Promise.resolve(queuedProcessingJob("guided_analysis", "curation_analysis"));
    }),
    getProcessingJob: vi.fn().mockImplementation((jobId: string) => {
      if (jobId === "guided_breakdown") {
        return Promise.resolve({
          ...queuedProcessingJob(jobId, "video_breakdown"),
          status: "complete",
          progress_message: "Video breakdown complete",
          derived_media_items: [audioDerivative, frameDerivative],
        });
      }
      if (jobId === "guided_cleaning") {
        return Promise.resolve({
          ...queuedProcessingJob(jobId, "audio_cleaning"),
          status: "complete",
          progress_message: "Voice preparation complete",
          derived_media_items: [{
            ...audioDerivative,
            id: "guided_audio_clean",
            raw_path: "/vault/derivatives/guided_audio_clean.wav",
            metadata_json: { source_media_item_id: "guided_audio", derivative_type: "audio_clean" },
          }],
        });
      }
      return Promise.resolve({
        ...queuedProcessingJob(jobId, "curation_analysis"),
        source_media_item_ids: analysisIds,
        status: "complete",
        progress_message: "Curation analysis complete",
        curation_analyses: analysisIds.map((mediaItemId) => ({
          media_item_id: mediaItemId,
          media_type: mediaItemId.includes("audio") ? "audio" : mediaItemId.includes("frame") ? "image" : "video",
          recommendation: "keep",
          confidence: 0.91,
          reasons: ["Strong training evidence"],
          warnings: [],
          analyzer: "fixture",
          analyzed_at: "2026-07-13T00:00:00Z",
        })),
      });
    }),
    createAudioCleaningJob: vi.fn().mockResolvedValue(queuedProcessingJob("guided_cleaning", "audio_cleaning")),
    addCurationHandoff: vi.fn().mockResolvedValue({ items: [], updated_at: "2026-07-13T00:00:00Z" }),
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
    listModelArtifacts: vi.fn().mockResolvedValue([]),
    listVoiceArtifactEvaluations: vi.fn().mockResolvedValue([]),
    getRecommendedVoiceArtifactEvaluation: vi.fn().mockResolvedValue(null),
    listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
    listIdLoraEvaluations: vi.fn().mockResolvedValue([]),
    getSyncNetCapability: vi.fn().mockResolvedValue({
      ready: false,
      backend: "syncnet",
      problems: ["runtime not installed"],
    }),
    getProviderReadiness: vi.fn().mockResolvedValue({
      project_id: "project-1",
      ready_count: 0,
      total_count: 0,
      items: [],
    }),
    assetUrl: (path: string) => path,
  } as unknown as EngineClient;
}

describe("GuidedExperience source intake", () => {
  beforeEach(() => window.localStorage.clear());

  it("persists the subject label and selected creation output before source intake", async () => {
    const user = userEvent.setup();
    const persistBrief = vi.fn().mockResolvedValue(undefined);
    render(
      <GuidedExperience
        engine={engineStub()}
        mediaItems={[]}
        target="image"
        onTargetChange={vi.fn()}
        onPersistCreationBrief={persistBrief}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    expect(screen.getByRole("region", { name: "Current project and next step" })).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Who or what is this identity for?" }),
      "Mary",
    );
    await user.selectOptions(screen.getByLabelText("Start with"), "video");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));

    expect(persistBrief).toHaveBeenCalledWith(
      "video",
      "Mary",
      ["video"],
      "new",
      expect.objectContaining({
        image: "runcomfy_flux1_dev_character",
        video: "runcomfy_wan22_14b_t2v_character",
      }),
    );
    expect(await screen.findByRole("heading", { name: "Give me everything you have" })).toBeInTheDocument();
  });

  it("lets a returning user choose which dataset to resume", async () => {
    const user = userEvent.setup();
    const onProjectChange = vi.fn();
    const onTargetChange = vi.fn();
    const imageProject = projectFixture("project-image", "Mary Images", "Mary", ["image"]);
    const voiceProject = projectFixture("project-voice", "Morgan Voice", "Morgan", ["voice"]);
    const engine = engineStub();
    engine.listCharacterProjects = vi.fn().mockResolvedValue([imageProject, voiceProject]);

    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="image"
        activeProjectId={imageProject.id}
        onTargetChange={onTargetChange}
        onProjectChange={onProjectChange}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    const picker = await screen.findByRole("combobox", { name: "Project to resume" });
    expect(picker).toHaveValue(imageProject.id);
    expect(screen.getAllByText("Mary").length).toBeGreaterThan(0);

    await user.selectOptions(picker, voiceProject.id);

    expect(onProjectChange).toHaveBeenCalledWith(voiceProject.id);
    expect(onTargetChange).toHaveBeenCalledWith("voice");
    expect(screen.getByRole("textbox", { name: "Who or what is this identity for?" })).toHaveValue("Morgan");
    await user.click(screen.getByText("Additional outputs and recipes"));
    expect(screen.getByRole("checkbox", { name: "Voice" })).toBeChecked();
    expect(screen.getByText("Fish Speech S2 Voice LoRA")).toBeInTheDocument();
  });

  it("consumes a home navigation request once, so output changes do not reset the stage", async () => {
    const user = userEvent.setup();
    const navigationRequest = { stage: "create" as const, token: 10 };
    const props = { engine: engineStub(), mediaItems: [], onTargetChange: vi.fn(), onMediaItemsImported: vi.fn(), onOpenStudio: vi.fn(), navigationRequest };
    const view = render(<GuidedExperience {...props} target="image" />);
    await user.click(screen.getByRole("button", { name: "Sources" }));
    view.rerender(<GuidedExperience {...props} target="video" />);
    expect(await screen.findByRole("heading", { name: "Give me everything you have" })).toBeInTheDocument();
  });

  it("shows every compatible catalog recipe at creation, including additional image models", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const catalog = await engine.listTrainingTargets();
    vi.mocked(engine.listTrainingTargets).mockResolvedValue([...catalog, { ...catalog[0], profile_id: "sdxl", label: "SDXL 1.0 Character", recipe: { status: "experimental" } } as typeof catalog[number]]);
    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    const selector = await screen.findByLabelText("Model recipe");
    await waitFor(() => expect(within(selector).getByRole("option", { name: "SDXL 1.0 Character · Experimental" })).toBeInTheDocument());
    expect(within(selector).queryByRole("option", { name: /WAN|Fish Speech|Zero-Shot/ })).not.toBeInTheDocument();
    await user.selectOptions(selector, "sdxl");
    expect(selector).toHaveValue("sdxl");
  });

  it("shows saved project candidates in Sources and its intake window with no local draft", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const project = projectFixture("project-1", "Saved project", "Subject", ["image"]);
    engine.getCharacterProject = vi.fn().mockResolvedValue({ ...project, candidate_media_item_ids: [importedImage.id] });
    render(<GuidedExperience engine={engine} mediaItems={[importedImage, { ...importedImage, id: "unrelated", raw_path: "/vault/unrelated.jpg" }]} target="image" activeProjectId="project-1" controlledStage="sources" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    expect(await screen.findByRole("img", { name: "approved.jpg" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "unrelated.jpg" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Local Media intake" }));
    const dialog = await screen.findByRole("dialog", { name: "Local Media" });
    expect(within(dialog).getByRole("img", { name: "approved.jpg" })).toBeInTheDocument();
  });

  it("restores project sources from persisted ingress jobs on another client", async () => {
    const engine = engineStub();
    engine.listIngressJobs = vi.fn().mockResolvedValue([
      { status: "complete", options: { project_id: "project-1", target: "image" }, imported_media_items: [importedImage] },
      { status: "complete", options: { project_id: "other-project", target: "image" }, imported_media_items: [{ ...importedImage, id: "other-image" }] },
    ]);
    render(<GuidedExperience engine={engine} mediaItems={[importedImage, { ...importedImage, id: "other-image" }]} target="image" activeProjectId="project-1" controlledStage="sources" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    expect(await screen.findByText("1 ready to curate")).toBeInTheDocument();
  });

  it("offers the saved handoff without requiring another preparation run", async () => {
    const user = userEvent.setup();
    const onStageChange = vi.fn();
    render(<GuidedExperience engine={engineStub()} mediaItems={[importedImage]} identifyItems={[importedImage]} target="image" activeProjectId="project-1" controlledStage="prepare" onStageChange={onStageChange} onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Continue to Verify" }));
    expect(onStageChange).toHaveBeenCalledWith("verify");
  });

  it("retrieves a social batch, stages AI recommendations, and confirms it", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const onImported = vi.fn();
    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="image"
        onTargetChange={vi.fn()}
        onMediaItemsImported={onImported}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    expect(screen.getByRole("dialog", { name: "Instagram" })).toBeInTheDocument();
    expect(screen.queryByLabelText("LoraSuite AI guide")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    expect(await screen.findByText("One source post")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Scan with AI" }));
    expect(await screen.findByText("AI keep 88%")).toBeInTheDocument();
    expect(engine.analyzeIngressCandidates).toHaveBeenCalledWith(
      expect.arrayContaining(["video_1", "poster_1"]),
      "image",
    );

    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    await user.hover(screen.getByRole("button", { name: "Video" }));
    expect(screen.getByTitle("Playing One source post")).toBeInTheDocument();
    expect(screen.getByText("Loading preview · 0s")).toBeInTheDocument();
    expect(play).toHaveBeenCalled();
    fireEvent.playing(screen.getByTitle("Playing One source post"));
    expect(screen.queryByText("Loading preview · 0s")).not.toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByRole("article"), { relatedTarget: document.body });
    expect(screen.queryByTitle("Playing One source post")).not.toBeInTheDocument();
    expect(pause).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Remove One source post" }));
    await waitFor(() => expect(screen.queryByText("One source post")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Restore 1 removed" }));
    await user.click(await screen.findByRole("button", { name: "Select One source post" }));

    await user.click(screen.getByRole("button", { name: "Confirm batch" }));
    expect(onImported).toHaveBeenCalledWith([importedImage]);
    expect(screen.getByRole("button", { name: /Next 24/ })).toBeDisabled();
    expect(engine.createIngressJob).toHaveBeenCalledWith(expect.objectContaining({
      source_kind: "instagram",
      candidate_ids: ["poster_1", "video_1"],
      reviewed_candidate_ids: expect.arrayContaining(["video_1", "poster_1"]),
    }));
  });

  it("labels AI rejects without hiding media or replacing the user's selections", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.analyzeIngressCandidates).mockResolvedValue({
      analyses: [
        {
          candidate_id: "video_1",
          recommendation: "reject",
          confidence: 0.96,
          reasons: ["video needs manual review"],
          warnings: [],
          analyzer: "fixture",
        },
        {
          candidate_id: "poster_1",
          recommendation: "reject",
          confidence: 0.94,
          reasons: ["poster needs manual review"],
          warnings: [],
          analyzer: "fixture",
        },
      ],
      errors: [],
    });

    const { container } = render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: "Retrieve first 100" }));
    await user.click(await screen.findByRole("button", { name: "Select One source post" }));
    await user.click(screen.getByRole("button", { name: "Scan with AI" }));

    await screen.findByText(/your selections and visible media were preserved/i);
    expect(container.querySelector(".source-ai-badge.reject")).toHaveTextContent(/AI reject 96%/i);
    expect(screen.getByText("One source post")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deselect One source post" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Remove One source post" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Restore removed" })).toBeDisabled();
  });

  it("scopes a Voice AI scan and its counts to audio candidates", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.scanInstagramBrowserUrl).mockResolvedValue({
      id: "voice_scan",
      errors: [],
      candidates: [
        {
          id: "voice_video",
          source_kind: "instagram",
          source_locator: "https://instagram.com/reel/voice",
          display_name: "Voice source post",
          media_type: "video",
          status: "ready",
          selected: false,
          metadata_json: { source_bundle_key: "voice_bundle" },
        },
        {
          id: "voice_poster",
          source_kind: "instagram",
          source_locator: "https://instagram.com/reel/voice",
          display_name: "Voice source poster",
          media_type: "image",
          thumbnail_path: "/vault/previews/voice.jpg",
          status: "ready",
          selected: false,
          metadata_json: { source_bundle_key: "voice_bundle", source_video_candidate_id: "voice_video" },
        },
        {
          id: "voice_audio",
          source_kind: "instagram",
          source_locator: "https://instagram.com/reel/voice",
          display_name: "Voice source audio",
          media_type: "audio",
          status: "ready",
          selected: false,
          metadata_json: { source_bundle_key: "voice_bundle", source_video_candidate_id: "voice_video" },
        },
      ],
    });
    vi.mocked(engine.analyzeIngressCandidates).mockResolvedValue({
      analyses: [{
        candidate_id: "voice_audio",
        recommendation: "review",
        confidence: 0.82,
        reasons: ["review for usable target speech"],
        warnings: [],
        analyzer: "fixture",
      }],
      errors: [],
    });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="voice" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "voice");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: "Retrieve first 100" }));
    await user.click(screen.getByRole("button", { name: "Scan with AI" }));

    expect(engine.analyzeIngressCandidates).toHaveBeenCalledWith(["voice_audio"], "voice");
    expect(await screen.findByText(/AI scan complete: 0 keep, 1 review, 0 reject/)).toBeInTheDocument();
  });

  it("uses a generated X video poster for both the bubble and image role", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    engine.scanXBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_x",
      errors: [],
      metadata_json: {},
      candidates: [
        {
          id: "x_video",
          source_kind: "x_twitter",
          source_locator: "https://x.com/subject/status/1",
          display_name: "X source video",
          media_type: "video",
          status: "ready",
          selected: false,
          metadata_json: { download_url: "https://video.twimg.com/ext_tw_video/1/clip.mp4" },
        },
        {
          id: "x_poster",
          source_kind: "x_twitter",
          source_locator: "https://x.com/subject/status/1#poster",
          display_name: "X source video poster",
          media_type: "image",
          status: "ready",
          selected: true,
          metadata_json: {
            source_video_candidate_id: "x_video",
            asset_role: "video_poster",
            materialize_from_video: true,
          },
        },
      ],
    });

    const { container } = render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="image"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open X / Twitter intake" }));
    await user.type(screen.getByRole("textbox", { name: "X / Twitter URL" }), "https://x.com/subject");
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));

    expect(await screen.findByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Video" })).toBeInTheDocument();
    expect(container.querySelector(".source-candidate-preview img")?.getAttribute("src")).toBe(
      "http://engine.test/ingress/candidates/x_video/thumbnail",
    );
    expect(engine.ingressCandidateThumbnailUrl).toHaveBeenCalledWith("x_video");
  });

  it("plays TikTok video roles through the cached engine preview", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    engine.scanTikTokBrowserUrl = vi.fn().mockResolvedValue({
      id: "scan_tiktok",
      errors: [],
      metadata_json: {},
      candidates: [
        {
          id: "tiktok_video",
          source_kind: "tiktok",
          source_locator: "https://www.tiktok.com/@subject/video/123",
          display_name: "TikTok speaking clip",
          media_type: "video",
          thumbnail_path: "/vault/previews/tiktok.jpg",
          status: "ready",
          selected: false,
          metadata_json: {
            source_url: "https://www.tiktok.com/@subject/video/123",
            browser_source: "chrome",
          },
        },
      ],
    });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();

    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="video"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Start with"), "video");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open TikTok intake" }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    await user.hover(await screen.findByRole("button", { name: "Video" }));

    const preview = screen.getByTitle("Playing TikTok speaking clip");
    expect(preview).toHaveAttribute(
      "src",
      "http://engine.test/ingress/candidates/tiktok_video/video-preview",
    );
    expect(engine.ingressCandidateVideoPreviewUrl).toHaveBeenCalledWith("tiktok_video");
    expect(play).toHaveBeenCalled();
  });

  it("continues from sources into the guided Prepare workspace", async () => {
    const user = userEvent.setup();
    const onOpenStudio = vi.fn();
    window.localStorage.setItem("lorasuite:guided-stage:v2", "sources");
    render(
      <GuidedExperience
        engine={engineStub()}
        mediaItems={[{ ...importedImage, media_type: "video" }]}
        target="video"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={onOpenStudio}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Prepare Video LoRA" }));
    expect(await screen.findByRole("heading", { name: "Prepare with AI" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Want me to prepare the motion?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Let AI prepare 1 item" })).toBeInTheDocument();
    expect(screen.queryByText("Filter")).not.toBeInTheDocument();
    expect(onOpenStudio).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Let AI prepare 1 item" }));
    expect(await screen.findByRole("heading", { name: "Your first pass is ready" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 ready" })).toBeInTheDocument();
  });

  it("accepts a video-only voice source and automatically plans audio extraction", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    window.localStorage.setItem("lorasuite:guided-stage:v2", "sources");
    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[{ ...importedImage, media_type: "video", raw_path: "/vault/raw/speaking.mp4" }]}
        target="voice"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Prepare Voice" }));

    expect(
      await screen.findByRole("heading", { name: "Prepare with AI" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Want me to prepare the voice?" })).toBeInTheDocument();
    expect(screen.getByText("Extract speech")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Let AI prepare 1 item" }));
    expect(await screen.findByRole("heading", { name: "Your first pass is ready" })).toBeInTheDocument();
    expect(engine.createProcessingJob).toHaveBeenCalledWith(expect.objectContaining({
      options: expect.objectContaining({ generate_frames: false, extract_audio: true }),
    }));
    expect(engine.createCurationAnalysisJob).toHaveBeenCalledWith(["guided_audio"]);
  });

  it("shows the complete guided journey through evaluation and improvement", () => {
    render(
      <GuidedExperience
        engine={engineStub()}
        mediaItems={[]}
        target="image"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    const journey = screen.getByRole("navigation", { name: "Guided creation steps" });
    expect(within(journey).getByRole("button", { name: "Create" })).toBeInTheDocument();
    expect(within(journey).getByRole("button", { name: "Sources" })).toBeInTheDocument();
    expect(within(journey).getByRole("button", { name: "Prepare" })).toBeInTheDocument();
    expect(within(journey).getByRole("button", { name: "Verify" })).toBeInTheDocument();
    expect(within(journey).getByRole("button", { name: "Build & Train" })).toBeInTheDocument();
    expect(within(journey).getByRole("button", { name: "Evaluate & Release" })).toBeInTheDocument();
  });

  it("keeps imported source media scoped to its project and output lane", () => {
    window.localStorage.setItem("lorasuite:guided-stage:v2", "sources");
    window.localStorage.setItem("lorasuite:guided-source-scopes:v2", JSON.stringify({
      "project-one:image": {
        progress: {
          local: { batches: 1, imported: 1 },
          instagram: { batches: 0, imported: 0 },
          x: { batches: 0, imported: 0 },
          tiktok: { batches: 0, imported: 0 },
        },
        drafts: {},
        mediaItemIds: [importedImage.id],
      },
    }));
    const props = {
      engine: engineStub(),
      mediaItems: [importedImage],
      target: "image" as const,
      onTargetChange: vi.fn(),
      onMediaItemsImported: vi.fn(),
      onOpenStudio: vi.fn(),
    };
    const { rerender } = render(
      <GuidedExperience {...props} activeProjectId="project-one" />,
    );

    expect(screen.getByRole("button", { name: "Prepare Image LoRA" })).toBeEnabled();

    rerender(<GuidedExperience {...props} activeProjectId="project-two" />);

    expect(screen.getByRole("button", { name: "Prepare Image LoRA" })).toBeDisabled();
  });

  it("uses engine workflow blockers instead of enabling Build for any project", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("lorasuite:guided-stage:v2", "sources");
    const engine = engineStub();
    engine.getTrainingWorkflow = vi.fn().mockResolvedValue({
      project_id: "project-one",
      project_name: "Mary",
      recommended_lane: "image",
      recommendation: "Image LoRA: Review identity candidates",
      complete_count: 0,
      updated_at: "2026-07-27T00:00:00Z",
      lanes: [{
        id: "image",
        label: "Image LoRA",
        state: "blocked",
        phase: "identity",
        summary: "No accepted identity images.",
        action_label: "Review identity candidates",
        target_mode: "image",
        target_workspace: "identify",
        counts: { accepted_sources: 0 },
        blockers: ["Accept identity-confirmed images before compiling."],
        warnings: [],
      }],
    });
    const { rerender } = render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="image"
        activeProjectId="project-one"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    await waitFor(() => expect(engine.getTrainingWorkflow).toHaveBeenCalledWith("project-one"));
    expect(screen.getByRole("button", { name: "Build & Train" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Build & Train" })).toHaveAttribute(
      "title",
      "Accept identity-confirmed images before compiling.",
    );
    const context = screen.getByRole("region", { name: "Current project and next step" });
    expect(within(context).getByText("Mary")).toBeInTheDocument();
    expect(within(context).getByText("Accept identity-confirmed images before compiling.")).toBeInTheDocument();
    expect(within(context).getByRole("button", { name: "Review identity candidates" })).toBeEnabled();
    await user.click(within(context).getByRole("button", { name: "Review identity candidates" }));
    expect(screen.getByRole("button", { name: "Verify" })).toHaveAttribute("aria-current", "step");
    engine.getTrainingWorkflow = vi.fn().mockImplementation(() => new Promise(() => {}));
    rerender(<GuidedExperience engine={engine} mediaItems={[]} target="image" activeProjectId="project-two"
      onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    expect(within(context).queryByText("Mary")).not.toBeInTheDocument();
    expect(within(context).queryByText("Accept identity-confirmed images before compiling.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build & Train" })).toBeDisabled();
  });

  it("shows the provider blocker and next action for the selected guided lane", () => {
    const matrix = {
      project_id: "project-1",
      ready_count: 0,
      total_count: 1,
      items: [{
        lane: "image",
        provider: "runcomfy",
        profile_id: "runcomfy_flux1_dev_character",
        state: "blocked",
        summary: "No exported provider dataset.",
        action_label: "Export image dataset",
        source_export_path: null,
        snapshot_id: null,
        bundle_id: null,
        run_id: null,
        endpoint_id: null,
        release_artifact_id: null,
        release_selected: false,
        smoke_run_id: null,
        smoke_ready: false,
        blockers: ["Freeze and export the reviewed dataset first."],
        warnings: [],
      }],
    } as ProviderReadinessMatrix;

    render(
      <GuidedProviderReadiness
        matrix={matrix}
        target="image"
        loading={false}
        status=""
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Export image dataset")).toBeInTheDocument();
    expect(screen.getByText("Freeze and export the reviewed dataset first.")).toBeInTheDocument();
  });

  it("shows machine-readable qualification progress through ComfyUI", () => {
    const matrix = {
      project_id: "project-1",
      ready_count: 0,
      total_count: 1,
      items: [{
        lane: "image",
        provider: "runcomfy",
        profile_id: "runcomfy_flux1_dev_character",
        state: "dataset_ready",
        summary: "Dataset ready.",
        action_label: "Launch training",
        release_selected: false,
        smoke_ready: true,
        blockers: [],
        warnings: [],
      }],
    } as ProviderReadinessMatrix;
    const report = {
      format: "lorasuite.partner-qualification.v1",
      project_id: "project-1",
      status: "in_progress",
      passed_count: 3,
      total_count: 12,
      lanes: [
        {
          partner: "runcomfy",
          lane: "image",
          profile_id: "runcomfy_flux1_dev_character",
          status: "in_progress",
          passed_count: 2,
          total_count: 5,
          checks: [],
        },
        {
          partner: "comfyui",
          lane: "image",
          profile_id: "comfyui_image_evaluation",
          status: "in_progress",
          passed_count: 1,
          total_count: 7,
          checks: [{
            id: "comfyui_installation",
            label: "ComfyUI installation",
            status: "pending",
            detail: "No ComfyUI installation is recorded.",
            action: "Install the artifact in ComfyUI.",
            evidence_ids: [],
          }],
        },
      ],
      next_actions: ["Launch training", "Install the artifact in ComfyUI."],
      generated_at: "2026-07-16T00:00:00Z",
    } as PartnerQualificationReport;

    render(
      <GuidedProviderReadiness
        matrix={matrix}
        report={report}
        target="image"
        loading={false}
        status=""
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("3 / 12 qualification gates")).toBeInTheDocument();
    expect(screen.getByText("ComfyUI")).toBeInTheDocument();
    expect(screen.getByText("Install the artifact in ComfyUI.")).toBeInTheDocument();
  });

  it("opens voice acceptance instead of reopening the voice compiler", async () => {
    window.localStorage.setItem("lorasuite:guided-stage:v2", "evaluate");
    render(
      <GuidedExperience
        engine={engineStub()}
        mediaItems={[]}
        target="voice"
        activeProjectId="project-voice"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Evaluate the trained voice" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Voice checkpoint evaluation" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Voice Sample Compiler" })).not.toBeInTheDocument();
  });

  it("opens ID-LoRA acceptance instead of reopening the contract compiler", async () => {
    window.localStorage.setItem("lorasuite:guided-stage:v2", "evaluate");
    render(
      <GuidedExperience
        engine={engineStub()}
        mediaItems={[]}
        target="id_lora"
        activeProjectId="project-id"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Evaluate the living identity" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "ID-LoRA acceptance" })).toBeInTheDocument();
    expect(screen.queryByText("Portable AV Package")).not.toBeInTheDocument();
  });

  it("filters an Instagram batch by source surface and limits bulk decisions to the visible bubbles", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.scanInstagramBrowserUrl).mockResolvedValue({
      id: "scan_surfaces",
      errors: [],
      candidates: [
        {
          id: "feed_image",
          source_kind: "instagram",
          source_locator: "/vault/feed.jpg",
          display_name: "Feed portrait",
          media_type: "image",
          thumbnail_path: "/vault/feed.jpg",
          status: "ready",
          selected: true,
          metadata_json: { scan_surface: "feed" },
        },
        {
          id: "tagged_image",
          source_kind: "instagram",
          source_locator: "/vault/tagged.jpg",
          display_name: "Tagged portrait",
          media_type: "image",
          thumbnail_path: "/vault/tagged.jpg",
          status: "ready",
          selected: true,
          metadata_json: { scan_surface: "tagged" },
        },
      ],
    });
    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[]}
        target="image"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));

    const sourceFilter = await screen.findByRole("group", { name: "Instagram source filter" });
    expect(engine.scanInstagramBrowserUrl).toHaveBeenCalledWith(
      expect.any(String),
      "chrome",
      100,
      undefined,
      "all",
      undefined,
      undefined,
    );
    await user.click(within(sourceFilter).getByRole("button", { name: "Tagged 1" }));
    expect(screen.getByText("Tagged portrait")).toBeInTheDocument();
    expect(screen.queryByText("Feed portrait")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Deselect all shown" }));
    await user.click(screen.getByRole("button", { name: "Remove unselected (1)" }));
    await waitFor(() => expect(screen.queryByText("Tagged portrait")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Everything 2" }));
    expect(screen.getByText("Feed portrait")).toBeInTheDocument();
    expect(screen.queryByText("Tagged portrait")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restore 1 removed" }));
    expect(screen.getByText("Tagged portrait")).toBeInTheDocument();
    await user.click(within(sourceFilter).getByRole("button", { name: "Feed 1" }));
    await user.click(screen.getByRole("button", { name: "Select all shown" }));

    await user.click(screen.getByRole("button", { name: "Confirm batch" }));
    expect(engine.createIngressJob).toHaveBeenCalledWith(expect.objectContaining({
      candidate_ids: ["feed_image"],
      reviewed_candidate_ids: ["feed_image", "tagged_image"],
    }));
  });

  it("deduplicates the same Instagram post while preserving each source filter", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.scanInstagramBrowserUrl)
      .mockResolvedValue({
        id: "duplicate_feed",
        errors: [],
        candidates: [
          {
            id: "feed_duplicate",
            source_kind: "instagram",
            source_locator: "https://www.instagram.com/p/SAME123/",
            display_name: "Shared post",
            media_type: "image",
            thumbnail_path: "/vault/shared.jpg",
            status: "ready",
            selected: false,
            metadata_json: { platform_media_id: "123456_999", scan_surface: "feed", source_url: "https://www.instagram.com/p/SAME123/" },
          },
          {
            id: "reel_duplicate",
            source_kind: "instagram",
            source_locator: "https://www.instagram.com/reel/SAME123/",
            display_name: "Shared post duplicate",
            media_type: "image",
            thumbnail_path: "/vault/shared.jpg",
            status: "ready",
            selected: false,
            metadata_json: { platform_media_id: "123456", scan_surface: "reels", source_url: "https://www.instagram.com/reel/SAME123/" },
          },
        ],
      });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    const filters = screen.getByRole("group", { name: "Instagram source filter" });

    expect(screen.getByText("Shared post")).toBeInTheDocument();
    expect(screen.queryByText("Shared post duplicate")).not.toBeInTheDocument();
    await user.click(within(filters).getByRole("button", { name: "Everything 1" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await user.click(within(filters).getByRole("button", { name: "Feed 1" }));
    expect(screen.getByText("Shared post")).toBeInTheDocument();
    await user.click(within(filters).getByRole("button", { name: "Reels 1" }));
    expect(screen.getByText("Shared post")).toBeInTheDocument();
  });

  it("sorts AI-scanned candidates by recommendation and then confidence", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.scanInstagramBrowserUrl).mockResolvedValue({
      id: "confidence_scan",
      errors: [],
      candidates: [
        { id: "low", source_kind: "instagram", source_locator: "/low.jpg", display_name: "Lower confidence", media_type: "image", thumbnail_path: "/low.jpg", status: "ready", selected: false, metadata_json: { scan_surface: "feed" } },
        { id: "high", source_kind: "instagram", source_locator: "/high.jpg", display_name: "Higher confidence", media_type: "image", thumbnail_path: "/high.jpg", status: "ready", selected: false, metadata_json: { scan_surface: "feed" } },
        { id: "reject", source_kind: "instagram", source_locator: "/reject.jpg", display_name: "Confident reject", media_type: "image", thumbnail_path: "/reject.jpg", status: "ready", selected: false, metadata_json: { scan_surface: "feed" } },
      ],
    });
    vi.mocked(engine.analyzeIngressCandidates).mockResolvedValue({
      analyses: [
        { candidate_id: "low", recommendation: "keep", confidence: 0.61, reasons: ["usable"], warnings: [], analyzer: "fixture" },
        { candidate_id: "high", recommendation: "keep", confidence: 0.96, reasons: ["strong"], warnings: [], analyzer: "fixture" },
        { candidate_id: "reject", recommendation: "reject", confidence: 0.99, reasons: ["not useful"], warnings: [], analyzer: "fixture" },
      ],
      errors: [],
    });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    await user.click(screen.getByRole("button", { name: "Scan with AI" }));

    const articles = screen.getAllByRole("article");
    expect(articles[0]).toHaveTextContent("Higher confidence");
    expect(articles[1]).toHaveTextContent("Lower confidence");
    expect(articles[2]).toHaveTextContent("Confident reject");
  });

  it("reviews a large retrieval pool in windows of 24", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    vi.mocked(engine.scanInstagramBrowserUrl).mockResolvedValue({
      id: "paged_pool",
      errors: [],
      candidates: Array.from({ length: 25 }, (_, index) => ({
        id: `candidate_${index + 1}`,
        source_kind: "instagram" as const,
        source_locator: `/candidate-${index + 1}.jpg`,
        display_name: `Candidate ${index + 1}`,
        media_type: "image" as const,
        thumbnail_path: `/candidate-${index + 1}.jpg`,
        status: "ready" as const,
        selected: false,
        metadata_json: { scan_surface: "feed" },
      })),
    });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));

    expect(screen.getAllByRole("article")).toHaveLength(24);
    await user.click(screen.getByRole("button", { name: /Next 24/ }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("Candidate 25")).toBeInTheDocument();
  });

  it("retrieves an unlimited source pool in explicit windows of 100", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const candidates = (start: number) => Array.from({ length: 100 }, (_, offset) => {
      const index = start + offset;
      return {
        id: `window_candidate_${index}`,
        source_kind: "instagram" as const,
        source_locator: `/window-candidate-${index}.jpg`,
        display_name: `Window candidate ${index}`,
        media_type: "image" as const,
        thumbnail_path: `/window-candidate-${index}.jpg`,
        status: "ready" as const,
        selected: false,
        metadata_json: { scan_surface: "feed" },
      };
    });
    vi.mocked(engine.scanInstagramBrowserUrl).mockImplementation(async (
      _url,
      _browser,
      _limit,
      cursor,
    ) => {
      const retrieved = cursor ? Number(cursor.replace("cursor_", "")) : 0;
      const total = retrieved + 100;
      return {
        id: `window_${total / 100}`,
        errors: [],
        candidates: candidates(retrieved + 1),
        metadata_json: total < 600 ? { next_cursor: `cursor_${total}` } : {},
      };
    });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));

    await user.click(screen.getByRole("button", { name: "Retrieve first 100" }));
    expect(await screen.findByRole("button", { name: "Retrieve next 100" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Everything 100" })).toBeInTheDocument();

    for (let window = 2; window <= 5; window += 1) {
      await user.click(screen.getByRole("button", { name: "Retrieve next 100" }));
      expect(await screen.findByRole("button", { name: "Retrieve next 100" })).toBeEnabled();
      expect(screen.getByRole("button", { name: `Everything ${window * 100}` })).toBeInTheDocument();
    }

    expect(screen.getByText("100 at a time · no total limit")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retrieve next 100" }));
    expect(await screen.findByRole("button", { name: "Retrieval complete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Everything 600" })).toBeInTheDocument();
    expect(engine.scanInstagramBrowserUrl).toHaveBeenNthCalledWith(
      6,
      expect.any(String),
      "chrome",
      100,
      "cursor_500",
      "all",
      undefined,
      undefined,
    );
  });

  it("archives a confirmed window and unlocks the next 100 for review", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const candidate = (id: string, name: string) => ({
      id,
      source_kind: "instagram" as const,
      source_locator: `/${id}.jpg`,
      display_name: name,
      media_type: "image" as const,
      thumbnail_path: `/${id}.jpg`,
      status: "ready" as const,
      selected: false,
      metadata_json: { scan_surface: "feed" },
    });
    vi.mocked(engine.scanInstagramBrowserUrl)
      .mockResolvedValueOnce({
        id: "confirm_window_1",
        errors: [],
        candidates: Array.from({ length: 100 }, (_, index) => candidate(
          `confirm_candidate_${index + 1}`,
          index === 0 ? "First window portrait" : `First window portrait ${index + 1}`,
        )),
        metadata_json: { next_cursor: "cursor_100" },
      })
      .mockResolvedValueOnce({
        id: "confirm_window_2",
        errors: [],
        candidates: Array.from({ length: 100 }, (_, index) => candidate(
          `confirm_candidate_${index + 101}`,
          index === 0 ? "Second window portrait" : `Second window portrait ${index + 1}`,
        )),
        metadata_json: {},
      });

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));

    await user.click(screen.getByRole("button", { name: "Retrieve first 100" }));
    await user.click(await screen.findByRole("button", { name: "Select First window portrait" }));
    await user.click(screen.getByRole("button", { name: "Confirm batch" }));

    expect(await screen.findByText("Batch saved")).toBeInTheDocument();
    expect(screen.queryByText("First window portrait")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrieve next 100" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Confirm batch" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Retrieve next 100" }));

    expect(await screen.findByText("Second window portrait")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select Second window portrait" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Remove Second window portrait" })).toBeEnabled();
    expect(engine.createIngressJob).toHaveBeenCalledWith(expect.objectContaining({
      candidate_ids: ["confirm_candidate_1"],
      reviewed_candidate_ids: expect.arrayContaining(["confirm_candidate_1", "confirm_candidate_100"]),
    }));
  });

  it("keeps loaded media controls available while the next 100 are retrieving", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const candidates = (start: number) => Array.from({ length: 100 }, (_, offset) => {
      const index = start + offset;
      return {
        id: `background_candidate_${index}`,
        source_kind: "instagram" as const,
        source_locator: `/background-candidate-${index}.jpg`,
        display_name: `Background candidate ${index}`,
        media_type: "image" as const,
        thumbnail_path: `/background-candidate-${index}.jpg`,
        status: "ready" as const,
        selected: false,
        metadata_json: { scan_surface: "feed" },
      };
    });
    let finishSecondWindow: ((result: Awaited<ReturnType<typeof engine.scanInstagramBrowserUrl>>) => void) | undefined;
    const secondWindow = new Promise<Awaited<ReturnType<typeof engine.scanInstagramBrowserUrl>>>((resolve) => {
      finishSecondWindow = resolve;
    });
    vi.mocked(engine.scanInstagramBrowserUrl)
      .mockResolvedValueOnce({
        id: "background_window_1",
        errors: [],
        candidates: candidates(1),
        metadata_json: { next_cursor: "cursor_100" },
      })
      .mockReturnValueOnce(secondWindow);

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: "Retrieve first 100" }));
    await user.click(await screen.findByRole("button", { name: "Retrieve next 100" }));

    expect(screen.getByRole("button", { name: "Retrieve next 100" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Select Background candidate 97" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Remove Background candidate 97" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous 24" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Select Background candidate 97" }));
    expect(screen.getByRole("button", { name: "Deselect Background candidate 97" })).toBeEnabled();

    finishSecondWindow?.({
      id: "background_window_2",
      errors: [],
      candidates: candidates(101),
      metadata_json: {},
    });
    expect(await screen.findByRole("button", { name: "Retrieval complete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deselect Background candidate 97" })).toBeEnabled();
  });

  it("reconciles a completed retrieval after restart without leaving confirmation busy", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const existingCandidate = {
      id: "restart_existing",
      source_kind: "instagram" as const,
      source_locator: "/restart-existing.jpg",
      display_name: "Selected before restart",
      media_type: "image" as const,
      thumbnail_path: "/restart-existing.jpg",
      status: "ready" as const,
      selected: false,
      metadata_json: { scan_surface: "feed" },
    };
    const recoveredCandidate = {
      ...existingCandidate,
      id: "restart_recovered",
      source_locator: "/restart-recovered.jpg",
      display_name: "Recovered after restart",
      thumbnail_path: "/restart-recovered.jpg",
    };
    const completedAcquisition: SocialAcquisitionJob = {
      id: "restart_job",
      request: {
        provider: "instagram",
        url: "https://www.instagram.com/subject",
        browser: "chrome",
        limit: 100,
      },
      request_fingerprint: "restart-fingerprint",
      status: "complete",
      attempt: 1,
      max_attempts: 3,
      progress_message: "Retrieved 1 candidate record",
      cancel_requested: false,
      result: {
        id: "restart_result",
        errors: [],
        candidates: [recoveredCandidate],
        metadata_json: { next_cursor: "restart_cursor" },
      },
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:01:00Z",
      completed_at: "2026-07-25T00:01:00Z",
    };
    engine.getSocialAcquisitionJob = vi.fn().mockResolvedValue(completedAcquisition);
    window.localStorage.setItem("lorasuite:guided-stage:v2", "sources");
    window.localStorage.setItem("lorasuite:guided-source-drafts:v1", JSON.stringify({
      instagram: {
        url: "https://www.instagram.com/subject",
        candidates: [existingCandidate],
        selectedIds: ["restart_existing"],
        activeAcquisitionJobId: "restart_job",
      },
    }));

    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Open Instagram intake" }));

    expect(await screen.findByText("Recovered 2 unique previews after restart. The next 100 are ready to retrieve.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deselect Selected before restart" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Confirm batch" })).toBeEnabled();
    expect(engine.getSocialAcquisitionJob).toHaveBeenCalledTimes(1);
  });

  it("clears the working retrieval queue without touching imported progress", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    render(<GuidedExperience engine={engine} mediaItems={[]} target="image" onTargetChange={vi.fn()} onMediaItemsImported={vi.fn()} onOpenStudio={vi.fn()} />);

    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    expect(await screen.findByText("One source post")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear queue" }));

    expect(screen.queryByText("One source post")).not.toBeInTheDocument();
    expect(screen.getByText("Retrieval queue cleared. Confirmed vault media was not changed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm batch" })).toBeDisabled();
  });

  it("requires a second click before clearing every imported media item", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const onAllMediaCleared = vi.fn();
    render(
      <GuidedExperience
        engine={engine}
        mediaItems={[importedImage]}
        target="image"
        onTargetChange={vi.fn()}
        onMediaItemsImported={vi.fn()}
        onAllMediaCleared={onAllMediaCleared}
        onOpenStudio={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Start with"), "image");
    await user.click(screen.getByRole("button", { name: "Continue to sources" }));
    await user.click(await screen.findByRole("button", { name: "Open Instagram intake" }, { timeout: 1200 }));
    await user.click(screen.getByRole("button", { name: /Retrieve (?:first|next) 100/ }));
    expect(await screen.findByText("One source post")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear all media" }));
    expect(engine.clearAllMedia).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm clear all" }));

    await waitFor(() => expect(engine.clearAllMedia).toHaveBeenCalledWith("CLEAR ALL MEDIA"));
    expect(onAllMediaCleared).toHaveBeenCalledOnce();
    expect(screen.queryByText("One source post")).not.toBeInTheDocument();
    expect(screen.getByText("All imported media and dependent workspace data were cleared.")).toBeInTheDocument();
  });
});
