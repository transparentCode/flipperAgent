from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SRStateKey,
    create_initial_state,
)
from libs.models.sr.evaluation import build_evaluation_trace, compute_diagnostics
from libs.models.sr.replay import replay_bars
from libs.models.sr.research.viewer.casebook_payload import (
    build_casebook_chart_payload as shared_build_casebook_chart_payload,
)
from libs.models.sr.scripts.baseline_trial.config import (
    load_and_resolve_input_config,
    load_trial_config,
)
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar
from libs.models.sr.tools.zone_viewer.payload import (
    SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION,
    build_casebook_chart_payload,
    build_chart_payload,
    chart_payload_identity,
)


_ROOT = Path(__file__).parents[5]
_TRIAL = load_trial_config(_ROOT / "configs/sr_trials/taousdt_1d_baseline.yaml")
_INPUT = load_and_resolve_input_config(
    _ROOT / "configs/sr_inputs.yaml", asset="TAOUSDT", timeframe="1d"
)
_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_casebook_payload_builder_keeps_tool_export_identity() -> None:
    assert build_casebook_chart_payload is shared_build_casebook_chart_payload


def _inputs(width: float):
    key = SRStateKey("binance_usdm", "TAOUSDT", "1d")
    paths = (
        "detection.pivot_span_bars",
        "detection.zone_half_width_atr",
        "association.merge_distance_atr",
        "lifecycle.touch_tolerance_atr",
        "lifecycle.break_buffer_atr",
        "lifecycle.break_confirm_closes",
        "lifecycle.max_age_bars",
        "runtime.max_active_zones",
    )
    config = ResolvedSRConfig.create(
        version="1",
        asset="TAOUSDT",
        timeframe="1d",
        detection=DetectionConfig(pivot_span_bars=1, zone_half_width_atr=width),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=50,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
        field_provenance={path: "defaults" for path in paths},
    )
    values = (
        (97.5, 100.0, 95.0, 97.5),
        (100.0, 110.0, 90.0, 100.0),
        (97.5, 101.0, 94.0, 97.5),
        (100.0, 111.0, 89.0, 100.0),
        (112.0, 113.0, 99.0, 112.0),
        (100.0, 111.0, 89.0, 100.0),
        (112.0, 113.0, 99.0, 112.0),
        (112.0, 113.0, 99.0, 112.0),
    )
    bars = tuple(
        ClosedBar(
            state_key=key,
            bar_id=f"bar-{index}",
            closed_at=_T0 + timedelta(days=index + 1),
            open=open_,
            high=high,
            low=low,
            close=close,
            atr_at_close=1.0,
        )
        for index, (open_, high, low, close) in enumerate(values)
    )
    _, snapshots = replay_bars(create_initial_state(key, config), bars, config)
    trace = build_evaluation_trace(snapshots, config)
    diagnostics = compute_diagnostics(trace)
    source = tuple(
        SourceBar(
            open_time=bar.closed_at - timedelta(days=1),
            closed_at=bar.closed_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=10.0,
            bar_id=bar.bar_id,
        )
        for bar in bars
    )
    return config, source, trace, diagnostics


def test_chart_payload_preserves_source_order_events_and_zone_identity() -> None:
    config, source, trace, diagnostics = _inputs(0.25)
    payload = build_chart_payload(
        trial=_TRIAL,
        bundle_id="a" * 64,
        resolved_sr_config=config,
        resolved_input=_INPUT,
        source_bars=source,
        trace=trace,
        diagnostics=diagnostics,
    )

    assert payload["schema_version"] == SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION
    assert [candle["bar_id"] for candle in payload["candles"]] == [bar.bar_id for bar in source]
    assert [event["event_id"] for event in payload["events"]] == [event.event_id for event in trace.events]
    assert payload["zones"]
    assert {zone["render_kind"] for zone in payload["zones"]} == {"BAND"}
    assert all(zone["visible_from"] == zone["available_at"] for zone in payload["zones"])
    assert any(zone["visible_until"] is not None for zone in payload["zones"])


def test_line_geometry_is_exported_without_backdating_visibility() -> None:
    config, source, trace, diagnostics = _inputs(0.0)
    payload = build_chart_payload(
        trial=_TRIAL,
        bundle_id=None,
        resolved_sr_config=config,
        resolved_input=_INPUT,
        source_bars=source,
        trace=trace,
        diagnostics=diagnostics,
    )

    assert payload["zones"]
    assert {zone["render_kind"] for zone in payload["zones"]} == {"LINE"}
    assert all(zone["lower_bound"] == zone["center"] == zone["upper_bound"] for zone in payload["zones"])


def test_chart_payload_identity_excludes_only_bundle_binding() -> None:
    config, source, trace, diagnostics = _inputs(0.25)
    first = build_chart_payload(
        trial=_TRIAL,
        bundle_id=None,
        resolved_sr_config=config,
        resolved_input=_INPUT,
        source_bars=source,
        trace=trace,
        diagnostics=diagnostics,
    )
    second = dict(first, bundle_id="b" * 64)
    assert chart_payload_identity(first) == chart_payload_identity(second)
    changed = dict(first, trial_name="different")
    assert chart_payload_identity(first) != chart_payload_identity(changed)
