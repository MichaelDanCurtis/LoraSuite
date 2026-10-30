import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EngineClient } from "./api";
import type { MediaItem } from "./types";
import { useProjectMedia } from "./useProjectMedia";

const media = ["candidate", "handoff", "import", "other"].map((id) => ({ id, raw_path: `/vault/${id}.jpg`, media_type: "image", status: "new" })) as MediaItem[];
describe("saved project media scope", () => {
  it("unites durable project records, handoff and import jobs, without leaking another project", async () => {
    const engine = {
      getCharacterProject: vi.fn((id) => Promise.resolve({ candidate_media_item_ids: id === "one" ? ["candidate"] : ["other"] })),
      getCurationHandoff: vi.fn((id) => Promise.resolve({ items: id === "one" ? [{ media_item_id: "handoff" }] : [] })),
      listIngressJobs: vi.fn().mockResolvedValue([{ options: { project_id: "one" }, imported_media_items: [media[2]] }]),
    } as unknown as EngineClient;
    const { result, rerender } = renderHook(({ id }) => useProjectMedia(engine, media, id), { initialProps: { id: "one" } });
    await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(["candidate", "handoff", "import"]));
    rerender({ id: "two" });
    expect(result.current.items).toEqual([]);
    await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(["other"]));
  });
  it("preserves project candidates when an auxiliary endpoint is unavailable", async () => {
    const engine = { getCharacterProject: vi.fn().mockResolvedValue({ candidate_media_item_ids: ["candidate"] }), getCurationHandoff: vi.fn().mockRejectedValue(new Error("offline")), listIngressJobs: vi.fn().mockResolvedValue([]) } as unknown as EngineClient;
    const { result } = renderHook(() => useProjectMedia(engine, media, "one"));
    await waitFor(() => expect(result.current.items).toEqual([media[0]]));
    expect(result.current.error).toMatch(/Some saved media records/);
  });
});
