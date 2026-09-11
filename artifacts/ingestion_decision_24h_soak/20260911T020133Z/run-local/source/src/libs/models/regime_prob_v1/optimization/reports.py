"""Review-friendly reports for RegimeProbV1 optimization runs."""

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
    baseline_edge = _segment_metric(baseline_oos, "oos", "mean_edge_return")
    tuned_edge = _segment_metric(tuned_oos, "oos", "mean_edge_return")
    baseline_positive_rate = _segment_metric(baseline_oos, "oos", "positive_window_rate")
    tuned_positive_rate = _segment_metric(tuned_oos, "oos", "positive_window_rate")

    return {
        "baseline_deployed": bool(baseline_oos.get("deployed")),
        "tuned_deployed": bool(tuned_oos.get("deployed")),
        "baseline_oos_score": baseline_score,
        "tuned_oos_score": tuned_score,
        "oos_score_delta": _round_or_none(_diff(tuned_score, baseline_score)),
        "baseline_mean_edge_return": baseline_edge,
        "tuned_mean_edge_return": tuned_edge,
        "mean_edge_return_delta": _round_or_none(_diff(tuned_edge, baseline_edge)),
        "baseline_positive_window_rate": baseline_positive_rate,
        "tuned_positive_window_rate": tuned_positive_rate,
        "positive_window_rate_delta": _round_or_none(_diff(tuned_positive_rate, baseline_positive_rate)),
    }


def build_promotion_gate(
    baseline_oos: dict[str, Any] | None,
    tuned_oos: dict[str, Any] | None,
    *,
    min_oos_score_delta: float = 0.0,
    min_mean_edge_return_delta: float = 0.0,
    positive_window_rate_tolerance: float = 0.0,
    max_brier_score_delta: float = 0.0,
    max_ece_delta: float = 0.0,
) -> dict[str, Any]:
    """Apply the hard default-vs-tuned promotion gate for shadow-ready params."""
    reasons: list[str] = []
    delta = summarize_oos_delta(baseline_oos, tuned_oos)
    tuned_gate_passed = bool((tuned_oos or {}).get("deployed"))

    if not tuned_gate_passed:
        raw_reasons = list((tuned_oos or {}).get("rejection_reasons") or [])
        if raw_reasons:
            reasons.extend(f"tuned:{reason}" for reason in raw_reasons)
        else:
            reasons.append("tuned:oos_gate_failed")

    if baseline_oos is None:
        reasons.append("baseline_not_evaluated")
    elif delta is None:
        reasons.append("baseline_delta_unavailable")
    else:
        if delta.get("oos_score_delta") is None or float(delta["oos_score_delta"]) <= float(min_oos_score_delta):
            reasons.append("oos_score_not_above_baseline")
        if (
            delta.get("mean_edge_return_delta") is None
            or float(delta["mean_edge_return_delta"]) < float(min_mean_edge_return_delta)
        ):
            reasons.append("mean_edge_return_not_above_baseline")
        positive_delta = delta.get("positive_window_rate_delta")
        if positive_delta is None or float(positive_delta) < -float(positive_window_rate_tolerance):
            reasons.append("positive_window_rate_regressed")

        brier_delta = _round_or_none(
            _diff(
                _segment_metric(tuned_oos, "oos", "mean_brier_score"),
                _segment_metric(baseline_oos, "oos", "mean_brier_score"),
            )
        )
        ece_delta = _round_or_none(
            _diff(
                _segment_metric(tuned_oos, "oos", "mean_expected_calibration_error"),
                _segment_metric(baseline_oos, "oos", "mean_expected_calibration_error"),
            )
        )
        if brier_delta is None or float(brier_delta) > float(max_brier_score_delta):
            reasons.append("brier_score_regressed")
        if ece_delta is None or float(ece_delta) > float(max_ece_delta):
            reasons.append("expected_calibration_error_regressed")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "ready": not unique_reasons,
        "rejection_reasons": unique_reasons,
        "requirements": {
            "min_oos_score_delta": float(min_oos_score_delta),
            "min_mean_edge_return_delta": float(min_mean_edge_return_delta),
            "positive_window_rate_tolerance": float(positive_window_rate_tolerance),
            "max_brier_score_delta": float(max_brier_score_delta),
            "max_ece_delta": float(max_ece_delta),
        },
        "metrics": {
            "oos_score_delta": None if delta is None else delta.get("oos_score_delta"),
            "mean_edge_return_delta": None if delta is None else delta.get("mean_edge_return_delta"),
            "positive_window_rate_delta": None if delta is None else delta.get("positive_window_rate_delta"),
            "brier_score_delta": _round_or_none(
                _diff(
                    _segment_metric(tuned_oos, "oos", "mean_brier_score"),
                    _segment_metric(baseline_oos, "oos", "mean_brier_score"),
                )
            ),
            "expected_calibration_error_delta": _round_or_none(
                _diff(
                    _segment_metric(tuned_oos, "oos", "mean_expected_calibration_error"),
                    _segment_metric(baseline_oos, "oos", "mean_expected_calibration_error"),
                )
            ),
        },
    }


