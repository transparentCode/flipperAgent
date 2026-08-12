from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.publication.stream_keys import canonical_lane_stream_key
from apps.signal_app.ohlcv_source import (
    IngestionHistoryFetcher,
    OhlcvSourceBinding,
    decode_ingestion_event,
    parse_ohlcv_source_bindings,
    stream_key_for_binding,
)
from apps.signal_app.pipeline.snapshot import FeatureSnapshotService
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from apps.signal_app.settings import SignalWorkerSettings
from libs.contracts.signal import FeatureVector, PriceUpdate

_BINDING = OhlcvSourceBinding(
    asset="BTCUSDT",
    source="ingestion",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
)
_CLOSE = datetime(2026, 8, 10, 12, 1, tzinfo=UTC)


def _payload(
    *,
    open_time: datetime = datetime(2026, 8, 10, 12, tzinfo=UTC),
    timeframe: str = "1m",
    venue: str = "binance",
    instrument_id: str = "BTC-USDT-PERP",
    taker_buy_base: str | None = "4",
) -> dict[str, object]:
    close_time = open_time + timedelta(minutes=1)
    return {
        "venue": venue,
        "instrument_id": instrument_id,
        "timeframe": timeframe,
        "open_time": open_time.isoformat().replace("+00:00", "Z"),
        "close_time": close_time.isoformat().replace("+00:00", "Z"),
        "open": "100",
        "high": "110",
        "low": "95",
        "close": "105",
        "volume": "10",
        "taker_buy_base": taker_buy_base,
        "source_type": "provider",
        "source_provider": "binance_native",
        "source_timeframe": None,
    }


