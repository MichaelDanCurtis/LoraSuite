import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppUpdateControl } from "./AppUpdateControl";

const { invokeMock, isTauriMock, relaunchMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  isTauriMock: vi.fn(),
  relaunchMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock,
  isTauri: isTauriMock,
}));

vi.mock("@tauri-apps/plugin-process", () => ({
  relaunch: relaunchMock,
}));

describe("AppUpdateControl", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    isTauriMock.mockReset();
    relaunchMock.mockReset();
  });

  it("is absent outside the desktop wrapper", () => {
    isTauriMock.mockReturnValue(false);
    render(<AppUpdateControl />);
    expect(screen.queryByRole("button", { name: "Application updates" })).not.toBeInTheDocument();
  });

  it("checks the signed stable channel when opened", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(true);
    invokeMock.mockImplementation((command: string) => {
      if (command === "desktop_update_journal") return Promise.resolve(null);
      return Promise.resolve({
        configured: true,
        channel: "stable",
        current_version: "1.0.0",
        available: true,
        version: "1.1.0",
        message: "A signed update is available.",
      });
    });

    render(<AppUpdateControl />);
    await user.click(screen.getByRole("button", { name: "Application updates" }));

    expect(await screen.findByText("Current release 1.1.0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install & Restart" })).toBeInTheDocument();
    expect(invokeMock).toHaveBeenCalledWith("check_desktop_update", { channel: "stable" });
  });

  it("installs the rechecked signed version and relaunches", async () => {
    const user = userEvent.setup();
    isTauriMock.mockReturnValue(true);
    invokeMock.mockImplementation((command: string) => {
      if (command === "desktop_update_journal") return Promise.resolve(null);
      if (command === "install_desktop_update") {
        return Promise.resolve({
          channel: "stable",
          from_version: "1.0.0",
          to_version: "1.1.0",
          state: "installed_pending_restart",
          message: "Update installed and awaiting a verified restart.",
          updated_at_unix: 42,
        });
      }
      return Promise.resolve({
        configured: true,
        channel: "stable",
        current_version: "1.0.0",
        available: true,
        version: "1.1.0",
        message: "A signed update is available.",
      });
    });
    relaunchMock.mockResolvedValue(undefined);

    render(<AppUpdateControl />);
    await user.click(screen.getByRole("button", { name: "Application updates" }));
    await user.click(await screen.findByRole("button", { name: "Install & Restart" }));

    expect(invokeMock).toHaveBeenCalledWith("install_desktop_update", {
      channel: "stable",
      version: "1.1.0",
    });
    expect(relaunchMock).toHaveBeenCalledOnce();
  });
});
