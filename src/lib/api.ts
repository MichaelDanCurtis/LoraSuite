import type {
  CreateIngressJobRequest,
  CreateProcessingJobRequest,
  ExportPackage,
  InstagramScanMode,
  IngressJob,
  IngressScanResult,
  LocalImportResponse,
  ProcessingJob,
  RunComfyExportRequest,
  SourceKind,
} from "./types";

interface EngineResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
  text?(): Promise<string>;
}

type FetchLike = (input: string, init: RequestInit) => Promise<EngineResponse>;

export interface EngineClient {
  importLocal(paths: string[]): Promise<LocalImportResponse>;
  scanLocalIngress(roots: string[], recursive?: boolean): Promise<IngressScanResult>;
  scanInstagramHelperPayload(
    payload: Record<string, unknown>,
    includeVideoPostersAsImageCandidates?: boolean,
  ): Promise<IngressScanResult>;
  scanInstagramBrowserUrl(
    url: string,
    browser?: string,
    limit?: number,
    cursor?: string,
    scanMode?: InstagramScanMode,
  ): Promise<IngressScanResult>;
  listIngressCandidates(sourceKind?: SourceKind): Promise<IngressScanResult>;
  createIngressJob(request: CreateIngressJobRequest): Promise<IngressJob>;
  listIngressJobs(): Promise<IngressJob[]>;
  getIngressJob(jobId: string): Promise<IngressJob>;
  createProcessingJob(request: CreateProcessingJobRequest): Promise<ProcessingJob>;
  listProcessingJobs(): Promise<ProcessingJob[]>;
  getProcessingJob(jobId: string): Promise<ProcessingJob>;
  processProcessingJob(jobId: string): Promise<ProcessingJob>;
  exportRunComfyImage(request: RunComfyExportRequest): Promise<ExportPackage>;
  assetUrl(path: string): string;
}

const defaultBaseUrl =
  (import.meta.env.VITE_LORASUITE_ENGINE_URL as string | undefined) || "http://127.0.0.1:8765";

export function createEngineClient(
  baseUrl = defaultBaseUrl,
  fetcher: FetchLike = fetch,
): EngineClient {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");

  async function postJson<TResponse>(path: string, body: unknown): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  async function getJson<TResponse>(path: string): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }

    return (await response.json()) as TResponse;
  }

  return {
    importLocal(paths: string[]) {
      return postJson<LocalImportResponse>("/vault/import/local", { paths });
    },
    scanLocalIngress(roots: string[], recursive = true) {
      return postJson<IngressScanResult>("/ingress/local/scan", { roots, recursive });
    },
    scanInstagramHelperPayload(
      payload: Record<string, unknown>,
      includeVideoPostersAsImageCandidates = true,
    ) {
      return postJson<IngressScanResult>("/ingress/instagram/helper-scan", {
        payload,
        include_video_posters_as_image_candidates: includeVideoPostersAsImageCandidates,
      });
    },
    scanInstagramBrowserUrl(
      url: string,
      browser = "chrome",
      limit = 24,
      cursor?: string,
      scanMode: InstagramScanMode = "all",
    ) {
      return postJson<IngressScanResult>("/ingress/instagram/browser-scan", {
        url,
        browser,
        limit,
        cursor,
        scan_mode: scanMode,
      });
    },
    listIngressCandidates(sourceKind?: SourceKind) {
      const query = sourceKind ? `?source_kind=${encodeURIComponent(sourceKind)}` : "";
      return getJson<IngressScanResult>(`/ingress/candidates${query}`);
    },
    createIngressJob(request: CreateIngressJobRequest) {
      return postJson<IngressJob>("/ingress/jobs", request);
    },
    listIngressJobs() {
      return getJson<IngressJob[]>("/ingress/jobs");
    },
    getIngressJob(jobId: string) {
      return getJson<IngressJob>(`/ingress/jobs/${jobId}`);
    },
    createProcessingJob(request: CreateProcessingJobRequest) {
      return postJson<ProcessingJob>("/processing/jobs", request);
    },
    listProcessingJobs() {
      return getJson<ProcessingJob[]>("/processing/jobs");
    },
    getProcessingJob(jobId: string) {
      return getJson<ProcessingJob>(`/processing/jobs/${jobId}`);
    },
    processProcessingJob(jobId: string) {
      return postJson<ProcessingJob>(`/processing/jobs/${jobId}/process`, {});
    },
    exportRunComfyImage(request: RunComfyExportRequest) {
      return postJson<ExportPackage>("/exports/runcomfy-image", request);
    },
    assetUrl(path: string) {
      return `${normalizedBaseUrl}/assets/file?path=${encodeURIComponent(path)}`;
    },
  };
}

async function readEngineError(response: EngineResponse): Promise<string> {
  try {
    const body = await response.json();
    if (isDetailBody(body)) {
      return body.detail;
    }
    if (body && typeof body === "object") {
      return JSON.stringify(body);
    }
  } catch {
    const text = await response.text?.();
    if (text) {
      return text;
    }
  }

  return `Engine request failed: ${response.status}`;
}

function isDetailBody(value: unknown): value is { detail: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "detail" in value &&
    typeof (value as { detail: unknown }).detail === "string"
  );
}
