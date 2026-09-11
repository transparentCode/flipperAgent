"""Descriptor information ladder for RegimeClassification outputs.

This is the pre-alpha gate: before optimizing overlays, verify whether regime
descriptors carry stable forward information versus time-preserving nulls.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from libs.models.regime_classification.optimization.benchmark_ladder import (
    _clean_price_frame,
    build_regime_feature_frame,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


_DEFAULT_DESCRIPTOR_TARGETS = [
    {"descriptor": "trend_strength", "target": "fwd_abs_return_5"},
    {"descriptor": "vol_percentile", "target": "fwd_vol_5"},
    {"descriptor": "fwd_vol_ewma", "target": "fwd_vol_5"},
    {"descriptor": "changepoint_prob", "target": "fwd_abs_return_1"},
    {"descriptor": "hmm_crisis_prob", "target": "fwd_abs_return_5"},
    {"descriptor": "cp_entropy", "target": "fwd_abs_return_5"},
    {"descriptor": "hurst", "target": "fwd_abs_return_10"},
]


def run_descriptor_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit descriptor information content on train/validation/OOS splits."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("descriptor_ladder", {})
    frame = _clean_price_frame(price_df)
    min_bars = int(ladder_cfg.get("min_bars", 500))
    if len(frame) < min_bars:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_data",
            "bars": int(len(frame)),
            "min_bars": min_bars,
        }

    regime = (
        regime_df.copy()
        if regime_df is not None
        else build_regime_feature_frame(
            frame,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
        )
    )
    regime = regime.reindex(frame.index)
    targets = _build_forward_targets(frame)

    split = WalkForwardSplitter(
        train_ratio=float(ladder_cfg.get("train_ratio", 0.60)),
        val_ratio=float(ladder_cfg.get("val_ratio", 0.20)),
        oos_ratio=1.0
        - float(ladder_cfg.get("train_ratio", 0.60))
        - float(ladder_cfg.get("val_ratio", 0.20)),
        purge_bars=int(ladder_cfg.get("purge_bars", 24)),
    ).split(len(frame))
    segments = {
        "train": slice(split.train_start, split.train_end),
        "validate": slice(split.val_start, split.val_end),
        "oos": slice(split.oos_start, split.oos_end),
        "full": slice(0, len(frame)),
    }

    null_regimes = _build_null_regimes(regime, ladder_cfg)
    rows = [
        _score_descriptor_pair(
            regime,
            null_regimes,
            targets,
            pair,
            segments,
            ladder_cfg,
        )
        for pair in _descriptor_targets(ladder_cfg)
    ]
    rows = [row for row in rows if row["status"] == "ok"]
    summary = _summarize_descriptor_rows(rows, ladder_cfg)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "descriptor_rows": rows,
        "summary": summary,
        "panel_decision": summary["decision"],
    }


def run_rolling_descriptor_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
    fold_bars: int | None = None,
    step_bars: int | None = None,
) -> dict[str, Any]:
    """Run descriptor information checks across repeated chronological folds."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_descriptor_ladder", {})
    frame = _clean_price_frame(price_df)
    fold_size = int(fold_bars or rolling_cfg.get("fold_bars", 2160))
    step_size = int(step_bars or rolling_cfg.get("step_bars", 720))
    min_folds = int(rolling_cfg.get("min_folds", 2))
    if len(frame) < fold_size:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_data",
            "bars": int(len(frame)),
            "fold_bars": fold_size,
        }

    regime = (
        regime_df.copy()
        if regime_df is not None
        else build_regime_feature_frame(
            frame,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
        )
    )
    regime = regime.reindex(frame.index)

    folds: list[dict[str, Any]] = []
    for fold_idx, start in enumerate(range(0, len(frame) - fold_size + 1, step_size)):
        end = start + fold_size
        fold_frame = frame.iloc[start:end]
        fold_report = run_descriptor_ladder(
            fold_frame,
            asset=asset,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
            regime_df=regime.loc[fold_frame.index],
            settings=cfg,
        )
        fold_report["fold_index"] = fold_idx
        fold_report["fold_start"] = _index_value(fold_frame, 0)
        fold_report["fold_end"] = _index_value(fold_frame, -1)
        folds.append(fold_report)

    if len(folds) < min_folds:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_folds",
            "bars": int(len(frame)),
            "folds": len(folds),
            "min_folds": min_folds,
        }

    summary = _summarize_rolling_folds(folds, cfg)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "fold_bars": fold_size,
        "step_bars": step_size,
        "folds": folds,
        "summary": summary,
        "panel_decision": summary["decision"],
    }


