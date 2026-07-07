export type MediaType = "image" | "video" | "audio";

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
