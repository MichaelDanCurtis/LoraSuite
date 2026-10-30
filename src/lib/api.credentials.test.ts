import { describe, expect, it, vi } from "vitest";

const credentialMocks = vi.hoisted(() => ({
  resolveCredential: vi.fn(),
}));

vi.mock("./credentials", async (importOriginal) => {
  const original = await importOriginal<typeof import("./credentials")>();
  return {
    ...original,
    resolveCredential: credentialMocks.resolveCredential,
  };
});

import { createEngineClient } from "./api";

describe("engine credential resolution", () => {
  it("injects stored credentials only into the matching provider request", async () => {
    credentialMocks.resolveCredential.mockImplementation(async (id: string, explicit?: string) => (
      explicit || {
        runcomfy_api: "stored-runcomfy",
        runpod_s3_access: "stored-access",
        runpod_s3_secret: "stored-secret",
        xai_api: "stored-grok",
      }[id]
    ));
    const fetchMock = vi.fn(async (_input: string, _init: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({}),
      text: async () => "",
    }));
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.createTrainingRun({
      snapshot_id: "snapshot-1",
      config_file: "config",
      gpu_type: "ADA_80_PLUS",
    });
    await client.createRunPodBundleUploadJob({
      bundle_path: "/bundle",
      volume_id: "volume-1",
      s3_endpoint: "https://s3.example",
      datacenter: "US-CA-2",
    });
    await client.createCaptionJob("snapshot-1", {
      item_ids: ["item-1"],
      provider_id: "grok",
      provider_label: "Grok API",
      dialect: "responses",
      base_url: "https://api.x.ai/v1",
      model: "grok-4.3",
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      api_token: "stored-runcomfy",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      access_key: "stored-access",
      secret_key: "stored-secret",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toMatchObject({
      api_key: "stored-grok",
    });
  });
});