def summarize_descriptor_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple descriptor ladder reports."""
    usable = [row for row in rows if row.get("status") == "ok"]
    decisions: dict[str, int] = {}
    promoted = 0
    rejected = 0
    for row in usable:
        decision = row.get("panel_decision", "reject")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "promote_to_alpha_research":
            promoted += 1
        else:
            rejected += 1
    return {
        "usable_slices": len(usable),
        "total_slices": len(rows),
        "decision_counts": decisions,
        "promoted_slices": promoted,
        "rejected_slices": rejected,
    }


def _score_descriptor_pair(
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    targets: pd.DataFrame,
    pair: dict[str, str],
    segments: dict[str, slice],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    descriptor = pair["descriptor"]
    target = pair["target"]
    if descriptor not in regime or target not in targets:
        return {
            "descriptor": descriptor,
            "target": target,
            "status": "missing_column",
        }

    segment_scores = {
        name: _ic(regime[descriptor].iloc[segment], targets[target].iloc[segment])
        for name, segment in segments.items()
    }
    null_scores = {
        mode: {
            name: _ic(null_regime[descriptor].iloc[segment], targets[target].iloc[segment])
            for name, segment in segments.items()
        }
        for mode, null_regime in null_regimes.items()
        if descriptor in null_regime
    }
    hardest_mode = _hardest_null_mode(null_scores, "oos")
    hardest_oos_ic = null_scores.get(hardest_mode, {}).get("oos", 0.0)
    oos_ic = segment_scores["oos"]
    validate_ic = segment_scores["validate"]
    ic_lift = abs(oos_ic) - abs(hardest_oos_ic)
    sign_stable = _same_sign(validate_ic, oos_ic)
    decision = _descriptor_decision(oos_ic, ic_lift, sign_stable, cfg)
    return {
        "descriptor": descriptor,
        "target": target,
        "status": "ok",
        "segments": segment_scores,
        "null_controls": null_scores,
        "null_control_mode": hardest_mode,
        "oos_ic_lift_vs_null": float(ic_lift),
        "validate_oos_sign_stable": sign_stable,
        "decision": decision,
    }


def _summarize_descriptor_rows(
    rows: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "stable_rows": 0,
            "median_abs_oos_ic": 0.0,
            "median_oos_ic_lift_vs_null": 0.0,
            "decision": "reject",
        }
    promoted = [row for row in rows if row["decision"] == "promote_to_alpha_research"]
    abs_oos = [abs(float(row["segments"]["oos"])) for row in rows]
    lifts = [float(row["oos_ic_lift_vs_null"]) for row in rows]
    stable = [row for row in rows if row["validate_oos_sign_stable"]]
    min_stable = min(int(cfg.get("min_stable_descriptor_pairs", 2)), len(rows))
    decision = (
        "promote_to_alpha_research"
        if len(promoted) >= min_stable
        and _median(abs_oos) >= float(cfg.get("min_median_abs_oos_ic", 0.02))
        and _median(lifts) >= float(cfg.get("min_median_ic_lift_vs_null", 0.0))
        else "reject"
    )
    return {
        "rows": len(rows),
        "promoted_rows": len(promoted),
        "stable_rows": len(stable),
        "median_abs_oos_ic": _median(abs_oos),
        "median_oos_ic_lift_vs_null": _median(lifts),
        "decision": decision,
    }


def _summarize_rolling_folds(
    folds: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rolling_cfg = cfg.get("rolling_descriptor_ladder", {})
    usable = [fold for fold in folds if fold.get("status") == "ok"]
    promoted = [
        fold for fold in usable if fold.get("panel_decision") == "promote_to_alpha_research"
    ]
    pass_rate = len(promoted) / len(usable) if usable else 0.0
    median_abs_ic = _median(
        fold["summary"]["median_abs_oos_ic"] for fold in usable
    )
    median_lift = _median(
        fold["summary"]["median_oos_ic_lift_vs_null"] for fold in usable
    )
    decision = (
        "promote_to_alpha_research"
        if len(promoted) >= int(rolling_cfg.get("min_promoted_folds", 2))
        and pass_rate >= float(rolling_cfg.get("min_pass_rate", 0.60))
        and median_abs_ic >= float(rolling_cfg.get("min_median_abs_oos_ic", 0.02))
        and median_lift >= float(rolling_cfg.get("min_median_ic_lift_vs_null", 0.0))
        else "reject"
    )
    return {
        "total_folds": len(folds),
        "usable_folds": len(usable),
        "promoted_folds": len(promoted),
        "rejected_folds": len(usable) - len(promoted),
        "pass_rate": float(pass_rate),
        "median_abs_oos_ic": float(median_abs_ic),
        "median_oos_ic_lift_vs_null": float(median_lift),
        "decision": decision,
    }


def _descriptor_decision(
    oos_ic: float,
    ic_lift: float,
    sign_stable: bool,
    cfg: dict[str, Any],
) -> str:
    if (
        sign_stable
        and abs(oos_ic) >= float(cfg.get("min_abs_oos_ic", 0.03))
        and ic_lift >= float(cfg.get("min_ic_lift_vs_null", 0.0))
    ):
        return "promote_to_alpha_research"
    return "reject"


def _build_forward_targets(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    returns = close.pct_change()
    return pd.DataFrame(
        {
            "fwd_return_1": returns.shift(-1),
            "fwd_abs_return_1": returns.shift(-1).abs(),
            "fwd_return_5": close.pct_change(5).shift(-5),
            "fwd_abs_return_5": close.pct_change(5).shift(-5).abs(),
            "fwd_return_10": close.pct_change(10).shift(-10),
            "fwd_abs_return_10": close.pct_change(10).shift(-10).abs(),
            "fwd_vol_5": returns.rolling(5).std().shift(-5),
            "fwd_vol_10": returns.rolling(10).std().shift(-10),
        },
        index=frame.index,
    )


def _descriptor_targets(cfg: dict[str, Any]) -> list[dict[str, str]]:
    configured = cfg.get("descriptor_targets", _DEFAULT_DESCRIPTOR_TARGETS)
    rows: list[dict[str, str]] = []
    for row in configured:
        if isinstance(row, dict) and row.get("descriptor") and row.get("target"):
            rows.append({"descriptor": str(row["descriptor"]), "target": str(row["target"])})
    return rows or list(_DEFAULT_DESCRIPTOR_TARGETS)


def _build_null_regimes(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    modes = cfg.get("null_controls", ["circular_shift", "block_shuffle"])
    if isinstance(modes, str):
        modes = [modes]
    nulls = {
        mode: _null_regime(regime_df, cfg, mode)
        for mode in modes
        if mode in {"row_shuffle", "circular_shift", "block_shuffle"}
    }
    if not nulls:
        nulls["circular_shift"] = _null_regime(regime_df, cfg, "circular_shift")
    return nulls


def _null_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
    mode: str,
) -> pd.DataFrame:
    if mode == "row_shuffle":
        return _row_shuffle_regime(regime_df, cfg)
    if mode == "block_shuffle":
        return _block_shuffle_regime(regime_df, cfg)
    return _circular_shift_regime(regime_df, cfg)


def _row_shuffle_regime(regime_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    shuffled = regime_df.sample(
        frac=1.0,
        random_state=int(cfg.get("shuffle_seed", 42)),
    ).reset_index(drop=True)
    shuffled.index = regime_df.index
    return shuffled


def _circular_shift_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    if len(regime_df) == 0:
        return regime_df.copy()
    shift = int(cfg.get("null_shift_bars", max(1, len(regime_df) // 3)))
    shift = shift % len(regime_df)
    if shift == 0:
        shift = max(1, len(regime_df) // 3)
    values = np.roll(regime_df.to_numpy(), shift=shift, axis=0)
    return pd.DataFrame(values, index=regime_df.index, columns=regime_df.columns)


def _block_shuffle_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    block_bars = max(int(cfg.get("null_block_bars", 96)), 1)
    rng = np.random.default_rng(int(cfg.get("shuffle_seed", 42)))
    blocks = [
        regime_df.iloc[start : start + block_bars]
        for start in range(0, len(regime_df), block_bars)
    ]
    if len(blocks) <= 1:
        return _circular_shift_regime(regime_df, cfg)
    order = rng.permutation(len(blocks))
    shuffled = pd.concat([blocks[idx] for idx in order], axis=0).reset_index(drop=True)
    shuffled.index = regime_df.index
    return shuffled


def _hardest_null_mode(
    null_scores: dict[str, dict[str, float]],
    segment: str,
) -> str:
    if not null_scores:
        return ""
    return max(
        null_scores,
        key=lambda mode: abs(float(null_scores[mode].get(segment, 0.0))),
    )


def _ic(a: pd.Series, b: pd.Series) -> float:
    joined = pd.concat([a, b], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(joined) < 20:
        return 0.0
    if joined.iloc[:, 0].nunique() <= 1 or joined.iloc[:, 1].nunique() <= 1:
        return 0.0
    rho, _ = stats.spearmanr(joined.iloc[:, 0], joined.iloc[:, 1])
    return 0.0 if np.isnan(rho) else float(rho)


def _same_sign(a: float, b: float) -> bool:
    if a == 0.0 or b == 0.0:
        return False
    return np.sign(a) == np.sign(b)


def _median(values) -> float:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if len(arr) else 0.0


def _index_value(frame: pd.DataFrame, idx: int) -> str:
    value = frame.index[idx]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
