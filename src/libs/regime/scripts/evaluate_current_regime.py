"""Evaluate current regime.yaml params on live Binance history.

This is a research runner, not an optimizer. It answers a narrower question:
do the currently configured regime params clear walk-forward truthfulness checks
against trivial baselines on a chosen asset/timeframe?
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.regime.config_loader import load_regime_config
from libs.regime.optimization.ablations import DEFAULT_VARIANTS, build_variants
from libs.regime.optimization.models import BenchmarkResults, OptimizationConfig
from libs.regime.optimization.optimizer import RegimeOptimizer

HMM_VARIANT_PRESETS: dict[str, dict[str, Any]] = {
    "current": {},
    "fixed2_diag": {
        "hmm_n_states": 2,
        "hmm_covariance_type": "diag",
        "hmm_robust_scoring": False,
    },
    "fixed2_full": {
        "hmm_n_states": 2,
        "hmm_covariance_type": "full",
        "hmm_robust_scoring": True,
    },
    "fixed3_diag": {
        "hmm_n_states": 3,
        "hmm_covariance_type": "diag",
        "hmm_robust_scoring": True,
    },
    "fixed3_full": {
        "hmm_n_states": 3,
        "hmm_covariance_type": "full",
        "hmm_robust_scoring": True,
    },
}

HMM_HEALTH_THRESHOLDS = {
    "fit_failure_rate": 0.05,
    "unstable_fit_rate": 0.15,
    "zero_transition_fit_rate": 0.05,
}


def _load_frame(asset: str, timeframe: str, *, start: datetime, end: datetime) -> pd.DataFrame:
    seconds_per_bar = {
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(timeframe)
    if seconds_per_bar is None:
        raise ValueError(f"Unsupported timeframe for evaluation: {timeframe}")

    limit = int(((end - start).total_seconds()) / seconds_per_bar) + 32
    df = fetch_historical_ohlcv(
        asset,
        timeframe,
        since=int(start.timestamp() * 1000),
        until=int(end.timestamp() * 1000),
        limit=limit,
    )
    if df.empty:
        return df

    frame = df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = frame[col].astype(float)
    return frame[["open", "high", "low", "close", "volume"]]


def _evaluate_current_params(
    asset: str,
    timeframe: str,
    *,
    days: int,
    include_ablations: bool = False,
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    frame = _load_frame(asset, timeframe, start=start, end=end)
    if frame.empty:
        return {"asset": asset, "timeframe": timeframe, "error": "no_data"}

    params = _load_params(asset, timeframe)
    return _evaluate_params_on_frame(
        frame,
        params=params,
        asset=asset,
        timeframe=timeframe,
        include_ablations=include_ablations,
        variant_name="current",
    )


def _load_params(asset: str, timeframe: str) -> dict[str, Any]:
    raw_cfg = load_regime_config()
    params = dict(raw_cfg.get("assets", {}).get(asset, {}).get(timeframe, {}))
    if params:
        return params
    return dict(raw_cfg.get("defaults", {}))


def _evaluate_params_on_frame(
    frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    asset: str,
    timeframe: str,
    include_ablations: bool,
    variant_name: str,
) -> dict[str, Any]:
    optimizer = RegimeOptimizer(OptimizationConfig(n_trials=1, timeout_seconds=1))
    optimizer._walk_forward.purge_bars = optimizer.config.walk_forward.purge_bars_for_timeframe(
        timeframe
    )

    fold_rows: list[dict[str, Any]] = []
    fold_benches: list[BenchmarkResults] = []
    fold_scores: list[float] = []
    ablation_fold_scores: dict[str, list[float]] = {name: [] for name in DEFAULT_VARIANTS}
    ablation_fold_benches: dict[str, list[BenchmarkResults]] = {name: [] for name in DEFAULT_VARIANTS}

    for fold_idx, (_, train_df, test_df) in enumerate(
        optimizer._walk_forward.iterate_splits(frame),
        start=1,
    ):
        score, bench = optimizer._evaluate_fold(train_df, test_df, params, asset, timeframe)
        fold_scores.append(score)
        fold_benches.append(bench)
        row = {
            "fold": fold_idx,
            "train_start": train_df.index[0].isoformat(),
            "train_end": train_df.index[-1].isoformat(),
            "test_start": test_df.index[0].isoformat(),
            "test_end": test_df.index[-1].isoformat(),
            "score": float(score),
            "benchmarks": bench.to_dict(),
        }
        if include_ablations:
            ablation_rows = _evaluate_fold_ablations(
                optimizer,
                train_df=train_df,
                test_df=test_df,
                params=params,
                asset=asset,
                timeframe=timeframe,
            )
            row["ablations"] = ablation_rows
            for name, result in ablation_rows.items():
                ablation_fold_scores[name].append(float(result["score"]))
                ablation_fold_benches[name].append(BenchmarkResults.from_dict(result["benchmarks"]))
        fold_rows.append(row)

    walk_forward = optimizer._aggregate_benchmarks(fold_benches).to_dict()
    full_sample = optimizer._compute_all_benchmarks(frame, params, asset, timeframe).to_dict()
    ablations = None
    if include_ablations:
        ablations = _evaluate_full_ablations(
            optimizer,
            frame=frame,
            params=params,
            asset=asset,
            timeframe=timeframe,
            fold_scores=ablation_fold_scores,
            fold_benches=ablation_fold_benches,
        )

    result = {
        "asset": asset,
        "timeframe": timeframe,
        "hmm_variant": variant_name,
        "date_from": frame.index[0].isoformat(),
        "date_to": frame.index[-1].isoformat(),
        "bars": int(len(frame)),
        "folds": int(len(fold_rows)),
        "mean_fold_score": float(sum(fold_scores) / len(fold_scores)) if fold_scores else None,
        "walk_forward": walk_forward,
        "fold_details": fold_rows,
        "full_sample": full_sample,
        "params": params,
        "hmm_health": {
            "walk_forward": _hmm_health_from_metrics(walk_forward, has_data=bool(fold_rows)),
            "full_sample": _hmm_health_from_metrics(full_sample, has_data=True),
        },
    }
    if ablations is not None:
        result["ablations"] = ablations
    return result


def _evaluate_hmm_variant_matrix(
    asset: str,
    timeframe: str,
    *,
    days: int,
    include_ablations: bool,
    variant_names: list[str],
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    frame = _load_frame(asset, timeframe, start=start, end=end)
    if frame.empty:
        return {"asset": asset, "timeframe": timeframe, "error": "no_data"}

    base_params = _load_params(asset, timeframe)
    variants: dict[str, Any] = {}
    ranking: list[dict[str, Any]] = []
    for name in variant_names:
        params = _params_for_hmm_variant(base_params, name)
        result = _evaluate_params_on_frame(
            frame,
            params=params,
            asset=asset,
            timeframe=timeframe,
            include_ablations=include_ablations,
            variant_name=name,
        )
        variants[name] = result
        walk = result["walk_forward"]
        health = result["hmm_health"]["walk_forward"]
        ranking.append(
            {
                "variant": name,
                "mean_fold_score": result["mean_fold_score"],
                "forward_return_ic": walk["forward_return_ic"],
                "sharpe_improvement": walk["sharpe_improvement"],
                "strict_pass": bool(walk["passed_strict_baseline_gate"]),
                "has_walk_forward_data": bool(result["folds"] > 0),
                "hmm_health_pass": bool(health["passed"]),
                "hmm_unstable_fit_rate": health["unstable_fit_rate"],
                "hmm_fit_failure_rate": health["fit_failure_rate"],
                "hmm_zero_transition_fit_rate": health["zero_transition_fit_rate"],
            }
        )

    ranking = _rank_hmm_variants(ranking)
    best_variant = ranking[0]["variant"] if ranking else None
    best_healthy = next((row["variant"] for row in ranking if row["hmm_health_pass"]), None)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "date_from": frame.index[0].isoformat(),
        "date_to": frame.index[-1].isoformat(),
        "bars": int(len(frame)),
        "variant_names": variant_names,
        "hmm_variants": variants,
        "hmm_variant_ranking": ranking,
        "best_variant": best_variant,
        "best_healthy_variant": best_healthy,
    }


def _evaluate_fold_ablations(
    optimizer: RegimeOptimizer,
    *,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    params: dict[str, Any],
    asset: str,
    timeframe: str,
) -> dict[str, dict[str, Any]]:
    orch = optimizer.orchestrator_factory(params, asset, timeframe)
    orch.analyze_series(train_df)
    features_df = orch.analyze_series(test_df)
    returns = _log_returns(test_df)
    hmm_diag = orch.hmm_classifier.diagnostics()
    ablation_frames = build_variants(
        features_df,
        position_scale_cfg=orch.aggregator.config.position_scale,
        cp_position_decay=orch.aggregator.config.cp_position_decay,
        vol_squeeze_pct=orch.aggregator.config.vol_squeeze_pct,
    )
    rows: dict[str, dict[str, Any]] = {}
    for name, variant_df in ablation_frames.items():
        score, bench = optimizer._compute_fold_score(
            variant_df,
            returns,
            price_df=test_df,
            hmm_diag=hmm_diag,
        )
        rows[name] = {
            "score": float(score),
            "benchmarks": bench.to_dict(),
        }
    return rows


def _evaluate_full_ablations(
    optimizer: RegimeOptimizer,
    *,
    frame: pd.DataFrame,
    params: dict[str, Any],
    asset: str,
    timeframe: str,
    fold_scores: dict[str, list[float]],
    fold_benches: dict[str, list[BenchmarkResults]],
) -> dict[str, Any]:
    orch = optimizer.orchestrator_factory(params, asset, timeframe)
    features_df = orch.analyze_series(frame)
    returns = _log_returns(frame)
    hmm_diag = orch.hmm_classifier.diagnostics()
    ablation_frames = build_variants(
        features_df,
        position_scale_cfg=orch.aggregator.config.position_scale,
        cp_position_decay=orch.aggregator.config.cp_position_decay,
        vol_squeeze_pct=orch.aggregator.config.vol_squeeze_pct,
    )
    walk_forward = {}
    full_sample = {}
    ranking = []
    for name, variant_df in ablation_frames.items():
        score, bench = optimizer._compute_fold_score(
            variant_df,
            returns,
            price_df=frame,
            hmm_diag=hmm_diag,
        )
        full_sample[name] = {
            "score": float(score),
            "benchmarks": bench.to_dict(),
        }
        agg = optimizer._aggregate_benchmarks(fold_benches[name]).to_dict()
        mean_score = float(sum(fold_scores[name]) / len(fold_scores[name])) if fold_scores[name] else None
        walk_forward[name] = {
            "score": mean_score,
            "benchmarks": agg,
        }
        ranking.append(
            {
                "variant": name,
                "walk_forward_score": mean_score,
                "walk_forward_forward_ic": agg["forward_return_ic"],
                "walk_forward_sharpe_improvement": agg["sharpe_improvement"],
                "strict_pass": bool(agg["passed_strict_baseline_gate"]),
            }
        )
    ranking.sort(
        key=lambda row: (
            row["walk_forward_score"] is not None,
            row["walk_forward_score"] if row["walk_forward_score"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    return {
        "variants": list(ablation_frames.keys()),
        "walk_forward": walk_forward,
        "full_sample": full_sample,
        "ranking": ranking,
    }


def _log_returns(frame: pd.DataFrame) -> Any:
    returns = np.log(frame["close"].values / (frame["close"].shift(1).values + 1e-10))
    return returns[1:]


def _params_for_hmm_variant(base_params: dict[str, Any], variant_name: str) -> dict[str, Any]:
    if variant_name not in HMM_VARIANT_PRESETS:
        raise ValueError(f"Unknown HMM variant: {variant_name}")
    params = dict(base_params)
    params.update(HMM_VARIANT_PRESETS[variant_name])
    return params


def _hmm_health_from_metrics(metrics: dict[str, Any], *, has_data: bool) -> dict[str, Any]:
    fit_failure_rate = float(metrics.get("hmm_fit_failure_rate", 1.0))
    unstable_fit_rate = float(metrics.get("hmm_unstable_fit_rate", 1.0))
    zero_transition_fit_rate = float(metrics.get("hmm_zero_transition_fit_rate", 1.0))
    passed = (
        has_data
        and fit_failure_rate <= HMM_HEALTH_THRESHOLDS["fit_failure_rate"]
        and unstable_fit_rate <= HMM_HEALTH_THRESHOLDS["unstable_fit_rate"]
        and zero_transition_fit_rate <= HMM_HEALTH_THRESHOLDS["zero_transition_fit_rate"]
    )
    return {
        "has_data": has_data,
        "passed": passed,
        "fit_failure_rate": fit_failure_rate,
        "unstable_fit_rate": unstable_fit_rate,
        "zero_transition_fit_rate": zero_transition_fit_rate,
    }


def _rank_hmm_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("has_walk_forward_data", False),
            row["strict_pass"] and row["hmm_health_pass"],
            row["hmm_health_pass"],
            row["strict_pass"],
            row["mean_fold_score"] is not None,
            row["mean_fold_score"] if row["mean_fold_score"] is not None else float("-inf"),
        ),
        reverse=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate current regime config on live Binance OHLCV",
    )
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--timeframes", nargs="+", default=["1h", "30m"])
    parser.add_argument("--days", type=int, default=300)
    parser.add_argument("--ablations", action="store_true")
    parser.add_argument("--hmm-variants", nargs="+", choices=sorted(HMM_VARIANT_PRESETS.keys()))
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    if args.hmm_variants:
        results = [
            _evaluate_hmm_variant_matrix(
                args.asset,
                timeframe,
                days=args.days,
                include_ablations=args.ablations,
                variant_names=args.hmm_variants,
            )
            for timeframe in args.timeframes
        ]
    else:
        results = [
            _evaluate_current_params(
                args.asset,
                timeframe,
                days=args.days,
                include_ablations=args.ablations,
            )
            for timeframe in args.timeframes
        ]
    payload = json.dumps(results, indent=2)
    print(payload)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)


if __name__ == "__main__":
    main()
