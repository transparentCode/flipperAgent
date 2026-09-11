"""Cross-boundary invariants for the structural-only SR v2 pipeline."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from libs.models.sr_v2.config import SRV2ConfigResolver, load_sr_v2_yaml
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.state import create_initial_state
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.kernels.registry import (
    KERNEL_CATALOG,
    KernelEvaluation,
    KernelSpec,
)
from libs.models.sr_v2.serialization.state_codec import decode_state, encode_state
from libs.models.sr_v2.structural import SRModel, SRStepRequest


def _bars_at(bars_by_timeframe, config, cutoff):
    """Extend each closed series only through its causal grid cutoff."""

    result = {}
    for timeframe, values in bars_by_timeframe.items():
        current = list(values)
        duration = grid_for(timeframe).duration
        expected = grid_for(timeframe).expected_closed_cutoff(cutoff)
        while current[-1].bar_close_at < expected:
            opened = current[-1].bar_close_at
            index = len(current)
            base = Decimal(100) + Decimal(index) / Decimal(10)
            current.append(
                SRBar(
                    timeframe=timeframe,
                    bar_open_at=opened,
                    bar_close_at=opened + duration,
                    market_as_of=opened + duration,
                    open=base,
                    high=base + Decimal(1),
                    low=base - Decimal(1),
                    close=base + Decimal("0.2"),
                    volume=Decimal(10),
                    taker_buy_base=Decimal(5),
                )
            )
        result[timeframe] = tuple(current)
    return result


def test_checkpoint_restart_matches_uninterrupted_structural_step(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
    first_bars = _bars_at(sr_v2_bars, sr_v2_config, sr_v2_now)
    next_bars = _bars_at(first_bars, sr_v2_config, next_cutoff)
    kwargs = {
        "venue": "binance_usdm",
        "instrument_id": "BTCUSDT",
        "asset": "BTCUSDT",
    }
    state = create_initial_state(config_fingerprint=sr_v2_config.config_fingerprint, **kwargs)
    engine = SRModel(sr_v2_config)
    first = engine.step(SRStepRequest(**kwargs, market_as_of=sr_v2_now, state=state, windows=first_bars))
    uninterrupted = engine.step(SRStepRequest(
        **kwargs,
        market_as_of=next_cutoff,
        state=first.state,
        windows={"15m": next_bars["15m"], "30m": next_bars["30m"]},
    ))
    checkpoint = decode_state(
        encode_state(first.state),
        expected_config_fingerprint=sr_v2_config.config_fingerprint,
        expected_venue=kwargs["venue"],
        expected_instrument_id=kwargs["instrument_id"],
        expected_asset=kwargs["asset"],
        max_active_lineages=sr_v2_config.max_active_lineages,
        max_terminal_tombstones=sr_v2_config.max_terminal_tombstones,
    )
    restarted = SRModel(sr_v2_config).step(SRStepRequest(
        **kwargs,
        market_as_of=next_cutoff,
        state=checkpoint,
        windows={"15m": next_bars["15m"], "30m": next_bars["30m"]},
    ))
    assert restarted.state == uninterrupted.state
    assert restarted.transitions == uninterrupted.transitions
    assert restarted.feature_rows == uninterrupted.feature_rows
    assert restarted.candidates_by_timeframe == uninterrupted.candidates_by_timeframe


def test_fixture_third_kernel_requires_only_catalog_and_yaml_entry(sr_v2_bars):
    identifier = "fixture_empty@1"

    def parse_parameters(raw, path):
        if set(raw) != {"enabled"} or not isinstance(raw["enabled"], bool):
            raise ValueError(f"{path}.enabled must be bool")
        return {"enabled": raw["enabled"]}

    def history_required(parameters):
        return 1

    def evaluate(bars, *, market_identity, parameters):
        return KernelEvaluation(candidates=(), consumed_feature_rows=({
            "timeframe": bars[-1].timeframe,
            "bar_close_at": bars[-1].bar_close_at,
            "kernel_id": "fixture_empty",
            "kernel_version": "1",
        },))

    fixture = KernelSpec(
        identifier=identifier,
        parse_parameters=parse_parameters,
        history_required=history_required,
        evaluate=evaluate,
        replacement_policy="independent",
    )
    catalog = {**KERNEL_CATALOG, identifier: fixture}
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["kernels"][identifier] = {
        "timeframes": {
            timeframe: {"enabled": True}
            for timeframe in raw["runtime"]["ladder"]
        }
    }
    config = SRV2ConfigResolver(raw, kernel_catalog=catalog).resolve()
    state = create_initial_state(
        config_fingerprint=config.config_fingerprint,
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    result = SRModel(config).step(SRStepRequest(
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        market_as_of=sr_v2_bars["15m"][-1].bar_close_at,
        state=state,
        windows=sr_v2_bars,
    ))
    assert any(row["kernel_id"] == "fixture_empty" for row in result.feature_rows)


def test_config_identity_changes_for_any_structural_yaml_value():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    baseline = SRV2ConfigResolver(raw).resolve()
    raw["lifecycle"]["break_confirmation_bars"] = 3
    changed = SRV2ConfigResolver(raw).resolve()
    assert changed.config_fingerprint != baseline.config_fingerprint
    assert changed.catalog_fingerprint == baseline.catalog_fingerprint


def test_structural_rejects_non_utc_or_future_history(sr_v2_config, sr_v2_bars, sr_v2_now):
    future = sr_v2_now + timedelta(minutes=15)
    with pytest.raises(ValueError, match="UTC"):
        SRModel(sr_v2_config).step(SRStepRequest(
            venue="v",
            instrument_id="i",
            asset="a",
            market_as_of=sr_v2_now.replace(tzinfo=None),
            state=create_initial_state(
                config_fingerprint=sr_v2_config.config_fingerprint,
                venue="v",
                instrument_id="i",
                asset="a",
            ),
            windows=sr_v2_bars,
        ))
    future_bars = dict(sr_v2_bars)
    future_bars["15m"] = sr_v2_bars["15m"][:-1] + (
        SRBar(
            timeframe="15m",
            bar_open_at=sr_v2_now,
            bar_close_at=future,
            market_as_of=future,
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100),
            volume=Decimal(1),
            taker_buy_base=Decimal(".5"),
        ),
    )
    with pytest.raises(ValueError, match="past|stale|cutoff|gapped"):
        SRModel(sr_v2_config).step(SRStepRequest(
            venue="v",
            instrument_id="i",
            asset="a",
            market_as_of=sr_v2_now,
            state=create_initial_state(
                config_fingerprint=sr_v2_config.config_fingerprint,
                venue="v",
                instrument_id="i",
                asset="a",
            ),
            windows=future_bars,
        ))
