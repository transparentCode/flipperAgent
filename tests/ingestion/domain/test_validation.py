from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from apps.ingestion_app.domain.validation import require_non_empty_string, require_utc


@pytest.mark.parametrize(
    ("validator", "value", "field_name", "error", "message"),
    [
        (
            require_non_empty_string,
            1,
            "symbol",
            TypeError,
            "symbol must be a string",
        ),
        (
            require_non_empty_string,
            " \t ",
            "symbol",
            ValueError,
            "symbol must be non-empty",
        ),
        (
            require_utc,
            "2026-01-01",
            "timestamp",
            TypeError,
            "timestamp must be a datetime",
        ),
        (
            require_utc,
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            "timestamp",
            ValueError,
            "timestamp must be timezone-aware UTC",
        ),
    ],
)
def test_shared_validators_preserve_exact_error_contract(
    validator: Callable[..., object],
    value: object,
    field_name: str,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=f"^{message}$"):
        validator(value, field_name=field_name)


def test_shared_validators_return_original_values_unchanged() -> None:
    text = "  BTCUSDT  "
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)

    assert require_non_empty_string(text, field_name="symbol") is text
    assert require_utc(timestamp, field_name="timestamp") is timestamp
