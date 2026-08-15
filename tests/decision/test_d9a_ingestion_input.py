from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.transport.ingestion import (
    CanonicalIngestionEventError,
    canonical_ingestion_stream_key,
    parse_canonical_ingestion_event,
)

BASE = datetime(2026, 1, 5, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)
SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)


def _event_fields(*, producer: str = "ingestion", bar_index: int = 0) -> dict[str, str]:
    opened = BASE + timedelta(hours=bar_index)
    closed = opened + timedelta(hours=1)
    payload = {
        "venue": SERIES.venue,
        "instrument_id": SERIES.instrument_id,
        "timeframe": SERIES.timeframe,
        "open_time": opened.isoformat().replace("+00:00", "Z"),
        "close_time": closed.isoformat().replace("+00:00", "Z"),
        "open": "100.0",
        "high": "103.0",
        "low": "99.0",
        "close": "102.0",
        "volume": "10.25",
        "taker_buy_base": "4.5",
        "source_type": "provider",
        "source_provider": "binance_native",
        "source_timeframe": None,
    }
    return {
        "event_id": f"event-{bar_index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": producer,
        "occurred_at": closed.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }


def test_parser_preserves_canonical_decimal_values_and_identity() -> None:
    stream = canonical_ingestion_stream_key(SERIES)
    parsed = parse_canonical_ingestion_event(
        stream_key=stream,
        stream_id="42-0",
        fields=_event_fields(),
        expected_series=SERIES,
        timeframe_grid=GRID,
    )

    assert parsed.event_id == "event-0"
    assert parsed.series_key == SERIES
    assert parsed.bar.market_as_of == BASE + timedelta(hours=1)
    assert parsed.bar.open == Decimal("100.0")
    assert parsed.bar.volume == Decimal("10.25")
    assert parsed.bar.taker_buy_base == Decimal("4.5")
    assert parsed.bar.closed is True


def test_parser_accepts_canonical_derived_source_metadata() -> None:
    fields = _event_fields()
    payload = json.loads(fields["payload"])
    payload["source_type"] = "derived"
    payload["source_provider"] = None
    payload["source_timeframe"] = "1m"
    fields["payload"] = json.dumps(payload)

    parsed = parse_canonical_ingestion_event(
        stream_key=canonical_ingestion_stream_key(SERIES),
        stream_id="42-0",
        fields=fields,
        expected_series=SERIES,
        timeframe_grid=GRID,
    )

    assert parsed.source_type == "derived"
    assert parsed.source_provider is None
    assert parsed.source_timeframe == "1m"


@pytest.mark.parametrize(
    ("source_type", "source_provider", "source_timeframe"),
    [
        ("provider", None, None),
        ("provider", "binance_native", "1m"),
        ("derived", "binance_native", "1m"),
        ("derived", None, None),
        ("unknown", "binance_native", None),
    ],
)
def test_parser_rejects_malformed_canonical_provenance(
    source_type: str,
    source_provider: str | None,
    source_timeframe: str | None,
) -> None:
    fields = _event_fields()
    payload = json.loads(fields["payload"])
    payload["source_type"] = source_type
    payload["source_provider"] = source_provider
    payload["source_timeframe"] = source_timeframe
    fields["payload"] = json.dumps(payload)

    with pytest.raises(CanonicalIngestionEventError, match="source"):
        parse_canonical_ingestion_event(
            stream_key=canonical_ingestion_stream_key(SERIES),
            stream_id="42-0",
            fields=fields,
            expected_series=SERIES,
            timeframe_grid=GRID,
        )


@pytest.mark.parametrize(
    ("source_type", "source_provider", "source_timeframe"),
    [
        ("provider", "binance_native", None),
        ("derived", None, "1m"),
    ],
)
def test_parser_matches_canonical_ingestion_event_builder(
    source_type: str,
    source_provider: str | None,
    source_timeframe: str | None,
) -> None:
    # This test is intentionally the one narrow test boundary allowed to
    # import the canonical producer, proving the decision adapter mirrors its
    # persisted source metadata rather than a hand-shaped approximation.
    from apps.ingestion_app.domain.candle import CanonicalCandle
    from apps.ingestion_app.domain.instrument import MarketLane
    from apps.ingestion_app.publication.outbox import build_candle_committed_event

    bar_open = BASE
    lane = MarketLane(SERIES.venue, SERIES.instrument_id, SERIES.timeframe)
    event = build_candle_committed_event(
        CanonicalCandle(
            lane=lane,
            open_time=bar_open,
            close_time=bar_open + timedelta(hours=1),
            open=Decimal(100),
            high=Decimal(103),
            low=Decimal(99),
            close=Decimal(101),
            volume=Decimal(10),
            taker_buy_base=Decimal(4),
            source_type=source_type,
            source_provider=source_provider,
            source_timeframe=source_timeframe,
        )
    )
    fields = {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "schema_version": str(event.schema_version),
        "producer": event.producer,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload_json,
    }

    parsed = parse_canonical_ingestion_event(
        stream_key=canonical_ingestion_stream_key(SERIES),
        stream_id="42-0",
        fields=fields,
        expected_series=SERIES,
        timeframe_grid=GRID,
    )

    assert (parsed.source_type, parsed.source_provider, parsed.source_timeframe) == (
        source_type,
        source_provider,
        source_timeframe,
    )


@pytest.mark.parametrize(
    "fields, message",
    [
        (_event_fields(producer="legacy"), "producer"),
        ({**_event_fields(), "event_type": "other"}, "event_type"),
        ({**_event_fields(), "schema_version": "2"}, "schema_version"),
    ],
)
def test_parser_rejects_retired_or_wrong_event_contract(
    fields: dict[str, str], message: str
) -> None:
    with pytest.raises(CanonicalIngestionEventError, match=message):
        parse_canonical_ingestion_event(
            stream_key=canonical_ingestion_stream_key(SERIES),
            stream_id="1-0",
            fields=fields,
            expected_series=SERIES,
            timeframe_grid=GRID,
        )


def test_parser_rejects_payload_stream_identity_mismatch_and_naive_time() -> None:
    fields = _event_fields()
    payload = json.loads(fields["payload"])
    payload["instrument_id"] = "ETH-USDT-PERP"
    fields["payload"] = json.dumps(payload)
    with pytest.raises(CanonicalIngestionEventError, match="identity"):
        parse_canonical_ingestion_event(
            stream_key=canonical_ingestion_stream_key(SERIES),
            stream_id="1-0",
            fields=fields,
            expected_series=SERIES,
            timeframe_grid=GRID,
        )

    fields = _event_fields()
    payload = json.loads(fields["payload"])
    payload["open_time"] = "2026-01-05T00:00:00"
    fields["payload"] = json.dumps(payload)
    with pytest.raises(CanonicalIngestionEventError, match="aware UTC"):
        parse_canonical_ingestion_event(
            stream_key=canonical_ingestion_stream_key(SERIES),
            stream_id="1-0",
            fields=fields,
            expected_series=SERIES,
            timeframe_grid=GRID,
        )


def test_parser_rejects_malformed_canonical_geometry() -> None:
    fields = _event_fields()
    payload = json.loads(fields["payload"])
    payload["open_time"] = (
        (BASE + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    )
    fields["payload"] = json.dumps(payload)
    with pytest.raises(ValueError, match="duration|aligned"):
        parse_canonical_ingestion_event(
            stream_key=canonical_ingestion_stream_key(SERIES),
            stream_id="1-0",
            fields=fields,
            expected_series=SERIES,
            timeframe_grid=GRID,
        )
