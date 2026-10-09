"""Validation gate: each rule, plus OI and funding semantics."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from scraper_v2_support import dec, epoch, load_fixture, make_spec, raw_bars, utc

from apps.scraper_app.adapters.tradingview import protocol
from apps.scraper_app.adapters.tradingview.protocol import SeriesAccumulator
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.bars import (
    RawBar,
    canonical_decimal,
    content_hash,
    expected_latest_closed_bar_open,
    validate_bars,
)
from apps.scraper_app.domain.datasets import Shape
from apps.scraper_app.domain.errors import ScraperError

FIRST = utc(2026, 10, 9, 1)
PROVIDER_TIME = epoch(utc(2026, 10, 9, 6, 17, 39))


def _gate(
    spec=None, bars=None, *, pro_name="CRYPTOCAP:TOTAL3", provider_time=PROVIDER_TIME
):
    spec = spec or make_spec()
    bars = bars if bars is not None else raw_bars(FIRST, 6)
    return _gate_result(spec, bars, pro_name, provider_time).bars


def _gate_result(spec, bars, pro_name, provider_time):
    return validate_bars(
        spec, pro_name=pro_name, provider_time=provider_time, raw_bars=bars
    )


def _code(**kwargs) -> str:
    with pytest.raises(ScraperError) as excinfo:
        _gate(**kwargs)
    return excinfo.value.code


def test_the_newest_returned_bar_is_never_accepted() -> None:
    bars = raw_bars(FIRST, 6)
    accepted = _gate(bars=bars)
    assert len(accepted) == 5
    assert accepted[-1].bar_open == FIRST + timedelta(hours=4)
    assert FIRST + timedelta(hours=5) not in {b.bar_open for b in accepted}


def test_bars_are_sorted_and_closing_time_is_open_plus_interval() -> None:
    bars = list(reversed(raw_bars(FIRST, 6)))
    accepted = _gate(bars=bars)
    assert [b.bar_open for b in accepted] == sorted(b.bar_open for b in accepted)
    assert all(b.bar_close - b.bar_open == timedelta(hours=1) for b in accepted)


def test_identity_mismatch() -> None:
    assert _code(pro_name="CRYPTOCAP:TOTAL2") == errors.IDENTITY_MISMATCH


def test_shape_mismatch_when_value_count_differs() -> None:
    assert _code(bars=raw_bars(FIRST, 6, volume=False)) == errors.SHAPE_MISMATCH
    ohlc = make_spec(shape=Shape.OHLC)
    assert (
        _code(spec=ohlc, bars=raw_bars(FIRST, 6, volume=True)) == errors.SHAPE_MISMATCH
    )


def test_shape_is_checked_on_the_dropped_bar_too() -> None:
    bars = raw_bars(FIRST, 5) + [RawBar(time=epoch(FIRST) + 5 * 3600, fields=(dec(1),))]
    assert _code(bars=bars) == errors.SHAPE_MISMATCH


def test_a_single_bar_leaves_nothing_and_is_empty() -> None:
    assert _code(bars=raw_bars(FIRST, 1)) == errors.EMPTY


def test_future_bar_is_rejected_after_dropping_only_the_newest() -> None:
    # Two bars still open at provider time: the newest is dropped, the other fails.
    bars = raw_bars(utc(2026, 10, 9, 5), 3)  # 05:00, 06:00, 07:00
    assert _code(bars=bars) == errors.FUTURE_BAR


def test_a_bar_closing_exactly_at_provider_time_is_closed() -> None:
    bars = raw_bars(utc(2026, 10, 9, 4), 3)  # 04:00, 05:00, 06:00(dropped)
    accepted = _gate(bars=bars, provider_time=epoch(utc(2026, 10, 9, 6)))
    assert [b.bar_open.hour for b in accepted] == [4, 5]


def test_holes_in_a_contiguous_dataset_are_counted_not_rejected() -> None:
    bars = raw_bars(FIRST, 8)
    del bars[2]
    del bars[3]  # two single-bar holes
    result = _gate_result(make_spec(), bars, "CRYPTOCAP:TOTAL3", PROVIDER_TIME + 7200)
    assert result.holes == 2
    assert len(result.bars) == 5
    assert (
        _gate_result(
            make_spec(), raw_bars(FIRST, 6), "CRYPTOCAP:TOTAL3", PROVIDER_TIME
        ).holes
        == 0
    )


def test_the_recorded_2015_daily_hole_is_accepted_with_three_missing_days() -> None:
    day = 86400
    spec = make_spec(interval="1D")
    times = [1420243200, 1420329600, 1420416000, 1420761600, 1420848000, 1420934400]
    bars = [RawBar(time=t, fields=raw_bars(FIRST, 1)[0].fields) for t in times]
    result = _gate_result(spec, bars, "CRYPTOCAP:TOTAL3", times[-1] + day)
    assert result.holes == 3
    assert [int(b.bar_open.timestamp()) for b in result.bars] == times[:-1]


def test_non_contiguous_dataset_accepts_skipped_hours() -> None:
    funding = make_spec(shape=Shape.OHLC, contiguous=False, non_negative=False)
    bars = raw_bars(FIRST, 6, volume=False)
    del bars[2]
    assert len(_gate(spec=funding, bars=bars)) == 4
    assert _gate_result(funding, bars, "CRYPTOCAP:TOTAL3", PROVIDER_TIME).holes == 0


def test_domain_rules() -> None:
    def with_fields(index: int, fields: tuple[Decimal, ...]):
        bars = raw_bars(FIRST, 6)
        bars[index] = RawBar(time=bars[index].time, fields=fields)
        return bars

    # low above open/close
    assert _code(
        bars=with_fields(1, (dec(100), dec(110), dec(101), dec(105), dec(1)))
    ) == (errors.DOMAIN_VIOLATION)
    # high below open/close
    assert _code(
        bars=with_fields(1, (dec(100), dec(99), dec(90), dec(95), dec(1)))
    ) == (errors.DOMAIN_VIOLATION)
    # negative volume
    assert _code(
        bars=with_fields(1, (dec(100), dec(110), dec(90), dec(95), dec(-1)))
    ) == (errors.DOMAIN_VIOLATION)
    # non-finite
    assert _code(
        bars=with_fields(1, (Decimal("NaN"), dec(110), dec(90), dec(95), dec(1)))
    ) == (errors.DOMAIN_VIOLATION)
    assert _code(
        bars=with_fields(1, (dec(100), Decimal("Infinity"), dec(90), dec(95), dec(1)))
    ) == (errors.DOMAIN_VIOLATION)


def test_open_interest_must_be_non_negative_funding_may_be_negative() -> None:
    oi = make_spec(shape=Shape.OHLC, non_negative=True)
    funding = make_spec(shape=Shape.OHLC, contiguous=False, non_negative=False)

    def negative_bars():
        bars = raw_bars(FIRST, 6, volume=False)
        bars[1] = RawBar(time=bars[1].time, fields=(dec(-1), dec(2), dec(-3), dec(-2)))
        return bars

    assert _code(spec=oi, bars=negative_bars()) == errors.DOMAIN_VIOLATION
    accepted = _gate(spec=funding, bars=negative_bars())
    assert accepted[1].low == Decimal(-3)
    assert accepted[1].volume is None


def test_recorded_exchanges_pass_the_gate_with_their_provider_time() -> None:
    cases = [
        ("index_total3_1h", make_spec(), 5),
        ("index_total3_4h", make_spec(interval="4h"), 3),
        ("index_total3_1d", make_spec(interval="1D"), 3),
        (
            "oi_btc_alias_1h",
            make_spec(
                canonical_symbol="BINANCE:BTCUSDT.P_OI",
                shape=Shape.OHLC,
                finality_horizon_seconds=0,
            ),
            5,
        ),
        (
            "funding_btc_1h",
            make_spec(
                canonical_symbol="BINANCE:BTCUSDT.P_FR",
                shape=Shape.OHLC,
                contiguous=False,
                non_negative=False,
                finality_horizon_seconds=0,
            ),
            5,
        ),
    ]
    for name, spec, expected_count in cases:
        acc = SeriesAccumulator()
        for raw in load_fixture(name)["received"]:
            for message in protocol.decode_message(raw):
                acc.feed(message)
        result = acc.result()
        accepted = validate_bars(
            spec,
            pro_name=result.pro_name,
            provider_time=result.provider_time,
            raw_bars=result.bars,
        )
        assert len(accepted.bars) == expected_count, name
        assert accepted.holes == 0, name


def test_canonical_decimal_and_hash_ignore_representation() -> None:
    assert canonical_decimal(Decimal("794191481969.0")) == "794191481969"
    assert canonical_decimal(Decimal("1E+3")) == "1000"
    assert canonical_decimal(Decimal("0.0")) == "0"
    assert canonical_decimal(Decimal("-0")) == "0"
    assert canonical_decimal(Decimal("2.947e-05")) == "0.00002947"
    a = content_hash(dec(1), dec(2), dec(0), dec(1), Decimal("5.0"))
    b = content_hash(Decimal("1.00"), dec(2), dec(0), dec(1), Decimal(5))
    assert a == b
    assert a != content_hash(dec(1), dec(2), dec(0), dec(1), None)
    assert a != content_hash(dec(1), dec(2), dec(0), dec(1), dec(6))


def test_expected_latest_closed_bar() -> None:
    now = utc(2026, 10, 9, 6, 17, 39)
    assert expected_latest_closed_bar_open(now, 3600) == utc(2026, 10, 9, 5)
    assert expected_latest_closed_bar_open(now, 14400) == utc(2026, 10, 9, 0)
    assert expected_latest_closed_bar_open(now, 86400) == utc(2026, 10, 8)
