import type { ComponentProps } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TrainTab } from "./TrainTab";
import type {
  CharacterProject,
  DatasetSnapshot,
  LoraModelCard,
  MediaItem,
  ModelIntentRecipe,
} from "../lib/types";

const { isTauriMock, openMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
  openMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: openMock }));

describe("TrainTab", () => {
  beforeEach(() => {
    isTauriMock.mockReturnValue(false);
    openMock.mockReset();
  });

  it("exposes the same compatible recipes and caption controls inside Guided advanced options", async () => {
    const user = userEvent.setup();
    const engine = engineStub();
    const catalog = await engine.listTrainingTargets();
    vi.mocked(engine.listTrainingTargets).mockResolvedValue([...catalog, { ...catalog[0], profile_id: "sdxl", label: "SDXL 1.0 Character" }, { ...catalog[0], profile_id: "video", label: "Video only", modality: "video" }]);
    render(<TrainTab engine={engine} targetItems={mediaItems} activeProjectId={project.id} guided />);
    await user.click(await screen.findByText("Advanced dataset options"));
    const selector = await screen.findByLabelText("Image target");
    expect(within(selector).getByRole("option", { name: "SDXL 1.0 Character" })).toBeInTheDocument();
    expect(within(selector).queryByRole("option", { name: "Video only" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Vision provider")).toBeInTheDocument();
    expect(screen.getByLabelText("AI review selection controls")).toBeInTheDocument();
  });

  it("restores a persistent caption snapshot and its balance", async () => {
    const engine = engineStub();
    render(<TrainTab engine={engine} />);

    expect(screen.getByRole("heading", { name: "Dataset Compiler" })).toBeInTheDocument();
    expect(await screen.findByText("crop.png")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Training caption")).toHaveValue(
        "example_person, person, close-up portrait",
      ),
    );
    expect(screen.getByText("Needs visual confirmation")).toBeInTheDocument();
    expect(screen.getByText("expression")).toBeInTheDocument();
    expect(screen.getByText("Caption review is incomplete.")).toBeInTheDocument();
  });

  it("presents model choice and one next action in Guided Build", async () => {
    const user = userEvent.setup();
    render(<TrainTab engine={engineStub()} guided />);

    expect(await screen.findByRole("heading", { name: "Where should this LoRA work?" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Model choices" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change model" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change model" }));
    expect(screen.getByRole("group", { name: "Model choices" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /KREA 2/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FLUX\.1 Dev/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText("More model options")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Build progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Let AI caption 1 item/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dataset Compiler" })).not.toBeInTheDocument();
    expect(screen.queryByText("LoRA Metadata")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("AI review selection controls")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Dataset compiler modes" })).not.toBeInTheDocument();
  });

  it("offers KREA 2 as a first-class guided target", async () => {
    const user = userEvent.setup();
    render(<TrainTab engine={engineStub()} guided />);

    await user.click(await screen.findByRole("button", { name: "Change model" }));
    await user.click(await screen.findByRole("button", { name: /KREA 2/ }));

    expect(screen.getByText("KREA 2 Character")).toBeInTheDocument();
    expect(screen.getByText("Training available")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Model choices" })).not.toBeInTheDocument();
  });

  it("turns provider selection into a focused training stage", async () => {
    const user = userEvent.setup();
    const exported = snapshot({
      status: "exported",
      export_path: "/tmp/runcomfy",
      fingerprint: "a".repeat(64),
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          status: "approved",
        },
      },
      balance: {
        ...snapshot().balance,
        approved_count: 1,
        review_count: 0,
        warnings: [],
      },
    });
    render(
      <TrainTab
        engine={engineStub({
          listDatasetSnapshots: vi.fn().mockResolvedValue([exported]),
          getDatasetSnapshot: vi.fn().mockResolvedValue(exported),
        })}
        guided
      />,
    );

    expect(await screen.findByRole("region", { name: "Training recipe" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Choose training provider/ }));

    expect(screen.queryByRole("region", { name: "Training recipe" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Training provider" })).toBeInTheDocument();
    expect(screen.getByText(/Not sure\? Choose RunComfy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /RunComfy.*Recommended/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /RunPod.*Advanced/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /RunPod/ }));

    expect(screen.queryByRole("group", { name: "Training provider" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Training provider workspace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change provider" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Training recipe" })).not.toBeInTheDocument();
  });

  it("previews, applies, and restores a strongest image set explicitly", async () => {
    const user = userEvent.setup();
    const items = Object.fromEntries(Array.from({ length: 90 }, (_, index) => {
      const record = snapshot().items.dataset_item_1;
      return [
        `dataset_item_${index}`,
        {
          ...record,
          id: `dataset_item_${index}`,
          source_media_item_id: `media_source_${index}`,
          strongest_set_excluded: false,
          strongest_set_rank: null,
        },
      ];
    }));
    const largeSnapshot = snapshot({
      status: "exported",
      items,
      balance: {
        ...snapshot().balance,
        total_count: 90,
        review_count: 90,
      },
    });
    const editableLargeSnapshot = {
      ...largeSnapshot,
      id: "dataset_snapshot_editable",
      version: 2,
      status: "draft" as const,
    };
    const proposal = {
      snapshot_id: largeSnapshot.id,
      target_count: 50,
      selected_count: 50,
      excluded_count: 40,
      already_excluded_count: 0,
      recipe_minimum: 20,
      recipe_recommended: 35,
      recipe_maximum: 80,
      selected: Array.from({ length: 50 }, (_, index) => ({
        item_id: `dataset_item_${index}`,
        score: 0.9 - index * 0.01,
        reasons: ["high visual quality"],
        group: (["face", "upper_body", "full_body", "environment"] as const)[index % 4],
      })),
      excluded_item_ids: Array.from({ length: 40 }, (_, index) => `dataset_item_${index + 50}`),
      view_counts: { face: 18, upper_body: 16, full_body: 16 },
      source_counts: { source_1: 25, source_2: 25 },
      average_quality: 0.92,
      average_diversity: 0.61,
      average_identity: 0.88,
      warnings: [],
    };
    const appliedSnapshot = {
      ...editableLargeSnapshot,
      items: Object.fromEntries(Object.entries(items).map(([id, record], index) => [
        id,
        index < 50
          ? { ...record, strongest_set_rank: index + 1 }
          : { ...record, status: "excluded" as const, strongest_set_excluded: true },
      ])),
      balance: {
        ...largeSnapshot.balance,
        review_count: 50,
        excluded_count: 40,
      },
    };
    const proposeDatasetStrongestSet = vi.fn().mockResolvedValue(proposal);
    const applyDatasetStrongestSet = vi.fn().mockResolvedValue({
      snapshot: appliedSnapshot,
      proposal,
    });
    const restoreDatasetStrongestSet = vi.fn().mockResolvedValue(largeSnapshot);
    const compileCharacterDataset = vi.fn().mockResolvedValue(editableLargeSnapshot);

    render(
      <TrainTab
        engine={engineStub({
          listDatasetSnapshots: vi.fn().mockResolvedValue([largeSnapshot]),
          getDatasetSnapshot: vi.fn().mockResolvedValue(largeSnapshot),
          compileCharacterDataset,
          proposeDatasetStrongestSet,
          applyDatasetStrongestSet,
          restoreDatasetStrongestSet,
        })}
        guided
      />,
    );

    const panel = await screen.findByLabelText("Build strongest image set");
    await user.click(within(panel).getByRole("button", { name: "Preview strongest 50" }));

    expect(proposeDatasetStrongestSet).toHaveBeenCalledWith(largeSnapshot.id, 50);
    expect((await within(panel).findAllByText("40", { selector: "strong" })).length).toBeGreaterThan(0);
    const strengthMap = within(panel).getByLabelText("Selected image strength map");
    expect(within(panel).getByLabelText("Face group")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Upper body group")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Full body group")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Environment group")).toBeInTheDocument();
    const centerImage = strengthMap.querySelector<HTMLElement>('[data-strength-rank="1"]');
    expect(centerImage).toHaveClass("is-center");
    await user.hover(centerImage!);
    expect(within(panel).getByRole("img", {
      name: "Rank 1 face preview",
    })).toBeInTheDocument();
    const plottedImages = Array.from(
      strengthMap.querySelectorAll<HTMLElement>("[data-strength-rank]"),
    ).map((element) => ({
      center: element.classList.contains("is-center"),
      left: Number.parseFloat(element.style.left),
      top: Number.parseFloat(element.style.top),
    }));
    plottedImages.forEach((image, index) => {
      plottedImages.slice(index + 1).forEach((other) => {
        const distance = Math.hypot(image.left - other.left, image.top - other.top);
        expect(distance).toBeGreaterThanOrEqual(image.center || other.center ? 11.2 : 7.55);
      });
    });
    const zoomViewport = within(panel).getByLabelText("Zoomable image strength map");
    fireEvent.wheel(zoomViewport, {
      deltaY: -400,
      clientX: 250,
      clientY: 250,
    });
    expect(strengthMap).toHaveStyle({ transform: "scale(1.6)" });
    await user.click(within(panel).getByRole("button", { name: "Reset 160%" }));
    expect(strengthMap).toHaveStyle({ transform: "scale(1)" });
    await user.click(within(panel).getByRole("button", { name: /Browse parked/ }));
    const parkedDialog = await screen.findByRole("dialog", { name: "Parked images" });
    await user.click(within(parkedDialog).getByRole("button", {
      name: "Exchange parked image dataset_item_50",
    }));
    expect(within(panel).getByText("Choose its replacement")).toBeInTheDocument();
    await user.click(within(strengthMap).getByRole("button", {
      name: "Replace rank 2 upper body image with parked image",
    }));
    expect(proposeDatasetStrongestSet).toHaveBeenLastCalledWith(
      largeSnapshot.id,
      50,
      ["dataset_item_1"],
      ["dataset_item_50"],
    );
    await user.click(within(strengthMap).getByRole("button", {
      name: "Disqualify rank 1 face image",
    }));
    expect(proposeDatasetStrongestSet).toHaveBeenLastCalledWith(
      largeSnapshot.id,
      50,
      ["dataset_item_1", "dataset_item_0"],
      ["dataset_item_50"],
    );
    expect(await within(panel).findByLabelText("Face disqualified stack")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Create editable set of 50" }));

    expect(compileCharacterDataset).toHaveBeenCalledWith(
      largeSnapshot.project_id,
      "runcomfy_flux1_dev_character",
    );
    expect(applyDatasetStrongestSet).toHaveBeenCalledWith(
      editableLargeSnapshot.id,
      50,
      ["dataset_item_1", "dataset_item_0"],
      ["dataset_item_50"],
    );
    await user.click(await within(panel).findByRole("button", { name: /Restore parked/ }));
    expect(restoreDatasetStrongestSet).toHaveBeenCalledWith(editableLargeSnapshot.id);
  });

  it("reviews duplicate groups before parking the rejected copies", async () => {
    const user = userEvent.setup();
    const baseRecord = snapshot().items.dataset_item_1;
    const items = Object.fromEntries(Array.from({ length: 90 }, (_, index) => [
      `dataset_item_${index}`,
      {
        ...baseRecord,
        id: `dataset_item_${index}`,
        source_media_item_id: `media_source_${index}`,
      },
    ]));
    const exportedSnapshot = snapshot({
      status: "exported",
      items,
      balance: {
        ...snapshot().balance,
        total_count: 90,
        review_count: 90,
      },
    });
    const editableSnapshot = {
      ...exportedSnapshot,
      id: "dataset_snapshot_dedupe_draft",
      version: 2,
      status: "draft" as const,
    };
    const dedupedSnapshot = {
      ...editableSnapshot,
      items: {
        ...editableSnapshot.items,
        dataset_item_0: {
          ...editableSnapshot.items.dataset_item_0,
          status: "excluded" as const,
        },
      },
    };
    const duplicateProposal = {
      snapshot_id: exportedSnapshot.id,
      scanned_count: 90,
      duplicate_count: 1,
      unreadable_count: 0,
      clusters: [{
        id: "dataset_duplicate_one",
        recommended_keep_item_id: "dataset_item_0",
        candidates: [
          {
            item_id: "dataset_item_0",
            training_media_item_id: baseRecord.training_media_item_id,
            hash_distance: 0,
            score: 0.91,
            group: "face" as const,
            is_recommended_keep: true,
          },
          {
            item_id: "dataset_item_1",
            training_media_item_id: baseRecord.training_media_item_id,
            hash_distance: 2,
            score: 0.72,
            group: "face" as const,
            is_recommended_keep: false,
          },
        ],
      }],
    };
    const proposeDatasetDuplicates = vi.fn().mockResolvedValue(duplicateProposal);
    const compileCharacterDataset = vi.fn().mockResolvedValue(editableSnapshot);
    const bulkUpdateDatasetItems = vi.fn().mockResolvedValue(dedupedSnapshot);

    render(
      <TrainTab
        engine={engineStub({
          listDatasetSnapshots: vi.fn().mockResolvedValue([exportedSnapshot]),
          getDatasetSnapshot: vi.fn().mockResolvedValue(exportedSnapshot),
          proposeDatasetDuplicates,
          compileCharacterDataset,
          bulkUpdateDatasetItems,
        })}
        guided
      />,
    );

    const panel = await screen.findByLabelText("Build strongest image set");
    await user.click(within(panel).getByRole("button", { name: "Dedupe" }));
    expect(proposeDatasetDuplicates).toHaveBeenCalledWith(exportedSnapshot.id);
    const dialog = await screen.findByRole("dialog", { name: "Dedupe" });
    const group = within(dialog).getByRole("article", { name: "Duplicate group 1" });
    const choices = within(group).getAllByRole("button");
    expect(choices[0]).toHaveAttribute("aria-pressed", "true");
    expect(choices[1]).toHaveAttribute("aria-pressed", "false");
    await user.click(choices[1]);
    expect(choices[1]).toHaveAttribute("aria-pressed", "true");
    await user.click(within(dialog).getByRole("button", { name: "Park 1 duplicates" }));

    expect(compileCharacterDataset).toHaveBeenCalledWith(
      exportedSnapshot.project_id,
      "runcomfy_flux1_dev_character",
    );
    expect(bulkUpdateDatasetItems).toHaveBeenCalledWith(
      editableSnapshot.id,
      "excluded",
      ["dataset_item_0"],
    );
    expect(screen.queryByRole("dialog", { name: "Dedupe" })).not.toBeInTheDocument();
  });

  it("sets a missing prompt name without leaving Guided Build", async () => {
    const user = userEvent.setup();
    const projectWithoutToken: CharacterProject = {
      ...project,
      intent: { ...project.intent, trigger_token: "" },
    };
    const blockedSnapshot = snapshot({
      intent: projectWithoutToken.intent,
      balance: {
        ...snapshot().balance,
        recipe_compliance: {
          recipe_id: "flux1_dev_character",
          recipe_version: 1,
          recipe_label: "FLUX.1 Dev Character",
          status: "blocked",
          score: 0.8,
          blocker_count: 1,
          warning_count: 0,
          checks: [{
            check_id: "trigger-token",
            label: "Trigger token",
            passed: false,
            severity: "blocker",
            detail: "Training intent requires a trigger token before freezing.",
          }],
        },
      },
    });
    const rebuiltSnapshot = snapshot({
      intent: { ...projectWithoutToken.intent, trigger_token: "mary_person" },
    });
    const updateCharacterProject = vi.fn().mockResolvedValue({
      ...projectWithoutToken,
      intent: rebuiltSnapshot.intent,
    });
    const compileCharacterDataset = vi.fn().mockResolvedValue(rebuiltSnapshot);

    render(
      <TrainTab
        engine={engineStub({
          listCharacterProjects: vi.fn().mockResolvedValue([projectWithoutToken]),
          listDatasetSnapshots: vi.fn().mockResolvedValue([blockedSnapshot]),
          getDatasetSnapshot: vi.fn().mockResolvedValue(blockedSnapshot),
          updateCharacterProject,
          compileCharacterDataset,
        })}
        guided
      />,
    );

    expect(await screen.findByRole("button", { name: "Change model" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Model choices" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Prompt name")).toHaveValue("mary_person");
    expect(screen.queryByRole("button", { name: /Return to identity/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save name and continue" }));

    expect(updateCharacterProject).toHaveBeenCalledWith(
      project.id,
      expect.objectContaining({
        intent: expect.objectContaining({ trigger_token: "mary_person" }),
      }),
    );
    expect(compileCharacterDataset).toHaveBeenCalledWith(
      project.id,
      "runcomfy_flux1_dev_character",
    );
  });

  it("starts a guided build from the preflight action", async () => {
    const user = userEvent.setup();
    const compileCharacterDataset = vi.fn().mockResolvedValue(snapshot());
    render(
      <TrainTab
        engine={engineStub({
          listDatasetSnapshots: vi.fn().mockResolvedValue([]),
          compileCharacterDataset,
        })}
        guided
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Build dataset draft/ }));

    expect(compileCharacterDataset).toHaveBeenCalledWith(
      "character_project_1",
      "runcomfy_flux1_dev_character",
    );
  });

  it("runs every unresolved caption through AI from the guided preflight action", async () => {
    const user = userEvent.setup();
    const createCaptionJob = vi.fn().mockResolvedValue({
      id: "guided_caption_job",
      snapshot_id: "dataset_snapshot_1",
      item_ids: ["dataset_item_1"],
      provider_id: "openai",
      provider_label: "OpenAI",
      model: "gpt-5",
      status: "queued",
      total_count: 1,
      completed_count: 0,
      failed_count: 0,
      progress_message: "Queued",
      errors: [],
      created_at: "2026-07-19T00:00:00Z",
      started_at: null,
      completed_at: null,
    });
    render(
      <TrainTab
        engine={engineStub({
          createCaptionJob,
          listCaptionProviders: vi.fn().mockResolvedValue([
            {
              id: "openai",
              label: "OpenAI",
              dialect: "responses",
              auth_mode: "api_key",
              base_url: "https://api.openai.com/v1",
              model: "gpt-5",
              configured: true,
            },
          ]),
        })}
        guided
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Let AI caption 1 item/ }));

    expect(createCaptionJob).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      expect.objectContaining({ item_ids: ["dataset_item_1"] }),
    );
    expect(screen.queryByRole("button", { name: /Select .* for AI review/ })).not.toBeInTheDocument();
  });

  it("streams finished captions into a non-blocking guided review while the batch continues", async () => {
    const user = userEvent.setup();
    const generated = snapshot({
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          caption: "example_person, smiling, red dress, close-up portrait",
          unresolved_attributes: ["environment"],
          caption_source: "vision",
          caption_provider: "OpenAI",
          caption_model: "gpt-5",
          caption_confidence: 0.91,
        },
      },
    });
    const queuedJob = {
      id: "guided_live_caption_job",
      snapshot_id: "dataset_snapshot_1",
      item_ids: ["dataset_item_1"],
      provider_id: "openai",
      provider_label: "OpenAI",
      model: "gpt-5",
      status: "queued" as const,
      total_count: 1,
      completed_count: 0,
      failed_count: 0,
      next_item_index: 0,
      progress_message: "Queued",
      errors: [],
      created_at: "2026-07-19T00:00:00Z",
      started_at: null,
      completed_at: null,
    };
    const runningJob = {
      ...queuedJob,
      status: "running" as const,
      completed_count: 1,
      next_item_index: 1,
      progress_message: "Generated 1 of 1 captions",
    };
    const canceledJob = {
      ...runningJob,
      status: "canceled" as const,
      progress_message: "Caption generation stopped by the user",
    };
    const getDatasetSnapshot = vi.fn().mockResolvedValue(generated);
    const updateDatasetItem = vi.fn();
    const cancelCaptionJob = vi.fn().mockResolvedValue(canceledJob);
    const engine = engineStub({
      createCaptionJob: vi.fn().mockResolvedValue(queuedJob),
      getCaptionJob: vi.fn().mockResolvedValue(runningJob),
      cancelCaptionJob,
      getDatasetSnapshot,
      updateDatasetItem,
      listCaptionProviders: vi.fn().mockResolvedValue([
        {
          id: "openai",
          label: "OpenAI",
          dialect: "responses",
          auth_mode: "api_key",
          base_url: "https://api.openai.com/v1",
          model: "gpt-5",
          configured: true,
        },
      ]),
    });
    render(<TrainTab engine={engine} guided />);

    await user.click(await screen.findByRole("button", { name: /Let AI caption 1 item/ }));

    const liveReview = await screen.findByLabelText("Review captions while AI works");
    expect(liveReview).toHaveTextContent("Review this one while the batch continues");
    expect(liveReview).toHaveTextContent("example_person, smiling, red dress, close-up portrait");
    expect(liveReview).toHaveTextContent("Check later: environment");
    expect(getDatasetSnapshot).toHaveBeenCalledWith("dataset_snapshot_1");

    await user.click(screen.getByRole("button", { name: /Edit later/ }));

    expect(updateDatasetItem).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Review captions while AI works")).not.toBeInTheDocument();
    expect(screen.getByText("Saved in the caption edit queue. AI is still generating the rest.")).toBeInTheDocument();
    expect(screen.getByLabelText("AI build progress")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stop captioning" }));

    expect(cancelCaptionJob).toHaveBeenCalledWith("guided_live_caption_job");
    expect(screen.getByText(/Caption generation stopped by the user/)).toBeInTheDocument();
  });

  it("edits release metadata without changing generated model facts", async () => {
    const user = userEvent.setup();
    const initial = snapshot({ model_card: modelCard() });
    const updated = snapshot({
      model_card: modelCard({
        license: "CC-BY-4.0",
        usage: {
          ...modelCard().usage,
          recommended_strength: 0.85,
        },
        validation: {
          status: "ready",
          blocker_count: 0,
          warning_count: 0,
          checks: modelCard().validation.checks.map((check) => ({ ...check, passed: true })),
        },
      }),
    });
    const updateDatasetModelCard = vi.fn().mockResolvedValue(updated);
    render(
      <TrainTab
        engine={engineStub({
          listDatasetSnapshots: vi.fn().mockResolvedValue([initial]),
          getDatasetSnapshot: vi.fn().mockResolvedValue(initial),
          updateDatasetModelCard,
        })}
      />,
    );

    expect(await screen.findByText("LoRA Metadata")).toBeInTheDocument();
    expect(screen.getAllByText("black-forest-labs/FLUX.1-dev")).not.toHaveLength(0);
    await waitFor(() =>
      expect(screen.getByLabelText("Model license")).toHaveValue("unspecified"),
    );
    await user.clear(screen.getByLabelText("Model license"));
    expect(screen.getByLabelText("Model license")).toHaveValue("");
    await user.type(screen.getByLabelText("Model license"), "CC-BY-4.0");
    await user.type(screen.getByLabelText("Recommended LoRA strength"), "0.85");
    await user.click(screen.getByRole("button", { name: "Save Metadata" }));

    expect(updateDatasetModelCard).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      expect.objectContaining({
        name: "mary-flux1-character",
        license: "CC-BY-4.0",
        recommended_strength: 0.85,
      }),
    );
    expect(await screen.findByText("Release ready")).toBeInTheDocument();
  });

  it("reviews timestamped voice segments and persists approval decisions", async () => {
    const user = userEvent.setup();
    const audioItem: MediaItem = {
      id: "audio_source",
      source_id: "source_audio",
      raw_path: "/tmp/vault/audio.wav",
      media_type: "audio",
      duration: 8,
    };
    const compilation = {
      project_id: project.id,
      source_media_item_ids: [audioItem.id],
      segments: {
        voice_segment_1: {
          id: "voice_segment_1",
          project_id: project.id,
          source_media_item_id: audioItem.id,
          media_item_id: "audio_segment_1",
          audio_path: "/tmp/vault/segment.wav",
          start_seconds: 1.2,
          end_seconds: 4.8,
          transcript: "This is a reviewed voice line.",
          language: "en",
          transcript_confidence: 0.94,
          speaker_similarity: 0.91,
          identity_recommendation: "keep" as const,
          identity_reasons: ["Speaker closely matches trusted anchors"],
          identity_warnings: [],
          quality: {
            quality_score: 0.82,
            recommendation: "keep" as const,
            active_audio_ratio: 0.74,
            silence_ratio: 0.26,
            clipping_ratio: 0.001,
            noise_floor_db: -48,
            snr_db: 22,
            dynamic_range_db: 31,
            reverb_risk: 0.2,
            background_music_risk: 0.08,
            speaker_count: 1,
            source_classification: "isolated_voice",
            voice_isolation_applied: true,
            reasons: ["clean active speech with usable signal separation"],
            warnings: [],
            analyzer: "portable-voice-quality-v1",
            analyzed_at: "2026-07-10T00:00:00Z",
          },
          recommendation: "keep" as const,
          status: "needs_review" as const,
          reasons: ["Speaker closely matches trusted anchors"],
          warnings: [],
          created_at: "2026-07-10T00:00:00Z",
          updated_at: "2026-07-10T00:00:00Z",
        },
      },
      export_path: null,
      updated_at: "2026-07-10T00:00:00Z",
    };
    const approved = {
      ...compilation,
      segments: {
        voice_segment_1: { ...compilation.segments.voice_segment_1, status: "approved" as const },
      },
    };
    const engine = engineStub({
      listVaultMedia: vi.fn().mockResolvedValue([audioItem]),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [{
          media_item_id: audioItem.id,
          lane: "audio",
          review_status: "accepted",
          updated_at: "2026-07-10T00:00:00Z",
        }],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      getVoiceIdentityProfile: vi.fn().mockResolvedValue({
        project_id: project.id,
        anchor_media_item_ids: [audioItem.id],
        evidence: {},
        updated_at: "2026-07-10T00:00:00Z",
      }),
      getVoiceDataset: vi.fn().mockResolvedValue(compilation),
      updateVoiceDatasetSegment: vi.fn().mockResolvedValue(approved),
      bulkUpdateVoiceDatasetSegments: vi.fn().mockResolvedValue(approved),
      analyzeVoiceDatasetQuality: vi.fn().mockResolvedValue(compilation),
    });
    render(<TrainTab engine={engine} />);

    await user.click(screen.getByRole("tab", { name: "Voice Dataset" }));

    expect(await screen.findByRole("heading", { name: "Voice Sample Compiler" })).toBeInTheDocument();
    expect(screen.getByLabelText("Voice segment transcript")).toHaveValue(
      "This is a reviewed voice line.",
    );
    expect(screen.getByText((_content, element) => element?.tagName === "SMALL" && element.textContent?.includes("91% voice") === true)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Quality Gate" }));
    expect(engine.analyzeVoiceDatasetQuality).toHaveBeenCalledWith(project.id);
    expect(await screen.findByText("Quality gate complete; 1 segment passes both identity and signal checks.")).toBeInTheDocument();
    await user.click(screen.getByTitle("Stage AI recommendations"));
    expect(engine.bulkUpdateVoiceDatasetSegments).not.toHaveBeenCalled();
    await user.click(screen.getByTitle("Stage rejection"));
    await user.click(screen.getByRole("button", { name: "Apply 1" }));

    expect(engine.bulkUpdateVoiceDatasetSegments).toHaveBeenCalledWith(
      project.id,
      { voice_segment_1: "rejected" },
    );
    expect(await screen.findByText("Applied 1 reviewed voice decisions.")).toBeInTheDocument();
  });

  it("edits and approves an individual caption record", async () => {
    const user = userEvent.setup();
    const updated = snapshot({
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          caption: "example_person, smiling person, close-up portrait",
          caption_source: "user",
          status: "approved",
        },
      },
      balance: {
        ...snapshot().balance,
        approved_count: 1,
        review_count: 0,
        warnings: ["Fewer than 20 items are approved for training."],
      },
    });
    const engine = engineStub({ updateDatasetItem: vi.fn().mockResolvedValue(updated) });
    render(<TrainTab engine={engine} />);

    const caption = await screen.findByLabelText("Training caption");
    await waitFor(() =>
      expect(caption).toHaveValue("example_person, person, close-up portrait"),
    );
    await user.clear(caption);
    await user.type(caption, "example_person, smiling person, close-up portrait");
    await user.click(screen.getByRole("button", { name: "Save Caption" }));

    expect(engine.updateDatasetItem).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      "dataset_item_1",
      { caption: "example_person, smiling person, close-up portrait" },
    );
    expect(screen.getByText("Caption record saved.")).toBeInTheDocument();
  });

  it("approves the review queue, freezes it, and exports the frozen version", async () => {
    const user = userEvent.setup();
    const approved = snapshot({
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          status: "approved",
        },
      },
      balance: {
        ...snapshot().balance,
        approved_count: 1,
        review_count: 0,
        warnings: ["Fewer than 20 items are approved for training."],
      },
    });
    const frozen = snapshot({ ...approved, status: "frozen", fingerprint: "a".repeat(64) });
    const exported = snapshot({
      ...frozen,
      status: "exported",
      export_path: "/tmp/runcomfy",
    });
    const engine = engineStub({
      bulkUpdateDatasetItems: vi.fn().mockResolvedValue(approved),
      freezeDatasetSnapshot: vi.fn().mockResolvedValue(frozen),
      exportDatasetSnapshotRunComfy: vi.fn().mockResolvedValue({
        snapshot: exported,
        package: {
          id: "export_1",
          export_type: "runcomfy_image",
          output_path: "/tmp/runcomfy",
          status: "complete",
          source_segment_ids: [],
        },
      }),
    });
    render(<TrainTab engine={engine} />);

    await user.click(await screen.findByRole("button", { name: "Approve Review" }));
    await waitFor(() =>
      expect(engine.bulkUpdateDatasetItems).toHaveBeenCalledWith(
        "dataset_snapshot_1",
        "approved",
        ["dataset_item_1"],
      ),
    );
    expect(await screen.findByText("1 caption records approved.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Freeze" }));
    await waitFor(() =>
      expect(engine.freezeDatasetSnapshot).toHaveBeenCalledWith("dataset_snapshot_1"),
    );

    await user.type(screen.getByLabelText("Output folder"), "/tmp/runcomfy");
    await user.click(screen.getByRole("button", { name: "Export Dataset" }));
    await waitFor(() =>
      expect(engine.exportDatasetSnapshotRunComfy).toHaveBeenCalledWith(
        "dataset_snapshot_1",
        "/tmp/runcomfy",
      ),
    );
    expect(screen.getByText("Export complete: /tmp/runcomfy")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Dataset export complete" })).toHaveTextContent("/tmp/runcomfy");
  });

  it("strips shell quotes from an export folder before sending it to the engine", async () => {
    const user = userEvent.setup();
    const frozen = snapshot({ status: "frozen", fingerprint: "a".repeat(64) });
    const exported = snapshot({
      ...frozen,
      status: "exported",
      export_path: "/tmp/runcomfy quoted",
    });
    const exportDatasetSnapshotRunComfy = vi.fn().mockResolvedValue({
      snapshot: exported,
      package: {
        id: "export_quoted",
        export_type: "runcomfy_image",
        output_path: "/tmp/runcomfy quoted",
        status: "complete",
        source_segment_ids: [],
      },
    });
    const engine = engineStub({
      listDatasetSnapshots: vi.fn().mockResolvedValue([frozen]),
      exportDatasetSnapshotRunComfy,
    });
    render(<TrainTab engine={engine} />);

    await user.type(await screen.findByLabelText("Output folder"), "'/tmp/runcomfy quoted'");
    await user.click(screen.getByRole("button", { name: "Export Dataset" }));

    expect(exportDatasetSnapshotRunComfy).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      "/tmp/runcomfy quoted",
    );
    expect(screen.getByRole("region", { name: "Dataset export complete" })).toBeInTheDocument();
  });

  it("uses the engine-backed folder selector in guided web mode", async () => {
    const user = userEvent.setup();
    const frozen = snapshot({
      status: "frozen",
      fingerprint: "a".repeat(64),
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          status: "approved",
        },
      },
      balance: {
        ...snapshot().balance,
        approved_count: 1,
        review_count: 0,
        warnings: [],
      },
    });
    const pickDirectory = vi.fn().mockResolvedValue({ path: "/tmp/guided-package" });
    const engine = engineStub({
      listDatasetSnapshots: vi.fn().mockResolvedValue([frozen]),
      getDatasetSnapshot: vi.fn().mockResolvedValue(frozen),
      pickDirectory,
    });
    render(<TrainTab engine={engine} guided />);

    const packageFolder = await screen.findByLabelText("Package folder");
    expect(packageFolder).toHaveAttribute("readonly");
    await user.click(screen.getByRole("button", { name: "Choose package folder" }));

    expect(pickDirectory).toHaveBeenCalledOnce();
    expect(packageFolder).toHaveValue("/tmp/guided-package");
  });

  it("generates a selected vision caption, clears the key, and restores review", async () => {
    const user = userEvent.setup();
    const generated = snapshot({
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          caption: "example_person, smiling, standing, red dress, close-up portrait",
          tags: ["smiling", "standing", "red dress", "close-up portrait"],
          unresolved_attributes: [],
          status: "needs_review",
          caption_source: "vision",
          caption_provider: "OpenAI",
          caption_model: "gpt-5",
          caption_confidence: 0.91,
        },
      },
    });
    const queuedJob = {
      id: "caption_job_1",
      snapshot_id: "dataset_snapshot_1",
      item_ids: ["dataset_item_1"],
      provider_id: "openai",
      provider_label: "OpenAI",
      model: "gpt-5",
      status: "queued" as const,
      total_count: 1,
      completed_count: 0,
      failed_count: 0,
      progress_message: "Queued",
      errors: [],
      created_at: "2026-07-09T00:00:00Z",
      started_at: null,
      completed_at: null,
    };
    const engine = engineStub({
      createCaptionJob: vi.fn().mockResolvedValue(queuedJob),
      getCaptionJob: vi.fn().mockResolvedValue({
        ...queuedJob,
        status: "complete",
        completed_count: 1,
        progress_message: "Generated 1 of 1 captions",
      }),
      getDatasetSnapshot: vi.fn().mockResolvedValue(generated),
    });
    render(<TrainTab engine={engine} />);

    const apiKey = await screen.findByLabelText("Vision API key");
    await user.type(apiKey, "job-secret");
    await user.click(screen.getByRole("button", { name: "Selected" }));

    expect(engine.createCaptionJob).toHaveBeenCalledWith("dataset_snapshot_1", {
      item_ids: ["dataset_item_1"],
      provider_id: "openai",
      provider_label: "OpenAI",
      dialect: "responses",
      base_url: "https://api.openai.com/v1",
      model: "gpt-5",
      api_key: "job-secret",
    });
    expect(apiKey).toHaveValue("");
    await waitFor(() => expect(engine.getCaptionJob).toHaveBeenCalledWith("caption_job_1"));
    await waitFor(() =>
      expect(screen.getByLabelText("Training caption")).toHaveValue(
        "example_person, smiling, standing, red dress, close-up portrait",
      ),
    );
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("Vision captions ready: 1 generated. Review before approval.")).toBeInTheDocument();
  });

  it("finishes a batch AI run before presenting fast guided decisions", async () => {
    const user = userEvent.setup();
    const secondRecord = {
      ...snapshot().items.dataset_item_1,
      id: "dataset_item_2",
      source_media_item_id: "media_source_2",
    };
    const initial = snapshot({
      items: {
        dataset_item_1: snapshot().items.dataset_item_1,
        dataset_item_2: secondRecord,
      },
      balance: { ...snapshot().balance, total_count: 2, review_count: 2 },
    });
    const generated = snapshot({
      ...initial,
      items: {
        dataset_item_1: {
          ...initial.items.dataset_item_1,
          caption_source: "vision",
          unresolved_attributes: [],
        },
        dataset_item_2: {
          ...initial.items.dataset_item_2,
          caption_source: "vision",
          unresolved_attributes: [],
        },
      },
    });
    const queuedJob = {
      id: "caption_job_batch",
      snapshot_id: "dataset_snapshot_1",
      item_ids: ["dataset_item_1", "dataset_item_2"],
      provider_id: "openai",
      provider_label: "OpenAI",
      model: "gpt-5",
      status: "queued" as const,
      total_count: 2,
      completed_count: 0,
      failed_count: 0,
      progress_message: "Queued",
      errors: [],
      created_at: "2026-07-09T00:00:00Z",
      started_at: null,
      completed_at: null,
    };
    const updateDatasetItem = vi.fn().mockResolvedValue(generated);
    const engine = engineStub({
      listDatasetSnapshots: vi.fn().mockResolvedValue([initial]),
      createCaptionJob: vi.fn().mockResolvedValue(queuedJob),
      getCaptionJob: vi.fn().mockResolvedValue({
        ...queuedJob,
        status: "complete",
        completed_count: 2,
        progress_message: "Generated 2 of 2 captions",
      }),
      getDatasetSnapshot: vi.fn().mockResolvedValue(generated),
      updateDatasetItem,
    });
    render(<TrainTab engine={engine} />);

    await user.type(await screen.findByLabelText("Vision API key"), "job-secret");
    expect(screen.getByText("2 of 2 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("0 of 2 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI Review (0)" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Select All" }));
    await user.click(screen.getByRole("button", { name: "AI Review (2)" }));

    expect(engine.createCaptionJob).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      expect.objectContaining({ item_ids: ["dataset_item_1", "dataset_item_2"] }),
    );
    expect(screen.queryByLabelText("Guided AI review")).not.toBeInTheDocument();
    expect(await screen.findByText("AI decision 1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Not Yet/ }));
    expect(updateDatasetItem).not.toHaveBeenCalled();
    expect(screen.getByText("AI decision 2 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Yes, Approve/ }));
    expect(updateDatasetItem).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      "dataset_item_2",
      { status: "approved" },
    );
  });

  it("navigates backward and YOLO approves remaining guided decisions", async () => {
    const user = userEvent.setup();
    const secondRecord = {
      ...snapshot().items.dataset_item_1,
      id: "dataset_item_2",
      source_media_item_id: "media_source_2",
      caption: "example_person, person, full-body portrait",
    };
    const generated = snapshot({
      items: {
        dataset_item_1: {
          ...snapshot().items.dataset_item_1,
          caption_source: "vision",
          unresolved_attributes: [],
        },
        dataset_item_2: {
          ...secondRecord,
          caption_source: "vision",
          unresolved_attributes: [],
        },
      },
      balance: { ...snapshot().balance, total_count: 2, review_count: 2 },
    });
    const bulkUpdateDatasetItems = vi.fn().mockResolvedValue(generated);
    const engine = engineStub({
      listDatasetSnapshots: vi.fn().mockResolvedValue([generated]),
      getDatasetSnapshot: vi.fn().mockResolvedValue(generated),
      bulkUpdateDatasetItems,
    });
    render(<TrainTab engine={engine} guided />);

    await user.click(await screen.findByRole("button", { name: /Review 2 AI decisions/ }));
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Not this one" }));
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Not this one" }));
    await user.click(screen.getByRole("button", { name: "YOLO: Approve All" }));

    expect(bulkUpdateDatasetItems).toHaveBeenCalledWith(
      "dataset_snapshot_1",
      "approved",
      ["dataset_item_2"],
    );
    expect(await screen.findByText("1 AI decision approved. 1 deferred item remains for review.")).toBeInTheDocument();
  });

  it("uses the local Grok OAuth session without exposing an API-key field", async () => {
    const user = userEvent.setup();
    const grokOAuthProvider = {
      id: "grok_oauth",
      label: "Grok OAuth",
      dialect: "grok_cli" as const,
      auth_mode: "grok_oauth" as const,
      base_url: "grok://local-oauth",
      model: "grok-4.5",
      configured: true,
    };
    const engine = engineStub({
      listCaptionProviders: vi.fn().mockResolvedValue([grokOAuthProvider]),
      createCaptionJob: vi.fn().mockResolvedValue({
        id: "caption_job_oauth",
        snapshot_id: "dataset_snapshot_1",
        item_ids: ["dataset_item_1"],
        provider_id: "grok_oauth",
        provider_label: "Grok OAuth",
        model: "grok-4.5",
        status: "queued",
        total_count: 1,
        completed_count: 0,
        failed_count: 0,
        progress_message: "Queued",
        errors: [],
        created_at: "2026-07-10T00:00:00Z",
      }),
    });
    render(<TrainTab engine={engine} />);

    await screen.findByLabelText("Vision provider");
    expect(screen.getByText("OAuth session ready")).toBeInTheDocument();
    expect(screen.queryByLabelText("Vision API key")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Selected" }));

    expect(engine.createCaptionJob).toHaveBeenCalledWith("dataset_snapshot_1", {
      item_ids: ["dataset_item_1"],
      provider_id: "grok_oauth",
      provider_label: "Grok OAuth",
      dialect: "grok_cli",
      base_url: "grok://local-oauth",
      model: "grok-4.5",
      api_key: undefined,
    });
  });

  it("uses Apple Local by default without exposing an API-key field", async () => {
    const user = userEvent.setup();
    const appleLocalProvider = {
      id: "apple_local",
      label: "Apple Local",
      dialect: "apple_foundation" as const,
      auth_mode: "local" as const,
      base_url: "apple://foundation-model",
      model: "system",
      configured: true,
    };
    const engine = engineStub({
      listCaptionProviders: vi.fn().mockResolvedValue([appleLocalProvider]),
      createCaptionJob: vi.fn().mockResolvedValue({
        id: "caption_job_apple",
        snapshot_id: "dataset_snapshot_1",
        item_ids: ["dataset_item_1"],
        provider_id: "apple_local",
        provider_label: "Apple Local",
        model: "system",
        status: "queued",
        total_count: 1,
        completed_count: 0,
        failed_count: 0,
        progress_message: "Queued",
        errors: [],
        created_at: "2026-07-26T00:00:00Z",
      }),
    });
    render(<TrainTab engine={engine} />);

    expect(await screen.findByText("On-device model ready · no API charges")).toBeInTheDocument();
    expect(screen.queryByLabelText("Vision API key")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Vision model")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Selected" }));

    expect(engine.createCaptionJob).toHaveBeenCalledWith("dataset_snapshot_1", {
      item_ids: ["dataset_item_1"],
      provider_id: "apple_local",
      provider_label: "Apple Local",
      dialect: "apple_foundation",
      base_url: "apple://foundation-model",
      model: "system",
      api_key: undefined,
    });
  });

  it("does not silently default to a configured cloud caption provider", async () => {
    const engine = engineStub({
      listCaptionProviders: vi.fn().mockResolvedValue([
        {
          id: "apple_local",
          label: "Apple Local",
          dialect: "apple_foundation",
          auth_mode: "local",
          base_url: "apple://foundation-model",
          model: "system",
          configured: false,
        },
        {
          id: "grok_oauth",
          label: "Grok OAuth",
          dialect: "grok_cli",
          auth_mode: "grok_oauth",
          base_url: "grok://local-oauth",
          model: "grok-4.5",
          configured: true,
        },
      ]),
    });
    render(<TrainTab engine={engine} />);

    expect(await screen.findByLabelText("Vision provider")).toHaveValue("apple_local");
    expect(screen.getByText("Apple Intelligence unavailable")).toBeInTheDocument();
    expect(screen.queryByText("OAuth session ready")).not.toBeInTheDocument();
  });

  it("opens the image compiler on the shared active character project", async () => {
    const secondProject: CharacterProject = { ...project, id: "character_project_2", name: "Second Character" };
    const secondSnapshot = snapshot({ id: "dataset_snapshot_2", project_id: secondProject.id, project_name: secondProject.name });
    const engine = engineStub({
      listCharacterProjects: vi.fn().mockResolvedValue([project, secondProject]),
      listDatasetSnapshots: vi.fn().mockResolvedValue([snapshot(), secondSnapshot]),
      getDatasetSnapshot: vi.fn().mockResolvedValue(secondSnapshot),
    });

    render(<TrainTab engine={engine} activeProjectId={secondProject.id} />);

    await waitFor(() => expect(screen.getByLabelText("Project")).toHaveValue(secondProject.id));
    expect(screen.getByText("Second Character · v1")).toBeInTheDocument();
  });

  function engineStub(
    overrides: Partial<ComponentProps<typeof TrainTab>["engine"]> = {},
  ): ComponentProps<typeof TrainTab>["engine"] {
    return {
      assetUrl: vi.fn((path: string) => `/asset/${path}`),
      pickDirectory: vi.fn().mockResolvedValue({ path: "/tmp/selected-package" }),
      listVaultMedia: vi.fn().mockResolvedValue(mediaItems),
      listCharacterProjects: vi.fn().mockResolvedValue([project]),
      updateCharacterProject: vi.fn().mockResolvedValue(project),
      getCurationHandoff: vi.fn().mockResolvedValue({
        items: [],
        updated_at: "2026-07-10T00:00:00Z",
      }),
      getVoiceIdentityProfile: vi.fn().mockResolvedValue({
        project_id: "character_project_1",
        anchor_media_item_ids: [],
        evidence: {},
        updated_at: "2026-07-10T00:00:00Z",
      }),
      setVoiceIdentityAnchors: vi.fn(),
      getVoiceDataset: vi.fn().mockResolvedValue({
        project_id: "character_project_1",
        source_media_item_ids: [],
        segments: {},
        export_path: null,
        updated_at: "2026-07-10T00:00:00Z",
      }),
      compileVoiceDataset: vi.fn(),
      updateVoiceDatasetSegment: vi.fn(),
      bulkUpdateVoiceDatasetSegments: vi.fn(),
      rescoreVoiceDataset: vi.fn(),
      analyzeVoiceDatasetQuality: vi.fn(),
      exportVoiceDataset: vi.fn(),
      listDatasetSnapshots: vi.fn().mockResolvedValue([snapshot()]),
      listTrainingTargets: vi.fn().mockResolvedValue([
        {
          profile_id: "runcomfy_flux1_dev_character",
          label: "FLUX.1 Dev Character",
          provider: "runcomfy",
          trainer: "ai_toolkit",
          modality: "image",
          model_family: "flux1",
          base_model: "black-forest-labs/FLUX.1-dev",
          compiler_version: "image-pairs-v1",
          resolution_buckets: [512, 768, 1024],
          caption_format: "paired_txt",
          output_format: "safetensors_lora",
          recipe_id: "flux1_dev_character",
          recipe_version: 1,
          description: "Character target",
          ready: true,
          config_template: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
          warnings: [],
          recipe: fluxRecipe(),
        },
        {
          profile_id: "runcomfy_krea2_raw_character",
          label: "KREA 2 Character",
          provider: "runcomfy",
          trainer: "ai_toolkit",
          modality: "image",
          model_family: "krea2",
          base_model: "krea/Krea-2-Raw",
          compiler_version: "image-pairs-v1",
          resolution_buckets: [512, 768, 1024],
          caption_format: "paired_txt",
          output_format: "safetensors_lora",
          recipe_id: "krea2_raw_character",
          recipe_version: 1,
          description: "KREA 2 RAW character target",
          ready: true,
          config_template: "model:\n  arch: krea2\n  name_or_path: krea/Krea-2-Raw\nfolder_path: /app/ai-toolkit/datasets/{dataset_name}",
          warnings: ["Complete the first paid cloud run before treating its quality baseline as production-verified."],
          recipe: kreaRecipe(),
        },
      ]),
      getDatasetSnapshot: vi.fn().mockResolvedValue(snapshot()),
      compileCharacterDataset: vi.fn().mockResolvedValue(snapshot()),
      updateDatasetItem: vi.fn().mockResolvedValue(snapshot()),
      updateDatasetModelCard: vi.fn().mockResolvedValue(snapshot()),
      bulkUpdateDatasetItems: vi.fn().mockResolvedValue(snapshot()),
      proposeDatasetStrongestSet: vi.fn(),
      proposeDatasetDuplicates: vi.fn(),
      applyDatasetStrongestSet: vi.fn(),
      restoreDatasetStrongestSet: vi.fn(),
      freezeDatasetSnapshot: vi.fn().mockResolvedValue(snapshot()),
      exportDatasetSnapshotRunComfy: vi.fn(),
      listVideoDatasetCandidates: vi.fn().mockResolvedValue([]),
      listVideoDatasetSnapshots: vi.fn().mockResolvedValue([]),
      getVideoDatasetSnapshot: vi.fn(),
      compileVideoDataset: vi.fn(),
      updateVideoDatasetItem: vi.fn(),
      bulkUpdateVideoDataset: vi.fn(),
      freezeVideoDataset: vi.fn(),
      exportVideoDataset: vi.fn(),
      listIdLoraManifests: vi.fn().mockResolvedValue([]),
      getIdLoraManifest: vi.fn(),
      compileIdLoraManifest: vi.fn(),
      exportIdLoraManifest: vi.fn(),
      createRunPodBundle: vi.fn(),
      listRunPodInfrastructureProfiles: vi.fn().mockResolvedValue([]),
      provisionRunPodInfrastructure: vi.fn(),
      listRunPodModelBootstrapRuns: vi.fn().mockResolvedValue([]),
      getRunPodModelBootstrapRun: vi.fn(),
      createRunPodModelBootstrapRun: vi.fn(),
      refreshRunPodModelBootstrapRun: vi.fn(),
      cancelRunPodModelBootstrapRun: vi.fn(),
      listRunPodBundles: vi.fn().mockResolvedValue([]),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([]),
      getRunPodBundleUploadJob: vi.fn(),
      createRunPodBundleUploadJob: vi.fn(),
      resumeRunPodBundleUploadJob: vi.fn(),
      listRunPodPreflightReports: vi.fn().mockResolvedValue([]),
      createRunPodPreflightReport: vi.fn(),
      listRunPodTrainingRuns: vi.fn().mockResolvedValue([]),
      getRunPodTrainingRun: vi.fn(),
      createRunPodTrainingRun: vi.fn(),
      refreshRunPodTrainingRun: vi.fn(),
      cancelRunPodTrainingRun: vi.fn(),
      downloadRunPodTrainingArtifacts: vi.fn(),
      registerRunPodTrainingArtifacts: vi.fn(),
      listVoiceArtifactEvaluations: vi.fn().mockResolvedValue([]),
      getVoiceArtifactEvaluation: vi.fn(),
      getRecommendedVoiceArtifactEvaluation: vi.fn().mockResolvedValue(null),
      createVoiceArtifactEvaluation: vi.fn(),
      selectVoiceArtifactEvaluation: vi.fn(),
      listIdLoraEvaluations: vi.fn().mockResolvedValue([]),
      getIdLoraEvaluation: vi.fn(),
      createIdLoraEvaluation: vi.fn(),
      getBenchmarkSuite: vi.fn().mockResolvedValue([]),
      prepareBenchmarkWorkspace: vi.fn(),
      listBenchmarkGenerationRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkGenerationRun: vi.fn(),
      retryBenchmarkGenerationRun: vi.fn(),
      createBenchmarkGenerationRun: vi.fn(),
      createRunPodBenchmarkGenerationRun: vi.fn(),
      getImageBenchmarkSuite: vi.fn().mockResolvedValue([]),
      prepareImageBenchmarkWorkspace: vi.fn(),
      createImageBenchmarkGenerationRun: vi.fn(),
      createRunPodImageBenchmarkGenerationRun: vi.fn(),
      listImageBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getImageBenchmarkRun: vi.fn(),
      createImageBenchmarkRun: vi.fn(),
      listBenchmarkRuns: vi.fn().mockResolvedValue([]),
      getBenchmarkRun: vi.fn(),
      createBenchmarkRun: vi.fn(),
      reviewBenchmarkCase: vi.fn(),
      getIdentityStatus: vi.fn().mockResolvedValue({ ready: false }),
      getVoiceIdentityStatus: vi.fn().mockResolvedValue({ ready: false }),
      getSyncNetCapability: vi.fn().mockResolvedValue({ configured: false, ready: false, mode: "unconfigured", problems: [], setup: [] }),
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      getTrainingRun: vi.fn(),
      createTrainingRun: vi.fn(),
      refreshTrainingRun: vi.fn(),
      resumeTrainingRun: vi.fn(),
      cancelTrainingRun: vi.fn(),
      listModelArtifacts: vi.fn().mockResolvedValue([]),
      listModelReleaseCandidates: vi.fn().mockResolvedValue([]),
      selectModelRelease: vi.fn(),
      registerTrainingArtifacts: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
      installModelArtifact: vi.fn(),
      listCaptionProviders: vi.fn().mockResolvedValue([
        {
          id: "openai",
          label: "OpenAI",
          dialect: "responses",
          auth_mode: "api_key",
          base_url: "https://api.openai.com/v1",
          model: "gpt-5",
          configured: false,
        },
      ]),
      listCaptionJobs: vi.fn().mockResolvedValue([]),
      startGrokOAuthLogin: vi.fn().mockResolvedValue({
        started: true,
        message: "Grok OAuth sign-in opened in your browser. Finish it, then refresh providers.",
      }),
      getCaptionJob: vi.fn(),
      cancelCaptionJob: vi.fn(),
      createCaptionJob: vi.fn(),
      ...overrides,
    };
  }

  const mediaItems: MediaItem[] = [
    {
      id: "media_crop",
      source_id: "source_1",
      raw_path: "/tmp/vault/crop.png",
      media_type: "image",
      width: 512,
      height: 512,
    },
  ];

  const project: CharacterProject = {
    id: "character_project_1",
    name: "Mary Character",
    intent: {
      target_type: "character",
      subject_name: "Mary",
      trigger_token: "example_person",
      description: "",
      learned_attributes: ["identity"],
      controllable_attributes: ["expression"],
      excluded_attributes: ["background"],
    },
    candidate_media_item_ids: [],
    observations: {},
    crop_recipes: {},
    health: {
      candidate_count: 0,
      accepted_count: 0,
      review_count: 0,
      rejected_count: 0,
      anchor_count: 0,
      effective_observation_count: 0,
      source_count: 0,
      largest_source_share: 0,
      average_quality: 0,
      average_diversity: 0,
      view_counts: {},
      analyzer: "test",
      warnings: [],
    },
    created_at: "2026-07-09T00:00:00Z",
    updated_at: "2026-07-09T00:00:00Z",
  };

  function snapshot(overrides: Partial<DatasetSnapshot> = {}): DatasetSnapshot {
    return {
      id: "dataset_snapshot_1",
      project_id: "character_project_1",
      project_name: "Mary Character",
      version: 1,
      status: "draft",
      intent: project.intent,
      items: {
        dataset_item_1: {
          id: "dataset_item_1",
          source_media_item_id: "media_source",
          training_media_item_id: "media_crop",
          crop_recipe_id: "crop_1",
          caption: "example_person, person, close-up portrait",
          tags: ["close-up portrait"],
          attributes: { framing: "close-up portrait", asset: "face" },
          unresolved_attributes: ["expression"],
          status: "needs_review",
          caption_source: "local_policy",
          view: "face",
          quality_score: 0.9,
          diversity_score: 0.7,
          identity_score: 0.8,
          is_anchor: true,
          source_id: "source_1",
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      },
      balance: {
        total_count: 1,
        approved_count: 0,
        review_count: 1,
        excluded_count: 0,
        source_count: 1,
        cropped_count: 1,
        average_quality: 0.9,
        average_diversity: 0.7,
        view_counts: { face: 1 },
        crop_counts: { face: 1 },
        warnings: ["Caption review is incomplete."],
      },
      fingerprint: null,
      export_package_id: null,
      export_path: null,
      created_at: "2026-07-09T00:00:00Z",
      updated_at: "2026-07-09T00:00:00Z",
      frozen_at: null,
      ...overrides,
    };
  }
});

