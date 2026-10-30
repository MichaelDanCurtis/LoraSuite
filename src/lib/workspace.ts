export type WorkspaceStage = "create" | "sources" | "prepare" | "verify" | "build" | "evaluate";
export interface WorkspaceSession {
  active_project_id: string;
  target: "image" | "video" | "voice" | "id_lora";
  stage: WorkspaceStage;
  experience: "guided" | "studio";
}
export interface WorkspacePreference { workspace: WorkspaceSession | null; updated_at: number }
export const workspaceStorageKey = "lorasuite:workspace:v1";
export function cachedWorkspace(): WorkspaceSession {
  let saved: Partial<WorkspaceSession> = {};
  try { saved = JSON.parse(localStorage.getItem(workspaceStorageKey) || "{}"); } catch { /* Recover from a corrupt client cache. */ }
  const target = saved?.target ?? localStorage.getItem("lorasuite:workflow-target:v1");
  const stage = saved?.stage ?? localStorage.getItem("lorasuite:guided-stage:v2");
  const experience = saved?.experience ?? localStorage.getItem("lorasuite:experience:v1");
  return {
    active_project_id: typeof saved?.active_project_id === "string" ? saved.active_project_id : localStorage.getItem("lorasuite:active-project:v1") || "",
    target: target === "video" || target === "voice" || target === "id_lora" ? target : "image",
    stage: ["sources", "prepare", "verify", "build", "evaluate"].includes(stage || "") ? stage as WorkspaceStage : "create",
    experience: experience === "studio" ? "studio" : "guided",
  };
}
