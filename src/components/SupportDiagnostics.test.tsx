import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  DiagnosticBundleRecord,
  StateMigrationReport,
} from "../lib/types";
import { SupportDiagnostics } from "./SupportDiagnostics";

describe("SupportDiagnostics", () => {
  it("shows state readiness and creates a downloadable privacy-safe bundle", async () => {
    const user = userEvent.setup();
    const createDiagnosticBundle = vi.fn().mockResolvedValue(bundle);
    const engine = {
      inspectStateMigrations: vi.fn().mockResolvedValue(stateReport),
      applyStateMigrations: vi.fn().mockResolvedValue(stateReport),
      listDiagnosticBundles: vi.fn().mockResolvedValue([]),
      createDiagnosticBundle,
      diagnosticBundleDownloadUrl: vi.fn((id: string) => `http://engine.test/diagnostic-bundles/${id}/download`),
      listComfyInstallations: vi.fn().mockResolvedValue([
        {
          root: "/tmp/ComfyUI",
          model_root: "/tmp/ComfyUI/models",
          lora_dir: "/tmp/ComfyUI/models/loras",
          checkpoints_dir: "/tmp/ComfyUI/models/checkpoints",
          unet_dir: "/tmp/ComfyUI/models/unet",
          diffusion_models_dir: "/tmp/ComfyUI/models/diffusion_models",
          custom_nodes_dir: "/tmp/ComfyUI/custom_nodes",
        },
      ]),
    };
    render(<SupportDiagnostics engine={engine} activeProjectId="project_1" />);

    await user.click(screen.getByRole("button", { name: "Support" }));

    expect(await screen.findByText("State schema current")).toBeInTheDocument();
    expect(screen.getByText(/Excludes credentials, media/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create Bundle" }));

    expect(createDiagnosticBundle).toHaveBeenCalledWith({
      comfy_root: "/tmp/ComfyUI",
      project_id: "project_1",
    });
    const download = await screen.findByRole("link", { name: "Download" });
    expect(download).toHaveAttribute(
      "href",
      "http://engine.test/diagnostic-bundles/diagnostic_bundle_1/download",
    );
  });

  it("closes from the modal backdrop", async () => {
    const user = userEvent.setup();
    const engine = {
      inspectStateMigrations: vi.fn().mockResolvedValue(stateReport),
      applyStateMigrations: vi.fn().mockResolvedValue(stateReport),
      listDiagnosticBundles: vi.fn().mockResolvedValue([]),
      createDiagnosticBundle: vi.fn().mockResolvedValue(bundle),
      diagnosticBundleDownloadUrl: vi.fn(),
      listComfyInstallations: vi.fn().mockResolvedValue([]),
    };
    render(<SupportDiagnostics engine={engine} />);

    await user.click(screen.getByRole("button", { name: "Support" }));
    await user.click(screen.getByRole("button", { name: "Close support and diagnostics" }));

    expect(screen.queryByLabelText("Support and diagnostics")).not.toBeInTheDocument();
  });
});

const stateReport: StateMigrationReport = {
  format: "lorasuite.state-schema.v1",
  vault_root: "/private/vault",
  dry_run: true,
  ready: true,
  updated_count: 0,
  pending_count: 0,
  invalid_count: 0,
  future_count: 0,
  files: [],
  ledger_path: "/private/vault/state_schema.json",
  backup_root: null,
  created_at: "2026-07-16T00:00:00Z",
};

const bundle: DiagnosticBundleRecord = {
  id: "diagnostic_bundle_1",
  format: "lorasuite.diagnostic-bundle.v1",
  archive_path: "/private/vault/diagnostics/diagnostic_bundle_1.zip",
  archive_sha256: "abcdef1234567890",
  size_bytes: 2048,
  included_files: [
    "diagnostic_report.json",
    "partner_readiness.json",
    "README.txt",
  ],
  exclusions: ["credentials", "private media"],
  state_ready: true,
  comfy_runtime_included: true,
  created_at: "2026-07-16T00:00:00Z",
};
