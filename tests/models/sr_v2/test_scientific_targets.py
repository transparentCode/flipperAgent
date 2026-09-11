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
from libs.models.sr_v2.forecast.targets import (
    REFERENCE_VOLATILITY_ID,
    SCIENTIFIC_TARGET_SCHEMA,
    ScientificReaction,
    compute_target_reference_volatility,
    label_scientific_target,
    resolve_target_spec,
    scientific_target_fingerprint,
)


def _bar(
    timeframe: str,
    opened: datetime,
    *,
    high: str = "101",
    low: str = "99",
    close: str | None = None,
    open_: str | None = None,
) -> SRBar:
    duration = grid_for(timeframe).duration
    high_value = Decimal(high)
    low_value = Decimal(low)
    midpoint = (high_value + low_value) / Decimal(2)
    return SRBar(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=(midpoint if open_ is None else Decimal(open_)),
        high=high_value,
        low=low_value,
        close=(midpoint if close is None else Decimal(close)),
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
    )


def _zone(issued_at: datetime, *, side: ZoneSide = ZoneSide.SUPPORT, atr: str = "1"):
    candidate = Candidate(
        candidate_key="candidate",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        source_timeframe="1h",
        kernel_id="kernel",
        kernel_version="1",
        side=side,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=issued_at - timedelta(hours=1),
        available_at=issued_at,
        source_evidence_id="evidence",
        creation_atr=Decimal(atr),
    )
    return lineage_from_candidate(candidate, config_fingerprint="config")


def _reference(issuance: datetime) -> tuple[SRBar, ...]:
    start = issuance - timedelta(hours=3)
    return (
        _bar("1h", start, high="102", low="99", close="100"),
        _bar(
            "1h",
            start + timedelta(hours=1),
            high="104",
            low="99",
            close="103",
            open_="100",
        ),
        _bar(
            "1h",
            start + timedelta(hours=2),
            high="105",
            low="102",
            close="104",
            open_="103",
        ),
    )


def _spec(*, multiplier: str = "0.5", source_timeframe: str = "1h"):
    return resolve_target_spec(
        source_timeframe=source_timeframe,
        source_horizon_bars=2,
        reference_lookback=2,
        barrier_multiplier=Decimal(multiplier),
        observation_timeframe="15m",
        observation_duration=timedelta(minutes=15),
    )


def _future(issuance: datetime, values: list[dict[str, str]]) -> tuple[SRBar, ...]:
    return tuple(
        _bar("15m", issuance + timedelta(minutes=15 * index), **value)
        for index, value in enumerate(values)
    )


def test_reference_volatility_is_exact_n_plus_one_and_content_addressed():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    receipt = compute_target_reference_volatility(
        _reference(issuance),
        source_timeframe="1h",
        issuance_cutoff=issuance,
        lookback=2,
    )
    assert receipt.algorithm_id == REFERENCE_VOLATILITY_ID
    assert receipt.value == Decimal(4)
    assert receipt.source_bar_identities[-1].endswith("04:00:00+00:00")
    assert len(receipt.source_bar_identities) == 3
    changed = replace(_reference(issuance)[-1], close=Decimal("104.5"))
    changed_receipt = compute_target_reference_volatility(
        (_reference(issuance)[0], _reference(issuance)[1], changed),
        source_timeframe="1h",
        issuance_cutoff=issuance,
        lookback=2,
    )
    assert changed_receipt.source_fingerprint != receipt.source_fingerprint
    with pytest.raises(ValueError, match=r"exactly N\+1"):
        compute_target_reference_volatility(
            _reference(issuance)[:-1],
            source_timeframe="1h",
            issuance_cutoff=issuance,
            lookback=2,
        )


def test_reference_rejects_future_gap_wrong_timeframe_and_wrong_cutoff():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    reference = _reference(issuance)
    future = replace(
        reference[-1],
        bar_close_at=issuance + timedelta(hours=1),
        market_as_of=issuance + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="final bar"):
        compute_target_reference_volatility(
            (*reference[:-1], future),
            source_timeframe="1h",
            issuance_cutoff=issuance,
            lookback=2,
        )
    gapped = replace(
        reference[1],
        bar_open_at=reference[1].bar_open_at + timedelta(hours=1),
        bar_close_at=reference[1].bar_close_at + timedelta(hours=1),
        market_as_of=reference[1].market_as_of + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="gapped|contiguous|duration"):
        compute_target_reference_volatility(
            (reference[0], gapped, reference[2]),
            source_timeframe="1h",
            issuance_cutoff=issuance,
            lookback=2,
        )
    wrong_tf = replace(
        reference[0],
        timeframe="30m",
        bar_close_at=reference[0].bar_open_at + timedelta(minutes=30),
        market_as_of=reference[0].bar_open_at + timedelta(minutes=30),
    )
    with pytest.raises(ValueError, match="timeframe"):
        compute_target_reference_volatility(
            (wrong_tf, reference[1], reference[2]),
            source_timeframe="1h",
            issuance_cutoff=issuance,
            lookback=2,
        )


