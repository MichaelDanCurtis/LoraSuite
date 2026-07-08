import shutil
from base64 import b64decode
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lorasuite_engine.models import (
    IngressCandidate,
    IngressCandidateStatus,
    IngressScanResult,
    MediaType,
    SourceKind,
)

TOKEN_LIKE_KEYS = frozenset(
    {"authorization", "cookie", "cookies", "csrf", "session", "token", "x-csrftoken"}
)
DATA_URL_IMAGE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}


def scan_instagram_helper_payload(
    payload: dict[str, Any],
    vault_root: Path,
    *,
    include_video_posters_as_image_candidates: bool = True,
) -> IngressScanResult:
    reject_token_like_fields(payload)
    result = IngressScanResult()
    helper_version = str(payload.get("helper_version") or "unknown")

    for item in payload.get("media", []):
        candidate = _candidate_from_item(item, Path(vault_root), helper_version)
        result.candidates.append(candidate)
        if (
            include_video_posters_as_image_candidates
            and candidate.media_type == MediaType.VIDEO
            and candidate.poster_asset_path is not None
        ):
            result.candidates.append(_poster_candidate(candidate))

    return result


def reject_token_like_fields(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in TOKEN_LIKE_KEYS or any(
                token_key in normalized_key for token_key in TOKEN_LIKE_KEYS
            ):
                raise ValueError(f"token-like field is not accepted: {path}.{key}")
            reject_token_like_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_token_like_fields(child, path=f"{path}[{index}]")


def _candidate_from_item(
    item: Mapping[str, Any],
    vault_root: Path,
    helper_version: str,
) -> IngressCandidate:
    media_id = str(item["id"])
    media_type = MediaType(str(item["media_type"]))
    poster_path = _cache_preview_asset(item, vault_root, media_id)
    source_url = str(item.get("source_url") or "")

    return IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator=source_url or media_id,
        display_name=str(item.get("display_name") or media_id),
        media_type=media_type,
        width=_optional_int(item.get("width")),
        height=_optional_int(item.get("height")),
        duration=_optional_float(item.get("duration")),
        thumbnail_path=poster_path,
        poster_asset_path=poster_path if media_type == MediaType.VIDEO else None,
        status=IngressCandidateStatus.READY,
        selected=media_type == MediaType.IMAGE,
        metadata_json={
            "platform_media_id": media_id,
            "source_url": source_url,
            "helper_version": helper_version,
            "download_url": item.get("download_url"),
            "poster_source_path": item.get("poster_path") or item.get("thumbnail_path"),
            "poster_source_url": item.get("poster_url") or item.get("thumbnail_url"),
            "browser_source": item.get("browser_source"),
            "extractor": item.get("extractor"),
        },
    )


def _poster_candidate(video_candidate: IngressCandidate) -> IngressCandidate:
    poster_path = video_candidate.poster_asset_path
    return IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator=str(poster_path),
        display_name=f"{video_candidate.display_name} poster",
        media_type=MediaType.IMAGE,
        width=video_candidate.width,
        height=video_candidate.height,
        thumbnail_path=poster_path,
        status=IngressCandidateStatus.READY,
        selected=True,
        metadata_json={
            **video_candidate.metadata_json,
            "source_video_candidate_id": video_candidate.id,
            "local_import_path": str(poster_path),
            "asset_role": "video_poster",
        },
    )


def _cache_preview_asset(
    item: Mapping[str, Any],
    vault_root: Path,
    media_id: str,
) -> Path | None:
    data_url_path = _cache_data_url_preview_asset(item, vault_root, media_id)
    if data_url_path is not None:
        return data_url_path

    raw_path = item.get("poster_path") or item.get("thumbnail_path")
    if not raw_path:
        return None

    source_path = Path(str(raw_path))
    if not source_path.exists() or not source_path.is_file():
        return None

    previews_dir = vault_root / "previews" / "social"
    previews_dir.mkdir(parents=True, exist_ok=True)
    target = previews_dir / f"{media_id}{source_path.suffix.lower()}"
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return target


def _cache_data_url_preview_asset(
    item: Mapping[str, Any],
    vault_root: Path,
    media_id: str,
) -> Path | None:
    raw_data_url = item.get("poster_data_url") or item.get("thumbnail_data_url")
    if not raw_data_url:
        return None

    data_url = str(raw_data_url)
    header, separator, encoded = data_url.partition(",")
    if not separator:
        return None

    mime_type = header.removeprefix("data:").split(";", maxsplit=1)[0].lower()
    suffix = DATA_URL_IMAGE_SUFFIXES.get(mime_type)
    if suffix is None or ";base64" not in header.lower():
        return None

    preview_bytes = b64decode(encoded, validate=True)
    previews_dir = vault_root / "previews" / "social"
    previews_dir.mkdir(parents=True, exist_ok=True)
    target = previews_dir / f"{media_id}{suffix}"
    target.write_bytes(preview_bytes)
    return target


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
