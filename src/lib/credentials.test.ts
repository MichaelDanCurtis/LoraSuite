import { beforeEach, describe, expect, it, vi } from "vitest";

const tauriMocks = vi.hoisted(() => ({
  isTauri: vi.fn(),
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: tauriMocks.isTauri,
  invoke: tauriMocks.invoke,
}));

import {
  deleteCredential,
  getCredential,
  getCredentialStatus,
  resolveCredential,
  setCredential,
} from "./credentials";

describe("credential storage", () => {
  beforeEach(() => {
    tauriMocks.isTauri.mockReset();
    tauriMocks.invoke.mockReset();
  });

  it("uses the native credential commands in Tauri", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke
      .mockResolvedValueOnce({ id: "runcomfy_api", stored: true })
      .mockResolvedValueOnce("stored-token")
      .mockResolvedValueOnce({ id: "runcomfy_api", stored: true })
      .mockResolvedValueOnce({ id: "runcomfy_api", stored: false });

    await expect(getCredentialStatus("runcomfy_api")).resolves.toEqual({
      id: "runcomfy_api",
      stored: true,
    });
    await expect(getCredential("runcomfy_api")).resolves.toBe("stored-token");
    await expect(setCredential("runcomfy_api", " new-token ")).resolves.toEqual({
      id: "runcomfy_api",
      stored: true,
    });
    await expect(deleteCredential("runcomfy_api")).resolves.toEqual({
      id: "runcomfy_api",
      stored: false,
    });

    expect(tauriMocks.invoke).toHaveBeenNthCalledWith(1, "credential_status", { id: "runcomfy_api" });
    expect(tauriMocks.invoke).toHaveBeenNthCalledWith(2, "credential_get", { id: "runcomfy_api" });
    expect(tauriMocks.invoke).toHaveBeenNthCalledWith(3, "credential_set", {
      id: "runcomfy_api",
      secret: "new-token",
    });
    expect(tauriMocks.invoke).toHaveBeenNthCalledWith(4, "credential_delete", { id: "runcomfy_api" });
  });

  it("keeps browser credentials in memory and prefers explicit overrides", async () => {
    tauriMocks.isTauri.mockReturnValue(false);

    await setCredential("runpod_api", "session-token");
    await expect(resolveCredential("runpod_api")).resolves.toBe("session-token");
    await expect(resolveCredential("runpod_api", "override-token")).resolves.toBe("override-token");
    await deleteCredential("runpod_api");
    await expect(resolveCredential("runpod_api")).resolves.toBeUndefined();
    expect(tauriMocks.invoke).not.toHaveBeenCalled();
  });
});
