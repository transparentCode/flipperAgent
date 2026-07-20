"""Plotly-only rendering from deterministic research rows."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go

from ..contracts import ContractValidationError
from .contracts import (
    ArtifactTrialRow,
    CorridorRow,
    EventRow,
    InteractionZoneRow,
    MTFProjectedMemberRow,
    MemberRailRow,
    record_to_dict,
)


_ROLE_COLORS = {"SUPPORT": "#237a57", "RESISTANCE": "#b44a3a"}


def build_price_figure(
    *,
    frame: pd.DataFrame,
    rails: Sequence[MemberRailRow],
    corridors: Sequence[CorridorRow] = (),
    zones: Sequence[InteractionZoneRow] = (),
    events: Sequence[EventRow] = (),
    include_volume: bool = False,
) -> go.Figure:
    """Render exact rails, corridor bounds, and zone bounds as distinct traces."""

    required = {"open", "high", "low", "close"}
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise ContractValidationError("chart frame requires open/high/low/close columns")
    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=frame.index,
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="confirmed OHLC",
        )
    )
    x_values = tuple(frame.index)
    rails_by_member_id = {rail.member_id: rail for rail in rails}
    for rail in sorted(rails, key=lambda row: (row.role, row.family_id, row.member_id)):
        price = tuple(
            rail.reference_price
            + rail.slope_per_second * (pd.Timestamp(timestamp).to_pydatetime() - rail.reference_time).total_seconds()
            for timestamp in x_values
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=price,
                mode="lines",
                name=f"{rail.role} rail {rail.member_id}",
                line={"color": _ROLE_COLORS.get(rail.role, "#777777"), "width": 3 if rail.representative else 1},
                customdata=[
                    [
                        rail.snapshot_id,
                        rail.family_id,
                        rail.member_id,
                        rail.candidate_id,
                        rail.role,
                        rail.lifecycle,
                        rail.confidence,
                        rail.age_bars,
                        rail.representative,
                    ]
                    for _ in x_values
                ],
                hovertemplate=(
                    "snapshot=%{customdata[0]}<br>family=%{customdata[1]}<br>member=%{customdata[2]}<br>candidate=%{customdata[3]}"
                    "<br>role=%{customdata[4]}<br>lifecycle=%{customdata[5]}<br>confidence=%{customdata[6]:.3f}"
                    "<br>age=%{customdata[7]}<br>representative=%{customdata[8]}<br>exact price=%{y:.6f}<extra></extra>"
                ),
            )
        )
        for anchor_time, anchor_price, pivot_kind in rail.anchor_points:
            figure.add_trace(
                go.Scatter(
                    x=[anchor_time],
                    y=[anchor_price],
                    mode="markers",
                    name=f"{pivot_kind} anchor {rail.member_id}",
                    marker={"size": 7, "symbol": "circle-open", "color": _ROLE_COLORS.get(rail.role, "#777777")},
                    customdata=[[rail.family_id, rail.member_id, pivot_kind]],
                    hovertemplate="family=%{customdata[0]}<br>member=%{customdata[1]}<br>pivot=%{customdata[2]}<br>anchor=%{y:.6f}<extra></extra>",
                )
            )
    for corridor in sorted(corridors, key=lambda row: (row.role, row.family_id, row.corridor_id)):
        corridor_rails = tuple(rails_by_member_id.get(member_id) for member_id in corridor.ordered_member_ids)
        if any(rail is None for rail in corridor_rails):
            continue
        exact_prices = tuple(
            tuple(
                rail.reference_price
                + rail.slope_per_second
                * (pd.Timestamp(timestamp).to_pydatetime() - rail.reference_time).total_seconds()
                for rail in corridor_rails
            )
            for timestamp in x_values
        )
        lower = tuple(min(prices) for prices in exact_prices)
        upper = tuple(max(prices) for prices in exact_prices)
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=lower,
                mode="lines",
                line={"width": 0},
                name=f"corridor {corridor.corridor_id} lower",
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=upper,
                mode="lines",
                fill="tonexty",
                fillcolor="rgba(100,100,100,0.14)",
                line={"width": 0},
                name=f"corridor {corridor.corridor_id}",
                hovertemplate=(
                    f"family={corridor.family_id}<br>role={corridor.role}<br>"
                    "view=snapshot_projection_exact_members_v1<br>"
                    "lower=%{y:.6f}<br>snapshot="
                    f"{corridor.snapshot_id}<extra></extra>"
                ),
            )
        )
    half_bar = _half_bar_width(frame.index)
    for zone in sorted(zones, key=lambda row: (row.role, row.family_id, row.observation_id)):
        zone_timestamp = pd.Timestamp(zone.timestamp)
        if zone_timestamp not in frame.index:
            continue
        zone_x = (zone_timestamp - half_bar, zone_timestamp + half_bar)
        figure.add_trace(
            go.Scatter(
                x=zone_x,
                y=(zone.lower_price, zone.lower_price),
                mode="lines",
                line={"width": 0},
                name=f"zone {zone.observation_id} lower",
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=zone_x,
                y=(zone.upper_price, zone.upper_price),
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor="rgba(90,120,190,0.10)",
                name=f"zone {zone.observation_id}",
                customdata=[[zone.snapshot_id, zone.family_id, zone.observation_id, zone.timestamp]] * 2,
                hovertemplate=(
                    "snapshot=%{customdata[0]}<br>family=%{customdata[1]}<br>observation=%{customdata[2]}"
                    "<br>timestamp=%{customdata[3]}<br>upper=%{y:.6f}<extra></extra>"
                ),
            )
        )
    for event in sorted(events, key=lambda row: (row.updated_at, row.event_id)):
        event_timestamp = pd.Timestamp(event.updated_at)
        if event_timestamp not in frame.index:
            continue
        event_price = frame.at[event_timestamp, "close"]
        figure.add_trace(
            go.Scatter(
                x=[event.updated_at],
                y=[event_price],
                mode="markers",
                name=f"event {event.state}",
                marker={"symbol": "diamond", "size": 9, "color": "#31455b"},
                customdata=[[event.event_id, event.family_id, event.state, event.last_observation_id]],
                hovertemplate=(
                    "event=%{customdata[0]}<br>family=%{customdata[1]}<br>state=%{customdata[2]}"
                    "<br>observation=%{customdata[3]}<extra></extra>"
                ),
            )
        )
    if include_volume and "volume" in frame.columns:
        figure.add_trace(go.Bar(x=frame.index, y=frame["volume"], name="volume", opacity=0.25, yaxis="y2"))
        figure.update_layout(yaxis2={"overlaying": "y", "side": "right", "showgrid": False, "title": "volume"})
    figure.update_layout(
        title="Canonical Trendline Family Research",
        xaxis_title="confirmed timestamp",
        yaxis_title="price",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
    )
    return figure


def _half_bar_width(index: pd.DatetimeIndex) -> pd.Timedelta:
    if len(index) < 2:
        return pd.Timedelta(minutes=1)
    differences = index.to_series().diff().dropna()
    width = differences.median()
    return pd.Timedelta(width) / 2


def build_validation_sensitivity_figure(
    *,
    rows: Sequence[ArtifactTrialRow],
    stage: str,
    metric: str,
) -> go.Figure:
    """Plot explicit validation stage/metric with aggregate, worst, and fold evidence."""

    if not isinstance(stage, str) or not stage:
        raise ContractValidationError("sensitivity stage must be non-empty text")
    if not isinstance(metric, str) or not metric:
        raise ContractValidationError("sensitivity metric must be non-empty text")
    selected = tuple(rows)
    if not selected:
        raise ContractValidationError("sensitivity figure requires validation trial rows")
    if any(not isinstance(row, ArtifactTrialRow) for row in selected):
        raise ContractValidationError("sensitivity figure requires ArtifactTrialRow values")
    if any(row.stage != stage for row in selected):
        raise ContractValidationError("sensitivity rows must match the explicit stage")
    if any(row.primary_metric_name != metric for row in selected):
        raise ContractValidationError("sensitivity rows must match the explicit primary metric")
    if any(
        not row.validation_only
        or not row.per_window_metrics
        or any(window.get("window_kind") != "validation" for window in row.per_window_metrics)
        for row in selected
    ):
        raise ContractValidationError("sensitivity figure cannot consume holdout evidence")
    parameters = tuple(sorted({name for row in selected for name in row.overrides}))
    if not parameters:
        raise ContractValidationError("sensitivity figure requires parameter overrides")
    figure = go.Figure()
    plotted = 0
    for parameter in parameters:
        points = tuple(
            sorted(
                (row for row in selected if parameter in row.overrides),
                key=lambda row: (_plot_sort_key(row.overrides[parameter]), row.trial_id),
            )
        )
        plotted += _add_sensitivity_summary_trace(
            figure,
            points=points,
            parameter=parameter,
            metric=metric,
            evidence_kind="aggregate",
        )
        plotted += _add_sensitivity_summary_trace(
            figure,
            points=points,
            parameter=parameter,
            metric=metric,
            evidence_kind="worst",
        )
        fold_ids = tuple(
            sorted(
                {
                    str(window.get("fold_id"))
                    for row in points
                    for window in row.per_window_metrics
                    if window.get("fold_id") is not None
                }
            )
        )
        for fold_id in fold_ids:
            values: list[tuple[ArtifactTrialRow, float, str]] = []
            for row in points:
                evidence = _window_metric_evidence(row, fold_id=fold_id, metric=metric)
                if evidence is not None:
                    value, window_result_id = evidence
                    values.append((row, value, window_result_id))
            if not values:
                continue
            plotted += len(values)
            figure.add_trace(
                go.Scatter(
                    x=[_plot_value(row.overrides[parameter]) for row, _, _ in values],
                    y=[value for _, value, _ in values],
                    mode="markers",
                    name=f"{parameter}:fold:{fold_id}",
                    customdata=[
                        [
                            "fold",
                            fold_id,
                            window_result_id,
                            row.trial_id,
                            row.result_id,
                            json.dumps(record_to_dict(row.overrides), sort_keys=True, separators=(",", ":")),
                        ]
                        for row, _, window_result_id in values
                    ],
                    hovertemplate=(
                        "evidence=%{customdata[0]}<br>fold=%{customdata[1]}"
                        "<br>window_result=%{customdata[2]}<br>parameter=" + parameter
                        + "<br>value=%{x}<br>metric=%{y}<br>trial=%{customdata[3]}"
                        "<br>result=%{customdata[4]}<br>overrides=%{customdata[5]}<extra></extra>"
                    ),
                )
            )
    if plotted == 0:
        raise ContractValidationError("sensitivity figure has no defined validation metric values")
    figure.update_layout(
        title=f"Validation Sensitivity: {stage}",
        xaxis_title="parameter value",
        yaxis_title=metric,
        template="plotly_white",
    )
    return figure


def _add_sensitivity_summary_trace(
    figure: go.Figure,
    *,
    points: Sequence[ArtifactTrialRow],
    parameter: str,
    metric: str,
    evidence_kind: str,
) -> int:
    metric_name = metric if evidence_kind == "aggregate" else f"{metric}__worst"
    values = tuple(
        (row, _aggregate_metric_value(row, metric_name))
        for row in points
    )
    defined = tuple((row, value) for row, value in values if value is not None)
    if not defined:
        return 0
    figure.add_trace(
        go.Scatter(
            x=[_plot_value(row.overrides[parameter]) for row, _ in defined],
            y=[value for _, value in defined],
            mode="markers+lines",
            name=f"{parameter}:{evidence_kind}",
            customdata=[
                [
                    evidence_kind,
                    row.trial_id,
                    row.result_id,
                    json.dumps(record_to_dict(row.overrides), sort_keys=True, separators=(",", ":")),
                ]
                for row, _ in defined
            ],
            hovertemplate=(
                "evidence=%{customdata[0]}<br>parameter=" + parameter
                + "<br>value=%{x}<br>metric=%{y}<br>trial=%{customdata[1]}"
                "<br>result=%{customdata[2]}<br>overrides=%{customdata[3]}<extra></extra>"
            ),
        )
    )
    return len(defined)


def _aggregate_metric_value(row: ArtifactTrialRow, metric_name: str) -> float | None:
    payload = row.aggregate_metrics.get(metric_name)
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _window_metric_evidence(
    row: ArtifactTrialRow,
    *,
    fold_id: str,
    metric: str,
) -> tuple[float, str] | None:
    for window in row.per_window_metrics:
        if str(window.get("fold_id")) != fold_id:
            continue
        for metric_record in window.get("metrics", ()):
            if metric_record.get("name") != metric:
                continue
            value = metric_record.get("value")
            result_id = window.get("result_id")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(result_id, str)
                and result_id
            ):
                return float(value), result_id
    return None


def _plot_value(value: object) -> object:
    converted = record_to_dict(value)
    if converted is None or isinstance(converted, (str, bool, int, float)):
        return converted
    return json.dumps(converted, sort_keys=True, separators=(",", ":"))


def _plot_sort_key(value: object) -> tuple[str, str]:
    converted = _plot_value(value)
    return (type(converted).__name__, str(converted))


def build_mtf_projection_figure(*, members: Sequence[MTFProjectedMemberRow]) -> go.Figure:
    """Render canonical projected members at one decision timestamp; never average rails."""

    figure = go.Figure()
    for member in sorted(members, key=lambda row: (row.source_timeframe, row.projected_family_id, row.source_order_index)):
        figure.add_trace(
            go.Scatter(
                x=[member.projection_timestamp],
                y=[member.projected_price],
                mode="markers",
                name=f"{member.source_timeframe} member {member.source_member_id}",
                customdata=[[member.source_snapshot_id, member.source_timeframe, member.source_family_id, member.source_member_id, member.source_candidate_id]],
                hovertemplate=(
                    "source_snapshot=%{customdata[0]}<br>timeframe=%{customdata[1]}<br>family=%{customdata[2]}"
                    "<br>member=%{customdata[3]}<br>candidate=%{customdata[4]}<br>projected=%{y:.6f}<extra></extra>"
                ),
            )
        )
    figure.update_layout(title="Canonical MTF Exact Member Projections", xaxis_title="decision timestamp", yaxis_title="projected price", template="plotly_white")
    return figure


__all__ = [
    "build_mtf_projection_figure",
    "build_price_figure",
    "build_validation_sensitivity_figure",
]
