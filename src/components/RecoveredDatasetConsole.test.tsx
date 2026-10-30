import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RecoveredDatasetExport } from "../lib/types";
import { RecoveredDatasetConsole } from "./RecoveredDatasetConsole";

const { isTauriMock, openMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
  openMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ isTauri: isTauriMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: openMock }));

describe("RecoveredDatasetConsole", () => {
  beforeEach(() => {
    isTauriMock.mockReturnValue(false);
    openMock.mockReset();
  });

  it("lists a verified package and selects it for training", async () => {
    const user = userEvent.setup();
    const onUseForTraining = vi.fn();
    const engine = {
      listRecoveredDatasetExports: vi.fn().mockResolvedValue([recoveredExport]),
      registerRecoveredDatasetExport: vi.fn(),
      verifyRecoveredDatasetExport: vi.fn().mockResolvedValue(recoveredExport),
    };
    render(
      <RecoveredDatasetConsole
        engine={engine}
        onUseForTraining={onUseForTraining}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Recovered Exports/ }));

    expect(await screen.findByText("FLUX.1 Dev Character")).toBeInTheDocument();
    expect(screen.getByText("marysue_person")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use for Training" }));

    expect(onUseForTraining).toHaveBeenCalledWith(recoveredExport);
  });

  it("registers and re-verifies an immutable export folder", async () => {
    const user = userEvent.setup();
    const registerRecoveredDatasetExport = vi.fn().mockResolvedValue(recoveredExport);
    const verifyRecoveredDatasetExport = vi.fn().mockResolvedValue(recoveredExport);
    const engine = {
      listRecoveredDatasetExports: vi.fn().mockResolvedValue([]),
      registerRecoveredDatasetExport,
      verifyRecoveredDatasetExport,
    };
    render(
      <RecoveredDatasetConsole
        engine={engine}
        onUseForTraining={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Recovered Exports/ }));
    await user.type(screen.getByLabelText("Export folder"), "/Volumes/Example Drive/test");
    await user.click(screen.getByRole("button", { name: "Recover Export" }));

    expect(registerRecoveredDatasetExport).toHaveBeenCalledWith("/Volumes/Example Drive/test");
    await user.click(await screen.findByRole("button", { name: "Verify" }));
    await waitFor(() =>
      expect(verifyRecoveredDatasetExport).toHaveBeenCalledWith(recoveredExport.id),
    );
  });
});

const recoveredExport: RecoveredDatasetExport = {
  id: "recovered_dataset_1",
  format: "lorasuite.recovered-dataset.v1",
  export_path: "/Volumes/Example Drive/test",
  manifest_path: "/Volumes/Example Drive/test/manifest.json",
  manifest_sha256: "manifest-sha",
  export_type: "runcomfy_image",
  modality: "image",
  project_id: "character_project_1",
  snapshot_id: "dataset_snapshot_1",
  dataset_version: 1,
  fingerprint: "4986688822774dbf915485b9206af804b77c9d7386fd1efb166b5d244dc3f601",
  fingerprint_source: "manifest",
  training_target: {
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
  },
  trigger_token: "marysue_person",
  trigger_token_source: "caption_consensus",
  model_card: null,
  revision_lineage: {},
  file_count: 40,
  verified_file_count: 40,
  integrity_status: "verified",
  ready: true,
  source_available: true,
  warnings: [],
  errors: [],
  imported_at: "2026-07-16T00:00:00Z",
  verified_at: "2026-07-16T00:00:00Z",
};
