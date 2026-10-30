import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useSharedWorkspace } from "./useSharedWorkspace";
import type { WorkspacePreference, WorkspaceSession } from "./workspace";
const shared: WorkspaceSession = { active_project_id: "project-a", target: "video", stage: "prepare", experience: "guided" };
beforeEach(() => localStorage.clear());
it("restores the shared project and stage without overwriting it with a client cache", async () => {
  localStorage.setItem("lorasuite:active-project:v1", "old-project");
  const engine = { getWorkspacePreference: vi.fn(async () => ({ workspace: shared, updated_at: 2 })), setWorkspacePreference: vi.fn() };
  const { result } = renderHook(() => useSharedWorkspace(engine));
  await waitFor(() => expect(result.current.workspace).toEqual(shared));
  expect(engine.setWorkspacePreference).not.toHaveBeenCalled();
});
it("ignores late reads and writes only fields explicitly changed", async () => {
  let finish!: (value: WorkspacePreference) => void;
  const engine = { getWorkspacePreference: vi.fn(() => new Promise<WorkspacePreference>(resolve => { finish = resolve; })), setWorkspacePreference: vi.fn(async (patch: Partial<WorkspaceSession>) => ({ workspace: { ...shared, ...patch }, updated_at: 3 })) };
  const { result } = renderHook(() => useSharedWorkspace(engine));
  await act(async () => { result.current.updateWorkspace({ stage: "verify" }); });
  await act(async () => finish({ workspace: shared, updated_at: 1 }));
  expect(result.current.workspace.stage).toBe("verify");
  expect(engine.setWorkspacePreference).toHaveBeenCalledWith({ stage: "verify" });
});
it("imports legacy navigation only into an empty vault preference", async () => {
  localStorage.setItem("lorasuite:guided-stage:v2", "build");
  const engine = { getWorkspacePreference: vi.fn(async () => ({ workspace: null, updated_at: 0 })), setWorkspacePreference: vi.fn(async (patch: Partial<WorkspaceSession>) => ({ workspace: { ...shared, ...patch }, updated_at: 1 })) };
  renderHook(() => useSharedWorkspace(engine));
  await waitFor(() => expect(engine.setWorkspacePreference).toHaveBeenCalledWith(expect.objectContaining({ stage: "build" }), true));
});
it("keeps navigation usable and reports unsynced state when disconnected", async () => {
  const engine = { getWorkspacePreference: vi.fn().mockRejectedValue(new Error("offline")), setWorkspacePreference: vi.fn().mockRejectedValue(new Error("offline")) };
  const { result } = renderHook(() => useSharedWorkspace(engine));
  await act(async () => result.current.updateWorkspace({ stage: "sources" }));
  expect(result.current.workspace.stage).toBe("sources");
  expect(result.current.workspaceSyncError).toContain("could not sync");
});

it("loads the shared project even when the desktop window starts hidden", async () => {
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  try {
    localStorage.setItem("lorasuite:active-project:v1", "stale-desktop-project");
    const engine = { getWorkspacePreference: vi.fn(async () => ({ workspace: shared, updated_at: 2 })), setWorkspacePreference: vi.fn() };
    const { result } = renderHook(() => useSharedWorkspace(engine));
    await waitFor(() => expect(result.current.workspace).toEqual(shared));
    expect(result.current.workspaceLoaded).toBe(true);
    expect(engine.setWorkspacePreference).not.toHaveBeenCalled();
  } finally { hidden.mockRestore(); }
});
