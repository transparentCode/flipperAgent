from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.runtime.offline import OfflineCompute, OfflineMode

_IDENTITY = {
    "venue": "binance_usdm",
    "instrument_id": "BTCUSDT",
    "asset": "BTCUSDT",
}


def _extend_bars(bars_by_timeframe, cutoff):
    result = {}
    for timeframe, values in bars_by_timeframe.items():
        current = list(values)
        duration = grid_for(timeframe).duration
        expected = grid_for(timeframe).expected_closed_cutoff(cutoff)
        while current[-1].bar_close_at < expected:
            opened = current[-1].bar_close_at
            base = current[-1].close + 1
            current.append(
                SRBar(
                    timeframe=timeframe,
                    bar_open_at=opened,
                    bar_close_at=opened + duration,
                    market_as_of=opened + duration,
                    open=base,
                    high=base + 1,
                    low=base - 1,
                    close=base + Decimal("0.2"),
                    volume=current[-1].volume,
                    taker_buy_base=current[-1].taker_buy_base,
                )
            )
        result[timeframe] = tuple(current)
    return result


def test_genesis_requires_identity_and_returns_only_bounded_final_result(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    with pytest.raises(ValueError, match="explicit runtime identity"):
        OfflineCompute(sr_v2_config).run(sr_v2_bars, cutoff=sr_v2_now)

    observed = []
    result = OfflineCompute(sr_v2_config, **_IDENTITY).run(
        sr_v2_bars,
        cutoff=sr_v2_now,
        on_step=observed.append,
    )

    assert result.mode is OfflineMode.GENESIS_EXACT
    assert result.steps == 1
    assert result.final_result is observed[-1]
    assert result.state == result.final_result.state
    assert result.provenance["config_fingerprint"] == sr_v2_config.config_fingerprint
    assert not hasattr(result, "trace")
    assert result == OfflineCompute(sr_v2_config, **_IDENTITY).run(
        sr_v2_bars,
        cutoff=sr_v2_now,
    )


def test_checkpoint_exact_matches_uninterrupted_genesis_run(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
    first_bars = _extend_bars(sr_v2_bars, sr_v2_now)
    next_bars = _extend_bars(first_bars, next_cutoff)
    compute = OfflineCompute(sr_v2_config, **_IDENTITY)

    first = compute.run(first_bars, cutoff=sr_v2_now)
    continued = compute.run(
        next_bars,
        checkpoint=first.state,
        cutoff=next_cutoff,
        mode=OfflineMode.CHECKPOINT_EXACT,
    )
    uninterrupted = compute.run(next_bars, cutoff=next_cutoff)

    assert continued.steps == 1
    assert uninterrupted.steps == 2
    assert continued.final_result == uninterrupted.final_result
    assert continued.state == uninterrupted.state
    assert continued.provenance["source_fingerprints"] == uninterrupted.provenance["source_fingerprints"]
    inferred_identity = OfflineCompute(sr_v2_config).run(
        next_bars,
        checkpoint=first.state,
        cutoff=next_cutoff,
        mode=OfflineMode.CHECKPOINT_EXACT,
    )
    assert inferred_identity.final_result == continued.final_result


def test_checkpoint_exact_rejects_identity_cutoff_and_state_mismatches(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    compute = OfflineCompute(sr_v2_config, **_IDENTITY)
    first = compute.run(sr_v2_bars, cutoff=sr_v2_now)
    next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
    next_bars = _extend_bars(sr_v2_bars, next_cutoff)

    with pytest.raises(TypeError, match="CHECKPOINT_EXACT"):
        compute.run(next_bars, cutoff=next_cutoff, mode=OfflineMode.CHECKPOINT_EXACT)
    with pytest.raises(ValueError, match="runtime identity"):
        OfflineCompute(sr_v2_config, venue="other", instrument_id="BTCUSDT", asset="BTCUSDT").run(
            next_bars,
            checkpoint=first.state,
            cutoff=next_cutoff,
            mode=OfflineMode.CHECKPOINT_EXACT,
        )
    with pytest.raises(ValueError, match="cutoff"):
        compute.run(
            next_bars,
            checkpoint=first.state,
            cutoff=sr_v2_now + timedelta(minutes=1),
            mode=OfflineMode.CHECKPOINT_EXACT,
        )
    bad_config_state = replace(first.state, config_fingerprint="other-config")
    with pytest.raises(ValueError, match="config fingerprint"):
        compute.run(
            next_bars,
            checkpoint=bad_config_state,
            cutoff=next_cutoff,
            mode=OfflineMode.CHECKPOINT_EXACT,
        )
    bad_cutoff_state = replace(
        first.state,
        source_cutoffs={**first.state.source_cutoffs, "15m": sr_v2_now - timedelta(minutes=15)},
    )
    with pytest.raises(ValueError, match="source cutoff"):
        compute.run(
            next_bars,
            checkpoint=bad_cutoff_state,
            cutoff=next_cutoff,
            mode=OfflineMode.CHECKPOINT_EXACT,
        )


def test_offline_dataset_is_closed_exact_and_ladder_bound(sr_v2_config, sr_v2_bars, sr_v2_now):
    compute = OfflineCompute(sr_v2_config, **_IDENTITY)
    with pytest.raises(ValueError, match="exact configured ladder"):
        compute.run(
            {**sr_v2_bars, "extra": sr_v2_bars["15m"]},
            cutoff=sr_v2_now,
        )
    malformed = dict(sr_v2_bars)
    malformed["15m"] = (*sr_v2_bars["15m"][:-1], object())
    with pytest.raises(TypeError, match="SRBar"):
        compute.run(malformed, cutoff=sr_v2_now)
