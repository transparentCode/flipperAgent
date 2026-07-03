"""Offline RegimeV2 trend overlay experiment for selection candidates.

This does not change the live SelectionLayer.  It replays candidate rows against
RegimeV2 comparison columns and compares baseline top picks with an overlay that
boosts Momentum/TrendFollowing candidates aligned with RegimeV2 trend evidence
and penalizes conflicting candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_DEFAULT_OVERLAY_MODELS = (
    "Momentum",
    "MomentumV2",
    "TrendFollowing",
    "TrendFollowingModel",
)

_DEFAULT_BREAKOUT_MODELS = (
    "SqueezeBreakout",
    "SqueezeBreakoutModel",
)

_DEFAULT_MEAN_REVERSION_MODELS = (
    "RegimePullbackScorer",
    "RegimePullback",
    "RegressionPullback",
)


@dataclass(frozen=True)
class RegimeV2TrendOverlayConfig:
    """Config for the offline RegimeV2 trend selection overlay."""

    target_model_names: tuple[str, ...] = _DEFAULT_OVERLAY_MODELS
    breakout_model_names: tuple[str, ...] = _DEFAULT_BREAKOUT_MODELS
    mean_reversion_model_names: tuple[str, ...] = _DEFAULT_MEAN_REVERSION_MODELS
    top_k: int = 1
    min_count: int = 20
    fee_bps: float = 0.0
    trend_score_floor: float = 0.24
    breakout_score_floor: float = 0.24
    mean_reversion_score_floor: float = 0.24
    aligned_boost: float = 0.35
    conflict_penalty: float = 0.70
    suppress_conflicts: bool = False


@dataclass(frozen=True)
class SelectionOverlayMetric:
    """Metrics for baseline vs overlay selected candidates."""

    name: str
    count: int
    mean_edge: float | None
    median_edge: float | None
    win_rate: float | None
    q25_edge: float | None
    q75_edge: float | None
    enough_samples: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": self.count,
            "mean_edge": self.mean_edge,
            "median_edge": self.median_edge,
            "win_rate": self.win_rate,
            "q25_edge": self.q25_edge,
            "q75_edge": self.q75_edge,
            "enough_samples": self.enough_samples,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SelectionOverlayResult:
    """Result of an offline selection overlay experiment."""

    baseline: SelectionOverlayMetric
    overlay: SelectionOverlayMetric
    gated: SelectionOverlayMetric
    summary: dict[str, Any]
    selected_frame: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "overlay": self.overlay.to_dict(),
            "gated": self.gated.to_dict(),
            "summary": dict(self.summary),
            "selected_rows": int(len(self.selected_frame)),
        }


def run_regime_v2_trend_selection_overlay(
    comparison_frame: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    config: RegimeV2TrendOverlayConfig | None = None,
) -> SelectionOverlayResult:
    """Compare baseline selection against a RegimeV2 trend overlay."""
    cfg = config or RegimeV2TrendOverlayConfig()
    joined = _prepare_joined_frame(comparison_frame, candidates, cfg)
    if joined.empty:
        empty = _metric(pd.Series(dtype=float), name="baseline_top", cfg=cfg, metadata={})
        return SelectionOverlayResult(baseline=empty, overlay=empty, gated=empty, summary=_summary(empty, empty, empty, pd.DataFrame(), cfg), selected_frame=pd.DataFrame())

    baseline_selected = _select_top(joined, score_column="_base_selection_score", top_k=cfg.top_k)
    overlay_selected = _select_top(joined, score_column="_overlay_selection_score", top_k=cfg.top_k)
    gated_selected = _select_top(
        joined[joined["_overlay_aligned_boost"]],
        score_column="_base_selection_score",
        top_k=cfg.top_k,
    )

    baseline = _metric(
        baseline_selected["_candidate_edge"],
        name="baseline_top",
        cfg=cfg,
        metadata={"top_k": cfg.top_k},
    )
    overlay = _metric(
        overlay_selected["_candidate_edge"],
        name="regime_v2_trend_overlay_top",
        cfg=cfg,
        metadata={"top_k": cfg.top_k},
    )
    gated = _metric(
        gated_selected["_candidate_edge"],
        name="regime_v2_trend_gated_top",
        cfg=cfg,
        metadata={"top_k": cfg.top_k, "gated": True},
    )
    selected = _selected_comparison_frame(baseline_selected, overlay_selected, gated_selected)
    return SelectionOverlayResult(
        baseline=baseline,
        overlay=overlay,
        gated=gated,
        summary=_summary(baseline, overlay, gated, selected, cfg),
        selected_frame=selected,
    )


def _prepare_joined_frame(comparison_frame: pd.DataFrame, candidates: pd.DataFrame, cfg: RegimeV2TrendOverlayConfig) -> pd.DataFrame:
    required = {"model_name", "direction"}
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"Selection overlay candidates missing required columns: {missing}")

    comparison = comparison_frame.copy()
    comparison["_join_key"] = _index_join_key(comparison.index).to_numpy()
    cand = candidates.copy()
    cand["_join_key"] = _candidate_join_key(cand, comparison_frame.index).to_numpy()
    joined = cand.merge(comparison, on="_join_key", how="left", suffixes=("", "_regime"))
    if joined.empty:
        return joined

    if "edge_score" not in joined.columns:
        joined["edge_score"] = 1.0
    if "conviction" not in joined.columns:
        joined["conviction"] = 1.0

    direction = pd.to_numeric(joined["direction"], errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    conviction = pd.to_numeric(joined["conviction"], errors="coerce").fillna(1.0).clip(lower=0.0)
    edge_abs = pd.to_numeric(joined["edge_score"], errors="coerce").fillna(1.0).abs()
    fwd = pd.to_numeric(joined.get("fwd_return"), errors="coerce")
    fee = float(cfg.fee_bps) / 10_000.0

    joined["_base_selection_score"] = edge_abs * conviction
    joined["_candidate_edge"] = direction * fwd * edge_abs * conviction - fee
    joined["_regime_side"] = _regime_trend_side(joined)
    joined["_direction_agrees"] = (joined["_regime_side"] != 0.0) & (direction == joined["_regime_side"])
    joined["_direction_conflicts"] = (joined["_regime_side"] != 0.0) & (direction == -joined["_regime_side"])
    model_names = joined["model_name"].astype(str)
    joined["_target_model"] = model_names.isin(set(cfg.target_model_names))
    joined["_breakout_model"] = model_names.isin(set(cfg.breakout_model_names))
    joined["_mean_reversion_model"] = model_names.isin(set(cfg.mean_reversion_model_names))

    trend_allowed = _bool_column(joined, "regime_v2_policy_allow_trend_following", default=False)
    trend_score = _numeric_column(joined, "regime_v2_policy_trend_score", default=0.0)
    trend_active = trend_allowed | (trend_score >= cfg.trend_score_floor)
    trend_aligned = joined["_target_model"] & trend_active & joined["_direction_agrees"]
    trend_conflict = joined["_target_model"] & trend_active & joined["_direction_conflicts"]

    breakout_allowed = _bool_column(joined, "regime_v2_policy_allow_breakout", default=False)
    breakout_score = _numeric_column(joined, "regime_v2_policy_breakout_score", default=0.0)
    breakout_active = breakout_allowed | (breakout_score >= cfg.breakout_score_floor)
    breakout_direction_ok = (joined["_regime_side"] == 0.0) | joined["_direction_agrees"]
    breakout_aligned = joined["_breakout_model"] & breakout_active & breakout_direction_ok & (direction != 0.0)
    breakout_conflict = joined["_breakout_model"] & breakout_active & joined["_direction_conflicts"]

    mean_reversion_allowed = _bool_column(joined, "regime_v2_policy_allow_mean_reversion", default=False)
    mean_reversion_score = _numeric_column(joined, "regime_v2_policy_mean_reversion_score", default=0.0)
    mean_reversion_active = mean_reversion_allowed | (mean_reversion_score >= cfg.mean_reversion_score_floor)
    mean_reversion_aligned = joined["_mean_reversion_model"] & mean_reversion_active & (direction != 0.0)

    playbook_score = pd.concat(
        [
            trend_score.where(trend_aligned, 0.0),
            breakout_score.where(breakout_aligned, 0.0),
            mean_reversion_score.where(mean_reversion_aligned, 0.0),
        ],
        axis=1,
    ).max(axis=1)

    overlay_score = joined["_base_selection_score"].copy()
    aligned_mask = trend_aligned | breakout_aligned | mean_reversion_aligned
    conflict_mask = trend_conflict | breakout_conflict
    boost_factor = 1.0 + cfg.aligned_boost * playbook_score.clip(lower=0.0, upper=1.0)
    overlay_score.loc[aligned_mask] = overlay_score.loc[aligned_mask] * boost_factor.loc[aligned_mask]
    if cfg.suppress_conflicts:
        overlay_score.loc[conflict_mask] = 0.0
    else:
        overlay_score.loc[conflict_mask] = overlay_score.loc[conflict_mask] * max(0.0, 1.0 - cfg.conflict_penalty)

    joined["_overlay_selection_score"] = overlay_score
    joined["_overlay_aligned_boost"] = aligned_mask
    joined["_overlay_conflict_penalty"] = conflict_mask
    joined["_overlay_playbook"] = np.select(
        [trend_aligned, breakout_aligned, mean_reversion_aligned],
        ["trend", "breakout", "mean_reversion"],
        default="none",
    )
    return joined.dropna(subset=["_candidate_edge"])


def _select_top(frame: pd.DataFrame, *, score_column: str, top_k: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    top_k = max(1, int(top_k))
    sorted_frame = frame.sort_values(["_join_key", score_column], ascending=[True, False])
    return sorted_frame.groupby("_join_key", as_index=False, group_keys=False).head(top_k).copy()


def _selected_comparison_frame(baseline: pd.DataFrame, overlay: pd.DataFrame, gated: pd.DataFrame) -> pd.DataFrame:
    diagnostics = _diagnostic_columns(overlay)
    b = baseline[["_join_key", "model_name", "direction", "_candidate_edge", "_base_selection_score"]].copy()
    b = b.rename(columns={"model_name": "baseline_model", "direction": "baseline_direction", "_candidate_edge": "baseline_edge", "_base_selection_score": "baseline_score"})
    o = overlay[["_join_key", "model_name", "direction", "_candidate_edge", "_overlay_selection_score", "_overlay_aligned_boost", "_overlay_conflict_penalty", "_overlay_playbook"]].copy()
    o = o.rename(columns={"model_name": "overlay_model", "direction": "overlay_direction", "_candidate_edge": "overlay_edge", "_overlay_selection_score": "overlay_score"})
    g = gated[["_join_key", "model_name", "direction", "_candidate_edge", "_base_selection_score"]].copy() if not gated.empty else pd.DataFrame(columns=["_join_key", "gated_model", "gated_direction", "gated_edge", "gated_score"])
    if not g.empty:
        g = g.rename(columns={"model_name": "gated_model", "direction": "gated_direction", "_candidate_edge": "gated_edge", "_base_selection_score": "gated_score"})
    return b.merge(o, on="_join_key", how="outer").merge(g, on="_join_key", how="outer").merge(diagnostics, on="_join_key", how="left")


def _diagnostic_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep regime context needed by offline failure diagnostics."""
    columns = [
        "_join_key",
        "_regime_side",
        "_direction_agrees",
        "_direction_conflicts",
        "regime_v2_trend_direction",
        "regime_v2_trend_strength",
        "regime_v2_policy_trend_score",
        "regime_v2_policy_breakout_score",
        "regime_v2_policy_mean_reversion_score",
        "regime_v2_confidence",
        "regime_v2_uncertainty",
        "regime_v2_chop_risk",
        "regime_v2_false_breakout_risk",
        "regime_v2_shock_risk",
        "regime_v2_summary_label",
    ]
    present = [column for column in columns if column in frame.columns]
    if not present:
        return pd.DataFrame(columns=["_join_key"])
    return frame[present].drop_duplicates("_join_key")


