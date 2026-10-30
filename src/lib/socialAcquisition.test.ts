import { describe, expect, it, vi } from "vitest";

import { acquireSocialMedia } from "./socialAcquisition";
import type { EngineClient } from "./api";
import type { SocialAcquisitionJob } from "./types";


function job(update: Partial<SocialAcquisitionJob> = {}): SocialAcquisitionJob {
  return {
    id: "social_1",
    request: { provider: "instagram", url: "https://www.instagram.com/subject", browser: "chrome" },
    request_fingerprint: "fingerprint",
    status: "queued",
    attempt: 0,
    max_attempts: 3,
    progress_message: "Queued",
    cancel_requested: false,
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
    ...update,
  };
}

describe("acquireSocialMedia", () => {
  it("reports persisted progress and returns the completed result", async () => {
    vi.useFakeTimers();
    const complete = job({
      status: "complete",
      attempt: 2,
      progress_message: "Retrieved 1 candidate records",
      result: {
        id: "scan_1",
        candidates: [],
        errors: [],
        metadata_json: { next_cursor: "cursor_2" },
      },
    });
    const engine = {
      createSocialAcquisitionJob: vi.fn().mockResolvedValue(job()),
      getSocialAcquisitionJob: vi.fn()
        .mockResolvedValueOnce(job({ status: "cooldown", retry_after_seconds: 1, progress_message: "Retrying in 1s" }))
        .mockResolvedValueOnce(complete),
    } as unknown as EngineClient;
    const progress = vi.fn();

    const pending = acquireSocialMedia(
      engine,
      { provider: "instagram", url: "https://www.instagram.com/subject" },
      progress,
    );
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toEqual(complete.result);
    expect(progress).toHaveBeenLastCalledWith(complete);
    vi.useRealTimers();
  });

  it("turns authentication failures into an actionable browser-session message", async () => {
    const engine = {
      createSocialAcquisitionJob: vi.fn().mockResolvedValue(job({
        status: "failed",
        error: { category: "authentication", message: "HTTP 401" },
        progress_message: "Browser session expired",
      })),
      getSocialAcquisitionJob: vi.fn(),
    } as unknown as EngineClient;

    await expect(acquireSocialMedia(engine, {
      provider: "instagram",
      url: "https://www.instagram.com/subject",
      browser: "chrome",
    })).rejects.toThrow("Log in again in Chrome and retry");
  });
});
