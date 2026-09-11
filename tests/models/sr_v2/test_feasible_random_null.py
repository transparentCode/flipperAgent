from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.zones import lineage_from_candidate
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.research.placebos import (
    FEASIBLE_RANDOM_PRICE_ID,
    build_feasible_random_price_null,
)


def _bar(opened: datetime, *, high: str, low: str) -> SRBar:
    duration = grid_for("15m").duration
    return SRBar(
        timeframe="15m",
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=Decimal(100),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(100),
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
    )


def _zone(
    *,
    side: ZoneSide = ZoneSide.SUPPORT,
    atr: str = "1",
    lower: str = "99",
    upper: str = "101",
):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    candidate = Candidate(
        candidate_key="candidate",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        source_timeframe="15m",
        kernel_id="kernel",
        kernel_version="1",
        side=side,
        center=Decimal(100),
        lower=Decimal(lower),
        upper=Decimal(upper),
        formed_at=now,
        available_at=now,
        source_evidence_id="evidence",
        creation_atr=Decimal(atr),
    )
    return lineage_from_candidate(candidate, config_fingerprint="config")


def _bars() -> tuple[SRBar, ...]:
    # The public null boundary requires an exact causal suffix ending at the
    # issuance/availability cutoff (the zone is issued at 00:00).
    start = datetime(2023, 12, 31, 23, 15, tzinfo=UTC)
    return (
        _bar(start, high="101", low="90"),
        _bar(start + timedelta(minutes=15), high="102", low="95"),
        _bar(start + timedelta(minutes=30), high="103", low="100"),
    )


def test_feasible_support_null_is_causal_deterministic_and_linked():
    zone = _zone()
    result = build_feasible_random_price_null(
        zone,
        kernel_bars=_bars(),
        active_zones=(zone,),
        seed="development-seed",
    )
    repeat = build_feasible_random_price_null(
        zone,
        kernel_bars=_bars(),
        active_zones=(zone,),
        seed="development-seed",
    )
    assert result.complete is True
    assert result.zone is not None
    assert result.zone.zone_id == repeat.zone.zone_id
    assert result.zone.side is ZoneSide.SUPPORT
    assert result.zone.upper - result.zone.center == Decimal(1)
    assert result.zone.center - result.zone.lower == Decimal(1)
    assert result.source_observation_id == zone.zone_id
    assert result.provenance["algorithm_id"] == FEASIBLE_RANDOM_PRICE_ID
    assert result.provenance["linkage"] == zone.zone_id
    assert zone.zone_id in result.excluded_active_zone_ids
    assert result.zone.lower > 0


@pytest.mark.parametrize("side", [ZoneSide.SUPPORT, ZoneSide.RESISTANCE])
def test_feasible_null_preserves_precision_asymmetric_stored_offsets(side):
    zone = _zone(
        side=side,
        lower="99.12345678901234567890123456",
        upper="101.12345678901234567890123457",
    )
    result = build_feasible_random_price_null(
        zone,
        kernel_bars=_bars(),
        active_zones=(),
        seed="asymmetric-seed",
    )

    assert result.complete is True
    assert result.zone is not None
    assert zone.center - zone.lower != zone.upper - zone.center
    assert result.zone.lower == result.zone.center - (zone.center - zone.lower)
    assert result.zone.upper == result.zone.center + (zone.upper - zone.center)
    assert result.provenance["algorithm_id"] == "feasible_random_price@3"
    assert result.provenance["placement_rule"] == "preserve_stored_offsets@1"
    assert result.provenance["left_width"] == zone.center - zone.lower
    assert result.provenance["right_width"] == zone.upper - zone.center
    assert result.provenance["source_geometry"] == {
        "center": zone.center,
        "lower": zone.lower,
        "upper": zone.upper,
    }
    assert "half_width" not in result.provenance
    assert zone == _zone(
        side=side,
        lower="99.12345678901234567890123456",
        upper="101.12345678901234567890123457",
    )


def test_feasible_null_uses_highs_for_resistance_and_not_creation_atr():
    first = build_feasible_random_price_null(
        _zone(side=ZoneSide.RESISTANCE, atr="1"),
        kernel_bars=_bars(),
        active_zones=(),
        seed="development-seed",
    )
    second = build_feasible_random_price_null(
        _zone(side=ZoneSide.RESISTANCE, atr="999"),
        kernel_bars=_bars(),
        active_zones=(),
        seed="development-seed",
    )
    assert first.zone is not None and second.zone is not None
    assert first.zone.center == second.zone.center
    assert first.zone.lower == second.zone.lower
    assert first.zone.upper == second.zone.upper
    assert first.zone.side is ZoneSide.RESISTANCE


def test_feasible_null_reports_unavailable_after_same_side_overlap():
    zone = _zone()
    result = build_feasible_random_price_null(
        zone,
        kernel_bars=(
            _bar(datetime(2023, 12, 31, 23, 45, tzinfo=UTC), high="101", low="99.5"),
        ),
        active_zones=(zone,),
        seed="seed",
    )
    assert result.complete is False
    assert result.zone is None
    assert result.reason


def test_feasible_null_rejects_future_stale_gapped_and_wrong_timeframe_windows():
    zone = _zone()
    values = _bars()
    future = tuple(
        replace(
            bar,
            bar_open_at=bar.bar_open_at + timedelta(minutes=15),
            bar_close_at=bar.bar_close_at + timedelta(minutes=15),
            market_as_of=bar.market_as_of + timedelta(minutes=15),
        )
        for bar in values
    )
    with pytest.raises(ValueError, match="future|end"):
        build_feasible_random_price_null(
            zone, kernel_bars=future, active_zones=(), seed="seed"
        )

    stale = tuple(
        replace(
            bar,
            bar_open_at=bar.bar_open_at - timedelta(minutes=15),
            bar_close_at=bar.bar_close_at - timedelta(minutes=15),
            market_as_of=bar.market_as_of - timedelta(minutes=15),
        )
        for bar in values
    )
    with pytest.raises(ValueError, match="end"):
        build_feasible_random_price_null(
            zone, kernel_bars=stale, active_zones=(), seed="seed"
        )

    gapped = (
        *values[:1],
        replace(
            values[1],
            bar_open_at=values[1].bar_open_at + timedelta(minutes=15),
            bar_close_at=values[1].bar_close_at + timedelta(minutes=15),
            market_as_of=values[1].market_as_of + timedelta(minutes=15),
        ),
        values[2],
    )
    with pytest.raises(ValueError, match="contiguous|gap"):
        build_feasible_random_price_null(
            zone, kernel_bars=gapped, active_zones=(), seed="seed"
        )

    wrong_timeframe = replace(values[-1], timeframe="30m")
    with pytest.raises(ValueError, match="timeframe|end"):
        build_feasible_random_price_null(
            zone,
            kernel_bars=(*values[:-1], wrong_timeframe),
            active_zones=(),
            seed="seed",
        )
