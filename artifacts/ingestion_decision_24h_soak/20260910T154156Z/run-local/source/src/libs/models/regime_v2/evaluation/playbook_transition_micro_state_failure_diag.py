"""Phase 7X failure-window diagnostics for transition micro-states.

This module explains weak rolling windows from Phase 7W. It is diagnostic only:
window outcome tags are used to understand failures, not to create live routing
rules or timestamp-specific filters.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def build_transition_micro_state_failure_diag_report(
    robust_payload: Mapping[str, Any],
    *,
    min_tail_loss: float = 0.02,
) -> dict[str, Any]:
    """Build diagnostics over a 7W robustness payload."""
    reports = list(robust_payload.get("variant_reports", []))
    windows = []
    for report in reports:
        summary = dict(report.get("summary", {}))
        asset = summary.get("asset")
        timeframe = summary.get("timeframe")
        for window in dict(report.get("robust_report", {})).get("windows", []):
            windows.append(_classify_window(asset, timeframe, window, min_tail_loss=float(min_tail_loss)))
    failure_windows = [row for row in windows if row.get("failure_class") != "supported_breakout_better"]
    supported_failures = [row for row in failure_windows if row.get("support_ok")]
    support_thin = [row for row in failure_windows if not row.get("support_ok")]
    signatures = _signature_rows(failure_windows)
    return {
        "phase": "phase_7x_transition_micro_state_failure_diag",
        "summary": {
            "window_count": len(windows),
            "failure_window_count": len(failure_windows),
            "supported_failure_count": len(supported_failures),
            "support_thin_count": len(support_thin),
            "assets": sorted({str(row.get("asset")) for row in windows}),
            "failure_class_distribution": _counts(row.get("failure_class") for row in windows),
            "signature_distribution": _tag_counts(failure_windows),
            "asset_summary": _asset_summary(windows),
            "worst_window": _worst_window(windows),
            "recommendation": _recommendation(supported_failures, support_thin),
            "criteria": {"min_tail_loss": float(min_tail_loss)},
        },
        "windows": windows,
        "failure_windows": failure_windows,
        "failure_signatures": signatures,
    }


def render_transition_micro_state_failure_diag_markdown(report: Mapping[str, Any]) -> str:
    """Render Phase 7X diagnostics as Markdown."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7X Transition Micro-State Failure Diagnostics",
        "",
        f"- Windows: {summary.get('window_count', 0)}",
        f"- Failure windows: {summary.get('failure_window_count', 0)}",
        f"- Supported failures: {summary.get('supported_failure_count', 0)}",
        f"- Support-thin failures: {summary.get('support_thin_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Worst window: {summary.get('worst_window')}",
        "",
        "## Asset summary",
        "",
        "| Asset | Windows | Supported failures | Support-thin | Worst compression | Worst breakout | Top signatures |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for asset, row in dict(summary.get("asset_summary", {})).items():
        lines.append(
            "| {asset} | {window_count} | {supported_failure_count} | {support_thin_count} | {worst_compression_return} | {worst_breakout_return} | {top_signatures} |".format(
                asset=asset,
                window_count=row.get("window_count"),
                supported_failure_count=row.get("supported_failure_count"),
                support_thin_count=row.get("support_thin_count"),
                worst_compression_return=row.get("worst_compression_return"),
                worst_breakout_return=row.get("worst_breakout_return"),
                top_signatures=row.get("top_signatures"),
            )
        )
    lines.extend([
        "",
        "## Failure signatures",
        "",
        "| Signature | Windows | Assets | Avg breakout | Avg compression | Worst compression |",
        "|---|---:|---|---:|---:|---:|",
    ])
    for row in report.get("failure_signatures", [])[:30]:
        lines.append(
            "| {signature} | {window_count} | {assets} | {avg_breakout_return} | {avg_compression_return} | {worst_compression_return} |".format(
                signature=row.get("signature"),
                window_count=row.get("window_count"),
                assets=",".join(row.get("assets", [])),
                avg_breakout_return=row.get("avg_breakout_return"),
                avg_compression_return=row.get("avg_compression_return"),
                worst_compression_return=row.get("worst_compression_return"),
            )
        )
    lines.extend([
        "",
        "## Failure windows",
        "",
        "| Asset | Window | Class | Support | Breakout active | Compression active | Breakout avg | Compression avg | Tags |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ])
    for row in report.get("failure_windows", []):
        lines.append(
            "| {asset} | {window_id} | {failure_class} | {support_ok} | {breakout_setup_active} | {compression_active} | {breakout_setup_avg_return} | {compression_avg_return} | {tags} |".format(
                asset=row.get("asset"),
                window_id=row.get("window_id"),
                failure_class=row.get("failure_class"),
                support_ok=row.get("support_ok"),
                breakout_setup_active=row.get("breakout_setup_active"),
                compression_active=row.get("compression_active"),
                breakout_setup_avg_return=row.get("breakout_setup_avg_return"),
                compression_avg_return=row.get("compression_avg_return"),
                tags=",".join(row.get("failure_tags", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _classify_window(asset: str | None, timeframe: str | None, window: Mapping[str, Any], *, min_tail_loss: float) -> dict[str, Any]:
    row = dict(window)
    support_ok = bool(row.get("support_ok"))
    breakout_better = bool(row.get("breakout_better"))
    b_avg = _float(row.get("breakout_setup_avg_return"), None)
    c_avg = _float(row.get("compression_avg_return"), None)
    b_worst = _float(row.get("breakout_setup_worst_return"), None)
    c_worst = _float(row.get("compression_worst_return"), None)
    tags: list[str] = []
    if not support_ok:
        tags.append("support_thin")
    if support_ok and not breakout_better:
        tags.append("compression_beats_breakout")
    if b_avg is not None and b_avg < 0.0:
        tags.append("breakout_avg_negative")
    if c_avg is not None and c_avg > 0.0:
        tags.append("compression_avg_positive")
    if b_avg is not None and c_avg is not None and b_avg < 0.0 and c_avg > 0.0:
        tags.append("state_inversion")
    if c_worst is not None and c_worst <= -abs(float(min_tail_loss)):
        tags.append("compression_tail_loss")
    if b_worst is not None and b_worst <= -abs(float(min_tail_loss)):
        tags.append("breakout_tail_loss")
    if b_avg is not None and c_avg is not None and b_avg < 0.0 and c_avg < 0.0:
        tags.append("both_avg_negative")
    failure_class = "supported_breakout_better"
    if not support_ok:
        failure_class = "support_thin"
    elif not breakout_better:
        failure_class = "supported_mixed_failure"
    return {
        "asset": asset,
        "timeframe": timeframe,
        "window_id": row.get("window_id"),
        "is_full": row.get("is_full"),
        "support_ok": support_ok,
        "breakout_better": breakout_better,
        "failure_class": failure_class,
        "failure_tags": sorted(set(tags)),
        "breakout_setup_active": row.get("breakout_setup_active"),
        "compression_active": row.get("compression_active"),
        "breakout_setup_avg_return": b_avg,
        "compression_avg_return": c_avg,
        "breakout_setup_worst_return": b_worst,
        "compression_worst_return": c_worst,
    }


def _signature_rows(windows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in windows:
        for tag in row.get("failure_tags", []):
            buckets[str(tag)].append(row)
    out = []
    for tag, rows in buckets.items():
        b_avgs = [_float(row.get("breakout_setup_avg_return")) for row in rows if row.get("breakout_setup_avg_return") is not None]
        c_avgs = [_float(row.get("compression_avg_return")) for row in rows if row.get("compression_avg_return") is not None]
        c_worst = [_float(row.get("compression_worst_return")) for row in rows if row.get("compression_worst_return") is not None]
        out.append(
            {
                "signature": tag,
                "window_count": len(rows),
                "assets": sorted({str(row.get("asset")) for row in rows}),
                "avg_breakout_return": _mean(b_avgs),
                "avg_compression_return": _mean(c_avgs),
                "worst_compression_return": min(c_worst) if c_worst else None,
            }
        )
    out.sort(key=lambda row: (row.get("window_count") or 0, -abs(_float(row.get("worst_compression_return"), 0.0))), reverse=True)
    return out


def _asset_summary(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for asset in sorted({str(row.get("asset")) for row in windows}):
        rows = [row for row in windows if str(row.get("asset")) == asset]
        fail = [row for row in rows if row.get("failure_class") != "supported_breakout_better"]
        tag_counter = Counter(tag for row in fail for tag in row.get("failure_tags", []))
        c_worst = [_float(row.get("compression_worst_return")) for row in rows if row.get("compression_worst_return") is not None]
        b_worst = [_float(row.get("breakout_setup_worst_return")) for row in rows if row.get("breakout_setup_worst_return") is not None]
        out[asset] = {
            "window_count": len(rows),
            "supported_failure_count": sum(1 for row in fail if row.get("support_ok")),
            "support_thin_count": sum(1 for row in fail if not row.get("support_ok")),
            "worst_compression_return": min(c_worst) if c_worst else None,
            "worst_breakout_return": min(b_worst) if b_worst else None,
            "top_signatures": dict(tag_counter.most_common(5)),
        }
    return out


def _worst_window(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not windows:
        return None
    row = sorted(windows, key=lambda item: _float(item.get("compression_worst_return"), 0.0))[0]
    return {
        "asset": row.get("asset"),
        "window_id": row.get("window_id"),
        "failure_class": row.get("failure_class"),
        "compression_worst_return": row.get("compression_worst_return"),
        "breakout_setup_worst_return": row.get("breakout_setup_worst_return"),
        "failure_tags": row.get("failure_tags", []),
    }


def _recommendation(supported_failures: Sequence[Mapping[str, Any]], support_thin: Sequence[Mapping[str, Any]]) -> str:
    if supported_failures:
        return "diagnose_supported_mixed_windows_next"
    if support_thin:
        return "collect_more_support_before_next_rule"
    return "no_failure_windows_detected"


def _tag_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(tag for row in rows for tag in row.get("failure_tags", [])).most_common())


def _counts(values) -> dict[str, int]:
    return dict(Counter(str(value) for value in values).most_common())


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_transition_micro_state_failure_diag_report", "render_transition_micro_state_failure_diag_markdown"]
