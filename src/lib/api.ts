import type { ExportPackage, LocalImportResponse, RunComfyExportRequest } from "./types";

interface EngineResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
  text?(): Promise<string>;
}

type FetchLike = (input: string, init: RequestInit) => Promise<EngineResponse>;

export interface EngineClient {
  importLocal(paths: string[]): Promise<LocalImportResponse>;
  exportRunComfyImage(request: RunComfyExportRequest): Promise<ExportPackage>;
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

  return {
    importLocal(paths: string[]) {
      return postJson<LocalImportResponse>("/vault/import/local", { paths });
    },
    exportRunComfyImage(request: RunComfyExportRequest) {
      return postJson<ExportPackage>("/exports/runcomfy-image", request);
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
