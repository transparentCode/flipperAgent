from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.storage.market_history import CanonicalMarketRecord
from libs.contracts.decision import CausalBarView
from research.analysis_capabilities.r3_source import (
    R3_SOURCE_REVISION,
    R3CanonicalSourceError,
    R3CanonicalSourceSlice,
    build_canonical_source_slice,
    source_slice_fingerprint,
)

KEY = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="4h",
)
GRID = TimeframeGrid(
    alignment_origin=datetime(1970, 1, 1, tzinfo=UTC),
    durations={"4h": timedelta(hours=4)},
)
START = datetime(2026, 1, 1, tzinfo=UTC)
_PATTERN = (0, 2, 5, 2, 0, -2, -5, -2)


def make_records(
    count: int = 300,
    *,
    start: datetime = START,
    source_type: str = "provider",
    source_provider: str | None = "binance_native",
    source_timeframe: str | None = None,
) -> tuple[CanonicalMarketRecord, ...]:
    records: list[CanonicalMarketRecord] = []
    for index in range(count):
        opened_at = start + timedelta(hours=4 * index)
        closed_at = opened_at + timedelta(hours=4)
        close = Decimal(100) + Decimal(_PATTERN[index % len(_PATTERN)])
        bar = CausalBarView(
            timeframe="4h",
            bar_open_at=opened_at,
            bar_close_at=closed_at,
            market_as_of=closed_at,
            open=close,
            high=close + Decimal(1),
            low=close - Decimal(1),
            close=close,
            volume=Decimal(100 + index),
            taker_buy_base=Decimal(10),
            closed=True,
        )
        records.append(
            CanonicalMarketRecord(
                series_key=KEY,
                bar=bar,
                source_type=source_type,
                source_provider=source_provider,
                source_timeframe=source_timeframe,
            )
        )
    return tuple(records)


def make_source_slice(
    records: tuple[CanonicalMarketRecord, ...] | None = None,
    *,
    source_available_at: datetime | None = None,
) -> R3CanonicalSourceSlice:
    values = make_records() if records is None else records
    available_at = source_available_at or values[-1].bar.bar_close_at + timedelta(
        minutes=1
    )
    return build_canonical_source_slice(
        values,
        series_key=KEY,
        timeframe_grid=GRID,
        source_available_at=available_at,
    )


def test_native_source_is_exactly_fingerprinted_and_immutable() -> None:
    source = make_source_slice()

    assert source.records == make_records()
    assert source.source.source_revision == R3_SOURCE_REVISION
    assert source.source.source_provider == "binance_native"
    assert source.source.source_timeframe is None
    assert source.market_as_of == source.records[-1].bar.bar_close_at
    assert source.source_slice_sha256 == source_slice_fingerprint(source.records, KEY)
    with pytest.raises(FrozenInstanceError):
        source.records = ()  # type: ignore[misc]


def test_fingerprint_is_deterministic_and_content_sensitive() -> None:
    records = make_records()
    baseline = source_slice_fingerprint(records, KEY)
    assert baseline == source_slice_fingerprint(tuple(records), KEY)

    changed_bar = replace(
        records[20].bar,
        close=records[20].bar.close + Decimal("0.01"),
    )
    changed = records[:20] + (replace(records[20], bar=changed_bar),) + records[21:]
    assert source_slice_fingerprint(changed, KEY) != baseline

    first = make_source_slice(records, source_available_at=records[-1].bar.bar_close_at)
    later = make_source_slice(
        records,
        source_available_at=records[-1].bar.bar_close_at + timedelta(hours=1),
    )
    assert first.source_slice_sha256 == later.source_slice_sha256
    assert first.source != later.source


