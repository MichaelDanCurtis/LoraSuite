import type { ComponentProps } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IdentifyTab } from "./IdentifyTab";
import type { CharacterProject, MediaItem } from "../lib/types";

describe("IdentifyTab", () => {
  const mediaItems: MediaItem[] = [
    {
      id: "media_portrait",
      source_id: "source_1",
      raw_path: "/tmp/vault/raw/portrait.png",
      media_type: "image",
      width: 768,
      height: 1024,
      status: "new",
    },
  ];

  it("restores a persistent character project and its health report", async () => {
    const engine = engineStub();
    render(<IdentifyTab mediaItems={mediaItems} engine={engine} />);

    expect(screen.getByRole("heading", { name: "Face Identity" })).toBeInTheDocument();
    expect((await screen.findAllByText("portrait.png")).length).toBeGreaterThan(0);
    expect(screen.getByText("Candidates")).toBeInTheDocument();
    expect(screen.getByText("Select at least 5 clear identity anchors.")).toBeInTheDocument();
    expect(engine.assetUrl).toHaveBeenCalledWith("/tmp/vault/raw/portrait.png");
  });

  it("continues directly from identity verification to dataset building", async () => {
    const user = userEvent.setup();
    const onBuildDatasets = vi.fn();
    render(<IdentifyTab mediaItems={mediaItems} engine={engineStub()} onBuildDatasets={onBuildDatasets} />);

    await user.click(await screen.findByRole("button", { name: "Build Datasets" }));
    expect(onBuildDatasets).toHaveBeenCalledOnce();
  });

  it("presents a simple guided identity result and confirms a ready visual identity", async () => {
    const user = userEvent.setup();
    const onBuildDatasets = vi.fn();
    const readyProject = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
          decision_source: "anchor",
          identity_score: 0.91,
        },
      },
      health: {
        ...project().health,
        accepted_count: 1,
        review_count: 0,
        anchor_count: 1,
        effective_observation_count: 1,
        warnings: [],
      },
    });
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([readyProject]),
    });

    render(
      <IdentifyTab
        mediaItems={mediaItems}
        engine={engine}
        guided
        guidedTarget="image"
        onBuildDatasets={onBuildDatasets}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Identity match ready" })).toBeInTheDocument();
    expect(screen.getByLabelText("AI reference photos")).toBeInTheDocument();
    expect(screen.queryByLabelText("Identity candidate bubbles")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Face Identity" })).not.toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm Identity" });
    expect(confirm).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Check reference photos" }));
    expect(screen.getByRole("dialog", { name: "Review reference photos" })).toBeInTheDocument();
    expect(screen.getByText("Does this clearly show the right person?")).toBeInTheDocument();
    await user.click(screen.getByTitle("Close review"));

    await user.click(confirm);
    expect(onBuildDatasets).toHaveBeenCalledOnce();
  });

  it("lets the user choose when to scan for the first identity anchors", async () => {
    const user = userEvent.setup();
    const analyzed = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          faces: [
            {
              index: 0,
              confidence: 0.96,
              bounding_box: { x: 0.3, y: 0.15, width: 0.35, height: 0.35 },
              landmarks: [],
              selected: true,
            },
          ],
          selected_face_index: 0,
        },
      },
    });
    const anchored = project({
      observations: {
        media_portrait: {
          ...analyzed.observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
          decision_source: "anchor",
        },
      },
      health: {
        ...project().health,
        accepted_count: 1,
        review_count: 0,
        anchor_count: 1,
      },
    });
    const setCharacterProjectAnchors = vi.fn().mockResolvedValue(anchored);
    const analyzeCharacterProject = vi.fn()
      .mockResolvedValueOnce(analyzed)
      .mockResolvedValueOnce(anchored);
    const engine = engineStub({ setCharacterProjectAnchors, analyzeCharacterProject });

    render(
      <IdentifyTab
        mediaItems={mediaItems}
        engine={engine}
        guided
        guidedTarget="image"
      />,
    );

    expect(await screen.findByRole("button", { name: "Choose reference photo" })).toBeEnabled();
    expect(analyzeCharacterProject).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Find automatically" }));
    expect(await screen.findByRole("button", { name: "Check reference photos" })).toBeInTheDocument();
    expect(screen.getByText(/clear reference photo/)).toBeInTheDocument();
    expect(screen.getByText("Identity anchors")).toBeInTheDocument();
    await waitFor(() => {
      expect(setCharacterProjectAnchors).toHaveBeenCalledWith(
        "character_project_1",
        ["media_portrait"],
      );
    });
    expect(await screen.findByText(/1 trusted face selected automatically/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check reference photos" })).toBeInTheDocument();
  });

  it("lets guided review select and anchor the correct detected person", async () => {
    const user = userEvent.setup();
    const multipleFaces = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          face_count: 2,
          selected_face_index: 0,
          faces: [
            {
              index: 0,
              confidence: 0.97,
              bounding_box: { x: 0.1, y: 0.12, width: 0.22, height: 0.24 },
              landmarks: [],
              selected: true,
            },
            {
              index: 1,
              confidence: 0.93,
              bounding_box: { x: 0.6, y: 0.14, width: 0.2, height: 0.22 },
              landmarks: [],
              selected: false,
            },
          ],
        },
      },
    });
    const selectedFace = project({
      ...multipleFaces,
      observations: {
        media_portrait: {
          ...multipleFaces.observations.media_portrait,
          selected_face_index: 1,
          faces: multipleFaces.observations.media_portrait.faces?.map((face) => ({
            ...face,
            selected: face.index === 1,
          })),
        },
      },
    });
    const anchored = project({
      ...selectedFace,
      observations: {
        media_portrait: {
          ...selectedFace.observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
          decision_source: "anchor",
        },
      },
      health: {
        ...selectedFace.health,
        accepted_count: 1,
        review_count: 0,
        anchor_count: 1,
      },
    });
    const selectCharacterProjectFace = vi.fn().mockResolvedValue(selectedFace);
    const setCharacterProjectAnchors = vi.fn().mockResolvedValue(anchored);
    const analyzeCharacterProject = vi.fn().mockResolvedValue(anchored);
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([multipleFaces]),
      selectCharacterProjectFace,
      setCharacterProjectAnchors,
      analyzeCharacterProject,
    });

    render(<IdentifyTab mediaItems={mediaItems} engine={engine} guided guidedTarget="image" />);

    await user.click(await screen.findByRole("button", { name: "Choose reference photo" }));
    await user.click(screen.getByRole("button", { name: /Face 2 93%/ }));
    await user.click(screen.getByRole("button", { name: "Anchor this person" }));

    await waitFor(() => expect(selectCharacterProjectFace).toHaveBeenCalledWith(
      "character_project_1",
      "media_portrait",
      1,
    ));
    expect(setCharacterProjectAnchors).toHaveBeenCalledWith("character_project_1", ["media_portrait"]);
    expect(await screen.findByText(/1 trusted face now defines the person/)).toBeInTheDocument();
  });

  it("explains the long identity wait instead of leaving disabled review choices", async () => {
    const user = userEvent.setup();
    const anchored = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
          decision_source: "anchor",
        },
      },
      health: {
        ...project().health,
        accepted_count: 1,
        review_count: 0,
        anchor_count: 1,
      },
    });
    let resolveAnalysis!: (value: CharacterProject) => void;
    const analysis = new Promise<CharacterProject>((resolve) => {
      resolveAnalysis = resolve;
    });
    const engine = engineStub({
      setCharacterProjectAnchors: vi.fn().mockResolvedValue(anchored),
      analyzeCharacterProject: vi.fn().mockReturnValue(analysis),
    });

    render(<IdentifyTab mediaItems={mediaItems} engine={engine} guided guidedTarget="image" />);

    await user.click(await screen.findByRole("button", { name: "Choose reference photo" }));
    await user.click(screen.getByRole("button", { name: "Anchor this person" }));

    expect(await screen.findByText("Matching this person across 1 image")).toBeInTheDocument();
    expect(screen.getByText(/nothing is needed from you/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anchor this person" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Review uncertain photos" })).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      resolveAnalysis(anchored);
      await analysis;
    });
    await waitFor(() => {
      expect(screen.queryByText("Matching this person across 1 image")).not.toBeInTheDocument();
    });
  });

  it("keeps guided voice verification gated until an accepted voice anchor exists", async () => {
    const readyProject = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
        },
      },
      health: {
        ...project().health,
        accepted_count: 1,
        review_count: 0,
        anchor_count: 1,
      },
    });
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([readyProject]),
    });

    render(
      <IdentifyTab
        mediaItems={mediaItems}
        engine={engine}
        guided
        guidedTarget="voice"
      />,
    );

    expect(await screen.findByRole("button", { name: "Confirm Identity" })).toBeDisabled();
    expect(screen.getByText("Still needed: confirmation for every accepted voice clip.")).toBeInTheDocument();
  });

  it("keeps voice readiness gated when any accepted sample lacks identity confirmation", async () => {
    const voiceItems: MediaItem[] = [
      ...mediaItems,
      { id: "voice_anchor", media_type: "audio", raw_path: "/tmp/vault/raw/anchor.wav" },
      { id: "voice_unconfirmed", media_type: "audio", raw_path: "/tmp/vault/raw/unconfirmed.wav" },
    ];
    const engine = engineStub({
      listVaultMedia: vi.fn().mockResolvedValue(voiceItems),
      getVoiceIdentityProfile: vi.fn().mockResolvedValue({
        project_id: "character_project_1",
        anchor_media_item_ids: ["voice_anchor"],
        evidence: {},
        updated_at: "2026-07-10T00:00:00Z",
      }),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [
          {
            media_item_id: "voice_anchor",
            lane: "audio",
            review_status: "accepted",
            speaker_confirmation: "anchor",
            updated_at: "2026-07-10T00:00:00Z",
          },
          {
            media_item_id: "voice_unconfirmed",
            lane: "audio",
            review_status: "accepted",
            updated_at: "2026-07-10T00:00:00Z",
          },
        ],
        updated_at: "2026-07-10T00:00:00Z",
      }),
    });

    render(
      <IdentifyTab
        mediaItems={voiceItems}
        engine={engine}
        guided
        guidedTarget="voice"
      />,
    );

    expect(await screen.findByRole("button", { name: "Confirm Identity" })).toBeDisabled();
    expect(screen.getByText("Still needed: confirmation for every accepted voice clip.")).toBeInTheDocument();
  });

  it("uses the source video poster as artwork for guided voice candidates", async () => {
    const user = userEvent.setup();
    const bundleKey = "instagram:post_1";
    const crossMedia: MediaItem[] = [
      ...mediaItems,
      {
        id: "media_poster",
        source_id: "source_1",
        media_type: "image",
        raw_path: "/tmp/vault/raw/poster.jpg",
        metadata_json: {
          source_bundle_key: bundleKey,
          asset_role: "video_poster",
        },
      },
      {
        id: "media_audio",
        source_id: "source_1",
        media_type: "audio",
        raw_path: "/tmp/vault/raw/voice.m4a",
        metadata_json: {
          source_bundle_key: bundleKey,
          asset_role: "video_audio",
        },
      },
    ];
    const engine = engineStub({
      listVaultMedia: vi.fn().mockResolvedValue(crossMedia),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [
          {
            media_item_id: "media_audio",
            lane: "audio",
            review_status: "pending",
            updated_at: "2026-07-10T00:00:00Z",
          },
        ],
        updated_at: "2026-07-10T00:00:00Z",
      }),
    });

    render(
      <IdentifyTab
        mediaItems={crossMedia}
        engine={engine}
        guided
        guidedTarget="voice"
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Review voice" }));
    expect(await screen.findByText("Keep samples spoken by the same person")).toBeInTheDocument();
    expect(document.querySelector(".guided-cross-media-preview img")).toHaveAttribute(
      "src",
      "/asset//tmp/vault/raw/poster.jpg",
    );
  });

  it("persists identity anchors and runs automatic dataset analysis", async () => {
    const user = userEvent.setup();
    const anchored = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          is_anchor: true,
          review_status: "accepted",
          decision_source: "anchor",
        },
      },
      health: { ...project().health, anchor_count: 1, accepted_count: 1, review_count: 0 },
    });
    const engine = engineStub({
      setCharacterProjectAnchors: vi.fn().mockResolvedValue(anchored),
      analyzeCharacterProject: vi.fn().mockResolvedValue(anchored),
    });
    render(<IdentifyTab mediaItems={mediaItems} engine={engine} />);

    await user.click(await screen.findByTitle("Trusted identity anchor"));
    expect(engine.setCharacterProjectAnchors).toHaveBeenCalledWith("character_project_1", [
      "media_portrait",
    ]);

    await user.click(screen.getByRole("button", { name: "Analyze Faces" }));
    await waitFor(() =>
      expect(engine.analyzeCharacterProject).toHaveBeenCalledWith("character_project_1"),
    );
    expect(screen.getByText("Compiled 1 candidates; 0 need review.")).toBeInTheDocument();
  });

  it("saves explicit LoRA intent instead of inferring it from the media", async () => {
    const user = userEvent.setup();
    const voiceProject = project({
      intent: {
        ...project().intent,
        requested_outputs: ["voice"],
        training_target_profile_ids: {
          voice: "runpod_fish_speech_s2_voice_lora",
        },
      },
    });
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([voiceProject]),
    });
    render(<IdentifyTab mediaItems={mediaItems} engine={engine} />);

    const subject = await screen.findByLabelText("Subject");
    expect(screen.getByText("Training intent and attribute policy").closest("details")).toHaveAttribute("open");
    await user.clear(subject);
    await user.type(subject, "Mary Sue");
    await user.type(screen.getByLabelText("Trigger token"), "example_person");
    await user.click(screen.getByRole("button", { name: "Save Intent" }));

    expect(engine.updateCharacterProject).toHaveBeenCalledWith(
      "character_project_1",
      expect.objectContaining({
        intent: expect.objectContaining({
          target_type: "character",
          subject_name: "Mary Sue",
          requested_outputs: ["voice"],
          training_target_profile_ids: {
            voice: "runpod_fish_speech_s2_voice_lora",
          },
          trigger_token: "example_person",
        }),
      }),
    );
  });

  it("selects a detected subject face and materializes its crop recipe", async () => {
    const user = userEvent.setup();
    const compiled = project({
      observations: {
        media_portrait: {
          ...project().observations.media_portrait,
          identity_backend: "opencv-sface-2021dec",
          selected_face_index: 0,
          faces: [
            {
              index: 0,
              confidence: 0.98,
              bounding_box: { x: 0.16, y: 0.1, width: 0.22, height: 0.2 },
              landmarks: [],
              anchor_similarity: 0.84,
              selected: true,
            },
            {
              index: 1,
              confidence: 0.95,
              bounding_box: { x: 0.6, y: 0.12, width: 0.2, height: 0.18 },
              landmarks: [],
              anchor_similarity: 0.31,
              selected: false,
            },
          ],
          crop_recipe_ids: ["crop_face"],
        },
      },
      crop_recipes: {
        crop_face: {
          id: "crop_face",
          media_item_id: "media_portrait",
          kind: "face",
          rect: { x: 0.1, y: 0.1, width: 0.6, height: 0.6 },
          aspect_ratio: "1:1",
          face_index: 0,
          status: "proposed",
          output_media_item_id: null,
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      },
    });
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([compiled]),
      selectCharacterProjectFace: vi.fn().mockResolvedValue(compiled),
      updateCharacterProjectCrop: vi.fn().mockResolvedValue(compiled),
      materializeCharacterProjectCrop: vi.fn().mockResolvedValue({
        project: compiled,
        media_item: mediaItems[0],
      }),
    });
    render(<IdentifyTab mediaItems={mediaItems} engine={engine} />);

    await user.click(await screen.findByRole("button", { name: "Select face 2" }));
    expect(engine.selectCharacterProjectFace).toHaveBeenCalledWith(
      "character_project_1",
      "media_portrait",
      1,
    );

    await user.click(screen.getByRole("button", { name: "Materialize" }));
    expect(engine.updateCharacterProjectCrop).toHaveBeenCalledWith(
      "character_project_1",
      "crop_face",
      {
        rect: { x: 0.1, y: 0.1, width: 0.6, height: 0.6 },
        status: "approved",
      },
    );
    expect(engine.materializeCharacterProjectCrop).toHaveBeenCalledWith(
      "character_project_1",
      "crop_face",
    );
    expect(screen.getByText("Training crop materialized in the vault.")).toBeInTheDocument();
  });

  it("reviews persistent video and audio identity handoffs in separate lanes", async () => {
    const user = userEvent.setup();
    const crossMedia: MediaItem[] = [
      ...mediaItems,
      { id: "media_video", media_type: "video", raw_path: "/tmp/vault/raw/clip.mp4" },
      { id: "media_audio", media_type: "audio", raw_path: "/tmp/vault/raw/voice.wav" },
    ];
    const acceptedHandoff = {
      items: [
        {
          media_item_id: "media_video",
          lane: "video" as const,
          review_status: "accepted" as const,
          updated_at: "2026-07-10T00:00:00Z",
        },
        {
          media_item_id: "media_audio",
          lane: "audio" as const,
          review_status: "pending" as const,
          updated_at: "2026-07-10T00:00:00Z",
        },
      ],
      updated_at: "2026-07-10T00:00:00Z",
    };
    const anchoredVoiceProfile = {
      project_id: "character_project_1",
      anchor_media_item_ids: ["media_audio"],
      evidence: {},
      updated_at: "2026-07-10T00:00:00Z",
    };
    const analyzedVoiceProfile = {
      ...anchoredVoiceProfile,
      evidence: {
        media_audio: {
          media_item_id: "media_audio",
          similarity: 1,
          recommendation: "keep" as const,
          is_anchor: true,
          anchor_count: 1,
          reasons: ["trusted voice anchor selected by user"],
          warnings: ["Use at least three varied voice anchors for a stronger consensus"],
          backend: "sherpa-onnx-wespeaker-campp",
          analyzed_at: "2026-07-10T00:00:00Z",
        },
      },
    };
    const confirmedHandoff = {
      ...acceptedHandoff,
      items: acceptedHandoff.items.map((item) =>
        item.media_item_id === "media_audio"
          ? { ...item, review_status: "accepted" as const, speaker_confirmation: "anchor" as const }
          : item,
      ),
    };
    const confirmVoiceIdentitySample = vi.fn().mockResolvedValue({
      project: project(),
      profile: anchoredVoiceProfile,
      handoff: confirmedHandoff,
    });
    const analyzeVoiceIdentity = vi.fn().mockResolvedValue(analyzedVoiceProfile);
    const engine = engineStub({
      listVaultMedia: vi.fn().mockResolvedValue(crossMedia),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [
          { ...acceptedHandoff.items[0], review_status: "pending" },
          acceptedHandoff.items[1],
        ],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      updateCurationReview: vi.fn().mockResolvedValue(acceptedHandoff),
      confirmVoiceIdentitySample,
      analyzeVoiceIdentity,
    });
    render(<IdentifyTab mediaItems={crossMedia} engine={engine} />);

    await user.click(await screen.findByRole("tab", { name: /Video Subject 1/ }));
    expect(screen.getByRole("heading", { name: "Video Subject" })).toBeInTheDocument();
    expect(document.querySelector("video")).toHaveAttribute("src", "/asset//tmp/vault/raw/clip.mp4");

    await user.click(screen.getByTitle("Accept"));
    expect(engine.updateCurationReview).toHaveBeenCalledWith(
      "media_video",
      "accepted",
      "character_project_1",
      "image",
      undefined,
    );

    await user.click(screen.getByRole("tab", { name: /Speaker 1/ }));
    expect(screen.getByRole("heading", { name: "Speaker Identity" })).toBeInTheDocument();
    expect(document.querySelector("audio")).toHaveAttribute("src", "/asset//tmp/vault/raw/voice.wav");

    await user.click(screen.getByTitle("Confirm as Character Dataset's voice"));
    expect(confirmVoiceIdentitySample).toHaveBeenCalledWith(
      "character_project_1",
      "media_audio",
      "Character Dataset",
      "voice",
    );
    await user.click(screen.getByRole("button", { name: "Compare Voices" }));
    expect(analyzeVoiceIdentity).toHaveBeenCalledWith("character_project_1", ["media_audio"]);
    expect(await screen.findByText("100%", { selector: "strong" })).toBeInTheDocument();
  });

  function engineStub(
    overrides: Partial<ComponentProps<typeof IdentifyTab>["engine"]> = {},
  ): ComponentProps<typeof IdentifyTab>["engine"] {
    const savedProject = project();
    return {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      listVaultMedia: vi.fn().mockResolvedValue(mediaItems),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      updateCurationReview: vi.fn().mockResolvedValue({
        items: [],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      getIdentityStatus: vi.fn().mockResolvedValue({
        backend: "opencv-sface",
        model_version: "test",
        installed: true,
        ready: true,
        download_size_bytes: 0,
        message: "SFace ready",
      }),
      installIdentityModels: vi.fn(),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({
        backend: "sherpa-onnx-wespeaker-campp",
        model_version: "test",
        installed: true,
        ready: true,
        download_size_bytes: 0,
        message: "Voice identity model ready",
      }),
      installVoiceIdentityModel: vi.fn(),
      getVoiceIdentityProfile: vi.fn().mockResolvedValue({
        project_id: "character_project_1",
        anchor_media_item_ids: [],
        evidence: {},
        updated_at: "2026-07-10T00:00:00Z",
      }),
      setVoiceIdentityAnchors: vi.fn(),
      confirmVoiceIdentitySample: vi.fn(),
      analyzeVoiceIdentity: vi.fn(),
      listCharacterProjects: vi.fn().mockResolvedValue([savedProject]),
      createCharacterProject: vi.fn().mockResolvedValue(savedProject),
      updateCharacterProject: vi.fn().mockResolvedValue(savedProject),
      addCharacterProjectCandidates: vi.fn().mockResolvedValue(savedProject),
      setCharacterProjectAnchors: vi.fn().mockResolvedValue(savedProject),
      updateCharacterProjectObservation: vi.fn().mockResolvedValue(savedProject),
      analyzeCharacterProject: vi.fn().mockResolvedValue(savedProject),
      selectCharacterProjectFace: vi.fn().mockResolvedValue(savedProject),
      updateCharacterProjectCrop: vi.fn().mockResolvedValue(savedProject),
      materializeCharacterProjectCrop: vi.fn().mockResolvedValue({
        project: savedProject,
        media_item: mediaItems[0],
      }),
      ...overrides,
    };
  }

  function project(overrides: Partial<CharacterProject> = {}): CharacterProject {
    return {
      id: "character_project_1",
      name: "Character Dataset",
      intent: {
        target_type: "character",
        subject_name: "",
        trigger_token: "",
        description: "",
        learned_attributes: ["identity", "face", "body"],
        controllable_attributes: ["expression", "pose", "clothing", "environment"],
        excluded_attributes: ["background", "other people", "watermark"],
      },
      candidate_media_item_ids: ["media_portrait"],
      observations: {
        media_portrait: {
          media_item_id: "media_portrait",
          review_status: "needs_review",
          decision_source: "automatic",
          view: "face",
          is_anchor: false,
          quality_score: 0.82,
          diversity_score: 1,
          identity_score: null,
          face_count: 1,
          face_area: 0.12,
          body_coverage: 0.1,
          aesthetic_score: 0.7,
          head_yaw: 0,
          reasons: ["select identity anchors before automatic comparison"],
          warnings: [],
          analyzer: "apple-vision-dataset-v1",
          updated_at: "2026-07-09T00:00:00Z",
        },
      },
      health: {
        candidate_count: 1,
        accepted_count: 0,
        review_count: 1,
        rejected_count: 0,
        anchor_count: 0,
        effective_observation_count: 0,
        source_count: 1,
        largest_source_share: 1,
        average_quality: 0.82,
        average_diversity: 1,
        view_counts: { face: 1 },
        analyzer: "apple-vision-dataset-v1",
        warnings: [
          "Select at least 5 clear identity anchors.",
          "Fewer than 20 observations are accepted for training.",
          "No full-body views are represented.",
        ],
      },
      created_at: "2026-07-09T00:00:00Z",
      updated_at: "2026-07-09T00:00:00Z",
      ...overrides,
    };
  }
});