function modelCard(overrides: Partial<LoraModelCard> = {}): LoraModelCard {
  return {
    schema_version: "lorasuite.model-card.v1",
    name: "mary-flux1-character",
    display_name: "Mary - FLUX.1 Dev Character",
    description: "Character LoRA for Mary.",
    license: "unspecified",
    tags: ["lorasuite", "character"],
    modality: "image",
    target_type: "character",
    subject_name: "Mary",
    trigger_token: "example_person",
    base_model: "black-forest-labs/FLUX.1-dev",
    model_family: "flux1",
    recipe_id: "flux1_dev_character",
    recipe_version: 1,
    recipe_status: "baseline",
    training_target_profile_id: "runcomfy_flux1_dev_character",
    dataset: { fingerprint: "dataset-fingerprint" },
    captions: {},
    training: {},
    evaluation: {},
    usage: {
      sample_prompts: ["portrait of example_person"],
      intended_use: ["Portrait generation"],
      limitations: ["Dataset coverage determines capability"],
      recommended_strength: null,
    },
    artifact: null,
    provenance: {},
    warnings: ["Output license is unspecified."],
    validation: {
      status: "review",
      blocker_count: 0,
      warning_count: 2,
      checks: [
        {
          check_id: "license",
          label: "License",
          passed: false,
          severity: "warning",
          message: "Output license is unspecified.",
        },
        {
          check_id: "recommended_strength",
          label: "Recommended strength",
          passed: false,
          severity: "warning",
          message: "Recommended LoRA strength has not been verified.",
        },
      ],
    },
    ...overrides,
  };
}

