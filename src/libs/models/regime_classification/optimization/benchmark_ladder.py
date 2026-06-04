"""Offline benchmark ladder for RegimeClassification descriptors.

This module intentionally lives beside the new ``regime_classification`` model
and does not import the older ``libs.regime`` pipeline. The ladder asks a
simple question before any downstream integration: do regime descriptors improve
basic deterministic strategies beyond buy-and-hold, ungated crossover baselines,
and a shuffled-regime control?
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from libs.models.regime_classification.model import RegimeClassificationModel
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


def build_regime_feature_frame(
    price_df: pd.DataFrame,
    *,
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run RegimeClassificationModel and return a feature DataFrame."""
    model = RegimeClassificationModel(
        params=params or {},
        timeframe=timeframe,
        frozen_overrides=frozen_overrides or {},
    )
    regime_series = model.batch_evaluate(_clean_price_frame(price_df))
    return pd.DataFrame(regime_series.tolist(), index=price_df.index)


def run_benchmark_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the regime benchmark ladder on one asset/timeframe frame."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("benchmark_ladder", {})
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

    split = WalkForwardSplitter(
        train_ratio=float(ladder_cfg.get("train_ratio", 0.60)),
        val_ratio=float(ladder_cfg.get("val_ratio", 0.20)),
        oos_ratio=1.0
        - float(ladder_cfg.get("train_ratio", 0.60))
        - float(ladder_cfg.get("val_ratio", 0.20)),
        purge_bars=int(ladder_cfg.get("purge_bars", 24)),
    ).split(len(frame))

    base_positions = _build_base_positions(frame, ladder_cfg)
    overlays = _build_regime_overlays(
        base_positions,
        regime,
        ladder_cfg,
        shuffle=False,
    )
    shuffled_overlays = _build_regime_overlays(
        base_positions,
        regime,
        ladder_cfg,
        shuffle=True,
    )

    segments = {
        "train": (split.train_start, split.train_end),
        "validate": (split.val_start, split.val_end),
        "oos": (split.oos_start, split.oos_end),
        "full": (0, len(frame)),
    }

    strategies: dict[str, Any] = {}
    for strategy_name, positions in base_positions.items():
        baseline = {
            seg_name: _score_positions(
                positions[start:end],
                frame.iloc[start:end],
                timeframe=timeframe,
                cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
            )
            for seg_name, (start, end) in segments.items()
        }
        overlay_rows: dict[str, Any] = {}
        for overlay_name, overlay_positions_by_strategy in overlays.items():
            overlay_positions = overlay_positions_by_strategy[strategy_name]
            shuffled_positions = shuffled_overlays[overlay_name][strategy_name]
            overlay_metrics = {
                seg_name: _score_positions(
                    overlay_positions[start:end],
                    frame.iloc[start:end],
                    timeframe=timeframe,
                    cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
                )
                for seg_name, (start, end) in segments.items()
            }
            shuffled_metrics = {
                seg_name: _score_positions(
                    shuffled_positions[start:end],
                    frame.iloc[start:end],
                    timeframe=timeframe,
                    cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
                )
                for seg_name, (start, end) in segments.items()
            }
            overlay_rows[overlay_name] = {
                "metrics": overlay_metrics,
                "shuffled_control": shuffled_metrics,
                "oos_lifts": _metric_lifts(
                    overlay_metrics["oos"],
                    baseline["oos"],
                    shuffled_metrics["oos"],
                ),
                "decision": _overlay_decision(
                    overlay_metrics["oos"],
                    baseline["oos"],
                    shuffled_metrics["oos"],
                    ladder_cfg,
                ),
            }

        strategies[strategy_name] = {
            "baseline": baseline,
            "overlays": overlay_rows,
            "ranking": _rank_overlays(overlay_rows),
        }

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "information_metrics": compute_information_metrics(regime, frame),
        "strategies": strategies,
        "panel_decision": _panel_decision(strategies),
    }