def _metric(edges: pd.Series, *, name: str, cfg: RegimeV2TrendOverlayConfig, metadata: dict[str, Any]) -> SelectionOverlayMetric:
    valid = pd.to_numeric(edges, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return SelectionOverlayMetric(
        name=name,
        count=int(len(valid)),
        mean_edge=_round_or_none(valid.mean()) if not valid.empty else None,
        median_edge=_round_or_none(valid.median()) if not valid.empty else None,
        win_rate=_round_or_none((valid > 0.0).mean()) if not valid.empty else None,
        q25_edge=_round_or_none(valid.quantile(0.25)) if not valid.empty else None,
        q75_edge=_round_or_none(valid.quantile(0.75)) if not valid.empty else None,
        enough_samples=int(len(valid)) >= cfg.min_count,
        metadata=metadata,
    )


def _summary(
    baseline: SelectionOverlayMetric,
    overlay: SelectionOverlayMetric,
    gated: SelectionOverlayMetric,
    selected: pd.DataFrame,
    cfg: RegimeV2TrendOverlayConfig,
) -> dict[str, Any]:
    lift = None
    gated_lift = None
    if baseline.mean_edge is not None and overlay.mean_edge is not None:
        lift = _round_or_none(overlay.mean_edge - baseline.mean_edge)
    if baseline.mean_edge is not None and gated.mean_edge is not None:
        gated_lift = _round_or_none(gated.mean_edge - baseline.mean_edge)
    changed_rate = None
    aligned_boost_rate = None
    conflict_penalty_rate = None
    if not selected.empty:
        changed_rate = _round_or_none((selected["baseline_model"] != selected["overlay_model"]).mean())
        aligned_boost_rate = _round_or_none(selected.get("_overlay_aligned_boost", pd.Series(False, index=selected.index)).fillna(False).astype(bool).mean())
        conflict_penalty_rate = _round_or_none(selected.get("_overlay_conflict_penalty", pd.Series(False, index=selected.index)).fillna(False).astype(bool).mean())
    return {
        "top_k": cfg.top_k,
        "min_count": cfg.min_count,
        "fee_bps": cfg.fee_bps,
        "target_model_names": list(cfg.target_model_names),
        "breakout_model_names": list(cfg.breakout_model_names),
        "mean_reversion_model_names": list(cfg.mean_reversion_model_names),
        "breakout_score_floor": cfg.breakout_score_floor,
        "mean_reversion_score_floor": cfg.mean_reversion_score_floor,
        "aligned_boost": cfg.aligned_boost,
        "conflict_penalty": cfg.conflict_penalty,
        "suppress_conflicts": cfg.suppress_conflicts,
        "lift_vs_baseline": lift,
        "gated_lift_vs_baseline": gated_lift,
        "changed_pick_rate": changed_rate,
        "aligned_boost_pick_rate": aligned_boost_rate,
        "conflict_penalty_pick_rate": conflict_penalty_rate,
        "overlay_better": bool(lift is not None and lift > 0.0),
        "gated_better": bool(gated_lift is not None and gated_lift > 0.0),
    }


def _regime_trend_side(frame: pd.DataFrame) -> pd.Series:
    direction = frame.get("regime_v2_trend_direction", pd.Series("neutral", index=frame.index)).astype(str)
    return direction.map({"bull": 1.0, "bear": -1.0}).fillna(0.0)


def _index_join_key(index: pd.Index) -> pd.Series:
    if isinstance(index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(index, utc=True).astype("int64"), index=index).reset_index(drop=True)
    return pd.Series(index).reset_index(drop=True)


def _candidate_join_key(candidates: pd.DataFrame, comparison_index: pd.Index) -> pd.Series:
    if "timestamp" not in candidates.columns:
        return _index_join_key(candidates.index)
    ts = candidates["timestamp"]
    if isinstance(comparison_index, pd.DatetimeIndex):
        if pd.api.types.is_numeric_dtype(ts):
            numeric = pd.to_numeric(ts, errors="coerce")
            unit = "ms" if numeric.dropna().median() > 10_000_000_000 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True).astype("int64")
        return pd.to_datetime(ts, utc=True).astype("int64")
    return ts.reset_index(drop=True)


def _numeric_column(frame: pd.DataFrame, column: str, *, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _bool_column(frame: pd.DataFrame, column: str, *, default: bool) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].fillna(default).astype(bool)


def _round_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = [
    "RegimeV2TrendOverlayConfig",
    "SelectionOverlayMetric",
    "SelectionOverlayResult",
    "run_regime_v2_trend_selection_overlay",
]
