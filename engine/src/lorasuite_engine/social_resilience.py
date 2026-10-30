from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar
from urllib.error import HTTPError, URLError


class SocialProviderError(RuntimeError):
    provider = "social"

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider",
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds

    def detail(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "category": self.category,
            "message": str(self),
            "status_code": self.status_code,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
        }


SocialErrorT = TypeVar("SocialErrorT", bound=SocialProviderError)


def error_from_http(
    error_type: type[SocialErrorT],
    prefix: str,
    error: HTTPError,
) -> SocialErrorT:
    status_code = int(error.code)
    category, retryable = classify_http_status(status_code)
    retry_after = retry_after_seconds(getattr(error, "headers", None))
    return error_type(
        f"{prefix} with HTTP {status_code}.",
        category=category,
        status_code=status_code,
        retryable=retryable,
        retry_after_seconds=retry_after,
    )


def error_from_url(
    error_type: type[SocialErrorT],
    prefix: str,
    error: URLError | OSError,
) -> SocialErrorT:
    reason = getattr(error, "reason", None) or str(error)
    return error_type(
        f"{prefix}: {reason}.",
        category="transient_network",
        retryable=True,
    )


def error_from_subprocess(
    error_type: type[SocialErrorT],
    prefix: str,
    detail: str,
) -> SocialErrorT:
    status_code = _status_code_from_text(detail)
    lowered = detail.lower()
    retry_after = _retry_after_from_text(detail)

    if status_code is not None:
        category, retryable = classify_http_status(status_code)
    elif any(token in lowered for token in _AUTH_TOKENS):
        category, retryable = "authentication", False
    elif any(token in lowered for token in _RATE_LIMIT_TOKENS):
        category, retryable = "rate_limited", True
    elif any(token in lowered for token in _TRANSIENT_TOKENS):
        category, retryable = "transient_network", True
    else:
        category, retryable = "provider", False

    return error_type(
        f"{prefix}: {detail}",
        category=category,
        status_code=status_code,
        retryable=retryable,
        retry_after_seconds=retry_after,
    )


def classify_http_status(status_code: int) -> tuple[str, bool]:
    if status_code in {401, 403}:
        return "authentication", False
    if status_code == 429:
        return "rate_limited", True
    if status_code in {408, 425, 500, 502, 503, 504}:
        return "transient_network", True
    return "provider", False


def retry_after_seconds(
    headers: Any,
    *,
    now: datetime | None = None,
) -> float | None:
    if headers is None:
        return None
    raw_value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())


_HTTP_STATUS_PATTERN = re.compile(r"(?:http(?: error)?|status(?: code)?)\D{0,8}(\d{3})", re.I)
_RETRY_AFTER_PATTERN = re.compile(r"retry[- ]after\D{0,8}(\d+(?:\.\d+)?)", re.I)
_AUTH_TOKENS = (
    "login required",
    "log in",
    "not logged in",
    "authentication",
    "unauthorized",
    "forbidden",
    "cookies are no longer valid",
    "cookie is no longer valid",
)
_RATE_LIMIT_TOKENS = (
    "too many requests",
    "rate limit",
    "rate-limit",
    "throttled",
)
_TRANSIENT_TOKENS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "connection refused",
    "remote end closed",
    "network is unreachable",
    "name or service not known",
    "try again",
)


def _status_code_from_text(detail: str) -> int | None:
    match = _HTTP_STATUS_PATTERN.search(detail)
    return int(match.group(1)) if match else None


def _retry_after_from_text(detail: str) -> float | None:
    match = _RETRY_AFTER_PATTERN.search(detail)
    return float(match.group(1)) if match else None
