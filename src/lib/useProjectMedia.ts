import { useEffect, useMemo, useState } from "react";
import type { EngineClient } from "./api";
import type { MediaItem } from "./types";

// Both modes resolve saved media from project records and durable import jobs.
// A client-side intake queue is never the source of truth for project contents.
export function useProjectMedia(engine: EngineClient, mediaItems: MediaItem[], projectId: string) {
  const [scope, setScope] = useState<{ projectId: string; ids: string[] }>({ projectId: "", ids: [] });
  const [error, setError] = useState("");
  useEffect(() => {
    if (!projectId) return;
    let ignore = false;
    setError("");
    void Promise.allSettled([
      engine.getCharacterProject?.(projectId),
      engine.getCurationHandoff?.(projectId),
      engine.listIngressJobs?.(),
    ]).then(([projectResult, handoffResult, jobsResult]) => {
      if (ignore) return;
      const project = projectResult.status === "fulfilled" ? projectResult.value : undefined;
      const handoff = handoffResult.status === "fulfilled" ? handoffResult.value : undefined;
      const jobs = jobsResult.status === "fulfilled" ? jobsResult.value : undefined;
      if ([projectResult, handoffResult, jobsResult].some((result) => result.status === "rejected")) setError("Some saved media records could not load. Check the engine connection and reopen Sources.");
      const ids = new Set([
        ...(project?.candidate_media_item_ids ?? []),
        ...(handoff?.items ?? []).map((item) => item.media_item_id),
        ...(jobs ?? []).filter((job) => job.options?.project_id === projectId)
          .flatMap((job) => job.imported_media_items.map((item) => item.id)),
      ]);
      setScope({ projectId, ids: [...ids] });
    }).catch(() => { if (!ignore) setError("Saved project media could not load. Check the engine connection and reopen Sources."); });
    return () => { ignore = true; };
  }, [engine, projectId, mediaItems]);
  const items = useMemo(() => {
    const ids = new Set(scope.projectId === projectId ? scope.ids : []);
    return mediaItems.filter((item) => ids.has(item.id) && item.status !== "ignored");
  }, [scope, projectId, mediaItems]);
  return { items, error, loading: Boolean(projectId && scope.projectId !== projectId && !error) };
}
