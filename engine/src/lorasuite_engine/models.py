from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ExportType(StrEnum):
    RUNCOMFY_IMAGE = "runcomfy_image"
    AI_TOOLKIT_VIDEO = "ai_toolkit_video"
    VOICE_HANDOFF = "voice_handoff"


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
        if self.candidate_count == 0 and self.candidate_ids:
            self.candidate_count = len(self.candidate_ids)
        return self


class VideoBreakdownOptions(BaseModel):
    generate_frames: bool = True
    extract_audio: bool = True
    frames_per_second: int = 1
    max_frame_count: int = 6

    @field_validator("frames_per_second", "max_frame_count")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("value must be an integer")
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


class ProcessingJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("processing_job"))
    job_type: str
    source_media_item_ids: list[str] = Field(default_factory=list)
    status: ProcessingJobStatus = ProcessingJobStatus.QUEUED
    progress_message: str = "Queued"
    options: dict[str, Any] = Field(default_factory=dict)
    derived_media_items: list[MediaItem] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SegmentCreate(BaseModel):
    media_item_id: str
    start_seconds: float
    end_seconds: float
    label: str = ""
    notes: str = ""
    quality_flags: list[str] = Field(default_factory=list)
    use_for_image: bool = False
    use_for_video: bool = False
    use_for_voice: bool = False

    @field_validator("start_seconds", "end_seconds")
    @classmethod
    def seconds_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("segment seconds must be finite")
        return value

    @model_validator(mode="after")
    def range_must_be_valid(self) -> Self:
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be zero or greater")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class Segment(SegmentCreate):
    id: str = Field(default_factory=lambda: new_id("segment"))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


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