def _event(payload: dict[str, object]) -> dict[str, str]:
    close_time = datetime.fromisoformat(str(payload["close_time"]))
    return {
        "event_id": "9d4f35db-c927-4e05-a5e1-5d8d8ecfce00",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": (close_time + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


def test_source_binding_requires_explicit_ingestion_identity() -> None:
    with pytest.raises(ValueError, match="explicit bindings"):
        parse_ohlcv_source_bindings(None)
    with pytest.raises(ValueError, match="explicit bindings"):
        parse_ohlcv_source_bindings({})
    with pytest.raises(ValueError, match="source must"):
        parse_ohlcv_source_bindings({"BTCUSDT": {"source": "legacy"}})
    with pytest.raises((TypeError, ValueError)):
        parse_ohlcv_source_bindings({"BTCUSDT": {}})
    assert parse_ohlcv_source_bindings(
        {
            "btcusdt": {
                "source": "ingestion",
                "venue": " binance ",
                "instrument_id": " BTC-USDT-PERP ",
            }
        }
    ) == (_BINDING,)

    with pytest.raises((TypeError, ValueError), match="venue"):
        parse_ohlcv_source_bindings({"BTCUSDT": {"source": "ingestion"}})
    with pytest.raises(ValueError, match="source must"):
        parse_ohlcv_source_bindings({"BTCUSDT": {"source": "unknown"}})

    settings = SignalWorkerSettings(ohlcv_sources=(_BINDING,))
    with pytest.raises(ValueError, match="no explicit"):
        settings.source_binding("ETHUSDT")


def test_stream_key_matches_ingestion_canonical_key() -> None:
    candle = CanonicalCandle(
        lane=MarketLane("binance", "BTC-USDT-PERP", "1m"),
        open_time=datetime(2026, 8, 10, 12, tzinfo=UTC),
        close_time=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(95),
        close=Decimal(105),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )
    event = build_candle_committed_event(candle)
    assert stream_key_for_binding(_BINDING, "1m") == canonical_lane_stream_key(event)
    encoded_binding = OhlcvSourceBinding(
        asset="BTCUSDT",
        source="ingestion",
        venue="binance/usdm",
        instrument_id="BTC:USDT",
    )
    assert stream_key_for_binding(encoded_binding, "1m") == (
        "stream:ohlcv:ingestion:binance%2Fusdm:BTC%3AUSDT:1m"
    )


def test_ingestion_event_decoder_maps_exact_envelope_and_rejects_null_taker_buy() -> (
    None
):
    candle = decode_ingestion_event(_event(_payload()), _BINDING, "1m")

    assert candle.exchange == "binance"
    assert candle.symbol == "BTCUSDT"
    assert candle.timestamp == datetime(2026, 8, 10, 12, tzinfo=UTC).timestamp()
    assert candle.close_timestamp == _CLOSE.timestamp()
    assert candle.taker_buy_base == 4.0
    assert candle.base_timeframe == "1m"
    assert candle.provider == "binance_native"
    assert candle.origin == "ingestion"
    assert candle.publication_lag_ms == 1000

    with pytest.raises(ValueError, match="taker_buy_base"):
        decode_ingestion_event(_event(_payload(taker_buy_base=None)), _BINDING, "1m")

    malformed = _event(_payload())
    malformed["payload"] = "{"
    with pytest.raises(ValueError, match="valid JSON"):
        decode_ingestion_event(malformed, _BINDING, "1m")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_type", "other.event", "event_type"),
        ("schema_version", "2", "schema_version"),
    ],
)
def test_ingestion_event_decoder_rejects_wrong_envelope_metadata(
    field: str,
    value: str,
    message: str,
) -> None:
    event = _event(_payload())
    event[field] = value
    with pytest.raises(ValueError, match=message):
        decode_ingestion_event(event, _BINDING, "1m")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("venue", "other", "venue"),
        ("instrument_id", "other", "instrument_id"),
        ("timeframe", "5m", "timeframe"),
    ],
)
def test_ingestion_event_decoder_rejects_wrong_payload_identity(
    field: str,
    value: str,
    message: str,
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        decode_ingestion_event(_event(payload), _BINDING, "1m")


class _FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.args: tuple[object, ...] | None = None

    async def fetch(self, _query: str, *args: object) -> list[dict[str, object]]:
        self.args = args
        return self.rows


class _Acquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _history_row(
    open_time: datetime, *, taker: Decimal | None = Decimal(4)
) -> dict[str, object]:
    return {
        "open_time": open_time,
        "close_time": open_time + timedelta(minutes=1),
        "open": Decimal(100),
        "high": Decimal(110),
        "low": Decimal(95),
        "close": Decimal(105),
        "volume": Decimal(10),
        "taker_buy_base": taker,
    }


@pytest.mark.asyncio
async def test_ingestion_history_fetcher_returns_ascending_contiguous_rows() -> None:
    first = datetime(2026, 8, 10, 12, tzinfo=UTC)
    connection = _FakeConnection(
        [_history_row(first + timedelta(minutes=1)), _history_row(first)]
    )
    fetcher = IngestionHistoryFetcher(_BINDING, pool=_FakePool(connection))

    result = await fetcher("btcusdt", "1m", 2)

    assert [row[5] for row in result] == [
        first.timestamp(),
        (first + timedelta(minutes=1)).timestamp(),
    ]
    assert connection.args == ("binance", "BTC-USDT-PERP", "1m", 2)


@pytest.mark.asyncio
async def test_ingestion_history_fetcher_rejects_gaps_and_null_taker_buy() -> None:
    first = datetime(2026, 8, 10, 12, tzinfo=UTC)
    gap_connection = _FakeConnection(
        [_history_row(first + timedelta(minutes=2)), _history_row(first)]
    )
    with pytest.raises(ValueError, match="gap or duplicate"):
        await IngestionHistoryFetcher(_BINDING, pool=_FakePool(gap_connection))(
            "BTCUSDT",
            "1m",
            2,
        )

    duplicate_connection = _FakeConnection([_history_row(first), _history_row(first)])
    with pytest.raises(ValueError, match="gap or duplicate"):
        await IngestionHistoryFetcher(
            _BINDING,
            pool=_FakePool(duplicate_connection),
        )("BTCUSDT", "1m", 2)

    null_connection = _FakeConnection([_history_row(first, taker=None)])
    with pytest.raises(ValueError, match="NULL taker_buy_base"):
        await IngestionHistoryFetcher(_BINDING, pool=_FakePool(null_connection))(
            "BTCUSDT",
            "1m",
            1,
        )


class _Publisher:
    def __init__(self) -> None:
        self.feature_calls: list[object] = []

    async def publish_feature_vector(self, value: object, **_kwargs: object) -> None:
        self.feature_calls.append(value)

    async def publish_price_update(self, _value: object) -> None:
        return None


class _Pipeline:
    enrichment_reader = None
    regime_features = None

    async def process_closed_candle_enriched(
        self, *, candle, **_kwargs: object
    ) -> tuple[object, object]:
        return (
            FeatureVector(
                asset="BTCUSDT",
                timeframe="1m",
                timestamp=candle.timestamp,
                features={},
                bar_data={"close": candle.close},
            ),
            PriceUpdate(
                asset="BTCUSDT",
                timeframe="1m",
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            ),
        )


@pytest.mark.asyncio
async def test_ingestion_worker_processes_each_canonical_timestamp_once() -> None:
    settings = SignalWorkerSettings(ohlcv_sources=(_BINDING,))
    publisher = _Publisher()
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1m",
        settings=settings,
        pipeline=_Pipeline(),
        publisher=publisher,
    )

    first = _event(_payload())
    older = _event(_payload(open_time=datetime(2026, 8, 10, 11, 59, tzinfo=UTC)))
    newer = _event(_payload(open_time=datetime(2026, 8, 10, 12, 1, tzinfo=UTC)))
    await worker.process_message("1-0", first)
    await worker.process_message("1-1", first)
    await worker.process_message("1-2", older)
    await worker.process_message("1-3", newer)

    assert len(publisher.feature_calls) == 2


@pytest.mark.asyncio
async def test_ingestion_worker_creates_group_at_dollar_before_base_connect() -> None:
    settings = SignalWorkerSettings(ohlcv_sources=(_BINDING,))
    redis = AsyncMock()
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1m",
        settings=settings,
        pipeline=_Pipeline(),
        publisher=_Publisher(),
    )

    await worker.connect(redis)

    assert redis.xgroup_create.await_args_list[0].kwargs["id"] == "$"
    assert redis.xgroup_create.await_args_list[1].kwargs["id"] == "0"


@pytest.mark.asyncio
async def test_snapshot_selects_ingestion_history_when_binding_is_configured(
    monkeypatch,
) -> None:
    seen: list[OhlcvSourceBinding] = []

    class _Fetcher:
        def __init__(self, binding: OhlcvSourceBinding) -> None:
            seen.append(binding)

        async def __call__(self, _asset: str, _timeframe: str, lookback: int):
            return [
                (100.0, 110.0, 95.0, 105.0, 10.0, float(index), 4.0)
                for index in range(lookback)
            ]

    monkeypatch.setattr(
        "apps.signal_app.pipeline.snapshot.IngestionHistoryFetcher", _Fetcher
    )
    settings = SignalWorkerSettings(ohlcv_sources=(_BINDING,))
    result = await FeatureSnapshotService(settings=settings).compute(
        asset="BTCUSDT",
        timeframe="1h",
        lookback=260,
    )

    assert result.asset == "BTCUSDT"
    assert seen == [_BINDING]
