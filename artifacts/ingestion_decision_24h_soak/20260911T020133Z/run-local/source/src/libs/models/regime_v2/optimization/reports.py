"""Review-friendly reports for RegimeV2 optimization runs."""

from __future__ import annotations

from typing import Any


def summarize_oos_delta(
    baseline_oos: dict[str, Any] | None,
    tuned_oos: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compare tuned OOS metrics against the current default-parameter baseline."""
    if baseline_oos is None or tuned_oos is None:
        return None

    baseline_score = _segment_score(baseline_oos, "oos")
    tuned_score = _segment_score(tuned_oos, "oos")
    baseline_lift = _segment_metric(baseline_oos, "oos", "mean_downstream_lift")
    tuned_lift = _segment_metric(tuned_oos, "oos", "mean_downstream_lift")
    baseline_positive_rate = _segment_metric(baseline_oos, "oos", "positive_window_rate")
    tuned_positive_rate = _segment_metric(tuned_oos, "oos", "positive_window_rate")

    return {
        "baseline_deployed": bool(baseline_oos.get("deployed")),
        "tuned_deployed": bool(tuned_oos.get("deployed")),
        "baseline_oos_score": baseline_score,
        "tuned_oos_score": tuned_score,
        "oos_score_delta": _round_or_none(_diff(tuned_score, baseline_score)),
        "baseline_mean_downstream_lift": baseline_lift,
        "tuned_mean_downstream_lift": tuned_lift,
        "mean_downstream_lift_delta": _round_or_none(_diff(tuned_lift, baseline_lift)),
        "baseline_positive_window_rate": baseline_positive_rate,
        "tuned_positive_window_rate": tuned_positive_rate,
        "positive_window_rate_delta": _round_or_none(_diff(tuned_positive_rate, baseline_positive_rate)),
    }


def render_markdown_report(result: dict[str, Any]) -> str:
    """Render a compact markdown audit for a single RegimeV2 optimization run."""
    best = result.get("best_trial") or {}
    validation = ((best.get("validation") or {}).get("aggregate") or {})
    oos = result.get("oos") or {}
    tuned_oos = ((oos.get("oos") or {}).get("aggregate") or {})
    delta = result.get("default_vs_tuned")

    lines = [
        f"# RegimeV2 Optimization: {result.get('asset')} {result.get('timeframe')}",
        "",
        "## Run",
        f"- Profile: `{result.get('profile')}`",
        f"- Trials: `{result.get('completed_trials')}/{result.get('n_trials')}` completed, `{result.get('rejected_trials')}` rejected",
        f"- Study: `{result.get('study_name')}`",
        f"- Storage: `{result.get('storage') or 'in-memory'}`",
        f"- Data rows: `{(result.get('data') or {}).get('rows')}`",
        f"- Data range: `{(result.get('data') or {}).get('start')}` to `{(result.get('data') or {}).get('end')}`",
        "",
        "## Best Trial",
        f"- Trial: `#{best.get('number')}`",
        f"- Validation objective: `{_fmt(best.get('value'))}`",
        f"- Validation score: `{_fmt(validation.get('score'))}`",
        f"- Validation positive windows: `{_fmt(validation.get('positive_window_rate'))}`",
        f"- Validation support rate: `{_fmt(validation.get('mean_support_rate'))}`",
        f"- Validation flip rate: `{_fmt(validation.get('mean_flip_rate'))}`",
        "",
        "## OOS Gate",
        f"- Deployed: `{oos.get('deployed')}`",
        f"- Rejection reasons: `{oos.get('rejection_reasons')}`",
        f"- OOS score: `{_fmt(tuned_oos.get('score'))}`",
        f"- OOS mean downstream lift: `{_fmt(tuned_oos.get('mean_downstream_lift'))}`",
        f"- OOS positive windows: `{_fmt(tuned_oos.get('positive_window_rate'))}`",
        f"- OOS support rate: `{_fmt(tuned_oos.get('mean_support_rate'))}`",
        f"- OOS flip rate: `{_fmt(tuned_oos.get('mean_flip_rate'))}`",
    ]

    if delta is not None:
        lines.extend(
            [
                "",
                "## Default Vs Tuned",
                f"- Baseline deployed: `{delta.get('baseline_deployed')}`",
                f"- Tuned deployed: `{delta.get('tuned_deployed')}`",
                f"- OOS score delta: `{_fmt(delta.get('oos_score_delta'))}`",
                f"- Mean downstream lift delta: `{_fmt(delta.get('mean_downstream_lift_delta'))}`",
                f"- Positive window rate delta: `{_fmt(delta.get('positive_window_rate_delta'))}`",
            ]
        )

    sweep = result.get("threshold_sweep")
    if sweep:
        lines.extend(["", "## Threshold Sweep", "| Param | Value | OOS Score | Deployed | Reasons |", "|---|---:|---:|---|---|"])
        for row in sweep.get("rows", [])[:20]:
            lines.append(
                f"| `{row.get('param')}` | `{_fmt(row.get('value'))}` | `{_fmt(row.get('oos_score'))}` | "
                f"`{row.get('deployed')}` | `{row.get('rejection_reasons')}` |"
            )

    lines.extend(["", "## Deploy Params", "```json"])
    lines.extend(_json_lines(result.get("deploy_params") or {}))
    lines.append("```")
    return "\n".join(lines) + "\n"


def _segment_score(payload: dict[str, Any], segment: str) -> float | None:
    return _segment_metric(payload, segment, "score")


def _segment_metric(payload: dict[str, Any], segment: str, metric: str) -> float | None:
    value = (((payload.get(segment) or {}).get("aggregate") or {}).get(metric))
    if value is None:
        return None
    return float(value)


def _diff(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8f}"
    return str(value)


def _json_lines(payload: dict[str, Any]) -> list[str]:
    import json

    return json.dumps(payload, indent=2, sort_keys=True).splitlines()


__all__ = ["render_markdown_report", "summarize_oos_delta"]
