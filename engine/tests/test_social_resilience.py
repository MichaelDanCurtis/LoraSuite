from email.message import Message
from urllib.error import HTTPError

from lorasuite_engine.instagram_browser import InstagramBrowserScanError
from lorasuite_engine.social_resilience import (
    error_from_http,
    error_from_subprocess,
    retry_after_seconds,
)
from lorasuite_engine.tiktok_browser import TikTokBrowserScanError
from lorasuite_engine.x_browser import XBrowserScanError


def test_http_authentication_error_is_not_retryable() -> None:
    error = HTTPError("https://instagram.com", 401, "Unauthorized", {}, None)

    classified = error_from_http(
        InstagramBrowserScanError,
        "Instagram request failed",
        error,
    )

    assert classified.category == "authentication"
    assert classified.status_code == 401
    assert classified.retryable is False


def test_http_rate_limit_honors_retry_after() -> None:
    headers = Message()
    headers["Retry-After"] = "17"
    error = HTTPError("https://instagram.com", 429, "Too Many Requests", headers, None)

    classified = error_from_http(
        InstagramBrowserScanError,
        "Instagram request failed",
        error,
    )

    assert classified.category == "rate_limited"
    assert classified.retryable is True
    assert classified.retry_after_seconds == 17


def test_subprocess_errors_are_classified_without_retrying_permanent_failures() -> None:
    authentication = error_from_subprocess(
        XBrowserScanError,
        "X scan failed",
        "ERROR: HTTP Error 403: Forbidden",
    )
    transient = error_from_subprocess(
        TikTokBrowserScanError,
        "TikTok scan failed",
        "ERROR: connection reset by peer",
    )

    assert authentication.category == "authentication"
    assert authentication.retryable is False
    assert transient.category == "transient_network"
    assert transient.retryable is True


def test_invalid_retry_after_is_ignored() -> None:
    headers = Message()
    headers["Retry-After"] = "later"

    assert retry_after_seconds(headers) is None
