"""Guarded replay for trendline warning baskets.

Read-only simulation: when a changed shadow pick matches a warning basket, the
replayed outcome falls back to baseline by setting shadow_minus_baseline to 0.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_WARNING_BASKET = (
    ("trendline_mid_channel_noise", 1.0),
    ("trendline_no_trade_warning", 1.0),
    ("trendline_confidence_annotation", "reversal_watch"),
)


@dataclass(frozen=True)
class GuardedReplayConfig:
    warning_basket: tuple[tuple[str, Any], ...] = _DEFAULT_WARNING_BASKET
    min_guarded_samples: int = 25
    min_loss_saved_rate: float = 0.55
    min_net_lift_delta: float = 0.0
    allowed_asset_timeframes: tuple[str, ...] = ()
    veto_asset_timeframes: tuple[str, ...] = ()


def build_trendline_guarded_replay(
    records: Iterable[Mapping[str, Any]],
    *,
    config: GuardedReplayConfig | None = None,
    source_path: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    cfg = config or GuardedReplayConfig()
    rows = [dict(record) for record in records]
    filtered = _filter_records(rows, asset=asset, timeframe=timeframe)
    labeled = [record for record in filtered if _has_lift(record)]
    replayed = [_replay_row(record, cfg) for record in labeled]
    guarded = [row for row in replayed if row["guarded"]]
    summary = _summary(labeled, replayed, guarded, cfg)
    return {
        "phase": "phase_tl_h20_trendline_guarded_replay",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(rows),
            "records_after_filter": len(filtered),
            "labeled_count": len(labeled),
            "changed_labeled_count": sum(1 for record in labeled if _bool(record.get("selection_changed"))),
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "warning_basket": [f"{field}={value}" for field, value in cfg.warning_basket],
            "allowed_asset_timeframes": list(cfg.allowed_asset_timeframes),
            "veto_asset_timeframes": list(cfg.veto_asset_timeframes),
            "min_guarded_samples": cfg.min_guarded_samples,
            "min_loss_saved_rate": cfg.min_loss_saved_rate,
            "min_net_lift_delta": cfg.min_net_lift_delta,
            **summary,
        },
        "grouped": {
            "asset_timeframe": _group_summary(replayed, ("asset", "timeframe"), cfg),
            "shadow_model": _group_summary(replayed, ("shadow_selected_model",), cfg),
            "risk_context": _group_summary(replayed, ("trendline_risk_context",), cfg),
            "confidence_annotation": _group_summary(replayed, ("trendline_confidence_annotation",), cfg),
        },
        "guarded_rows": _guarded_rows_summary(guarded),
    }


def _replay_row(record: Mapping[str, Any], config: GuardedReplayConfig) -> dict[str, Any]:
    original = _float(record.get("shadow_minus_baseline"), 0.0) or 0.0
    changed = _bool(record.get("selection_changed"))
    warning = any(_matches(record.get(field), value) for field, value in config.warning_basket)
    asset_timeframe = f"{str(record.get('asset') or '').upper()}|{record.get('timeframe') or ''}"
    allow_ok = not config.allowed_asset_timeframes or asset_timeframe in set(config.allowed_asset_timeframes)
    vetoed = asset_timeframe in set(config.veto_asset_timeframes)
    guarded = changed and warning and allow_ok and not vetoed
    return {
        **dict(record),
        "original_shadow_lift": original,
        "replayed_shadow_lift": 0.0 if guarded else original,
        "guarded": guarded,
        "warning_fired": warning,
        "asset_timeframe_guard_allowed": allow_ok,
        "asset_timeframe_guard_vetoed": vetoed,
        "saved_loss": -original if guarded and original < 0.0 else 0.0,
        "missed_good": original if guarded and original > 0.0 else 0.0,
    }


def _summary(
    labeled: list[dict[str, Any]],
    replayed: list[dict[str, Any]],
    guarded: list[dict[str, Any]],
    config: GuardedReplayConfig,
) -> dict[str, Any]:
    original_total = sum(row["original_shadow_lift"] for row in replayed)
    replayed_total = sum(row["replayed_shadow_lift"] for row in replayed)
    count = max(len(replayed), 1)
    loss_saved_count = sum(1 for row in guarded if row["saved_loss"] > 0.0)
    missed_good_count = sum(1 for row in guarded if row["missed_good"] > 0.0)
    guarded_count = len(guarded)
    loss_saved_rate = loss_saved_count / guarded_count if guarded_count else None
    net_delta = (replayed_total - original_total) / count
    pass_samples = guarded_count >= config.min_guarded_samples
    pass_loss_saved = loss_saved_rate is not None and loss_saved_rate >= config.min_loss_saved_rate
    pass_net = net_delta >= config.min_net_lift_delta
    status = "candidate_ready" if pass_samples and pass_loss_saved and pass_net else "needs_more_evidence"
    return {
        "original_total_shadow_lift": original_total,
        "replayed_total_shadow_lift": replayed_total,
        "original_avg_shadow_lift": original_total / count,
        "replayed_avg_shadow_lift": replayed_total / count,
        "net_lift_delta": net_delta,
        "guarded_count": guarded_count,
        "guarded_rate_over_labeled": guarded_count / count,
        "guarded_rate_over_changed": guarded_count / max(sum(1 for record in labeled if _bool(record.get("selection_changed"))), 1),
        "loss_saved_count": loss_saved_count,
        "missed_good_count": missed_good_count,
        "loss_saved_rate": loss_saved_rate,
        "loss_saved_total": sum(row["saved_loss"] for row in guarded),
        "missed_good_total": sum(row["missed_good"] for row in guarded),
        "pass_min_guarded_samples": pass_samples,
        "pass_loss_saved_rate": pass_loss_saved,
        "pass_net_lift_delta": pass_net,
        "replay_status": status,
    }


def render_trendline_guarded_replay_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    grouped = dict(report.get("grouped", {}))
    lines = [
        "# RegimeV2 Trendline Guarded Replay",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Labeled rows: {summary.get('labeled_count', 0)}",
        f"- Changed rows: {summary.get('changed_labeled_count', 0)}",
        f"- Guarded rows: {summary.get('guarded_count', 0)}",
        f"- Original avg lift: {summary.get('original_avg_shadow_lift')}",
        f"- Replayed avg lift: {summary.get('replayed_avg_shadow_lift')}",
        f"- Net lift delta: {summary.get('net_lift_delta')}",
        f"- Loss saved rate: {summary.get('loss_saved_rate')}",
        f"- Replay status: {summary.get('replay_status')}",
        "",
        "## Grouped Impact: Asset / Timeframe",
        "",
        "| Group | Rows | Guarded | Original avg | Replayed avg | Delta | Loss saved rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in grouped.get("asset_timeframe", []):
        lines.append(_group_row(row))
    lines.extend([
        "",
        "## Grouped Impact: Shadow Model",
        "",
        "| Group | Rows | Guarded | Original avg | Replayed avg | Delta | Loss saved rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in grouped.get("shadow_model", []):
        lines.append(_group_row(row))
    lines.extend([
        "",
        "## Grouped Impact: Risk Context",
        "",
        "| Group | Rows | Guarded | Original avg | Replayed avg | Delta | Loss saved rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in grouped.get("risk_context", []):
        lines.append(_group_row(row))
    lines.append("")
    return "\n".join(lines)


def _group_summary(rows: list[dict[str, Any]], keys: tuple[str, ...], config: GuardedReplayConfig) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = "|".join(str(row.get(item) or "none") for item in keys)
        grouped[key].append(row)
    out: list[dict[str, Any]] = []
    for key, items in grouped.items():
        guarded = [row for row in items if row["guarded"]]
        out.append({"group": key, "row_count": len(items), **_summary(items, items, guarded, config)})
    return sorted(out, key=lambda row: (-(row.get("net_lift_delta") or 0.0), str(row.get("group"))))


def _guarded_rows_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "asset_timeframe": _group_count(rows, ("asset", "timeframe")),
        "shadow_model": _count_key(rows, "shadow_selected_model"),
        "risk_context": _count_key(rows, "trendline_risk_context"),
        "confidence_annotation": _count_key(rows, "trendline_confidence_annotation"),
        "outcome_label": _count_key(rows, "outcome_label"),
    }


def _group_row(row: Mapping[str, Any]) -> str:
    return "| {group} | {rows} | {guarded} | {orig} | {replayed} | {delta} | {loss_rate} |".format(
        group=row.get("group"),
        rows=row.get("row_count"),
        guarded=row.get("guarded_count"),
        orig=row.get("original_avg_shadow_lift"),
        replayed=row.get("replayed_avg_shadow_lift"),
        delta=row.get("net_lift_delta"),
        loss_rate=row.get("loss_saved_rate"),
    )


def _filter_records(records: list[dict[str, Any]], *, asset: str | None, timeframe: str | None) -> list[dict[str, Any]]:
    asset_filter = asset.upper() if asset else None
    out: list[dict[str, Any]] = []
    for record in records:
        if asset_filter and str(record.get("asset", "")).upper() != asset_filter:
            continue
        if timeframe and str(record.get("timeframe", "")) != timeframe:
            continue
        out.append(record)
    return out


def _matches(observed: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        parsed = _float(observed, None)
        return parsed == expected
    return str(observed) == str(expected)


def _has_lift(record: Mapping[str, Any]) -> bool:
    return _float(record.get("shadow_minus_baseline"), None) is not None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


__all__ = [
    "GuardedReplayConfig",
    "build_trendline_guarded_replay",
    "render_trendline_guarded_replay_markdown",
]
