from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from lorasuite_engine.training_targets import RecipeCompliance, TrainingTargetSpec
from lorasuite_engine.model_metadata import LoraModelCard, LoraModelCardOverrides


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceKind(StrEnum):
    LOCAL = "local"
    INSTAGRAM = "instagram"
    X_TWITTER = "x_twitter"
    TIKTOK = "tiktok"


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class CurationLane(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class CurationReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CurationRecommendation(StrEnum):
    KEEP = "keep"
    REVIEW = "review"
    REJECT = "reject"


class MediaStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    IGNORED = "ignored"
    EXPORTED = "exported"


class IngressCandidateStatus(StrEnum):
    READY = "ready"
    DUPLICATE = "duplicate"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class IngressJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELED = "canceled"


class AssetType(StrEnum):
    THUMBNAIL = "thumbnail"
    POSTER = "poster"
    FRAME = "frame"
    CLIP = "clip"
    AUDIO = "audio"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"
    MASK = "mask"


class AssetRole(StrEnum):
    SOURCE = "source"
    DERIVATIVE = "derivative"


class DerivativeType(StrEnum):
    POSTER = "poster"
    THUMBNAIL = "thumbnail"
    VIDEO_FRAME = "video_frame"
    VIDEO_CLIP = "video_clip"
    AUDIO_CLIP = "audio_clip"
    AUDIO_CLEAN = "audio_clean"
    VOICE_SEGMENT = "voice_segment"
    TRANSCRIPT = "transcript"
    CAPTION = "caption"
    FACE_CROP = "face_crop"
    PERSON_CROP = "person_crop"


class ProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELED = "canceled"


class VideoFrameDecision(StrEnum):
    CANDIDATE = "candidate"
    KEEPER = "keeper"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class VideoClipDecision(StrEnum):
    KEEP = "keep"
    REVIEW = "review"
    REJECT = "reject"


class LoraTargetType(StrEnum):
    CHARACTER = "character"
    STYLE = "style"
    CONCEPT = "concept"
    POSE = "pose"
    CLOTHING = "clothing"
    OBJECT = "object"


class RequestedOutput(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    ID_LORA = "id_lora"


class SpeakerConfirmation(StrEnum):
    ANCHOR = "anchor"
    MODEL_MATCH = "model_match"
    HUMAN_OVERRIDE = "human_override"


class DatasetReviewStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class DatasetDecisionSource(StrEnum):
    AUTOMATIC = "automatic"
    USER = "user"
    ANCHOR = "anchor"


class DatasetView(StrEnum):
    FACE = "face"
    UPPER_BODY = "upper_body"
    FULL_BODY = "full_body"
    ENVIRONMENT = "environment"
    UNKNOWN = "unknown"


class CropKind(StrEnum):
    FACE = "face"
    UPPER_BODY = "upper_body"
    FULL_BODY = "full_body"
    SQUARE = "square"


class CropRecipeStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    MATERIALIZED = "materialized"


class DatasetItemStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    EXCLUDED = "excluded"


class DatasetSnapshotStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    EXPORTED = "exported"


class CaptionSource(StrEnum):
    LOCAL_POLICY = "local_policy"
    USER = "user"
    VISION = "vision"


class VisionProviderDialect(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"
    GROK_CLI = "grok_cli"
    APPLE_FOUNDATION = "apple_foundation"


class VisionProviderAuthMode(StrEnum):
    API_KEY = "api_key"
    GROK_OAUTH = "grok_oauth"
    LOCAL = "local"


class ExportType(StrEnum):
    RUNCOMFY_IMAGE = "runcomfy_image"
    AI_TOOLKIT_VIDEO = "ai_toolkit_video"
    MINIMAX_H3_REFERENCE = "minimax_h3_reference"
    VOICE_HANDOFF = "voice_handoff"
    ID_LORA_AV = "id_lora_av"


class MediaSource(BaseModel):
    id: str = Field(default_factory=lambda: new_id("source"))
    kind: SourceKind
    source_url: str | None = None
    account_handle: str | None = None
    cookie_profile_id: str | None = None
    imported_at: datetime = Field(default_factory=utc_now)
    download_tool: str | None = None
    tool_version: str | None = None


class MediaItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("media"))
    source_id: str
    raw_path: Path
    media_type: MediaType
    sha256: str
    perceptual_hash: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    status: MediaStatus = MediaStatus.NEW


class CurationBundleItem(BaseModel):
    media_item_id: str
    lane: CurationLane
    role: str = "source"
    source_media_item_id: str | None = None
    derivative_type: str | None = None


class CurationSourceBundle(BaseModel):
    id: str
    title: str
    source_kind: SourceKind | None = None
    source_locator: str | None = None
    root_media_item_ids: list[str] = Field(default_factory=list)
    intent_lanes: list[CurationLane] = Field(default_factory=list)
    items: list[CurationBundleItem] = Field(default_factory=list)


class CurationHandoffItem(BaseModel):
    media_item_id: str
    lane: CurationLane
    project_id: str | None = None
    requested_output: RequestedOutput | None = None
    review_status: CurationReviewStatus = CurationReviewStatus.PENDING
    speaker_confirmation: SpeakerConfirmation | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class CurationHandoff(BaseModel):
    items: list[CurationHandoffItem] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class IngressCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("candidate"))
    source_kind: SourceKind
    source_locator: str
    display_name: str
    media_type: MediaType | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    thumbnail_path: Path | None = None
    poster_asset_path: Path | None = None
    status: IngressCandidateStatus = IngressCandidateStatus.READY
    error_message: str | None = None
    selected: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class IngressScanResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scan"))
    candidates: list[IngressCandidate] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class IngressJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ingress_job"))
    source_kind: SourceKind
    candidate_ids: list[str] = Field(default_factory=list)
    reviewed_candidate_ids: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    candidate_count: int = 0
    selected_count: int = 0
    imported_count: int = 0
    deferred_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    status: IngressJobStatus = IngressJobStatus.QUEUED
    progress_message: str = "Queued"
    errors: list[dict[str, str]] = Field(default_factory=list)
    deferred_candidates: list[dict[str, Any]] = Field(default_factory=list)
    imported_media_items: list[MediaItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def count_candidates(self) -> Self:
        if not self.reviewed_candidate_ids and self.candidate_ids:
            self.reviewed_candidate_ids = list(self.candidate_ids)
        if self.candidate_count == 0:
            self.candidate_count = len(self.reviewed_candidate_ids or self.candidate_ids)
        return self


class VideoBreakdownOptions(BaseModel):
    generate_frames: bool = True
    extract_audio: bool = True
    frames_per_second: int = 1
    max_frame_count: int = 6
    intelligent_selection: bool = False
    analysis_width: int = 640
    max_analysis_frame_count: int = 480

    @field_validator("frames_per_second", mode="before")
    @classmethod
    def bounded_frames_per_second(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer")
        if value <= 0:
            raise ValueError("value must be greater than zero")
        if value > 8:
            raise ValueError("frames_per_second must be 8 or lower")
        return value

    @field_validator("max_frame_count", mode="before")
    @classmethod
    def bounded_max_frame_count(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer")
        if value <= 0:
            raise ValueError("value must be greater than zero")
        if value > 600:
            raise ValueError("max_frame_count must be 600 or lower")
        return value

    @field_validator("analysis_width", mode="before")
    @classmethod
    def bounded_analysis_width(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer")
        if value < 256 or value > 1280:
            raise ValueError("analysis_width must be between 256 and 1280")
        return value

    @field_validator("max_analysis_frame_count", mode="before")
    @classmethod
    def bounded_analysis_frame_count(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer")
        if value < 12 or value > 2400:
            raise ValueError("max_analysis_frame_count must be between 12 and 2400")
        return value


class VideoFrameScores(BaseModel):
    overall: float
    sharpness: float
    exposure: float
    stability: float
    detail: float
    face_quality: float = 0.0
    face_area: float = 0.0
    body_coverage: float = 0.0
    scene_change: float = 0.0
    aesthetic: float = 0.0
    pose_coverage: float = 0.0
    diversity: float = 0.0
    face_count: int = 0
    head_yaw: float | None = None
    head_pitch: float | None = None
    head_roll: float | None = None


class VideoAnalysisFrame(BaseModel):
    id: str = Field(default_factory=lambda: new_id("analysis_frame"))
    source_media_item_id: str
    timestamp_seconds: float
    thumbnail_path: Path
    width: int
    height: int
    decision: VideoFrameDecision = VideoFrameDecision.CANDIDATE
    scores: VideoFrameScores
    reasons: list[str] = Field(default_factory=list)
    stable_range_id: str | None = None
    duplicate_cluster_id: str | None = None
    duplicate_of_frame_id: str | None = None
    output_media_item_id: str | None = None


class VideoStableRange(BaseModel):
    id: str = Field(default_factory=lambda: new_id("stable_range"))
    source_media_item_id: str
    start_seconds: float
    end_seconds: float
    scene_index: int
    frame_ids: list[str] = Field(default_factory=list)


class VideoClipScores(BaseModel):
    quality: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    identity_coverage: float = Field(ge=0.0, le=1.0)
    motion: float = Field(ge=0.0, le=1.0)
    scene_change: float = Field(ge=0.0, le=1.0)
    aesthetic: float = Field(ge=0.0, le=1.0)


class VideoClipProposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clip_proposal"))
    source_media_item_id: str
    stable_range_ids: list[str] = Field(default_factory=list)
    start_seconds: float
    end_seconds: float
    decision: VideoClipDecision = VideoClipDecision.REVIEW
    scores: VideoClipScores
    reasons: list[str] = Field(default_factory=list)
    output_media_item_id: str | None = None


class VideoClipCommit(BaseModel):
    clip_id: str
    start_seconds: float
    end_seconds: float
    decision: VideoClipDecision


class VideoBreakdownCommitRequest(BaseModel):
    frame_ids: list[str] = Field(default_factory=list)
    clips: list[VideoClipCommit] = Field(default_factory=list)


class VideoBreakdownAnalysis(BaseModel):
    source_media_item_id: str
    duration_seconds: float
    sample_fps: float
    analyzer: str
    selection_method: str = "quality-ranked-v1"
    semantic_backend: str = "none"
    requested_keeper_count: int | None = None
    frames: list[VideoAnalysisFrame] = Field(default_factory=list)
    stable_ranges: list[VideoStableRange] = Field(default_factory=list)
    clip_proposals: list[VideoClipProposal] = Field(default_factory=list)


class TrainingIntent(BaseModel):
    target_type: LoraTargetType = LoraTargetType.CHARACTER
    subject_name: str = ""
    requested_outputs: list[RequestedOutput] = Field(
        default_factory=lambda: [RequestedOutput.IMAGE]
    )
    training_target_profile_ids: dict[RequestedOutput, str] = Field(default_factory=dict)
    trigger_token: str = ""
    description: str = ""
    learned_attributes: list[str] = Field(
        default_factory=lambda: ["identity", "face", "body"]
    )
    controllable_attributes: list[str] = Field(
        default_factory=lambda: ["expression", "pose", "clothing", "environment"]
    )
    excluded_attributes: list[str] = Field(
        default_factory=lambda: ["background", "other people", "watermark"]
    )


class NormalizedPoint(BaseModel):
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def normalized_coordinate(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("normalized coordinate must be between zero and one")
        return value


class NormalizedRect(BaseModel):
    x: float
    y: float
    width: float
    height: float

    @model_validator(mode="after")
    def valid_normalized_rect(self) -> Self:
        if self.x < 0.0 or self.y < 0.0:
            raise ValueError("crop origin must be zero or greater")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("crop dimensions must be greater than zero")
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("crop rectangle must remain inside the image")
        return self


class IdentityFace(BaseModel):
    index: int
    confidence: float
    bounding_box: NormalizedRect
    landmarks: list[NormalizedPoint] = Field(default_factory=list)
    anchor_similarity: float | None = None
    selected: bool = False


class CropRecipe(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crop_recipe"))
    media_item_id: str
    kind: CropKind
    rect: NormalizedRect
    aspect_ratio: str
    face_index: int | None = None
    status: CropRecipeStatus = CropRecipeStatus.PROPOSED
    output_media_item_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IdentityRuntimeStatus(BaseModel):
    backend: str = "opencv-sface"
    model_version: str = "opencv-sface-2021dec-yunet-2023mar"
    installed: bool = False
    ready: bool = False
    download_size_bytes: int = 0
    message: str = "Identity models are not installed"


class DatasetObservation(BaseModel):
    media_item_id: str
    review_status: DatasetReviewStatus = DatasetReviewStatus.NEEDS_REVIEW
    decision_source: DatasetDecisionSource = DatasetDecisionSource.AUTOMATIC
    view: DatasetView = DatasetView.UNKNOWN
    is_anchor: bool = False
    quality_score: float = 0.0
    diversity_score: float = 0.0
    identity_score: float | None = None
    face_count: int = 0
    face_area: float = 0.0
    body_coverage: float = 0.0
    aesthetic_score: float = 0.0
    head_yaw: float | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analyzer: str = "pending"
    identity_backend: str = "unavailable"
    selected_face_index: int | None = None
    faces: list[IdentityFace] = Field(default_factory=list)
    crop_recipe_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class DatasetHealth(BaseModel):
    candidate_count: int = 0
    accepted_count: int = 0
    review_count: int = 0
    rejected_count: int = 0
    anchor_count: int = 0
    effective_observation_count: float = 0.0
    source_count: int = 0
    largest_source_share: float = 0.0
    average_quality: float = 0.0
    average_diversity: float = 0.0
    view_counts: dict[str, int] = Field(default_factory=dict)
    analyzer: str = "pending"
    warnings: list[str] = Field(default_factory=list)


class CharacterProject(BaseModel):
    id: str = Field(default_factory=lambda: new_id("character_project"))
    name: str = "Character Dataset"
    intent: TrainingIntent = Field(default_factory=TrainingIntent)
    candidate_media_item_ids: list[str] = Field(default_factory=list)
    observations: dict[str, DatasetObservation] = Field(default_factory=dict)
    crop_recipes: dict[str, CropRecipe] = Field(default_factory=dict)
    health: DatasetHealth = Field(default_factory=DatasetHealth)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VisionCaptionEvidence(BaseModel):
    expression: str = "unknown"
    pose: str = "unknown"
    clothing: str = "unknown"
    environment: str = "unknown"
    camera: str = "unknown"
    lighting: str = "unknown"
    visual_style: str = "unknown"
    other_people: str = "none"
    watermark: str = "none"
    content: str = "general"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DatasetCaptionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dataset_item"))
    source_media_item_id: str
    training_media_item_id: str
    crop_recipe_id: str | None = None
    caption: str
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    unresolved_attributes: list[str] = Field(default_factory=list)
    status: DatasetItemStatus = DatasetItemStatus.NEEDS_REVIEW
    caption_source: CaptionSource = CaptionSource.LOCAL_POLICY
    caption_provider: str | None = None
    caption_model: str | None = None
    caption_confidence: float | None = None
    vision_evidence: VisionCaptionEvidence | None = None
    strongest_set_excluded: bool = False
    strongest_set_rank: int | None = None
    strongest_set_score: float | None = None
    strongest_set_reasons: list[str] = Field(default_factory=list)
    view: DatasetView = DatasetView.UNKNOWN
    quality_score: float = 0.0
    diversity_score: float = 0.0
    identity_score: float | None = None
    is_anchor: bool = False
    source_id: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DatasetBalance(BaseModel):
    total_count: int = 0
    approved_count: int = 0
    review_count: int = 0
    excluded_count: int = 0
    source_count: int = 0
    cropped_count: int = 0
    average_quality: float = 0.0
    average_diversity: float = 0.0
    view_counts: dict[str, int] = Field(default_factory=dict)
    crop_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    recipe_compliance: RecipeCompliance | None = None


class StrongestSetCandidate(BaseModel):
    item_id: str
    score: float = Field(ge=0.0)
    reasons: list[str] = Field(default_factory=list)
    group: DatasetView = DatasetView.UNKNOWN


class DatasetStrongestSetProposal(BaseModel):
    snapshot_id: str
    target_count: int
    selected_count: int
    excluded_count: int
    already_excluded_count: int = 0
    recipe_minimum: int
    recipe_recommended: int
    recipe_maximum: int
    selected: list[StrongestSetCandidate] = Field(default_factory=list)
    excluded_item_ids: list[str] = Field(default_factory=list)
    view_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    average_quality: float = 0.0
    average_diversity: float = 0.0
    average_identity: float | None = None
    warnings: list[str] = Field(default_factory=list)


class DatasetDuplicateCandidate(BaseModel):
    item_id: str
    training_media_item_id: str
    hash_distance: int = Field(ge=0)
    score: float = Field(ge=0.0)
    group: DatasetView = DatasetView.UNKNOWN
    is_recommended_keep: bool = False


class DatasetDuplicateCluster(BaseModel):
    id: str
    recommended_keep_item_id: str
    candidates: list[DatasetDuplicateCandidate] = Field(default_factory=list)


class DatasetDuplicateProposal(BaseModel):
    snapshot_id: str
    scanned_count: int
    duplicate_count: int
    unreadable_count: int = 0
    clusters: list[DatasetDuplicateCluster] = Field(default_factory=list)


class DatasetSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dataset_snapshot"))
    project_id: str
    project_name: str
    version: int = Field(default=1, ge=1)
    status: DatasetSnapshotStatus = DatasetSnapshotStatus.DRAFT
    intent: TrainingIntent = Field(default_factory=TrainingIntent)
    training_target: TrainingTargetSpec = Field(default_factory=TrainingTargetSpec)
    items: dict[str, DatasetCaptionRecord] = Field(default_factory=dict)
    balance: DatasetBalance = Field(default_factory=DatasetBalance)
    model_card_overrides: LoraModelCardOverrides = Field(
        default_factory=LoraModelCardOverrides
    )
    model_card: LoraModelCard | None = None
    fingerprint: str | None = None
    export_package_id: str | None = None
    export_path: Path | None = None
    parent_snapshot_id: str | None = None
    parent_fingerprint: str | None = None
    improvement_request_id: str | None = None
    source_artifact_id: str | None = None
    source_checkpoint_sha256: str | None = None
    revision_plan: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    frozen_at: datetime | None = None


class VisionProviderPreset(BaseModel):
    id: str
    label: str
    dialect: VisionProviderDialect
    auth_mode: VisionProviderAuthMode = VisionProviderAuthMode.API_KEY
    base_url: str
    model: str
    configured: bool = False


class CaptionGenerationJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("caption_job"))
    snapshot_id: str
    item_ids: list[str] = Field(default_factory=list)
    provider_id: str
    provider_label: str
    model: str
    provider_dialect: VisionProviderDialect | None = None
    provider_base_url: str | None = None
    provider_auth_mode: VisionProviderAuthMode | None = None
    status: ProcessingJobStatus = ProcessingJobStatus.QUEUED
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    next_item_index: int = Field(default=0, ge=0)
    progress_message: str = "Queued"
    errors: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CurationAnalysisEvidence(BaseModel):
    media_item_id: str
    media_type: MediaType
    recommendation: CurationRecommendation
    confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    face_count: int | None = Field(default=None, ge=0)
    face_area: float | None = Field(default=None, ge=0.0, le=1.0)
    body_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    pose_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    aesthetic_score: float | None = Field(default=None, ge=0.0, le=1.0)
    head_yaw: float | None = None
    head_pitch: float | None = None
    head_roll: float | None = None
    sample_count: int | None = Field(default=None, ge=0)
    active_audio_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    clipping_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    transcript: str | None = None
    language: str | None = None
    speech_duration_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    transcript_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    word_count: int | None = Field(default=None, ge=0)
    speaker_count: int | None = Field(default=None, ge=0)
    speaker_duration_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analyzer: str
    analyzed_at: datetime = Field(default_factory=utc_now)


class AudioCleaningRecipe(BaseModel):
    media_item_id: str
    high_pass_hz: int = Field(default=80, ge=20, le=500)
    low_pass_hz: int = Field(default=14000, ge=3000, le=22000)
    noise_floor_db: int = Field(default=-55, ge=-80, le=-20)
    noise_reduction_db: int = Field(default=6, ge=0, le=30)
    gate_threshold_db: int = Field(default=-55, ge=-80, le=-20)
    presence_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0)
    normalize: bool = True
    isolate_voice: bool = False
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_frequency_range(self) -> Self:
        if self.high_pass_hz >= self.low_pass_hz:
            raise ValueError("high-pass frequency must be below low-pass frequency")
        return self


class AudioCleaningBatchOptions(BaseModel):
    force_voice_isolation: bool = False


class AudioCleaningResult(BaseModel):
    recipe: AudioCleaningRecipe
    preview_path: Path
    recipe_digest: str
    separation_available: bool = False
    isolation_applied: bool = False
    warnings: list[str] = Field(default_factory=list)
    rendered_media_item: MediaItem | None = None


class AudioSeparationRuntimeStatus(BaseModel):
    backend: str = "audio-separator-uvr-mdx"
    model_name: str
    model_sha256: str
    download_size_bytes: int = 0
    runtime_installed: bool = False
    model_installed: bool = False
    ready: bool = False
    message: str


class VoiceIdentityEvidence(BaseModel):
    media_item_id: str
    similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    recommendation: CurationRecommendation = CurationRecommendation.REVIEW
    is_anchor: bool = False
    anchor_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    backend: str = "sherpa-onnx-wespeaker-campp"
    analyzed_at: datetime = Field(default_factory=utc_now)


class VoiceIdentityProfile(BaseModel):
    project_id: str
    anchor_media_item_ids: list[str] = Field(default_factory=list)
    evidence: dict[str, VoiceIdentityEvidence] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class VoiceSegmentStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class VoiceExportTarget(StrEnum):
    VOICE_CLONING = "voice_cloning"
    AV_LORA = "av_lora"
    BOTH = "both"


class VoiceSegmentQualityEvidence(BaseModel):
    quality_score: float = Field(ge=0.0, le=1.0)
    recommendation: CurationRecommendation
    active_audio_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    silence_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    clipping_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    noise_floor_db: float | None = Field(default=None, le=0.0)
    snr_db: float | None = Field(default=None, ge=0.0)
    dynamic_range_db: float | None = Field(default=None, ge=0.0)
    reverb_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    background_music_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    speaker_count: int | None = Field(default=None, ge=0)
    source_classification: str = "unverified_voice"
    voice_isolation_applied: bool = False
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analyzer: str = "portable-voice-quality-v1"
    analyzed_at: datetime = Field(default_factory=utc_now)


class VoiceDatasetSegment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("voice_segment"))
    project_id: str
    source_media_item_id: str
    media_item_id: str
    audio_path: Path
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    transcript: str
    language: str | None = None
    transcript_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    speaker_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    identity_recommendation: CurationRecommendation = CurationRecommendation.REVIEW
    identity_reasons: list[str] = Field(default_factory=list)
    identity_warnings: list[str] = Field(default_factory=list)
    quality: VoiceSegmentQualityEvidence | None = None
    recommendation: CurationRecommendation = CurationRecommendation.REVIEW
    status: VoiceSegmentStatus = VoiceSegmentStatus.NEEDS_REVIEW
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("voice segment end must be after its start")
        return self


class VoiceDatasetBalance(BaseModel):
    total_count: int = 0
    approved_count: int = 0
    review_count: int = 0
    rejected_count: int = 0
    source_count: int = 0
    total_duration_seconds: float = 0.0
    average_quality: float = 0.0
    average_speaker_similarity: float = 0.0
    average_transcript_confidence: float = 0.0
    average_active_audio_ratio: float = 0.0
    average_silence_ratio: float = 0.0
    average_clipping_ratio: float = 0.0
    average_background_music_risk: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    recipe_compliance: RecipeCompliance | None = None


class VoiceDatasetCompilation(BaseModel):
    project_id: str
    source_media_item_ids: list[str] = Field(default_factory=list)
    segments: dict[str, VoiceDatasetSegment] = Field(default_factory=dict)
    target_profile_id: str = "runpod_fish_speech_s2_voice_lora"
    target_label: str = "Fish Speech S2 Voice LoRA"
    balance: VoiceDatasetBalance = Field(default_factory=VoiceDatasetBalance)
    dataset_fingerprint: str | None = None
    export_path: Path | None = None
    export_target: VoiceExportTarget | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class ProcessingJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("processing_job"))
    job_type: str
    source_media_item_ids: list[str] = Field(default_factory=list)
    status: ProcessingJobStatus = ProcessingJobStatus.QUEUED
    progress_message: str = "Queued"
    options: dict[str, Any] = Field(default_factory=dict)
    derived_media_items: list[MediaItem] = Field(default_factory=list)
    video_analyses: list[VideoBreakdownAnalysis] = Field(default_factory=list)
    curation_analyses: list[CurationAnalysisEvidence] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None






class DerivedAsset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asset"))
    media_item_id: str
    segment_id: str | None = None
    asset_type: AssetType
    path: Path
    sha256: str
    generation_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ExportPackage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("export"))
    export_type: ExportType
    output_path: Path
    created_at: datetime = Field(default_factory=utc_now)
    preset_json: dict[str, Any] = Field(default_factory=dict)
    manifest_path: Path | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    status: str = "created"
