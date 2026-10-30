export type MediaType = "image" | "video" | "audio";
export type CurationLane = MediaType;
export type CurationReviewStatus = "pending" | "accepted" | "rejected";
export type CurationRecommendation = "keep" | "review" | "reject";
export type SourceKind = "local" | "instagram" | "x_twitter" | "tiktok";
export type InstagramScanMode = "all" | "feed" | "reels" | "tagged";
export type IngressCandidateStatus = "ready" | "duplicate" | "unsupported" | "error";
export type IngressJobStatus = "queued" | "running" | "complete" | "failed" | "canceled";
export type ProcessingJobStatus = "queued" | "running" | "complete" | "failed" | "canceled";
export type VideoFrameDecision = "candidate" | "keeper" | "duplicate" | "rejected";
export type LoraTargetType = "character" | "style" | "concept" | "pose" | "clothing" | "object";
export type RequestedOutput = "image" | "video" | "voice" | "id_lora";
export type SpeakerConfirmation = "anchor" | "model_match" | "human_override";
export type DatasetReviewStatus = "accepted" | "needs_review" | "rejected";
export type DatasetDecisionSource = "automatic" | "user" | "anchor";
export type DatasetView = "face" | "upper_body" | "full_body" | "environment" | "unknown";
export type CropKind = "face" | "upper_body" | "full_body" | "square";
export type CropRecipeStatus = "proposed" | "approved" | "materialized";
export type DatasetItemStatus = "needs_review" | "approved" | "excluded";
export type DatasetSnapshotStatus = "draft" | "frozen" | "exported";
export type CaptionSource = "local_policy" | "user" | "vision";
export type VisionProviderDialect = "responses" | "chat_completions" | "grok_cli" | "apple_foundation";
export type VisionProviderAuthMode = "api_key" | "grok_oauth" | "local";

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

export interface VaultMediaPage {
  items: MediaItem[];
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
  next_offset: number | null;
  snapshot: string;
}

export interface ExactDuplicateCluster {
  id: string;
  media_type: MediaType;
  sha256: string;
  canonical_media_item_id: string;
  canonical_raw_path: string;
  duplicate_count: number;
  media_item_ids: string[];
  source_bundle_keys: string[];
  original_paths: string[];
  origins: Array<Record<string, unknown>>;
}

export interface CurationBundleItem {
  media_item_id: string;
  lane: CurationLane;
  role: string;
  source_media_item_id?: string | null;
  derivative_type?: string | null;
}

export interface CurationSourceBundle {
  id: string;
  title: string;
  source_kind?: SourceKind | null;
  source_locator?: string | null;
  root_media_item_ids: string[];
  intent_lanes: CurationLane[];
  items: CurationBundleItem[];
}

export interface CurationHandoffItem {
  media_item_id: string;
  lane: CurationLane;
  project_id?: string | null;
  requested_output?: RequestedOutput | null;
  review_status: CurationReviewStatus;
  speaker_confirmation?: SpeakerConfirmation | null;
  updated_at: string;
}

export interface CurationHandoff {
  items: CurationHandoffItem[];
  updated_at: string;
}

export interface LocalImportResponse {
  media_items: MediaItem[];
  errors: ImportErrorInfo[];
}

export interface ClearAllMediaResult {
  status: "cleared";
  files_removed: number;
  bytes_removed: number;
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
  metadata_json?: Record<string, unknown>;
}

export type SocialAcquisitionProvider = "instagram" | "x" | "tiktok";
export type SocialAcquisitionStatus =
  | "queued"
  | "running"
  | "cooldown"
  | "complete"
  | "failed"
  | "canceled";

export interface SocialAcquisitionRequest {
  provider: SocialAcquisitionProvider;
  url: string;
  browser?: string;
  limit?: number;
  cursor?: string;
  scan_mode?: InstagramScanMode;
  date_from?: string;
  date_to?: string;
}

