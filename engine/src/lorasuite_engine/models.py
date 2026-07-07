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


class AssetType(StrEnum):
    FRAME = "frame"
    CLIP = "clip"
    AUDIO = "audio"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"
    MASK = "mask"


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