def compute_information_metrics(
    regime_df: pd.DataFrame,
    price_df: pd.DataFrame,
) -> dict[str, float]:
    """Compute descriptor information content against future returns/vol."""
    close = price_df["close"].astype(float)
    fwd_return = close.pct_change(1).shift(-1)
    fwd_abs_return = fwd_return.abs()
    fwd_vol = close.pct_change().rolling(5).std().shift(-5)

    return {
        "trend_strength_fwd_abs_return_spearman": _spearman(
            regime_df.get("trend_strength"),
            fwd_abs_return,
        ),
        "vol_percentile_fwd_vol_spearman": _spearman(
            regime_df.get("vol_percentile"),
            fwd_vol,
        ),
        "changepoint_fwd_abs_return_spearman": _spearman(
            regime_df.get("changepoint_prob"),
            fwd_abs_return,
        ),
        "crisis_prob_fwd_abs_return_spearman": _spearman(
            regime_df.get("hmm_crisis_prob"),
            fwd_abs_return,
        ),
    }


def summarize_ladder_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple asset/timeframe benchmark reports."""
    usable = [row for row in rows if row.get("status") == "ok"]
    decisions: dict[str, int] = {}
    promoted = 0
    rejected = 0
    for row in usable:
        decision = row.get("panel_decision", "reject")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "promote_to_downstream_research":
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


def _clean_price_frame(price_df: pd.DataFrame) -> pd.DataFrame:
    required = ["close", "volume"]
    missing = [col for col in required if col not in price_df.columns]
    if missing:
        raise ValueError(f"price_df missing required columns: {missing}")
    frame = price_df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=["close", "volume"]).sort_index()


def _build_base_positions(
    frame: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, np.ndarray]:
    close = frame["close"].astype(float)
    sma_fast = close.rolling(int(cfg.get("sma_fast", 20))).mean()
    sma_slow = close.rolling(int(cfg.get("sma_slow", 50))).mean()
    ema_fast = close.ewm(span=int(cfg.get("ema_fast", 20)), adjust=False).mean()
    ema_slow = close.ewm(span=int(cfg.get("ema_slow", 50)), adjust=False).mean()
    return {
        "buy_and_hold": np.ones(len(frame), dtype=float),
        "sma_cross": np.where(sma_fast > sma_slow, 1.0, 0.0),
        "ema_cross": np.where(ema_fast > ema_slow, 1.0, 0.0),
    }


def _build_regime_overlays(
    base_positions: dict[str, np.ndarray],
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    shuffle: bool,
) -> dict[str, dict[str, np.ndarray]]:
    regime = regime_df.copy()
    if shuffle:
        regime = regime.sample(
            frac=1.0,
            random_state=int(cfg.get("shuffle_seed", 42)),
        ).reset_index(drop=True)
        regime.index = regime_df.index

    trend = _series(regime, "trend_strength", 0.0).clip(0.0, 1.0).to_numpy()
    confidence = _posterior_confidence(regime).to_numpy()
    risk_gate = _risk_gate(regime, cfg).to_numpy()
    trend_gate = (
        _series(regime, "trend_strength", 0.0)
        >= float(cfg.get("trend_strength_threshold", 0.35))
    ).astype(float).to_numpy()

    overlays: dict[str, dict[str, np.ndarray]] = {
        "risk_filtered": {},
        "trend_scaled": {},
        "confidence_scaled": {},
        "combined": {},
    }
    for name, base in base_positions.items():
        overlays["risk_filtered"][name] = base * risk_gate
        overlays["trend_scaled"][name] = base * trend
        overlays["confidence_scaled"][name] = base * confidence * risk_gate
        overlays["combined"][name] = base * trend_gate * confidence * risk_gate
    return overlays


def _score_positions(
    positions: np.ndarray,
    frame: pd.DataFrame,
    *,
    timeframe: str,
    cost_bps: float,
) -> dict[str, float]:
    if len(frame) < 2:
        return _empty_metrics()
    close = frame["close"].astype(float).to_numpy()
    returns, trade_mask = compute_returns(positions, close, cost_bps=cost_bps)
    total_return = _compound(returns)
    max_drawdown = compute_max_drawdown(returns)
    return {
        "total_return": total_return,
        "sharpe": compute_sharpe(returns, timeframe),
        "max_drawdown": max_drawdown,
        "calmar": total_return / abs(max_drawdown) if max_drawdown < 0 else 0.0,
        "turnover": float(np.sum(np.abs(np.diff(positions)))) / max(len(positions), 1),
        "avg_position": float(np.mean(np.abs(positions))) if len(positions) else 0.0,
        "trades": int(np.sum(trade_mask)),
    }


def _metric_lifts(
    overlay: dict[str, float],
    baseline: dict[str, float],
    shuffled: dict[str, float],
) -> dict[str, float]:
    return {
        "sharpe_vs_baseline": overlay["sharpe"] - baseline["sharpe"],
        "calmar_vs_baseline": overlay["calmar"] - baseline["calmar"],
        "total_return_vs_baseline": overlay["total_return"] - baseline["total_return"],
        "sharpe_vs_shuffled": overlay["sharpe"] - shuffled["sharpe"],
        "calmar_vs_shuffled": overlay["calmar"] - shuffled["calmar"],
    }


def _overlay_decision(
    overlay: dict[str, float],
    baseline: dict[str, float],
    shuffled: dict[str, float],
    cfg: dict[str, Any],
) -> str:
    lifts = _metric_lifts(overlay, baseline, shuffled)
    if (
        lifts["sharpe_vs_baseline"] >= float(cfg.get("min_sharpe_lift", 0.10))
        and lifts["calmar_vs_baseline"] >= float(cfg.get("min_calmar_lift", 0.05))
        and lifts["total_return_vs_baseline"]
        >= float(cfg.get("min_total_return_lift", 0.0))
        and lifts["sharpe_vs_shuffled"] >= 0
        and overlay["sharpe"] >= float(cfg.get("min_oos_sharpe", 0.0))
        and overlay["total_return"] >= float(cfg.get("min_oos_total_return", 0.0))
        and overlay["avg_position"] >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_to_downstream_research"
    return "reject"


def _rank_overlays(overlay_rows: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, payload in overlay_rows.items():
        oos = payload["metrics"]["oos"]
        rows.append(
            {
                "overlay": name,
                "decision": payload["decision"],
                "oos_sharpe": oos["sharpe"],
                "oos_calmar": oos["calmar"],
                "oos_total_return": oos["total_return"],
                **payload["oos_lifts"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["decision"] == "promote_to_downstream_research",
            row["oos_calmar"],
            row["oos_sharpe"],
            row["oos_total_return"],
        ),
        reverse=True,
    )


def _panel_decision(strategies: dict[str, Any]) -> str:
    promoted = 0
    for strategy in strategies.values():
        promoted += sum(
            1
            for overlay in strategy["overlays"].values()
            if overlay["decision"] == "promote_to_downstream_research"
        )
    return "promote_to_downstream_research" if promoted > 0 else "reject"


def _posterior_confidence(regime_df: pd.DataFrame) -> pd.Series:
    hmm_cols = [col for col in regime_df.columns if col.startswith("hmm_p_state_")]
    if not hmm_cols:
        return pd.Series(np.ones(len(regime_df)), index=regime_df.index)
    return regime_df[hmm_cols].max(axis=1).fillna(0.0).clip(0.0, 1.0)


def _risk_gate(regime_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.Series:
    vol_ok = _series(regime_df, "vol_percentile", 50.0) <= float(
        cfg.get("max_vol_percentile", 85.0)
    )
    cp_ok = _series(regime_df, "changepoint_prob", 0.0) <= float(
        cfg.get("max_changepoint_prob", 0.65)
    )
    crisis_ok = _series(regime_df, "hmm_crisis_prob", 0.0) <= float(
        cfg.get("max_crisis_prob", 0.50)
    )
    return (vol_ok & cp_ok & crisis_ok).astype(float)


def _series(regime_df: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in regime_df:
        return pd.Series(np.full(len(regime_df), default), index=regime_df.index)
    return pd.to_numeric(regime_df[column], errors="coerce").fillna(default)


def _spearman(a: pd.Series | None, b: pd.Series | None) -> float:
    if a is None or b is None:
        return 0.0
    joined = pd.concat([a, b], axis=1).dropna()
    if len(joined) < 20:
        return 0.0
    if joined.iloc[:, 0].nunique() <= 1 or joined.iloc[:, 1].nunique() <= 1:
        return 0.0
    rho, _ = stats.spearmanr(joined.iloc[:, 0], joined.iloc[:, 1])
    if np.isnan(rho):
        return 0.0
    return float(rho)


def _compound(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    return float(np.prod(1.0 + returns) - 1.0)


def _empty_metrics() -> dict[str, float]:
    return {
        "total_return": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "calmar": 0.0,
        "turnover": 0.0,
        "avg_position": 0.0,
        "trades": 0,
    }


def _index_value(frame: pd.DataFrame, idx: int) -> str:
    value = frame.index[idx]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
