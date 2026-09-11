from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from libs.models.sr_v2.config import SRV2ConfigResolver, load_sr_v2_yaml
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.identity import window_fingerprint
from libs.models.sr_v2.domain.state import SRState, create_initial_state
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.kernels.registry import (
    KERNEL_CATALOG,
    KernelEvaluation,
    KernelSpec,
)
from libs.models.sr_v2.structural import SRModel, SRStepRequest


def _state(config, *, venue="v", instrument_id="i", asset="a"):
    return create_initial_state(
        config_fingerprint=config.config_fingerprint,
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
    )


def _request(config, bars, state, cutoff, **identity):
    return SRStepRequest(
        venue=identity.get("venue", "v"),
        instrument_id=identity.get("instrument_id", "i"),
        asset=identity.get("asset", "a"),
        market_as_of=cutoff,
        state=state,
        windows=bars,
    )


def _next_bars(bars, config, cutoff):
    result = {}
    for timeframe, values in bars.items():
        current = list(values)
        duration = grid_for(timeframe).duration
        expected = grid_for(timeframe).expected_closed_cutoff(cutoff)
        while current[-1].bar_close_at < expected:
            opened = current[-1].bar_close_at
            base = current[-1].close
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


def test_exact_suffix_and_content_fingerprint_are_causal(sr_v2_config, sr_v2_bars, sr_v2_now):
    model = SRModel(sr_v2_config)
    baseline = model.step(_request(sr_v2_config, sr_v2_bars, _state(sr_v2_config), sr_v2_now))
    older = {}
    for timeframe, values in sr_v2_bars.items():
        first = values[0]
        duration = grid_for(timeframe).duration
        older[timeframe] = (
            replace(
                first,
                bar_open_at=first.bar_open_at - duration,
                bar_close_at=first.bar_open_at,
                market_as_of=first.bar_open_at,
            ),
            *values,
        )
    extended = model.step(_request(sr_v2_config, older, _state(sr_v2_config), sr_v2_now))
    assert extended.state == baseline.state
    assert extended.transitions == baseline.transitions
    assert window_fingerprint(sr_v2_bars["15m"][-21:]) == window_fingerprint(older["15m"][-21:])

    changed = replace(sr_v2_bars["15m"][-1], close=Decimal("102.3"))
    with pytest.raises(ValueError, match="conflict"):
        model.step(_request(
            sr_v2_config,
            {"15m": sr_v2_bars["15m"][:-1] + (changed,)},
            baseline.state,
            sr_v2_now,
        ))