export interface SocialAcquisitionJob {
  id: string;
  request: SocialAcquisitionRequest;
  request_fingerprint: string;
  status: SocialAcquisitionStatus;
  attempt: number;
  max_attempts: number;
  progress_message: string;
  retry_at?: string | null;
  retry_after_seconds?: number | null;
  cancel_requested: boolean;
  error?: Record<string, unknown> | null;
  result?: IngressScanResult | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface IngressCandidateAnalysis {
  candidate_id: string;
  recommendation: CurationRecommendation;
  confidence: number;
  quality_score?: number | null;
  face_count?: number | null;
  face_area?: number | null;
  body_coverage?: number | null;
  pose_coverage?: number | null;
  aesthetic_score?: number | null;
  reasons: string[];
  warnings: string[];
  analyzer: string;
}

export interface IngressCandidateAnalysisResponse {
  analyses: IngressCandidateAnalysis[];
  errors: Array<{ candidate_id: string; message: string }>;
}

export interface CreateIngressJobRequest {
  source_kind: SourceKind;
  candidate_ids: string[];
  reviewed_candidate_ids?: string[];
  options?: Record<string, unknown>;
}

export interface IngressJob {
  id: string;
  options?: Record<string, unknown>;
  source_kind: SourceKind;
  candidate_ids: string[];
  candidate_count: number;
  selected_count: number;
  imported_count: number;
  deferred_count: number;
  skipped_count: number;
  failed_count: number;
  status: IngressJobStatus;
  progress_message: string;
  errors: Array<Record<string, string>>;
  deferred_candidates: Array<Record<string, unknown>>;
  imported_media_items: MediaItem[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface VideoBreakdownOptions {
  frames_per_second?: number;
  max_frame_count?: number;
  extract_audio?: boolean;
  generate_frames?: boolean;
  intelligent_selection?: boolean;
  analysis_width?: number;
  max_analysis_frame_count?: number;
}

export interface VideoFrameScores {
  overall: number;
  sharpness: number;
  exposure: number;
  stability: number;
  detail: number;
  face_quality: number;
  face_area: number;
  body_coverage: number;
  scene_change: number;
  aesthetic?: number;
  pose_coverage?: number;
  diversity?: number;
  face_count?: number;
  head_yaw?: number | null;
  head_pitch?: number | null;
  head_roll?: number | null;
}

export interface VideoAnalysisFrame {
  id: string;
  source_media_item_id: string;
  timestamp_seconds: number;
  thumbnail_path: string;
  width: number;
  height: number;
  decision: VideoFrameDecision;
  scores: VideoFrameScores;
  reasons: string[];
  stable_range_id?: string | null;
  duplicate_cluster_id?: string | null;
  duplicate_of_frame_id?: string | null;
  output_media_item_id?: string | null;
}

export interface VideoStableRange {
  id: string;
  source_media_item_id: string;
  start_seconds: number;
  end_seconds: number;
  scene_index: number;
  frame_ids: string[];
}

export type VideoClipDecision = "keep" | "review" | "reject";

export interface VideoClipScores {
  quality: number;
  stability: number;
  identity_coverage: number;
  motion: number;
  scene_change: number;
  aesthetic: number;
}

export interface VideoClipProposal {
  id: string;
  source_media_item_id: string;
  stable_range_ids: string[];
  start_seconds: number;
  end_seconds: number;
  decision: VideoClipDecision;
  scores: VideoClipScores;
  reasons: string[];
  output_media_item_id?: string | null;
}

export interface VideoClipCommit {
  clip_id: string;
  start_seconds: number;
  end_seconds: number;
  decision: VideoClipDecision;
}

export interface VideoBreakdownCommitRequest {
  frame_ids: string[];
  clips: VideoClipCommit[];
}

export interface VideoBreakdownAnalysis {
  source_media_item_id: string;
  duration_seconds: number;
  sample_fps: number;
  analyzer: string;
  selection_method?: string;
  semantic_backend?: string;
  requested_keeper_count?: number | null;
  frames: VideoAnalysisFrame[];
  stable_ranges: VideoStableRange[];
  clip_proposals?: VideoClipProposal[];
}

export interface CreateProcessingJobRequest {
  job_type: "video_breakdown";
  source_media_item_ids: string[];
  options?: VideoBreakdownOptions;
}

export interface ProcessingJob {
  id: string;
  job_type: "video_breakdown" | "curation_analysis" | "audio_cleaning";
  source_media_item_ids: string[];
  options: VideoBreakdownOptions | Record<string, unknown>;
  status: ProcessingJobStatus;
  progress_message: string;
  errors: Array<Record<string, string>>;
  derived_media_items: MediaItem[];
  video_analyses?: VideoBreakdownAnalysis[];
  curation_analyses?: CurationAnalysisEvidence[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface CurationAnalysisEvidence {
  media_item_id: string;
  media_type: MediaType;
  recommendation: CurationRecommendation;
  confidence: number;
  quality_score?: number | null;
  face_count?: number | null;
  face_area?: number | null;
  body_coverage?: number | null;
  pose_coverage?: number | null;
  aesthetic_score?: number | null;
  head_yaw?: number | null;
  head_pitch?: number | null;
  head_roll?: number | null;
  sample_count?: number | null;
  active_audio_ratio?: number | null;
  clipping_ratio?: number | null;
  transcript?: string | null;
  language?: string | null;
  speech_duration_ratio?: number | null;
  transcript_confidence?: number | null;
  word_count?: number | null;
  speaker_count?: number | null;
  speaker_duration_ratio?: number | null;
  reasons: string[];
  warnings: string[];
  analyzer: string;
  analyzed_at: string;
}

export interface AudioCleaningRecipe {
  media_item_id: string;
  high_pass_hz: number;
  low_pass_hz: number;
  noise_floor_db: number;
  noise_reduction_db: number;
  gate_threshold_db: number;
  presence_gain_db: number;
  normalize: boolean;
  isolate_voice: boolean;
  updated_at?: string;
}

export interface AudioCleaningResult {
  recipe: AudioCleaningRecipe;
  preview_path: string;
  recipe_digest: string;
  separation_available: boolean;
  isolation_applied: boolean;
  warnings: string[];
  rendered_media_item?: MediaItem | null;
}

export interface AudioSeparationRuntimeStatus {
  backend: string;
  model_name: string;
  model_sha256: string;
  download_size_bytes: number;
  runtime_installed: boolean;
  model_installed: boolean;
  ready: boolean;
  message: string;
}

export interface TrainingIntent {
  target_type: LoraTargetType;
  subject_name: string;
  requested_outputs?: RequestedOutput[];
  training_target_profile_ids?: Partial<Record<RequestedOutput, string>>;
  trigger_token: string;
  description: string;
  learned_attributes: string[];
  controllable_attributes: string[];
  excluded_attributes: string[];
}

export interface DatasetObservation {
  media_item_id: string;
  review_status: DatasetReviewStatus;
  decision_source: DatasetDecisionSource;
  view: DatasetView;
  is_anchor: boolean;
  quality_score: number;
  diversity_score: number;
  identity_score?: number | null;
  face_count: number;
  face_area: number;
  body_coverage: number;
  aesthetic_score: number;
  head_yaw?: number | null;
  reasons: string[];
  warnings: string[];
  analyzer: string;
  identity_backend?: string;
  selected_face_index?: number | null;
  faces?: IdentityFace[];
  crop_recipe_ids?: string[];
  updated_at: string;
}

export interface NormalizedPoint {
  x: number;
  y: number;
}

export interface NormalizedRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface IdentityFace {
  index: number;
  confidence: number;
  bounding_box: NormalizedRect;
  landmarks: NormalizedPoint[];
  anchor_similarity?: number | null;
  selected: boolean;
}

export interface CropRecipe {
  id: string;
  media_item_id: string;
  kind: CropKind;
  rect: NormalizedRect;
  aspect_ratio: string;
  face_index?: number | null;
  status: CropRecipeStatus;
  output_media_item_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IdentityRuntimeStatus {
  backend: string;
  model_version: string;
  installed: boolean;
  ready: boolean;
  download_size_bytes: number;
  message: string;
}

export interface VoiceIdentityEvidence {
  media_item_id: string;
  similarity?: number | null;
  recommendation: CurationRecommendation;
  is_anchor: boolean;
  anchor_count: number;
  reasons: string[];
  warnings: string[];
  backend: string;
  analyzed_at: string;
}

export interface VoiceIdentityProfile {
  project_id: string;
  anchor_media_item_ids: string[];
  evidence: Record<string, VoiceIdentityEvidence>;
  updated_at: string;
}

export interface VoiceSampleConfirmationResult {
  project: CharacterProject;
  profile: VoiceIdentityProfile;
  handoff: CurationHandoff;
}

export type VoiceSegmentStatus = "needs_review" | "approved" | "rejected";
export type VoiceExportTarget = "voice_cloning" | "av_lora" | "both";

export interface VoiceSegmentQualityEvidence {
  quality_score: number;
  recommendation: CurationRecommendation;
  active_audio_ratio?: number | null;
  silence_ratio?: number | null;
  clipping_ratio?: number | null;
  noise_floor_db?: number | null;
  snr_db?: number | null;
  dynamic_range_db?: number | null;
  reverb_risk?: number | null;
  background_music_risk?: number | null;
  speaker_count?: number | null;
  source_classification: string;
  voice_isolation_applied: boolean;
  reasons: string[];
  warnings: string[];
  analyzer: string;
  analyzed_at: string;
}

export interface VoiceDatasetSegment {
  id: string;
  project_id: string;
  source_media_item_id: string;
  media_item_id: string;
  audio_path: string;
  start_seconds: number;
  end_seconds: number;
  transcript: string;
  language?: string | null;
  transcript_confidence?: number | null;
  speaker_similarity?: number | null;
  identity_recommendation: CurationRecommendation;
  identity_reasons: string[];
  identity_warnings: string[];
  quality?: VoiceSegmentQualityEvidence | null;
  recommendation: CurationRecommendation;
  status: VoiceSegmentStatus;
  reasons: string[];
  warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface VoiceDatasetBalance {
  total_count: number;
  approved_count: number;
  review_count: number;
  rejected_count: number;
  source_count: number;
  total_duration_seconds: number;
  average_quality: number;
  average_speaker_similarity: number;
  average_transcript_confidence: number;
  average_active_audio_ratio: number;
  average_silence_ratio: number;
  average_clipping_ratio: number;
  average_background_music_risk: number;
  warnings: string[];
  recipe_compliance?: RecipeCompliance | null;
}

export interface VoiceDatasetCompilation {
  project_id: string;
  source_media_item_ids: string[];
  segments: Record<string, VoiceDatasetSegment>;
  target_profile_id?: string;
  target_label?: string;
  balance?: VoiceDatasetBalance;
  dataset_fingerprint?: string | null;
  export_path?: string | null;
  export_target?: VoiceExportTarget | null;
  updated_at: string;
}

export interface VoiceDatasetExportResponse {
  compilation: VoiceDatasetCompilation;
  package: ExportPackage;
}

export interface DatasetHealth {
  candidate_count: number;
  accepted_count: number;
  review_count: number;
  rejected_count: number;
  anchor_count: number;
  effective_observation_count: number;
  source_count: number;
  largest_source_share: number;
  average_quality: number;
  average_diversity: number;
  view_counts: Record<string, number>;
  analyzer: string;
  warnings: string[];
}

export interface CharacterProject {
  id: string;
  name: string;
  intent: TrainingIntent;
  candidate_media_item_ids: string[];
  observations: Record<string, DatasetObservation>;
  crop_recipes?: Record<string, CropRecipe>;
  health: DatasetHealth;
  created_at: string;
  updated_at: string;
}

export interface VisionCaptionEvidence {
  expression: string;
  pose: string;
  clothing: string;
  environment: string;
  camera: string;
  lighting: string;
  visual_style: string;
  other_people: string;
  watermark: string;
  content: string;
  confidence: number;
}

export interface DatasetCaptionRecord {
  id: string;
  source_media_item_id: string;
  training_media_item_id: string;
  crop_recipe_id?: string | null;
  caption: string;
  tags: string[];
  attributes: Record<string, string>;
  unresolved_attributes: string[];
  status: DatasetItemStatus;
  caption_source: CaptionSource;
  caption_provider?: string | null;
  caption_model?: string | null;
  caption_confidence?: number | null;
  vision_evidence?: VisionCaptionEvidence | null;
  strongest_set_excluded?: boolean;
  strongest_set_rank?: number | null;
  strongest_set_score?: number | null;
  strongest_set_reasons?: string[];
  view: DatasetView;
  quality_score: number;
  diversity_score: number;
  identity_score?: number | null;
  is_anchor: boolean;
  source_id: string;
  created_at: string;
  updated_at: string;
}

export interface DatasetBalance {
  total_count: number;
  approved_count: number;
  review_count: number;
  excluded_count: number;
  source_count: number;
  cropped_count: number;
  average_quality: number;
  average_diversity: number;
  view_counts: Record<string, number>;
  crop_counts: Record<string, number>;
  warnings: string[];
  recipe_compliance?: RecipeCompliance | null;
}

export interface StrongestSetCandidate {
  item_id: string;
  score: number;
  reasons: string[];
  group: DatasetView;
}

export interface DatasetStrongestSetProposal {
  snapshot_id: string;
  target_count: number;
  selected_count: number;
  excluded_count: number;
  already_excluded_count: number;
  recipe_minimum: number;
  recipe_recommended: number;
  recipe_maximum: number;
  selected: StrongestSetCandidate[];
  excluded_item_ids: string[];
  view_counts: Record<string, number>;
  source_counts: Record<string, number>;
  average_quality: number;
  average_diversity: number;
  average_identity?: number | null;
  warnings: string[];
}

export interface DatasetStrongestSetApplyResponse {
  snapshot: DatasetSnapshot;
  proposal: DatasetStrongestSetProposal;
}

export interface DatasetDuplicateCandidate {
  item_id: string;
  training_media_item_id: string;
  hash_distance: number;
  score: number;
  group: DatasetView;
  is_recommended_keep: boolean;
}

export interface DatasetDuplicateCluster {
  id: string;
  recommended_keep_item_id: string;
  candidates: DatasetDuplicateCandidate[];
}

export interface DatasetDuplicateProposal {
  snapshot_id: string;
  scanned_count: number;
  duplicate_count: number;
  unreadable_count: number;
  clusters: DatasetDuplicateCluster[];
}

export interface DatasetSnapshot {
  id: string;
  project_id: string;
  project_name: string;
  version: number;
  status: DatasetSnapshotStatus;
  intent: TrainingIntent;
  training_target?: TrainingTargetSpec;
  items: Record<string, DatasetCaptionRecord>;
  balance: DatasetBalance;
  model_card_overrides?: LoraModelCardOverrides;
  model_card?: LoraModelCard | null;
  fingerprint?: string | null;
  export_package_id?: string | null;
  export_path?: string | null;
  parent_snapshot_id?: string | null;
  parent_fingerprint?: string | null;
  improvement_request_id?: string | null;
  source_artifact_id?: string | null;
  source_checkpoint_sha256?: string | null;
  revision_plan?: string[];
  created_at: string;
  updated_at: string;
  frozen_at?: string | null;
}

export interface TrainingTargetSpec {
  profile_id: string;
  label: string;
  provider: string;
  trainer: string;
  modality: "image" | "video" | "voice" | "audio_visual";
  model_family: string;
  base_model: string;
  compiler_version: string;
  resolution_buckets: number[];
  caption_format: string;
  output_format: string;
  recipe_id?: string | null;
  recipe_version?: number | null;
}

export interface TrainingTargetProfile extends TrainingTargetSpec {
  description: string;
  ready: boolean;
  config_template: string;
  warnings: string[];
  recipe?: ModelIntentRecipe | null;
  duration_baselines?: TrainingDurationBaseline[];
}

export interface RecoveredDatasetExport {
  id: string;
  format: "lorasuite.recovered-dataset.v1";
  export_path: string;
  manifest_path: string;
  manifest_sha256: string;
  export_type: string;
  modality: "image" | "video" | "voice" | "audio_visual";
  project_id: string;
  snapshot_id: string;
  dataset_version: number;
  fingerprint: string;
  fingerprint_source: "manifest" | "content";
  training_target: TrainingTargetSpec;
  trigger_token: string;
  trigger_token_source: "model_card" | "caption_consensus" | "unknown";
  model_card?: LoraModelCard | null;
  revision_lineage: {
    parent_snapshot_id?: string | null;
    parent_dataset_fingerprint?: string | null;
    improvement_request_id?: string | null;
    parent_artifact_id?: string | null;
    parent_checkpoint_sha256?: string | null;
  };
  file_count: number;
  verified_file_count: number;
  integrity_status: "verified" | "structural" | "failed";
  ready: boolean;
  source_available: boolean;
  warnings: string[];
  errors: string[];
  imported_at: string;
  verified_at: string;
}

export interface StateFileMigration {
  filename: string;
  path: string;
  exists: boolean;
  current_version?: number | null;
  target_version: number;
  status: "missing" | "current" | "pending" | "migrated" | "registered" | "invalid" | "future";
  action: "none" | "register" | "migrate";
  embedded_version: boolean;
  sha256_before?: string | null;
  sha256_after?: string | null;
  backup_path?: string | null;
  message: string;
}

export interface StateMigrationReport {
  format: "lorasuite.state-schema.v1";
  vault_root: string;
  dry_run: boolean;
  ready: boolean;
  updated_count: number;
  pending_count: number;
  invalid_count: number;
  future_count: number;
  files: StateFileMigration[];
  ledger_path: string;
  backup_root?: string | null;
  created_at: string;
}

export interface DiagnosticBundleRecord {
  id: string;
  format: "lorasuite.diagnostic-bundle.v1";
  archive_path: string;
  archive_sha256: string;
  size_bytes: number;
  included_files: string[];
  exclusions: string[];
  state_ready: boolean;
  comfy_runtime_included: boolean;
  partner_qualification_included?: boolean;
  created_at: string;
}

export interface TrainingDurationBaseline {
  gpu_family: "h100" | "h200";
  baseline_steps: number;
  low_hours: number;
  expected_hours: number;
  high_hours: number;
  confidence: "low" | "medium" | "high";
  basis: string;
  assumptions: string[];
}

export interface DatasetRecipePolicy {
  minimum_approved_items: number;
  recommended_approved_items: number;
  maximum_approved_items: number;
  minimum_sources: number;
  maximum_source_share: number;
  minimum_face_views: number;
  minimum_upper_body_views: number;
  minimum_full_body_views: number;
  minimum_materialized_crops: number;
  minimum_average_quality: number;
  minimum_average_diversity: number;
  allowed_image_extensions: string[];
  allowed_video_extensions?: string[];
  allowed_audio_extensions?: string[];
  minimum_total_duration_seconds?: number | null;
  recommended_total_duration_seconds?: number | null;
  maximum_total_duration_seconds?: number | null;
  minimum_clip_duration_seconds?: number | null;
  maximum_clip_duration_seconds?: number | null;
  target_fps?: number | null;
  target_num_frames?: number | null;
  maximum_normalized_dimension?: number | null;
  minimum_average_identity?: number | null;
  minimum_average_stability?: number | null;
  minimum_average_motion?: number | null;
  maximum_average_motion?: number | null;
  minimum_average_speaker_similarity?: number | null;
  minimum_average_transcript_confidence?: number | null;
  minimum_average_active_audio_ratio?: number | null;
  maximum_average_silence_ratio?: number | null;
  maximum_average_clipping_ratio?: number | null;
  maximum_average_background_music_risk?: number | null;
  maximum_multi_speaker_segments?: number | null;
  minimum_visual_examples?: number | null;
  minimum_synchronized_pairs?: number | null;
  minimum_voice_references?: number | null;
  minimum_validation_examples?: number | null;
  guidance: string[];
}

export interface CaptionRecipePolicy {
  trigger_token_required: boolean;
  caption_format: string;
  render_style?: "concise" | "narrative" | "tags";
  required_evidence: string[];
  controllable_attributes: string[];
  excluded_identity_attributes: string[];
  guidance: string[];
}

export interface TrainingRecipeDefaults {
  network_rank: number;
  network_alpha: number;
  steps: number;
  minimum_steps: number;
  maximum_steps: number;
  learning_rate: number;
  optimizer: string;
  precision: string;
  batch_size: number;
  save_every: number;
  sample_every: number;
  caption_dropout_rate: number;
  train_text_encoder: boolean;
  gradient_checkpointing: boolean;
  cache_text_embeddings: boolean;
  sample_steps: number;
  sample_guidance_scale: number;
}

export interface InferenceRecipeDefaults {
  pipeline: string;
  reference_audio_seconds?: number | null;
  inference_steps: number;
  guidance_scale: number;
  output_width?: number | null;
  output_height?: number | null;
  output_frames?: number | null;
}

export interface EvaluationRecipePolicy {
  required_gates: string[];
  minimum_identity_score: number;
  minimum_prompt_adherence: number;
  minimum_temporal_stability?: number | null;
  minimum_motion_quality?: number | null;
  minimum_speaker_similarity?: number | null;
  minimum_transcript_similarity?: number | null;
  minimum_audio_quality?: number | null;
  maximum_artifact_rate: number;
  benchmark_prompt_count: number;
  guidance: string[];
}

export interface MetadataRecipePolicy {
  schema_version: string;
  required_fields: string[];
}

export interface ModelIntentRecipe {
  recipe_id: string;
  version: number;
  label: string;
  status: "baseline" | "validated" | "experimental";
  workflow_kind?: "training" | "inference";
  modality: "image" | "video" | "voice" | "audio_visual";
  model_family: string;
  base_model: string;
  intent: LoraTargetType;
  dataset: DatasetRecipePolicy;
  captions: CaptionRecipePolicy;
  training?: TrainingRecipeDefaults | null;
  inference?: InferenceRecipeDefaults | null;
  evaluation: EvaluationRecipePolicy;
  metadata: MetadataRecipePolicy;
  rationale: string[];
  evidence_urls: string[];
}

export interface LoraModelCard {
  schema_version: string;
  name: string;
  display_name: string;
  description: string;
  license: string;
  tags: string[];
  modality: "image" | "video" | "voice" | "audio_visual";
  target_type: string;
  subject_name: string;
  trigger_token: string;
  base_model: string;
  model_family: string;
  recipe_id?: string | null;
  recipe_version?: number | null;
  recipe_status?: string | null;
  training_target_profile_id: string;
  dataset: Record<string, unknown>;
  captions: Record<string, unknown>;
  training: Record<string, unknown>;
  evaluation: Record<string, unknown>;
  usage: Record<string, unknown>;
  artifact?: Record<string, unknown> | null;
  provenance: Record<string, unknown>;
  warnings: string[];
  validation: ModelCardValidation;
}

export interface ModelCardCheck {
  check_id: string;
  label: string;
  passed: boolean;
  severity: "blocker" | "warning";
  message: string;
}

export interface ModelCardValidation {
  status: "ready" | "review" | "blocked";
  blocker_count: number;
  warning_count: number;
  checks: ModelCardCheck[];
}

export interface LoraModelCardOverrides {
  name?: string | null;
  display_name?: string | null;
  description?: string | null;
  license?: string | null;
  tags?: string[] | null;
  intended_use?: string[] | null;
  limitations?: string[] | null;
  sample_prompts?: string[] | null;
  recommended_strength?: number | null;
}

export interface RecipeCheck {
  check_id: string;
  label: string;
  passed: boolean;
  severity: "blocker" | "warning";
  detail: string;
  current?: number | string | null;
  target?: number | string | null;
}

export interface RecipeCompliance {
  recipe_id: string;
  recipe_version: number;
  recipe_label: string;
  status: "ready" | "review" | "blocked";
  score: number;
  blocker_count: number;
  warning_count: number;
  checks: RecipeCheck[];
}

export interface VisionProviderPreset {
  id: string;
  label: string;
  dialect: VisionProviderDialect;
  auth_mode: VisionProviderAuthMode;
  base_url: string;
  model: string;
  configured: boolean;
}

export interface CaptionGenerationRequest {
  item_ids: string[];
  provider_id: string;
  provider_label: string;
  dialect: VisionProviderDialect;
  base_url: string;
  model: string;
  api_key?: string;
}

export interface CaptionGenerationJob {
  id: string;
  snapshot_id: string;
  item_ids: string[];
  provider_id: string;
  provider_label: string;
  model: string;
  provider_dialect?: VisionProviderDialect | null;
  provider_base_url?: string | null;
  provider_auth_mode?: VisionProviderAuthMode | null;
  status: ProcessingJobStatus;
  total_count: number;
  completed_count: number;
  failed_count: number;
  next_item_index?: number;
  progress_message: string;
  errors: Array<Record<string, string>>;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface DatasetExportResponse {
  snapshot: DatasetSnapshot;
  package: ExportPackage;
}

export type TrainingRunStatus =
  | "queued"
  | "uploading"
  | "dataset_ready"
  | "in_queue"
  | "running"
  | "stopped"
  | "downloading"
  | "completed"
  | "failed"
  | "canceled";

export interface TrainingArtifact {
  kind: string;
  name: string;
  remote_url: string;
  local_path?: string | null;
  step?: number | null;
  prompt?: string | null;
  sample_index?: number | null;
}

export interface TrainingUploadCheckpoint {
  relative_path: string;
  provider_filename: string;
  size_bytes: number;
  sha256: string;
  transport: string;
  uploaded_at: string;
}

export interface TrainingRun {
  id: string;
  provider: "runcomfy" | string;
  snapshot_id: string;
  dataset_fingerprint: string;
  parent_snapshot_id?: string | null;
  parent_dataset_fingerprint?: string | null;
  improvement_request_id?: string | null;
  parent_artifact_id?: string | null;
  parent_checkpoint_sha256?: string | null;
  config_digest?: string;
  config_file: string;
  gpu_type: "ADA_80_PLUS" | "HOPPER_141";
  status: TrainingRunStatus;
  dataset_id?: string | null;
  dataset_name?: string | null;
  upload_manifest_digest?: string | null;
  uploaded_files?: TrainingUploadCheckpoint[];
  provider_job_id?: string | null;
  progress_current: number;
  progress_total: number;
  progress_percent: number;
  progress_message: string;
  export_path: string;
  artifact_dir?: string | null;
  artifacts: TrainingArtifact[];
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateTrainingRunRequest {
  snapshot_id: string;
  config_file: string;
  gpu_type: "ADA_80_PLUS" | "HOPPER_141";
  api_token?: string;
}

export interface EstimateRange {
  low: number;
  expected: number;
  high: number;
}

export interface TrainingEstimateRequest {
  provider: "runcomfy" | "runpod";
  training_target_profile_id: string;
  gpu_type: string;
  pricing_tier?: string;
  config_file?: string;
  steps?: number;
  dataset_item_count?: number;
  hourly_rate_usd?: number;
}

export interface TrainingCostEstimate {
  schema_version: "lorasuite.training-estimate.v1" | string;
  available: boolean;
  provider: "runcomfy" | "runpod";
  training_target_profile_id: string;
  training_target_label: string;
  gpu_type: string;
  gpu_family: string;
  pricing_tier: string;
  step_count?: number | null;
  dataset_item_count?: number | null;
  duration_hours?: EstimateRange | null;
  hourly_rate_usd?: number | null;
  cost_usd?: EstimateRange | null;
  confidence: "low" | "medium" | "high";
  historical_run_count: number;
  duration_basis: string;
  pricing_basis: string;
  pricing_source_url?: string | null;
  pricing_snapshot_date?: string | null;
  assumptions: string[];
  warnings: string[];
}

export interface ArtifactEvaluation {
  status: "ready" | "review" | "failed";
  checkpoint_valid: boolean;
  provenance_valid: boolean;
  config_present: boolean;
  sample_count: number;
  tensor_count: number;
  parameter_count: number;
  warnings: string[];
  evaluated_at: string;
}

export interface ArtifactAcceptance {
  status: "not_evaluated" | "running" | "screening_passed" | "certified" | "blocked" | "failed" | "error";
  benchmark_run_id?: string | null;
  screening_ready: boolean;
  release_ready: boolean;
  passed_count: number;
  failed_count: number;
  blocked_count: number;
  identity_similarity?: number | null;
  visual_quality?: number | null;
  subject_coverage?: number | null;
  temporal_stability?: number | null;
  speaker_similarity?: number | null;
  av_sync_proxy?: number | null;
  warnings: string[];
  evaluated_at?: string | null;
}

export interface ModelArtifactRecord {
  id: string;
  project_id?: string;
  training_run_id: string;
  snapshot_id: string;
  dataset_fingerprint: string;
  parent_snapshot_id?: string | null;
  parent_dataset_fingerprint?: string | null;
  improvement_request_id?: string | null;
  parent_artifact_id?: string | null;
  parent_checkpoint_sha256?: string | null;
  checkpoint_name: string;
  checkpoint_path: string;
  checkpoint_sha256: string;
  checkpoint_size_bytes: number;
  config_path?: string | null;
  sample_paths: string[];
  trigger_token: string;
  base_model?: string | null;
  modality: "image" | "video" | "voice" | "audio_visual";
  model_family: string;
  model_card?: LoraModelCard | null;
  model_card_path?: string | null;
  evaluation: ArtifactEvaluation;
  acceptance?: ArtifactAcceptance;
  selected_for_release?: boolean;
  release_selected_at?: string | null;
  installed_paths: string[];
  workflow_paths: string[];
  handoff_paths?: string[];
  comfy_installations?: ComfyArtifactInstallState[];
  created_at: string;
  updated_at: string;
}

export interface ComfyArtifactInstallState {
  root: string;
  checkpoint_path: string;
  handoff_path: string;
  extension_path: string;
  extension_version: string;
  compatibility_status: "ready" | "review" | "blocked";
  workflow_paths: string[];
  runnable_workflow_count: number;
  installed_at: string;
}

export interface ComfyCompatibilityCheck {
  check_id: string;
  label: string;
  status: "passed" | "warning" | "blocked";
  detail: string;
}

export interface ComfyModelBinding {
  binding_id: string;
  label: string;
  model_directory: string;
  required: boolean;
  selected_name?: string | null;
  candidates: string[];
  patterns: string[];
}

export interface ComfyWorkflowRecord {
  workflow_id: string;
  label: string;
  purpose: "inference" | "evaluation" | "component";
  path: string;
  runnable: boolean;
  required_nodes: string[];
  missing_bindings: string[];
  warnings: string[];
}

export interface ComfyHandoffManifest {
  format: "lorasuite.comfy-handoff.v1";
  contract_version: number;
  generated_at: string;
  artifact: Record<string, unknown>;
  inference: {
    trigger_token?: string;
    recommended_strength?: number;
    sample_prompts?: string[];
  };
  compatibility: {
    status: "ready" | "review" | "blocked";
    model_family: string;
    modality: string;
    checks: ComfyCompatibilityCheck[];
    model_bindings: ComfyModelBinding[];
    warnings: string[];
  };
  workflows: ComfyWorkflowRecord[];
  extension: Record<string, unknown>;
  evaluation_report: Record<string, unknown>;
}

export interface ComfyEvaluationReport {
  id: string;
  artifact_id: string;
  project_id: string;
  checkpoint_sha256: string;
  workflow_id: string;
  verdict: "pass" | "review" | "fail";
  rating: number;
  prompt: string;
  seed?: number | null;
  output_paths: string[];
  notes: string;
  metrics: Record<string, number>;
  comfy_root?: string | null;
  created_at: string;
}

export interface ArtifactEvidenceRecord {
  artifact_id: string;
  checkpoint_name: string;
  checkpoint_sha256: string;
  dataset_snapshot_id: string;
  dataset_fingerprint: string;
  training_run_id: string;
  model_family: string;
  modality: string;
  benchmark_run_id: string;
  benchmark_generation_run_id?: string | null;
  benchmark_status: string;
  case_ids: string[];
  prompt_seed_signature?: string | null;
  baseline_signature?: string | null;
  comfy_report_ids: string[];
}

export interface EvaluationMetricDelta {
  metric: string;
  direction: "higher" | "lower" | "target";
  reference_value?: number | null;
  candidate_value?: number | null;
  reference_baseline?: number | null;
  candidate_baseline?: number | null;
  reference_lift?: number | null;
  candidate_lift?: number | null;
  delta?: number | null;
  verdict: "improved" | "regressed" | "unchanged" | "unavailable";
}

export interface EvaluationCaseComparison {
  case_id: string;
  label: string;
  prompt: string;
  seed?: number | null;
  reference_passed?: boolean | null;
  candidate_passed: boolean;
  reference_blocked?: boolean | null;
  candidate_blocked: boolean;
  metrics: EvaluationMetricDelta[];
  candidate_reasons: string[];
}

export interface ComfyEvidenceSummary {
  report_count: number;
  pass_count: number;
  review_count: number;
  fail_count: number;
  average_rating?: number | null;
  average_metrics: Record<string, number>;
}

export interface ArtifactComparison {
  format: "lorasuite.artifact-comparison.v1";
  contract_version: number;
  id: string;
  project_id: string;
  benchmark_kind: "image" | "audio_visual";
  comparison_kind: "baseline_vs_artifact" | "artifact_vs_artifact";
  reference?: ArtifactEvidenceRecord | null;
  candidate: ArtifactEvidenceRecord;
  comparability: "exact_baseline" | "prompt_seed_matched" | "case_matched" | "partial";
  comparability_notes: string[];
  cases: EvaluationCaseComparison[];
  aggregate_metrics: EvaluationMetricDelta[];
  improved_count: number;
  regressed_count: number;
  unchanged_count: number;
  reference_comfy?: ComfyEvidenceSummary | null;
  candidate_comfy: ComfyEvidenceSummary;
  created_at: string;
}

export interface ImprovementAction {
  id: string;
  category:
    | "dataset_coverage"
    | "curation"
    | "caption_policy"
    | "identity_evidence"
    | "training_recipe"
    | "video_data"
    | "voice_data"
    | "evaluation_setup";
  priority: "high" | "medium" | "low";
  title: string;
  recommendation: string;
  evidence: string[];
  automatic: boolean;
}

export interface ImprovementRequest {
  format: "lorasuite.improvement-request.v1";
  contract_version: number;
  id: string;
  comparison_id: string;
  project_id: string;
  benchmark_kind: "image" | "audio_visual";
  candidate_artifact_id: string;
  candidate_checkpoint_sha256: string;
  reference_artifact_id?: string | null;
  reference_checkpoint_sha256?: string | null;
  status: "draft" | "approved" | "rejected";
  summary: string;
  actions: ImprovementAction[];
  decision_note: string;
  created_at: string;
  updated_at: string;
  decided_at?: string | null;
}

export interface DatasetRevisionRecord {
  format: "lorasuite.dataset-revision.v1";
  contract_version: number;
  id: string;
  improvement_request_id: string;
  comparison_id: string;
  project_id: string;
  modality: "image" | "video";
  source_artifact_id: string;
  source_checkpoint_sha256: string;
  parent_snapshot_id: string;
  parent_snapshot_fingerprint: string;
  revision_snapshot_id: string;
  revision_version: number;
  action_ids: string[];
  status: "draft";
  created_at: string;
}

export interface ArtifactReleaseCandidate {
  rank: number;
  score: number;
  eligible: boolean;
  selected: boolean;
  artifact: ModelArtifactRecord;
  metrics: Record<string, number>;
  reasons: string[];
}

export interface VoiceEvaluationSample {
  id: string;
  audio_path: string;
  transcript_path: string;
  expected_transcript: string;
  actual_transcript?: string | null;
  duration_seconds: number;
  quality_score?: number | null;
  speaker_similarity?: number | null;
  transcript_similarity?: number | null;
  active_audio_ratio?: number | null;
  silence_ratio?: number | null;
  clipping_ratio?: number | null;
  snr_db?: number | null;
  checks: Record<string, boolean | null>;
  passed: boolean;
  blocked: boolean;
  notes: string[];
}

export interface VoiceEvaluationSummary {
  sample_count: number;
  passed_count: number;
  failed_count: number;
  blocked_count: number;
  average_quality?: number | null;
  average_speaker_similarity?: number | null;
  average_transcript_similarity?: number | null;
  screening_ready: boolean;
  rank_score: number;
  warnings: string[];
}

export interface VoiceArtifactEvaluationRun {
  id: string;
  project_id: string;
  artifact_id: string;
  checkpoint_name: string;
  checkpoint_step?: number | null;
  samples_dir: string;
  status: "queued" | "running" | "complete" | "failed";
  samples: Record<string, VoiceEvaluationSample>;
  summary: VoiceEvaluationSummary;
  selected_for_release: boolean;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateVoiceArtifactEvaluationRequest {
  project_id: string;
  artifact_id: string;
  samples_dir: string;
}

export interface ComfyInstallation {
  root: string;
  label: string;
  models_path: string;
  workflows_path: string;
}

export interface ComfyRuntimeStatus {
  root: string;
  base_url: string;
  reachable: boolean;
  extension_installed: boolean;
  extension_version?: string | null;
  required_nodes: string[];
  loaded_nodes: string[];
  missing_nodes: string[];
  restart_required: boolean;
  error?: string | null;
  checked_at: string;
}

export type VideoDatasetItemStatus = "needs_review" | "approved" | "excluded";
export type VideoDatasetSnapshotStatus = "draft" | "frozen" | "exported";
export type VideoDatasetSplit = "unassigned" | "train" | "validation";

export interface VideoDatasetItem {
  id: string;
  media_item_id: string;
  source_media_item_id: string;
  caption: string;
  status: VideoDatasetItemStatus;
  split: VideoDatasetSplit;
  duration_seconds: number;
  width: number;
  height: number;
  fps?: number | null;
  quality_score: number;
  identity_score: number;
  stability_score: number;
  motion_score: number;
  created_at: string;
  updated_at: string;
}

export interface VideoDatasetBalance {
  total_count: number;
  approved_count: number;
  review_count: number;
  excluded_count: number;
  source_count: number;
  total_duration_seconds: number;
  train_count: number;
  validation_count: number;
  average_quality: number;
  average_identity: number;
  average_stability?: number;
  average_motion?: number;
  warnings: string[];
  recipe_compliance?: RecipeCompliance | null;
}

export interface VideoDatasetSnapshot {
  id: string;
  project_id: string;
  project_name: string;
  version: number;
  status: VideoDatasetSnapshotStatus;
  trigger_token: string;
  intent_type?: string;
  target_profile_id: string;
  target_label: string;
  reference_image_media_item_ids?: string[];
  reference_audio_media_item_ids?: string[];
  items: Record<string, VideoDatasetItem>;
  balance: VideoDatasetBalance;
  fingerprint?: string | null;
  export_path?: string | null;
  parent_snapshot_id?: string | null;
  parent_fingerprint?: string | null;
  improvement_request_id?: string | null;
  source_artifact_id?: string | null;
  source_checkpoint_sha256?: string | null;
  revision_plan?: string[];
  created_at: string;
  updated_at: string;
  frozen_at?: string | null;
}

export interface VideoDatasetExportResponse {
  snapshot: VideoDatasetSnapshot;
  package: ExportPackage;
}

export type IdLoraPairingKind = "synchronized_av" | "visual_only";

export interface IdLoraExample {
  id: string;
  video_dataset_item_id: string;
  video_media_item_id: string;
  video_source_media_item_id: string;
  video_start_seconds: number;
  video_end_seconds: number;
  visual_caption: string;
  voice_segment_id?: string | null;
  audio_media_item_id?: string | null;
  audio_source_media_item_id?: string | null;
  audio_start_seconds?: number | null;
  audio_end_seconds?: number | null;
  transcript?: string | null;
  reference_voice_segment_id?: string | null;
  reference_audio_media_item_id?: string | null;
  reference_audio_source_media_item_id?: string | null;
  multimodal_caption: string;
  pairing_kind: IdLoraPairingKind;
  split: "train" | "validation";
  identity_score: number;
  speaker_similarity?: number | null;
  warnings: string[];
}

export interface IdLoraVoiceReference {
  voice_segment_id: string;
  audio_media_item_id: string;
  audio_source_media_item_id: string;
  transcript: string;
  split: "train" | "validation";
  speaker_similarity?: number | null;
  quality_score?: number | null;
}

export interface IdLoraManifest {
  id: string;
  project_id: string;
  video_snapshot_id: string;
  video_fingerprint: string;
  target_profile_id?: string;
  target_label?: string;
  workflow_kind?: "inference";
  status: "ready" | "blocked";
  examples: Record<string, IdLoraExample>;
  voice_references: Record<string, IdLoraVoiceReference>;
  balance: {
    visual_example_count: number;
    synchronized_pair_count: number;
    visual_only_count: number;
    voice_reference_count: number;
    train_count: number;
    validation_count: number;
    source_count: number;
    average_identity?: number;
    average_speaker_similarity?: number;
    warnings: string[];
    recipe_compliance?: RecipeCompliance | null;
  };
  fingerprint: string;
  export_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IdLoraExportResponse {
  manifest: IdLoraManifest;
  package: ExportPackage;
}

export interface IdLoraEvaluationCase {
  id: string;
  output_name: string;
  prompt: string;
  expected_transcript?: string | null;
  video_path: string;
  metrics: BenchmarkMetrics;
  checks: Record<string, boolean | null>;
  certified_checks: Record<string, boolean | null>;
  passed: boolean;
  blocked: boolean;
  certified: boolean;
  reasons: string[];
}

export interface IdLoraEvaluationRun {
  id: string;
  project_id: string;
  runpod_run_id: string;
  contract_path: string;
  video_paths: Record<string, string>;
  status: "queued" | "running" | "complete" | "failed";
  cases: Record<string, IdLoraEvaluationCase>;
  summary: {
    case_count: number;
    passed_count: number;
    failed_count: number;
    blocked_count: number;
    average_identity?: number | null;
    average_speaker_similarity?: number | null;
    average_transcript_similarity?: number | null;
    average_stability: number;
    screening_ready: boolean;
    release_ready: boolean;
    warnings: string[];
  };
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface BenchmarkCaseDefinition {
  id: string;
  label: string;
  filename: string;
  prompt: string;
  audio_required: boolean;
  expected_transcript?: string | null;
}

export interface BenchmarkMetrics {
  visual_quality: number;
  temporal_stability: number;
  motion_score: number;
  subject_coverage: number;
  identity_similarity?: number | null;
  identity_frame_coverage?: number | null;
  audio_quality?: number | null;
  speaker_similarity?: number | null;
  transcript_similarity?: number | null;
  av_sync_proxy?: number | null;
  syncnet_lse_c?: number | null;
  syncnet_lse_d?: number | null;
  syncnet_offset_frames?: number | null;
  duration_seconds: number;
  analyzer_notes: string[];
}

export interface BenchmarkCaseResult {
  definition: BenchmarkCaseDefinition;
  baseline_path: string;
  lora_path: string;
  baseline: BenchmarkMetrics;
  lora: BenchmarkMetrics;
  passed: boolean;
  blocked: boolean;
  checks: Record<string, boolean | null>;
  certified_checks: Record<string, boolean | null>;
  reasons: string[];
  review_decision: "pending" | "accepted" | "rejected";
  review_note: string;
  reviewed_at?: string | null;
}

export interface BenchmarkRun {
  id: string;
  project_id: string;
  artifact_id?: string | null;
  baseline_dir: string;
  lora_dir: string;
  status: "queued" | "running" | "complete" | "failed";
  cases: Record<string, BenchmarkCaseResult>;
  summary: {
    passed_count: number;
    failed_count: number;
    blocked_count: number;
    identity_gain?: number | null;
    average_lora_identity?: number | null;
    average_lora_stability: number;
    average_lora_motion: number;
    average_speaker_similarity?: number | null;
    average_av_sync_proxy?: number | null;
    average_syncnet_lse_c?: number | null;
    average_syncnet_lse_d?: number | null;
    screening_ready: boolean;
    automated_release_ready: boolean;
    human_review_ready: boolean;
    release_ready: boolean;
    review_pending_count: number;
    review_accepted_count: number;
    review_rejected_count: number;
    validation_level: "screening" | "certified";
    warnings: string[];
  };
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface BenchmarkWorkspace {
  project_id: string;
  root: string;
  baseline_dir: string;
  lora_dir: string;
  contract_path: string;
  cases: BenchmarkCaseDefinition[];
}

export type BenchmarkGenerationStatus = "queued" | "submitting" | "in_queue" | "running" | "downloading" | "completed" | "failed";

export interface BenchmarkGenerationItem {
  id: string;
  case_id: string;
  variant: "baseline" | "lora";
  media_type?: "image" | "video";
  filename: string;
  prompt: string;
  seed: number;
  status: BenchmarkGenerationStatus;
  request_id?: string | null;
  output_path?: string | null;
  remote_url?: string | null;
  error?: string | null;
}

export interface BenchmarkGenerationRun {
  id: string;
  project_id: string;
  provider: "runcomfy_model_api" | string;
  benchmark_kind?: "audio_visual" | "image";
  endpoint_id?: string | null;
  model_id: string;
  lora_path: string;
  artifact_id?: string | null;
  workspace_root: string;
  baseline_dir: string;
  lora_dir: string;
  baseline_payload: Record<string, unknown>;
  lora_payload: Record<string, unknown>;
  seed_base: number;
  auto_evaluate: boolean;
  benchmark_run_id?: string | null;
  parent_run_id?: string | null;
  case_ids?: string[];
  evaluation_error?: string | null;
  status: BenchmarkGenerationStatus;
  items: BenchmarkGenerationItem[];
  progress_current: number;
  progress_total: number;
  progress_message: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateBenchmarkGenerationRequest {
  project_id: string;
  workspace_root: string;
  model_id: string;
  lora_path: string;
  artifact_id?: string;
  baseline_payload?: Record<string, unknown>;
  lora_payload?: Record<string, unknown>;
  seed_base?: number;
  auto_evaluate?: boolean;
  api_token?: string;
}

export interface CreateRunPodBenchmarkGenerationRequest extends Omit<CreateBenchmarkGenerationRequest, "model_id"> {
  endpoint_id: string;
  model_id?: string;
}

export interface ImageBenchmarkCaseDefinition {
  id: string;
  label: string;
  filename: string;
  prompt: string;
  composition: "face" | "upper_body" | "full_body" | "any";
}

export interface ImageBenchmarkMetrics {
  visual_quality: number;
  aesthetic_score: number;
  subject_coverage: number;
  face_count: number;
  face_area: number;
  body_coverage: number;
  pose_coverage: number;
  identity_similarity?: number | null;
  analyzer_notes: string[];
}

export interface ImageBenchmarkCaseResult {
  definition: ImageBenchmarkCaseDefinition;
  baseline_path: string;
  lora_path: string;
  baseline: ImageBenchmarkMetrics;
  lora: ImageBenchmarkMetrics;
  passed: boolean;
  blocked: boolean;
  checks: Record<string, boolean | null>;
  reasons: string[];
}

export interface ImageBenchmarkRun {
  id: string;
  project_id: string;
  artifact_id?: string | null;
  baseline_dir: string;
  lora_dir: string;
  status: "queued" | "running" | "complete" | "failed";
  cases: Record<string, ImageBenchmarkCaseResult>;
  summary: {
    passed_count: number;
    failed_count: number;
    blocked_count: number;
    identity_gain?: number | null;
    average_lora_identity?: number | null;
    average_visual_quality: number;
    average_subject_coverage: number;
    screening_ready: boolean;
    release_ready: boolean;
    warnings: string[];
  };
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface ImageBenchmarkWorkspace {
  project_id: string;
  root: string;
  baseline_dir: string;
  lora_dir: string;
  contract_path: string;
  cases: ImageBenchmarkCaseDefinition[];
}

export type RunPodModality = "image" | "video" | "voice" | "audio_visual";

export interface RunPodInfrastructureProfile {
  id: string;
  provider: "runpod";
  name: string;
  image_name: string;
  data_center_id: string;
  network_volume_id?: string | null;
  network_volume_name: string;
  network_volume_size_gb: number;
  template_id?: string | null;
  template_name: string;
  container_disk_gb: number;
  endpoint_id?: string | null;
  endpoint_name: string;
  gpu_type_ids: string[];
  workers_min: number;
  workers_max: number;
  idle_timeout_seconds: number;
  execution_timeout_ms: number;
  status: "draft" | "provisioning" | "ready" | "failed";
  progress_message: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface ProvisionRunPodInfrastructureRequest {
  profile_id?: string;
  name?: string;
  image_name: string;
  data_center_id: string;
  network_volume_id?: string;
  network_volume_name?: string;
  network_volume_size_gb?: number;
  template_id?: string;
  template_name?: string;
  container_disk_gb?: number;
  endpoint_id?: string;
  endpoint_name?: string;
  gpu_type_ids?: string[];
  workers_min?: number;
  workers_max?: number;
  idle_timeout_seconds?: number;
  execution_timeout_ms?: number;
  runtime_environment?: Record<string, string>;
  api_token?: string;
}

export interface RunPodModelBootstrapRun {
  id: string;
  provider: "runpod";
  training_target_profile_id: string;
  endpoint_id: string;
  provider_job_id?: string | null;
  status: RunPodRunStatus;
  progress_message: string;
  required_paths: string[];
  manifest_path?: string | null;
  reused: boolean;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateRunPodModelBootstrapRequest {
  endpoint_id: string;
  training_target_profile_id: string;
  api_token?: string;
}

export interface RunPodBundle {
  id: string;
  provider: "runpod";
  modality: RunPodModality;
  fingerprint: string;
  config_digest?: string;
  project_id?: string | null;
  snapshot_id?: string | null;
  source_export_path: string;
  output_path: string;
  archive_path: string;
  manifest_path: string;
  input_path: string;
  config_path: string;
  serverless_config_path: string;
  pod_template_path: string;
  pod_launcher_path: string;
  trainer_launcher_path: string;
  remote_root: string;
  remote_dataset_path: string;
  serverless_root: string;
  serverless_dataset_path: string;
  training_target_profile_id?: string | null;
  ready: boolean;
  available: boolean;
  warnings: string[];
  created_at: string;
}

export interface ProviderSmokeCheck {
  id: string;
  passed: boolean;
  detail: string;
}

export interface ProviderSmokeRun {
  id: string;
  provider: "runcomfy" | "runpod";
  modality: RunPodModality;
  training_target_profile_id: string;
  project_id?: string | null;
  source_export_path: string;
  source_fingerprint: string;
  config_file: string;
  bundle_id?: string | null;
  status: "complete" | "failed";
  ready: boolean;
  checks: ProviderSmokeCheck[];
  error?: string | null;
  created_at: string;
  completed_at: string;
}

export interface CreateRunPodBundleRequest {
  source_export_path: string;
  output_path: string;
  modality: RunPodModality;
  trigger_token: string;
  fingerprint: string;
  training_target_profile_id?: string;
  remote_root?: string;
  endpoint_id?: string;
}

export type RunPodRunStatus = "queued" | "in_queue" | "running" | "completed" | "failed" | "canceled" | "timed_out";

export interface RunPodRunArtifact {
  kind: string;
  name: string;
  remote_url?: string | null;
  volume_path?: string | null;
  local_path?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  group_id?: string | null;
}

export interface RunPodTrainingRun {
  id: string;
  provider: "runpod";
  bundle_path: string;
  bundle_fingerprint: string;
  config_digest?: string;
  modality: RunPodModality;
  training_target_profile_id: string;
  action: "train_lora" | "run_id_lora";
  endpoint_id: string;
  provider_job_id?: string | null;
  snapshot_id?: string | null;
  project_id?: string | null;
  parent_snapshot_id?: string | null;
  parent_dataset_fingerprint?: string | null;
  improvement_request_id?: string | null;
  parent_artifact_id?: string | null;
  parent_checkpoint_sha256?: string | null;
  status: RunPodRunStatus;
  progress_message: string;
  delay_time_ms?: number | null;
  execution_time_ms?: number | null;
  artifacts: RunPodRunArtifact[];
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface RunPodPreflightCheck {
  id: string;
  passed: boolean;
  detail: string;
  size_bytes?: number | null;
}

export interface RunPodPreflightReport {
  id: string;
  provider: "runpod";
  bundle_path: string;
  bundle_fingerprint: string;
  config_digest?: string;
  training_target_profile_id: string;
  endpoint_id: string;
  worker_contract_version: number;
  ready: boolean;
  volume_root: string;
  platform: string;
  python_version: string;
  gpu: {
    available: boolean;
    name: string;
    memory_gb: number;
    driver_version: string;
  };
  checks: RunPodPreflightCheck[];
  checked_at: string;
}

export interface RunPodBundleUploadJob {
  id: string;
  provider: "runpod";
  bundle_path: string;
  bundle_fingerprint: string;
  training_target_profile_id: string;
  volume_id: string;
  endpoint_url: string;
  datacenter: string;
  remote_prefix: string;
  status: "queued" | "running" | "complete" | "failed";
  files_total: number;
  files_uploaded: number;
  bytes_total: number;
  bytes_uploaded: number;
  current_file?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateRunPodBundleUploadRequest {
  bundle_path: string;
  volume_id: string;
  s3_endpoint: string;
  datacenter: string;
  access_key?: string;
  secret_key?: string;
}

export interface CreateRunPodTrainingRunRequest {
  bundle_path: string;
  endpoint_id: string;
  api_token?: string;
}

export interface CreateRunPodPreflightRequest {
  bundle_path: string;
  endpoint_id: string;
  api_token?: string;
}

export interface RunPodArtifactDownloadRequest {
  output_dir: string;
  volume_id: string;
  s3_endpoint: string;
  datacenter: string;
  access_key?: string;
  secret_key?: string;
}

export type TrainingWorkflowLaneId = "image" | "video" | "voice" | "id_lora" | "evaluate";
export type TrainingWorkflowState = "blocked" | "ready" | "working" | "complete";

export interface SyncNetCapability {
  configured: boolean;
  ready: boolean;
  mode: "custom" | "canonical" | "unconfigured";
  executable?: string | null;
  repository_path?: string | null;
  model_path?: string | null;
  problems: string[];
  setup: string[];
}

export type ProviderReadinessState = "blocked" | "dataset_ready" | "bundle_ready" | "endpoint_ready" | "running" | "outputs_ready" | "complete";

export interface ProviderReadinessItem {
  lane: "image" | "video" | "voice" | "id_lora";
  provider: "runcomfy" | "runpod";
  profile_id: string;
  state: ProviderReadinessState;
  summary: string;
  action_label: string;
  source_export_path?: string | null;
  snapshot_id?: string | null;
  bundle_id?: string | null;
  run_id?: string | null;
  endpoint_id?: string | null;
  release_artifact_id?: string | null;
  release_selected?: boolean;
  smoke_run_id?: string | null;
  smoke_ready?: boolean;
  blockers: string[];
  warnings: string[];
}

export interface ProviderReadinessMatrix {
  project_id: string;
  ready_count: number;
  total_count: number;
  items: ProviderReadinessItem[];
}

export interface PartnerQualificationCheck {
  id: string;
  label: string;
  status: "passed" | "pending" | "failed";
  detail: string;
  action?: string | null;
  evidence_ids: string[];
}

export interface PartnerQualificationLane {
  partner: "runcomfy" | "runpod" | "comfyui";
  lane: "image" | "video" | "voice" | "id_lora";
  profile_id: string;
  status: "qualified" | "in_progress" | "blocked";
  passed_count: number;
  total_count: number;
  checks: PartnerQualificationCheck[];
}

export interface PartnerQualificationReport {
  format: "lorasuite.partner-qualification.v1";
  project_id: string;
  status: "qualified" | "in_progress" | "blocked";
  passed_count: number;
  total_count: number;
  lanes: PartnerQualificationLane[];
  next_actions: string[];
  generated_at: string;
}

export type CloudFeatureSupport = "native" | "adapter" | "partial" | "unavailable";

export interface CloudProviderFeature {
  id: string;
  label: string;
  support: CloudFeatureSupport;
  detail: string;
}

export interface CloudProviderDescriptor {
  id: "runcomfy" | "runpod";
  label: string;
  contract_version: string;
  auth_environment_variables: string[];
  target_profile_ids: string[];
  modalities: RunPodModality[];
  actions: string[];
  gpu_families: string[];
  billing_models: string[];
  documentation_urls: string[];
  pricing_snapshot_date: string;
  features: CloudProviderFeature[];
  warnings: string[];
}

export type CloudRunState =
  | "queued"
  | "preparing"
  | "running"
  | "paused"
  | "retrieving"
  | "completed"
  | "failed"
  | "canceled";

export type CloudRunAction =
  | "refresh"
  | "cancel"
  | "resume"
  | "retry"
  | "download_artifacts"
  | "register_artifacts"
  | "evaluate";

export interface CloudRunRecord {
  id: string;
  provider: "runcomfy" | "runpod";
  provider_job_id?: string | null;
  project_id?: string | null;
  snapshot_id?: string | null;
  training_target_profile_id: string;
  modality?: RunPodModality | null;
  operation: "train" | "inference";
  state: CloudRunState;
  provider_status: string;
  progress: {
    current: number;
    total: number;
    percent: number;
    message: string;
  };
  dataset_fingerprint: string;
  config_digest: string;
  gpu?: string | null;
  artifact_count: number;
  local_artifact_count: number;
  checksum_artifact_count: number;
  registered_artifact_count: number;
  available_actions: CloudRunAction[];
  error?: string | null;
  failure_category?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface TrainingWorkflowLane {
  id: TrainingWorkflowLaneId;
  label: string;
  state: TrainingWorkflowState;
  phase: string;
  summary: string;
  action_label: string;
  target_mode: TrainingWorkflowLaneId;
  target_workspace: "ingest" | "curate" | "identify" | "train";
  counts: Record<string, number>;
  blockers: string[];
  warnings: string[];
}

export interface TrainingWorkflowStatus {
  project_id: string;
  project_name: string;
  recommended_lane: TrainingWorkflowLaneId;
  recommendation: string;
  complete_count: number;
  lanes: TrainingWorkflowLane[];
  updated_at: string;
}

export interface ExportPackage {
  id: string;
  export_type: string;
  output_path: string;
  manifest_path?: string | null;
  source_segment_ids: string[];
  status: string;
}

export interface PreparationCheckpoint {
  sourceItems: MediaItem[];
  breakdownJobId?: string;
  analysisJobId?: string;
  preparedItems?: MediaItem[];
  evidence?: CurationAnalysisEvidence[];
  includedIds?: string[];
  decisions?: Record<string, boolean>;
}
