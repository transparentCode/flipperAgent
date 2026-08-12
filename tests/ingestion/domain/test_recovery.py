from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest

LANE = MarketLane("binance", "BTC-USDT-PERP", "2h")
SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = datetime(2026, 1, 1, 1, tzinfo=UTC)


def _request(**changes: object) -> RecoveryRequest:
    values: dict[str, object] = {
        "lane": LANE,
        "since": SINCE,
        "until": UNTIL,
        "reason": "startup gap",
    }
    values.update(changes)
    return RecoveryRequest(**values)  # type: ignore[arg-type]


def test_valid_recovery_request_uses_half_open_bounds() -> None:
    request = _request(reason="manual review")

    assert request.since < request.until
    assert request.reason == "manual review"


def test_recovery_request_is_immutable() -> None:
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.reason = "other"  # type: ignore[misc]


def test_recovery_request_requires_market_lane() -> None:
    with pytest.raises(TypeError, match="lane must be a MarketLane"):
        _request(lane=object())


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("since", datetime(2026, 1, 1)),  # noqa: DTZ001
        ("until", datetime(2026, 1, 1, 1)),  # noqa: DTZ001
        (
            "since",
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        ),
    ],
)
def test_recovery_request_requires_utc_bounds(
    field_name: str,
    invalid_value: datetime,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        _request(**{field_name: invalid_value})


@pytest.mark.parametrize("until", [SINCE, datetime(2025, 12, 31, tzinfo=UTC)])
def test_recovery_request_requires_positive_range(until: datetime) -> None:
    with pytest.raises(ValueError, match="until must be after since"):
        _request(until=until)


@pytest.mark.parametrize("reason", ["", " ", "\t"])
def test_recovery_request_rejects_blank_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="reason must be non-empty"):
        _request(reason=reason)
