import { useCallback, useEffect, useRef, useState } from "react";
import type { EngineClient } from "./api";
import { cachedWorkspace, workspaceStorageKey, type WorkspaceSession } from "./workspace";

type WorkspaceEngine = Pick<EngineClient, "getWorkspacePreference" | "setWorkspacePreference">;
export function useSharedWorkspace(engine: WorkspaceEngine) {
  const [workspace, setWorkspace] = useState(cachedWorkspace);
  const [workspaceLoaded, setLoaded] = useState(false);
  const [workspaceSyncError, setError] = useState("");
  const current = useRef(workspace);
  const version = useRef(0);
  const pending = useRef(0);
  const writes = useRef(Promise.resolve());
  const apply = useCallback((value: WorkspaceSession) => {
    current.current = value;
    localStorage.setItem(workspaceStorageKey, JSON.stringify(value));
    setWorkspace(value);
  }, []);
  useEffect(() => {
    let disposed = false, reading = false, initialized = false;
    const refresh = async () => {
      if (reading || pending.current || (initialized && document.hidden)) return;
      reading = true;
      const observed = version.current;
      try {
        let result = await engine.getWorkspacePreference();
        if (disposed || pending.current || observed !== version.current) return;
        if (!result.workspace) result = await engine.setWorkspacePreference(current.current, true);
        if (!disposed && !pending.current && observed === version.current && result.workspace) {
          apply(result.workspace); setError("");
        }
      } catch {
        if (!disposed) setError("Workspace saved on this device. Reconnect to sync with the desktop.");
      } finally { initialized = true; reading = false; if (!disposed) setLoaded(true); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => { disposed = true; clearInterval(timer); window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onFocus); };
  }, [engine, apply]);
  const updateWorkspace = useCallback((patch: Partial<WorkspaceSession>) => {
    if (Object.entries(patch).every(([key, value]) => current.current[key as keyof WorkspaceSession] === value)) return;
    const selected = ++version.current;
    apply({ ...current.current, ...patch });
    pending.current++;
    writes.current = writes.current.then(async () => {
      try {
        const result = await engine.setWorkspacePreference(patch);
        if (selected === version.current && result.workspace) { apply(result.workspace); setError(""); }
      } catch {
        if (selected === version.current) setError("Workspace changed here, but could not sync. Your projects are still saved.");
      } finally { pending.current--; }
    });
  }, [engine, apply]);
  return { workspace, updateWorkspace, workspaceSyncError, workspaceLoaded };
}