def test_fingerprint_covers_every_required_content_family() -> None:
    records = make_records()
    baseline = source_slice_fingerprint(records, KEY)

    def changed_bar(**changes):
        index = 20
        return (
            records[:index]
            + (replace(records[index], bar=replace(records[index].bar, **changes)),)
            + records[index + 1 :]
        )

    mutations = {
        "series identity": source_slice_fingerprint(
            records, replace(KEY, instrument_id="BTC-USDT-SPOT")
        ),
        "bar timestamps": source_slice_fingerprint(
            changed_bar(
                bar_open_at=records[20].bar.bar_open_at + timedelta(minutes=1),
                bar_close_at=records[20].bar.bar_close_at + timedelta(minutes=1),
                market_as_of=records[20].bar.market_as_of + timedelta(minutes=1),
            ),
            KEY,
        ),
        "OHLC": source_slice_fingerprint(
            changed_bar(high=records[20].bar.high + Decimal("0.01")), KEY
        ),
        "volume": source_slice_fingerprint(
            changed_bar(volume=records[20].bar.volume + Decimal("0.01")), KEY
        ),
        "taker_buy_base": source_slice_fingerprint(
            changed_bar(
                taker_buy_base=records[20].bar.taker_buy_base + Decimal("0.01")
            ),
            KEY,
        ),
        "source provenance": source_slice_fingerprint(
            records[:20]
            + (replace(records[20], source_provider="ccxt_binance"),)
            + records[21:],
            KEY,
        ),
        "record order": source_slice_fingerprint(
            (records[1], records[0], *records[2:]), KEY
        ),
    }

    assert set(mutations) == {
        "series identity",
        "bar timestamps",
        "OHLC",
        "volume",
        "taker_buy_base",
        "source provenance",
        "record order",
    }
    assert all(value != baseline for value in mutations.values())


def test_source_rejects_noncanonical_identity_and_provenance() -> None:
    with pytest.raises(TypeError):
        build_canonical_source_slice(
            list(make_records()),  # type: ignore[arg-type]
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=make_records()[-1].bar.bar_close_at,
        )

    wrong_key = replace(KEY, asset="ETHUSDT")
    with pytest.raises(R3CanonicalSourceError):
        build_canonical_source_slice(
            make_records(),
            series_key=wrong_key,
            timeframe_grid=GRID,
            source_available_at=make_records()[-1].bar.bar_close_at,
        )

    derived = make_records(
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )
    with pytest.raises(R3CanonicalSourceError):
        build_canonical_source_slice(
            derived,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=derived[-1].bar.bar_close_at,
        )


def test_source_rejects_ccxt_and_mixed_provider_rows() -> None:
    ccxt_records = make_records(source_provider="ccxt_binance")
    with pytest.raises(R3CanonicalSourceError):
        build_canonical_source_slice(
            ccxt_records,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=ccxt_records[-1].bar.bar_close_at,
        )

    records = make_records()
    mixed_records = (
        records[:20]
        + (replace(records[20], source_provider="ccxt_binance"),)
        + records[21:]
    )
    with pytest.raises(R3CanonicalSourceError):
        build_canonical_source_slice(
            mixed_records,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=mixed_records[-1].bar.bar_close_at,
        )


@pytest.mark.parametrize(
    "records",
    (
        make_records(301)[0:1] + make_records(301)[2:],
        (make_records()[0], make_records()[2], make_records()[1], *make_records()[3:]),
    ),
)
def test_source_rejects_gaps_and_reordered_records(
    records: tuple[CanonicalMarketRecord, ...],
) -> None:
    with pytest.raises(R3CanonicalSourceError, match="contiguous"):
        build_canonical_source_slice(
            records,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=records[-1].bar.bar_close_at,
        )


def test_source_rejects_bad_grid_duration_alignment_and_availability() -> None:
    bad_duration_bar = replace(
        make_records()[0].bar,
        bar_close_at=make_records()[0].bar.bar_open_at + timedelta(hours=3),
        market_as_of=make_records()[0].bar.bar_open_at + timedelta(hours=3),
    )
    bad_duration = (replace(make_records()[0], bar=bad_duration_bar),) + make_records()[
        1:
    ]
    with pytest.raises(R3CanonicalSourceError, match="duration"):
        build_canonical_source_slice(
            bad_duration,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=bad_duration[-1].bar.bar_close_at,
        )

    off_grid = make_records(start=START + timedelta(hours=1))
    with pytest.raises(R3CanonicalSourceError, match="aligned"):
        build_canonical_source_slice(
            off_grid,
            series_key=KEY,
            timeframe_grid=GRID,
            source_available_at=off_grid[-1].bar.bar_close_at,
        )

    records = make_records()
    with pytest.raises(R3CanonicalSourceError, match="available"):
        make_source_slice(
            records,
            source_available_at=records[-1].bar.bar_close_at - timedelta(seconds=1),
        )


def test_source_value_object_revalidates_authenticated_fields() -> None:
    source = make_source_slice()
    forged_source = replace(source.source, source_slice_sha256="0" * 64)
    with pytest.raises(R3CanonicalSourceError, match="digest"):
        R3CanonicalSourceSlice(
            records=source.records,
            source=forged_source,
            market_as_of=source.market_as_of,
        )