def test_source_horizon_is_derived_for_each_supported_timeframe():
    for timeframe in ("1d", "6h", "4h", "1h", "30m", "15m"):
        spec = _spec(source_timeframe=timeframe)
        assert spec.horizon == grid_for(timeframe).duration * 2
        assert spec.observation_timeframe == "15m"


def test_two_stage_first_touch_and_later_ordered_reaction_are_causal():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    spec = _spec()
    future = _future(
        issuance,
        [
            {"high": "100.5", "low": "99.5", "close": "100"},
            {"high": "104", "low": "100.5", "close": "103"},
        ]
        + [{"high": "110", "low": "109", "close": "109"}] * 6,
    )
    result = label_scientific_target(
        _zone(issuance),
        issued_at=issuance,
        future_bars=future,
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    assert result.touch is True
    assert result.reaction is ScientificReaction.BOUNCE
    assert result.reaction_eligible is True
    assert result.view.touch_at == issuance + timedelta(minutes=15)
    assert result.event_observation is not None


def test_first_touch_and_later_dual_barriers_are_ambiguous():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    spec = _spec()
    first_touch_dual = _future(
        issuance,
        [{"high": "104", "low": "96", "close": "100"}]
        + [{"high": "110", "low": "109", "close": "109"}] * 7,
    )
    later_dual = _future(
        issuance,
        [
            {"high": "100.5", "low": "99.5", "close": "100"},
            {"high": "104", "low": "96", "close": "100"},
        ]
        + [{"high": "110", "low": "109", "close": "109"}] * 6,
    )
    first = label_scientific_target(
        _zone(issuance),
        issued_at=issuance,
        future_bars=first_touch_dual,
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    later = label_scientific_target(
        _zone(issuance),
        issued_at=issuance,
        future_bars=later_dual,
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    for result in (first, later):
        assert result.touch is True
        assert result.reaction is None
        assert result.reaction_eligible is False
        assert result.view.ambiguous is True


def test_first_touch_single_terminal_barrier_is_also_ambiguous():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    spec = _spec()
    first_favorable = _future(
        issuance,
        [{"high": "104", "low": "100"}]
        + [{"high": "110", "low": "109", "close": "109"}] * 7,
    )
    first_adverse = _future(
        issuance,
        [{"high": "100", "low": "96"}]
        + [{"high": "110", "low": "109", "close": "109"}] * 7,
    )
    for future in (first_favorable, first_adverse):
        result = label_scientific_target(
            _zone(issuance),
            issued_at=issuance,
            future_bars=future,
            target_spec=spec,
            reference_bars=_reference(issuance),
        )
        assert result.touch is True
        assert result.reaction is None
        assert result.reaction_eligible is False
        assert result.view.ambiguous is True


def test_incomplete_prefix_is_censored_and_issuance_bar_is_not_future_evidence():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    spec = _spec()
    before = _bar(
        "15m", issuance - timedelta(minutes=15), high="104", low="96", close="100"
    )
    first = _bar("15m", issuance, high="110", low="109", close="109")
    gap = _bar(
        "15m", issuance + timedelta(minutes=30), high="110", low="109", close="109"
    )
    result = label_scientific_target(
        _zone(issuance),
        issued_at=issuance,
        future_bars=(before, first, gap),
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    assert result.touch is None
    assert result.censored is True
    assert result.last_observed_cutoff == issuance + timedelta(minutes=15)


def test_creation_atr_does_not_enter_scientific_label_or_fingerprint():
    issuance = datetime(2024, 1, 1, 4, tzinfo=UTC)
    spec = _spec()
    future = _future(issuance, [{"high": "110", "low": "109", "close": "109"}] * 8)
    first = label_scientific_target(
        _zone(issuance, atr="1"),
        issued_at=issuance,
        future_bars=future,
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    second = label_scientific_target(
        _zone(issuance, atr="999"),
        issued_at=issuance,
        future_bars=future,
        target_spec=spec,
        reference_bars=_reference(issuance),
    )
    assert first.view == second.view
    assert scientific_target_fingerprint(spec) == spec.target_fingerprint
    assert SCIENTIFIC_TARGET_SCHEMA == "sr_v2.two_stage_targets.v2"
    assert len(scientific_target_fingerprint(spec)) == 64


def test_target_spec_requires_explicit_positive_scientific_values():
    with pytest.raises(ValueError, match="positive"):
        resolve_target_spec(
            source_timeframe="1h",
            source_horizon_bars=0,
            reference_lookback=2,
            barrier_multiplier=Decimal("0.5"),
            observation_timeframe="15m",
            observation_duration=timedelta(minutes=15),
        )
    with pytest.raises(ValueError, match="exact multiple"):
        resolve_target_spec(
            source_timeframe="15m",
            source_horizon_bars=1,
            reference_lookback=2,
            barrier_multiplier=Decimal("0.5"),
            observation_timeframe="30m",
            observation_duration=timedelta(minutes=30),
        )
