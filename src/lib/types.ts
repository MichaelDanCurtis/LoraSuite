export type MediaType = "image" | "video" | "audio";
export type SourceKind = "local" | "instagram" | "x_twitter" | "tiktok";
export type IngressCandidateStatus = "ready" | "duplicate" | "unsupported" | "error";
export type IngressJobStatus = "queued" | "running" | "complete" | "failed" | "canceled";

export interface ImportErrorInfo {
  path: string;
  code: string;
  message: string;
}

export interface MediaItem {
  id: string;
  source_id?: string;
  raw_path?: string;
  media_type: MediaType;
  sha256?: string;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  status?: string;
  metadata_json?: Record<string, unknown>;
}

export interface LocalImportResponse {
  media_items: MediaItem[];
  errors: ImportErrorInfo[];
}

export interface IngressCandidate {
  id: string;
  source_kind: SourceKind;
  source_locator: string;
  display_name: string;
  media_type?: MediaType | null;
  size_bytes?: number | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  thumbnail_path?: string | null;
  poster_asset_path?: string | null;
  status: IngressCandidateStatus;
  error_message?: string | null;
  selected: boolean;
  metadata_json?: Record<string, unknown>;
}

export interface IngressScanResult {
  id: string;
  candidates: IngressCandidate[];
  errors: Array<Record<string, string>>;
}

export interface CreateIngressJobRequest {
  source_kind: SourceKind;
  candidate_ids: string[];
  options?: Record<string, unknown>;
}

export interface IngressJob {
  id: string;
  source_kind: SourceKind;
  candidate_ids: string[];
  candidate_count: number;
  selected_count: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  status: IngressJobStatus;
  progress_message: string;
  errors: Array<Record<string, string>>;
  imported_media_items: MediaItem[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface RunComfyExportRequest {
  frames: string[];
  output_dir: string;
  caption_template: string;
  source_segment_ids: string[];
}

export interface ExportPackage {
  id: string;
  export_type: string;
  output_path: string;
  manifest_path?: string | null;
  source_segment_ids: string[];
  status: string;
}