def test_sparse_sources_are_explicit_and_unchanged_sources_are_not_replayed(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    model = SRModel(sr_v2_config)
    first = model.step(_request(sr_v2_config, sr_v2_bars, _state(sr_v2_config), sr_v2_now))
    cutoff = sr_v2_now + sr_v2_config.trigger_duration
    next_bars = _next_bars(sr_v2_bars, sr_v2_config, cutoff)
    second = model.step(_request(
        sr_v2_config,
        {"15m": next_bars["15m"], "30m": next_bars["30m"]},
        first.state,
        cutoff,
    ))
    assert second.evaluated_timeframes == ("30m", "15m")
    with pytest.raises(ValueError, match="missing=30m"):
        model.step(_request(sr_v2_config, {"15m": next_bars["15m"]}, first.state, cutoff))
    with pytest.raises(ValueError, match="extra=1h"):
        model.step(_request(
            sr_v2_config,
            {"15m": next_bars["15m"], "30m": next_bars["30m"], "1h": next_bars["1h"]},
            first.state,
            cutoff,
        ))
    duplicate = model.step(_request(sr_v2_config, {"15m": sr_v2_bars["15m"]}, first.state, sr_v2_now))
    assert duplicate.duplicate_delivery
    assert duplicate.evaluated_timeframes == ()
    assert duplicate.state == first.state


def test_advancing_source_windows_reject_changed_committed_overlap(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    model = SRModel(sr_v2_config)
    first = model.step(_request(sr_v2_config, sr_v2_bars, _state(sr_v2_config), sr_v2_now))
    cutoff = sr_v2_now + sr_v2_config.trigger_duration
    next_bars = _next_bars(sr_v2_bars, sr_v2_config, cutoff)

    trigger_overlap = next_bars["15m"][-2]
    changed_trigger = replace(trigger_overlap, close=trigger_overlap.close + Decimal(".1"))
    with pytest.raises(ValueError, match="overlap"):
        model.step(_request(
            sr_v2_config,
            {"15m": next_bars["15m"][:-2] + (changed_trigger, next_bars["15m"][-1]), "30m": next_bars["30m"]},
            first.state,
            cutoff,
        ))

    higher_overlap = next_bars["30m"][-2]
    changed_higher = replace(higher_overlap, close=higher_overlap.close + Decimal(".1"))
    with pytest.raises(ValueError, match="overlap"):
        model.step(_request(
            sr_v2_config,
            {"15m": next_bars["15m"], "30m": next_bars["30m"][:-2] + (changed_higher, next_bars["30m"][-1])},
            first.state,
            cutoff,
        ))


def test_genesis_and_committed_state_invariants_fail_closed():
    common = {
        "config_fingerprint": "config",
        "venue": "v",
        "instrument_id": "i",
        "asset": "a",
    }
    with pytest.raises(ValueError, match="generation zero"):
        SRState(**common, generation=1, last_trigger_at=None)
    with pytest.raises(ValueError, match="positive generation"):
        SRState(**common, generation=0, last_trigger_at=datetime(2024, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="source identities"):
        SRState(**common, generation=1, last_trigger_at=datetime(2024, 1, 1, tzinfo=UTC))


def test_core_requires_state_and_kernel_catalog_bounds_are_code_owned(sr_v2_config, sr_v2_bars, sr_v2_now):
    with pytest.raises(TypeError, match="state must be SRState"):
        SRStepRequest(
            venue="v",
            instrument_id="i",
            asset="a",
            market_as_of=sr_v2_now,
            state=None,
            windows=sr_v2_bars,
        )

    identifier = "too_many_rows@1"

    def parse_parameters(raw, path):
        return {"enabled": bool(raw["enabled"])}

    def history_required(parameters):
        return 1

    def evaluate(bars, *, market_identity, parameters):
        row = {"timeframe": bars[-1].timeframe, "bar_close_at": bars[-1].bar_close_at}
        return KernelEvaluation(candidates=(), consumed_feature_rows=(row, row))

    catalog = {
        identifier: KernelSpec(
            identifier=identifier,
            parse_parameters=parse_parameters,
            history_required=history_required,
            evaluate=evaluate,
            replacement_policy="independent",
            max_evidence_rows=1,
        )
    }
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["kernels"] = {
        identifier: {
            "timeframes": {
                timeframe: {"enabled": True} for timeframe in raw["runtime"]["ladder"]
            }
        }
    }
    config = SRV2ConfigResolver(raw, kernel_catalog=catalog).resolve()
    with pytest.raises(ValueError, match="evidence-row bound"):
        SRModel(config).step(_request(config, sr_v2_bars, _state(config), sr_v2_now))


def test_selected_catalog_and_order_are_part_of_identity(sr_v2_config):
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["kernels"].pop("plateau_sweep_reclaim@1")
    selected = SRV2ConfigResolver(raw).resolve()
    assert selected.catalog_fingerprint != sr_v2_config.catalog_fingerprint
    assert selected.config_fingerprint != sr_v2_config.config_fingerprint

    unused = "unused@1"
    base = KERNEL_CATALOG["previous_period_anchor@1"]
    expanded_catalog = {
        **KERNEL_CATALOG,
        unused: KernelSpec(
            identifier=unused,
            parse_parameters=base.parse_parameters,
            history_required=base.history_required,
            evaluate=base.evaluate,
            replacement_policy=base.replacement_policy,
        ),
    }
    expanded = SRV2ConfigResolver(
        load_sr_v2_yaml("configs/sr_v2.yaml"),
        kernel_catalog=expanded_catalog,
    ).resolve()
    assert expanded.catalog_fingerprint == sr_v2_config.catalog_fingerprint
    assert expanded.config_fingerprint == sr_v2_config.config_fingerprint

    reordered = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    reordered["kernels"] = dict(reversed(tuple(reordered["kernels"].items())))
    reordered_config = SRV2ConfigResolver(reordered).resolve()
    assert reordered_config.catalog_fingerprint == sr_v2_config.catalog_fingerprint
    assert reordered_config.config_fingerprint != sr_v2_config.config_fingerprint
