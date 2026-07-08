import { describe, expect, it, vi } from "vitest";

import { createEngineClient } from "./api";

describe("createEngineClient", () => {
  it("posts local import paths to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        media_items: [{ id: "media_1", media_type: "image" }],
        errors: [],
      }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    const result = await client.importLocal(["/tmp/a.png"]);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/vault/import/local", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: ["/tmp/a.png"] }),
    });
    expect(result.media_items[0].id).toBe("media_1");
    expect(result.errors).toEqual([]);
  });

  it("surfaces engine detail messages for failed requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "WebP is not supported" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await expect(
      client.exportRunComfyImage({
        frames: ["/tmp/a.webp"],
        output_dir: "/tmp/export",
        caption_template: "caption",
        source_segment_ids: [],
      }),
    ).rejects.toThrow("WebP is not supported");
  });

  it("posts local scan roots to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_1", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.scanLocalIngress(["/tmp/media"], true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/local/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roots: ["/tmp/media"], recursive: true }),
    });
  });

  it("posts instagram helper payloads to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_ig", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const payload = { helper_version: "fixture", media: [] };

    await client.scanInstagramHelperPayload(payload, true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/instagram/helper-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payload,
        include_video_posters_as_image_candidates: true,
      }),
    });
  });

  it("posts instagram browser scans to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_browser", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.scanInstagramBrowserUrl(
      "https://www.instagram.com/reel/example/",
      "chrome",
      8,
      "cursor_2",
      "tagged",
    );

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/instagram/browser-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: "https://www.instagram.com/reel/example/",
        browser: "chrome",
        limit: 8,
        cursor: "cursor_2",
        scan_mode: "tagged",
      }),
    });
  });

  it("lists stored ingress candidates by source", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.listIngressCandidates("instagram");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/ingress/candidates?source_kind=instagram",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("creates an ingress job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "job_1", source_kind: "local", candidate_ids: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.createIngressJob({
      source_kind: "local",
      candidate_ids: ["candidate_1"],
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_kind: "local", candidate_ids: ["candidate_1"] }),
    });
  });

  it("builds engine asset URLs for local vault paths", () => {
    const client = createEngineClient("http://engine.test/");

    expect(client.assetUrl("/tmp/vault/previews/thumb one.jpg")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fthumb%20one.jpg",
    );
  });
});