function fluxRecipe(): ModelIntentRecipe {
  return {
    recipe_id: "flux1_dev_character",
    version: 1,
    label: "FLUX.1 Dev Character",
    status: "baseline",
    modality: "image",
    model_family: "flux1",
    base_model: "black-forest-labs/FLUX.1-dev",
    intent: "character",
    dataset: {
      minimum_approved_items: 20,
      recommended_approved_items: 35,
      maximum_approved_items: 80,
      minimum_sources: 2,
      maximum_source_share: 0.65,
      minimum_face_views: 4,
      minimum_upper_body_views: 4,
      minimum_full_body_views: 4,
      minimum_materialized_crops: 3,
      minimum_average_quality: 0.6,
      minimum_average_diversity: 0.35,
      allowed_image_extensions: [".jpg", ".jpeg", ".png"],
      guidance: [],
    },
    captions: {
      trigger_token_required: true,
      caption_format: "paired_txt",
      required_evidence: ["framing"],
      controllable_attributes: ["expression", "pose", "clothing", "environment", "camera"],
      excluded_identity_attributes: ["background", "other people", "watermark"],
      guidance: [],
    },
    training: {
      network_rank: 16,
      network_alpha: 16,
      steps: 2000,
      minimum_steps: 500,
      maximum_steps: 4000,
      learning_rate: 0.0001,
      optimizer: "adamw8bit",
      precision: "bf16",
      batch_size: 1,
      save_every: 250,
      sample_every: 250,
      caption_dropout_rate: 0.05,
      train_text_encoder: false,
      gradient_checkpointing: true,
      cache_text_embeddings: false,
      sample_steps: 20,
      sample_guidance_scale: 4,
    },
    evaluation: {
      required_gates: ["identity_similarity", "prompt_adherence", "attribute_control", "artifact_rate"],
      minimum_identity_score: 0.72,
      minimum_prompt_adherence: 0.65,
      maximum_artifact_rate: 0.15,
      benchmark_prompt_count: 12,
      guidance: [],
    },
    metadata: {
      schema_version: "lorasuite.model-card.v1",
      required_fields: ["name", "description"],
    },
    rationale: [],
    evidence_urls: [],
  };
}

function kreaRecipe(): ModelIntentRecipe {
  return {
    ...fluxRecipe(),
    recipe_id: "krea2_raw_character",
    label: "KREA 2 Character",
    model_family: "krea2",
    base_model: "krea/Krea-2-Raw",
    rationale: [
      "Train against KREA 2 RAW, then use the resulting adapter with KREA 2 Turbo.",
    ],
  };
}