def render_markdown_report(result: dict[str, Any]) -> str:
    """Render a compact markdown audit for a single RegimeProbV1 optimization run."""
    best = result.get("best_trial") or {}
    validation = ((best.get("validation") or {}).get("aggregate") or {})
    oos = result.get("oos") or {}
    tuned_oos = ((oos.get("oos") or {}).get("aggregate") or {})
    delta = result.get("default_vs_tuned")
    promotion = result.get("promotion_gate") or {}

    lines = [
        f"# RegimeProbV1 Optimization: {result.get('asset')} {result.get('timeframe')}",
        "",
        "## Run",
        f"- Profile: `{result.get('profile')}`",
        f"- Playbook: `{result.get('playbook') or 'multi-playbook'}`",
        f"- Horizon: `{result.get('horizon')}`",
        f"- Trials: `{result.get('completed_trials')}/{result.get('n_trials')}` completed, `{result.get('rejected_trials')}` rejected",
        f"- Study: `{result.get('study_name')}`",
        f"- Storage: `{result.get('storage') or 'in-memory'}`",
        f"- Data rows: `{(result.get('data') or {}).get('rows')}`",
        "",
        "## Best Trial",
        f"- Trial: `#{best.get('number')}`",
        f"- Validation objective: `{_fmt(best.get('value'))}`",
        f"- Validation score: `{_fmt(validation.get('score'))}`",
        f"- Validation positive windows: `{_fmt(validation.get('positive_window_rate'))}`",
        f"- Validation support rate: `{_fmt(validation.get('mean_support_rate'))}`",
        f"- Validation edge return: `{_fmt(validation.get('mean_edge_return'))}`",
        "",
        "## OOS Gate",
        f"- Deployed: `{oos.get('deployed')}`",
        f"- Raw OOS gate passed: `{oos.get('oos_gate_passed', oos.get('deployed'))}`",
        f"- Rejection reasons: `{oos.get('rejection_reasons')}`",
        f"- OOS score: `{_fmt(tuned_oos.get('score'))}`",
        f"- OOS edge return: `{_fmt(tuned_oos.get('mean_edge_return'))}`",
        f"- OOS positive windows: `{_fmt(tuned_oos.get('positive_window_rate'))}`",
        f"- OOS support rate: `{_fmt(tuned_oos.get('mean_support_rate'))}`",
        f"- OOS Brier: `{_fmt(tuned_oos.get('mean_brier_score'))}`",
        f"- OOS ECE: `{_fmt(tuned_oos.get('mean_expected_calibration_error'))}`",
    ]

    if oos.get("hmm_state_source") is not None:
        lines.extend(
            [
                "",
                "## HMM Support",
                f"- State source: `{oos.get('hmm_state_source')}`",
                f"- In-sample rows: `{oos.get('hmm_in_sample_rows')}`",
                f"- OOS-filtered rows: `{oos.get('hmm_oos_filtered_rows')}`",
                f"- Proxy-fallback rows: `{oos.get('hmm_proxy_fallback_rows')}`",
                f"- OOS-filtered support rate: `{_fmt(oos.get('hmm_oos_filtered_support_rate'))}`",
            ]
        )

    activation_audit = oos.get("full_shadow_activation_audit")
    if activation_audit:
        overall = activation_audit.get("overall") or {}
        validation_audit = ((activation_audit.get("by_segment") or {}).get("validation") or {})
        oos_audit = ((activation_audit.get("by_segment") or {}).get("oos") or {})
        lines.extend(
            [
                "",
                "## Full Shadow Activation Audit",
                f"- Overall active rate: `{_fmt(((overall.get('final_selection_stage') or {}).get('final_decision_active_rate')) )}`",
                f"- Overall final reasons: `{((overall.get('final_selection_stage') or {}).get('final_reason_distribution'))}`",
                f"- Validation rows: `{validation_audit.get('rows')}`",
                f"- Validation active rate: `{_fmt(((validation_audit.get('final_selection_stage') or {}).get('final_decision_active_rate')) )}`",
                f"- OOS rows: `{oos_audit.get('rows')}`",
                f"- OOS active rate: `{_fmt(((oos_audit.get('final_selection_stage') or {}).get('final_decision_active_rate')) )}`",
                "",
                "```json",
            ]
        )
        lines.extend(_json_lines(activation_audit))
        lines.append("```")

    if promotion:
        lines.extend(
            [
                "",
                "## Promotion Gate",
                f"- Ready: `{promotion.get('ready')}`",
                f"- Rejection reasons: `{promotion.get('rejection_reasons')}`",
                f"- OOS score delta: `{_fmt(((promotion.get('metrics') or {}).get('oos_score_delta')) )}`",
                f"- Mean edge return delta: `{_fmt(((promotion.get('metrics') or {}).get('mean_edge_return_delta')) )}`",
                f"- Positive window rate delta: `{_fmt(((promotion.get('metrics') or {}).get('positive_window_rate_delta')) )}`",
                f"- Brier delta: `{_fmt(((promotion.get('metrics') or {}).get('brier_score_delta')) )}`",
                f"- ECE delta: `{_fmt(((promotion.get('metrics') or {}).get('expected_calibration_error_delta')) )}`",
            ]
        )

    if delta is not None:
        lines.extend(
            [
                "",
                "## Default Vs Tuned",
                f"- Baseline deployed: `{delta.get('baseline_deployed')}`",
                f"- Tuned deployed: `{delta.get('tuned_deployed')}`",
                f"- OOS score delta: `{_fmt(delta.get('oos_score_delta'))}`",
                f"- Mean edge return delta: `{_fmt(delta.get('mean_edge_return_delta'))}`",
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


__all__ = ["build_promotion_gate", "render_markdown_report", "summarize_oos_delta"]
