from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from lorasuite_engine.models import MediaType, SourceKind


def canonical_source_identity(
    source_kind: SourceKind,
    metadata: dict[str, Any],
    source_locator: str,
) -> str:
    explicit = _string(metadata.get("canonical_source_id"))
    if explicit:
        return explicit

    source_url = _string(metadata.get("source_url")) or source_locator
    provider_identity = _provider_source_identity(source_kind, source_url)
    if provider_identity:
        return provider_identity

    platform_media_id = _normalized_platform_media_id(
        source_kind,
        _string(metadata.get("platform_media_id")),
        source_level=True,
    )
    if platform_media_id:
        return platform_media_id

    if source_kind == SourceKind.LOCAL:
        return str(Path(source_locator).expanduser().resolve())
    return normalized_source_url(source_url) or source_locator


def canonical_asset_identity(
    source_kind: SourceKind,
    metadata: dict[str, Any],
    source_locator: str,
) -> str:
    explicit = _string(metadata.get("canonical_asset_id"))
    if explicit:
        return explicit

    platform_media_id = _normalized_platform_media_id(
        source_kind,
        _string(metadata.get("platform_media_id")),
        source_level=False,
    )
    if platform_media_id:
        return platform_media_id

    download_url = _string(metadata.get("download_url"))
    if download_url:
        return normalized_source_url(download_url)
    if source_kind == SourceKind.LOCAL:
        return str(Path(source_locator).expanduser().resolve())
    return normalized_source_url(source_locator) or source_locator


def candidate_asset_role(
    metadata: dict[str, Any],
    media_type: MediaType | None,
) -> str:
    return _string(metadata.get("asset_role")) or (
        media_type.value if media_type is not None else "unknown"
    )


def canonical_candidate_key(
    source_kind: SourceKind,
    metadata: dict[str, Any],
    source_locator: str,
    media_type: MediaType | None,
) -> str:
    source_id = canonical_source_identity(source_kind, metadata, source_locator)
    asset_id = canonical_asset_identity(source_kind, metadata, source_locator)
    role = candidate_asset_role(metadata, media_type)
    return f"{source_kind.value}:{source_id}:{asset_id}:{role}"


def deterministic_candidate_id(
    source_kind: SourceKind,
    metadata: dict[str, Any],
    source_locator: str,
    media_type: MediaType | None,
) -> str:
    key = canonical_candidate_key(source_kind, metadata, source_locator, media_type)
    return f"candidate_{sha256(key.encode('utf-8')).hexdigest()[:32]}"


def canonical_identity_metadata(
    source_kind: SourceKind,
    metadata: dict[str, Any],
    source_locator: str,
    media_type: MediaType | None,
) -> dict[str, Any]:
    source_id = canonical_source_identity(source_kind, metadata, source_locator)
    asset_id = canonical_asset_identity(source_kind, metadata, source_locator)
    role = candidate_asset_role(metadata, media_type)
    candidate_key = f"{source_kind.value}:{source_id}:{asset_id}:{role}"
    return {
        "canonical_source_id": source_id,
        "canonical_asset_id": asset_id,
        "canonical_candidate_key": candidate_key,
        "source_bundle_key": f"{source_kind.value}:{source_id}",
    }


def normalized_source_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(("https", f"{hostname}{port}", path, "", urlencode(sorted(query)), ""))


def _provider_source_identity(source_kind: SourceKind, source_url: str) -> str | None:
    normalized = normalized_source_url(source_url)
    try:
        parsed = urlparse(normalized)
    except ValueError:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if source_kind == SourceKind.INSTAGRAM:
        for index, part in enumerate(parts[:-1]):
            if part.lower() in {"p", "reel", "tv"}:
                return f"post:{parts[index + 1].lower()}"
    elif source_kind == SourceKind.X_TWITTER:
        for index, part in enumerate(parts[:-1]):
            if part.lower() == "status":
                return f"post:{parts[index + 1]}"
    elif source_kind == SourceKind.TIKTOK:
        for index, part in enumerate(parts[:-1]):
            if part.lower() == "video":
                return f"post:{parts[index + 1]}"
    return None


def _normalized_platform_media_id(
    source_kind: SourceKind,
    value: str | None,
    *,
    source_level: bool,
) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if source_kind == SourceKind.INSTAGRAM:
        base_id = normalized.split("_", maxsplit=1)[0]
        if base_id.isdigit():
            normalized = base_id
    if source_kind == SourceKind.TIKTOK and normalized.startswith("tiktok_"):
        normalized = normalized.removeprefix("tiktok_")
    return f"asset:{normalized}" if not source_level else f"post:{normalized}"


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
