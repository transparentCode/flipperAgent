"""Stable error codes shared by the adapter, gate and store."""

from __future__ import annotations

CONNECT_FAILED = "connect_failed"
TIMEOUT = "timeout"
SYMBOL_ERROR = "symbol_error"
SERIES_ERROR = "series_error"
PROTOCOL_ERROR = "protocol_error"
OVERSIZE = "oversize"
INCOMPLETE = "incomplete"
IDENTITY_MISMATCH = "identity_mismatch"
EMPTY = "empty"
SHAPE_MISMATCH = "shape_mismatch"
FUTURE_BAR = "future_bar"
DOMAIN_VIOLATION = "domain_violation"
STORAGE_ERROR = "storage_error"
ENGINE_UNREACHABLE = "engine_unreachable"
ENGINE_ERROR = "engine_error"
NAVIGATION_FAILED = "navigation_failed"
HELPER_MISSING = "helper_missing"
HELPER_TIMEOUT = "helper_timeout"
PROVIDER_REFUSED = "provider_refused"
NOT_AUTHORIZED = "not_authorized"
PAYLOAD_TOO_LARGE = "payload_too_large"
PAYLOAD_INVALID = "payload_invalid"
STALE_PAYLOAD = "stale_payload"
COIN_MISSING = "coin_missing"
CYCLE_DEADLINE = "cycle_deadline"

ERROR_CODES = frozenset(
    {
        CONNECT_FAILED,
        TIMEOUT,
        SYMBOL_ERROR,
        SERIES_ERROR,
        PROTOCOL_ERROR,
        OVERSIZE,
        INCOMPLETE,
        IDENTITY_MISMATCH,
        EMPTY,
        SHAPE_MISMATCH,
        FUTURE_BAR,
        DOMAIN_VIOLATION,
        STORAGE_ERROR,
        ENGINE_UNREACHABLE,
        ENGINE_ERROR,
        NAVIGATION_FAILED,
        HELPER_MISSING,
        HELPER_TIMEOUT,
        PROVIDER_REFUSED,
        NOT_AUTHORIZED,
        PAYLOAD_TOO_LARGE,
        PAYLOAD_INVALID,
        STALE_PAYLOAD,
        COIN_MISSING,
        CYCLE_DEADLINE,
    }
)


class ScraperError(Exception):
    """A read failed for a reason that is recorded in ``reads.error_code``."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown scraper error code: {code}")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


__all__ = ["ERROR_CODES", "ScraperError"]
