export interface LibraryEntry {
  id: string;
  kind: 'image' | 'video' | 'audio' | 'model' | 'recipe' | 'page';
  title: string;
  url: string;
  page_url: string;
  project_id: string;
  requested_output: string;
  status: 'pending' | 'imported';
  archived?: boolean;
  result?: { path?: string; sha256?: string; h3_fused_layout?: boolean; compatibility?: string; media_item_ids?: string[] };
}
export interface LibraryStatus {
  ready: boolean;
  issue: string;
  port: number;
  url: string;
  model_root: string;
  export_ready?: boolean;
  export_issue?: string;
  items: LibraryEntry[];
  training_exports?: LibraryTrainingExport[];
}
export interface LibraryArtifactOptions {
  title?: string;
  base_model?: string;
  trigger_words?: string[];
  tags?: string[];
  description?: string;
  preview_paths?: string[];
  replace_metadata?: boolean;
}
export interface LibraryTrainingExport {
  artifact_id: string;
  manager_synced?: boolean;
  sync_issue?: string;
  metadata_preserved?: boolean;
  preview_paths?: string[];
  gallery_imported_paths?: string[];
  path: string;
  sha256: string;
  compatibility: 'unverified';
}
export type LibraryCategory = 'loras' | 'checkpoints' | 'embeddings';
export interface LibraryModel {
  path: string;
  name: string;
  category: LibraryCategory;
  base_model: string;
  sha256: string;
  trigger_words: string[];
  available: boolean;
  selectable: boolean;
  compatibility: 'unverified';
}
export interface LibraryCatalog {
  items: LibraryModel[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}
