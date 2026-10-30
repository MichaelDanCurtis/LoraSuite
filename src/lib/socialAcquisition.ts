import type { EngineClient } from "./api";
import type {
  IngressScanResult,
  SocialAcquisitionJob,
  SocialAcquisitionRequest,
} from "./types";


const terminalStatuses = new Set(["complete", "failed", "canceled"]);

export async function acquireSocialMedia(
  engine: EngineClient,
  request: SocialAcquisitionRequest,
  onProgress?: (job: SocialAcquisitionJob) => void,
): Promise<IngressScanResult> {
  if (
    !engine.createSocialAcquisitionJob
    || !engine.getSocialAcquisitionJob
  ) {
    return legacyScan(engine, request);
  }

  let job = await engine.createSocialAcquisitionJob(request);
  onProgress?.(job);
  for (let poll = 0; poll < 1_800 && !terminalStatuses.has(job.status); poll += 1) {
    await delay(500);
    job = await engine.getSocialAcquisitionJob(job.id);
    onProgress?.(job);
  }

  if (job.status === "complete" && job.result) {
    return job.result;
  }
  if (job.status === "canceled") {
    throw new Error("Social media retrieval was canceled.");
  }
  if (job.status === "failed") {
    throw new Error(socialAcquisitionError(job));
  }
  throw new Error("Social media retrieval did not finish within 15 minutes.");
}

export function socialAcquisitionError(job: SocialAcquisitionJob): string {
  const category = typeof job.error?.category === "string" ? job.error.category : undefined;
  if (category === "authentication") {
    return `The ${providerLabel(job.request.provider)} browser session expired or was rejected. Log in again in ${browserLabel(job.request.browser)} and retry.`;
  }
  const message = typeof job.error?.message === "string" ? job.error.message : undefined;
  return message || job.progress_message || "Social media retrieval failed.";
}

function legacyScan(
  engine: EngineClient,
  request: SocialAcquisitionRequest,
): Promise<IngressScanResult> {
  if (request.provider === "instagram") {
    return engine.scanInstagramBrowserUrl(
      request.url,
      request.browser,
      request.limit,
      request.cursor,
      request.scan_mode,
      request.date_from,
      request.date_to,
    );
  }
  if (request.provider === "x" && engine.scanXBrowserUrl) {
    return engine.scanXBrowserUrl(
      request.url,
      request.browser,
      request.limit,
      request.cursor,
      request.date_from,
      request.date_to,
    );
  }
  if (request.provider === "tiktok" && engine.scanTikTokBrowserUrl) {
    return engine.scanTikTokBrowserUrl(
      request.url,
      request.browser,
      request.limit,
      request.cursor,
      request.date_from,
      request.date_to,
    );
  }
  throw new Error(`${providerLabel(request.provider)} retrieval is not available in this engine.`);
}

function providerLabel(provider: SocialAcquisitionRequest["provider"]): string {
  if (provider === "x") return "X";
  return provider[0].toUpperCase() + provider.slice(1);
}

function browserLabel(browser?: string): string {
  if (!browser) return "the selected browser";
  return browser[0].toUpperCase() + browser.slice(1);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));
}
