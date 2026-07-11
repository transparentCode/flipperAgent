"""CLI runner for RegimeV2 optimization.

Usage:
    PYTHONPATH=src python -m libs.models.regime_v2.optimization.optimize \
        --asset BTCUSDT --timeframe 1h --profile core --n-trials 80
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path when run as a script.
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import optuna  # noqa: E402
import pandas as pd  # noqa: E402

from libs.common.enums import SystemComponent  # noqa: E402
from libs.common.logging.logger_utils import bind_logger  # noqa: E402
from libs.models.regime_v2.optimization import optimizer as regime_v2_optimizer  # noqa: E402
from libs.models.regime_v2.optimization.params import (  # noqa: E402
    ProfileName,
    extract_profile_defaults,
)
from libs.models.regime_v2.optimization.reports import (  # noqa: E402
    render_markdown_report,
    summarize_oos_delta,
)
from libs.models.regime_v2.optimization.threshold_sweep import (  # noqa: E402
    run_threshold_sweep,
)
from libs.models.regime_v2.optimization.validation import (  # noqa: E402
    RegimeV2OptimizationGates,
    RegimeV2RollingValidationConfig,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv  # noqa: E402

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RegimeV2 optimization study")
    parser.add_argument("--asset", required=True, help="Asset symbol, e.g. BTCUSDT")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 1h or 4h")
    parser.add_argument(
        "--profile",
        default=regime_v2_optimizer.STUDY_DEFAULTS["profile"],
        choices=["core", "windows", "fusion", "policy", "full"],
        help="RegimeV2 optimization profile",
    )
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--since", default=None, help="Start time as ms or ISO date")
    parser.add_argument("--until", default=None, help="End time as ms or ISO date")
    parser.add_argument("--input-csv", type=Path, default=None, help="Local OHLCV CSV path")
    parser.add_argument("--output-json", type=Path, default=None, help="Audit JSON output path")
    parser.add_argument("--output-markdown", type=Path, default=None, help="Markdown audit output path")
    parser.add_argument("--study-name", default=None)
    parser.add_argument("--storage", default=None, help="Optuna storage URL, e.g. sqlite:///research/regime_v2.db")
    parser.add_argument("--resume", action="store_true", help="Resume an existing Optuna study if present")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.60)
    parser.add_argument("--val-ratio", type=float, default=0.20)
    parser.add_argument("--purge-bars", type=int, default=24)
    parser.add_argument("--window-bars", type=int, default=240)
    parser.add_argument("--step-bars", type=int, default=120)
    parser.add_argument("--min-window-bars", type=int, default=120)
    parser.add_argument("--min-support-count", type=int, default=20)
    parser.add_argument("--min-support-rate", type=float, default=0.02)
    parser.add_argument("--max-flip-rate", type=float, default=0.35)
    parser.add_argument("--max-policy-turnover", type=float, default=0.45)
    parser.add_argument("--min-oos-score-ratio", type=float, default=0.50)
    parser.add_argument("--skip-baseline", action="store_true", help="Skip default-vs-tuned OOS comparison")
    parser.add_argument("--threshold-sweep", action="store_true", help="Audit sensitive gates around best params")
    parser.add_argument("--threshold-sweep-step", type=float, default=0.02)
    parser.add_argument("--threshold-sweep-radius", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    ohlcv = _load_ohlcv(args)
    if len(ohlcv) < 100 + 2 * int(args.purge_bars):
        raise SystemExit(
            f"Insufficient data for RegimeV2 optimization: {len(ohlcv)} rows"
        )

    result = run_study(
        ohlcv,
        asset=args.asset,
        timeframe=args.timeframe,
        profile=args.profile,
        n_trials=args.n_trials or int(regime_v2_optimizer.STUDY_DEFAULTS["n_trials"]),
        horizon_bars=args.horizon_bars,
        study_name=args.study_name,
        storage=args.storage,
        load_if_exists=args.resume,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        purge_bars=args.purge_bars,
        validation_config=_validation_config_from_args(args),
        include_baseline=not args.skip_baseline,
        include_threshold_sweep=args.threshold_sweep,
        threshold_sweep_step=args.threshold_sweep_step,
        threshold_sweep_radius=args.threshold_sweep_radius,
    )
    output_path = args.output_json or _default_output_path(args.asset, args.timeframe, args.profile)
    _write_json(output_path, result)
    markdown_path = args.output_markdown
    if markdown_path is not None:
        _write_text(markdown_path, render_markdown_report(result))
    _print_summary(result, output_path, markdown_path)


def run_study(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    profile: ProfileName = "core",
    n_trials: int = 80,
    horizon_bars: int = 12,
    study_name: str | None = None,
    storage: str | None = None,
    load_if_exists: bool = False,
    seed: int = 42,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
    validation_config: RegimeV2RollingValidationConfig | None = None,
    include_baseline: bool = True,
    include_threshold_sweep: bool = False,
    threshold_sweep_step: float = 0.02,
    threshold_sweep_radius: int = 2,
) -> dict[str, Any]:
    """Run a RegimeV2 Optuna study and return a JSON-serializable report."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    cfg = validation_config or RegimeV2RollingValidationConfig()
    objective = regime_v2_optimizer.make_objective(
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        profile=profile,
        horizon_bars=horizon_bars,
        validation_config=cfg,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        purge_bars=purge_bars,
    )
    study = optuna.create_study(
        study_name=study_name or f"RegimeV2_{asset}_{timeframe}_{profile}",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(),
        storage=_prepare_storage(storage),
        load_if_exists=load_if_exists,
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    completed = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        raise RuntimeError("No completed RegimeV2 optimization trials")
    best = study.best_trial
    processed_params = regime_v2_optimizer.post_process_params(
        best.params,
        timeframe=timeframe,
        profile=profile,
    )
    oos = regime_v2_optimizer.evaluate_oos(
        ohlcv,
        processed_params,
        asset=asset,
        timeframe=timeframe,
        profile=profile,
        horizon_bars=horizon_bars,
        validation_config=cfg,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        purge_bars=purge_bars,
    )
    baseline_oos = None
    if include_baseline:
        default_params = extract_profile_defaults(timeframe, profile=profile)
        baseline_oos = regime_v2_optimizer.evaluate_oos(
            ohlcv,
            default_params,
            asset=asset,
            timeframe=timeframe,
            profile=profile,
            horizon_bars=horizon_bars,
            validation_config=cfg,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            purge_bars=purge_bars,
        )

    threshold_sweep = None
    if include_threshold_sweep:
        threshold_sweep = run_threshold_sweep(
            ohlcv,
            processed_params,
            asset=asset,
            timeframe=timeframe,
            profile=profile,
            horizon_bars=horizon_bars,
            validation_config=cfg,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            purge_bars=purge_bars,
            step=threshold_sweep_step,
            radius=threshold_sweep_radius,
        )

    result = {
        "model_name": regime_v2_optimizer.MODEL_NAME,
        "asset": asset.upper(),
        "timeframe": timeframe,
        "profile": profile,
        "n_trials": int(n_trials),
        "completed_trials": len(completed),
        "rejected_trials": _rejected_trial_count(completed),
        "study_name": study.study_name,
        "storage": storage,
        "load_if_exists": bool(load_if_exists),
        "seed": int(seed),
        "horizon_bars": int(horizon_bars),
        "data": {
            "rows": int(len(ohlcv)),
            "start": _format_index_value(ohlcv.index[0]) if len(ohlcv) else None,
            "end": _format_index_value(ohlcv.index[-1]) if len(ohlcv) else None,
        },
        "split": {
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "oos_ratio": 1.0 - train_ratio - val_ratio,
            "purge_bars": int(purge_bars),
        },
        "best_trial": {
            "number": best.number,
            "value": best.value,
            "params": processed_params,
            "validation": best.user_attrs.get("regime_v2_validation"),
        },
        "oos": oos,
        "baseline_oos": baseline_oos,
        "default_vs_tuned": summarize_oos_delta(baseline_oos, oos),
        "threshold_sweep": threshold_sweep,
        "deploy_params": regime_v2_optimizer.format_deploy_params(
            processed_params,
            timeframe=timeframe,
            profile=profile,
        ),
        "study_defaults": dict(regime_v2_optimizer.STUDY_DEFAULTS),
        "validation_config": _validation_config_to_dict(cfg),
    }
    return result


def _validation_config_from_args(args: argparse.Namespace) -> RegimeV2RollingValidationConfig:
    return RegimeV2RollingValidationConfig(
        window_bars=args.window_bars,
        step_bars=args.step_bars,
        min_window_bars=args.min_window_bars,
        gates=RegimeV2OptimizationGates(
            min_support_count=args.min_support_count,
            min_support_rate=args.min_support_rate,
            max_flip_rate=args.max_flip_rate,
            max_policy_turnover=args.max_policy_turnover,
            min_oos_score_ratio=args.min_oos_score_ratio,
        ),
    )


def _load_ohlcv(args: argparse.Namespace) -> pd.DataFrame:
    if args.input_csv is not None:
        logger.info(f"Loading OHLCV from {args.input_csv}")
        return _read_ohlcv_csv(args.input_csv)

    until_ms = _coerce_time_ms(getattr(args, "until", None))
    since_ms = _coerce_time_ms(args.since)
    if since_ms is None:
        end_seconds = time.time() if until_ms is None else until_ms / 1000
        since_ms = int((end_seconds - args.days * 86_400) * 1000)
    limit = _limit_for_range(args.timeframe, since_ms=since_ms, until_ms=until_ms, days=args.days)
    logger.info(f"Fetching {limit} {args.timeframe} candles for {args.asset}")
    return _normalize_ohlcv(
        fetch_historical_ohlcv(
            symbol=args.asset,
            timeframe=args.timeframe,
            since=since_ms,
            until=until_ms,
            limit=limit,
        )
    )


def _read_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return _normalize_ohlcv(df)


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    out = df.copy()
    if "timestamp" in out.columns:
        ts = out.pop("timestamp")
        numeric_ts = pd.to_numeric(ts, errors="coerce").dropna()
        if numeric_ts.empty:
            out.index = pd.to_datetime(ts, utc=True, errors="coerce")
        else:
            unit = "ms" if numeric_ts.max() > 10_000_000_000 else "s"
            out.index = pd.to_datetime(ts, unit=unit, utc=True, errors="coerce")
    elif not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.RangeIndex(len(out))

    out = out.loc[~out.index.isna()]
    out = out.loc[~out.index.duplicated(keep="last")]
    if hasattr(out.index, "is_monotonic_increasing") and not out.index.is_monotonic_increasing:
        out = out.sort_index()
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[required]


def _limit_for_days(timeframe: str, days: int) -> int:
    bars_per_day = {
        "1m": 1440,
        "3m": 480,
        "5m": 288,
        "15m": 96,
        "30m": 48,
        "1h": 24,
        "2h": 12,
        "4h": 6,
        "1d": 1,
    }.get(timeframe, 24)
    return max(int(days) * bars_per_day, 100)


def _limit_for_range(
    timeframe: str,
    *,
    since_ms: int | None,
    until_ms: int | None,
    days: int,
) -> int:
    if since_ms is None or until_ms is None:
        return _limit_for_days(timeframe, days)
    if until_ms <= since_ms:
        raise ValueError(f"until must be greater than since: since={since_ms}, until={until_ms}")
    millis_per_bar = _millis_per_bar(timeframe)
    if millis_per_bar is None:
        return _limit_for_days(timeframe, days)
    return max(int((until_ms - since_ms) // millis_per_bar) + 2, 100)


def _millis_per_bar(timeframe: str) -> int | None:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    unit = timeframe[-1:]
    if unit not in units:
        return None
    try:
        count = int(timeframe[:-1])
    except ValueError:
        return None
    return count * units[unit]


def _coerce_time_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp/date value: {value!r}")
    if isinstance(parsed, datetime):
        dt = parsed
    else:
        dt = parsed.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _rejected_trial_count(trials: list[optuna.trial.FrozenTrial]) -> int:
    return int(
        sum(
            trial.value is not None
            and trial.value <= regime_v2_optimizer.REJECTED_TRIAL_SCORE
            for trial in trials
        )
    )


def _validation_config_to_dict(cfg: RegimeV2RollingValidationConfig) -> dict[str, Any]:
    return {
        "window_bars": cfg.window_bars,
        "step_bars": cfg.step_bars,
        "min_window_bars": cfg.min_window_bars,
        "downstream": {
            "top_quantile": cfg.downstream.top_quantile,
            "score_floor": cfg.downstream.score_floor,
            "fee_bps": cfg.downstream.fee_bps,
            "min_count": cfg.downstream.min_count,
        },
        "gates": {
            "min_support_count": cfg.gates.min_support_count,
            "min_support_rate": cfg.gates.min_support_rate,
            "max_flip_rate": cfg.gates.max_flip_rate,
            "max_policy_turnover": cfg.gates.max_policy_turnover,
            "min_oos_score_ratio": cfg.gates.min_oos_score_ratio,
        },
        "weights": {
            "lift": cfg.weights.lift,
            "positive_window_rate": cfg.weights.positive_window_rate,
            "support": cfg.weights.support,
            "tail_penalty": cfg.weights.tail_penalty,
            "flip_penalty": cfg.weights.flip_penalty,
            "turnover_penalty": cfg.weights.turnover_penalty,
            "low_support_penalty": cfg.weights.low_support_penalty,
        },
    }


def _default_output_path(asset: str, timeframe: str, profile: str) -> Path:
    return Path("research") / f"regime_v2_optimization_{asset.upper()}_{timeframe}_{profile}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _prepare_storage(storage: str | None) -> str | None:
    if storage is None or not storage.startswith("sqlite:///"):
        return storage
    raw_path = storage.removeprefix("sqlite:///")
    if raw_path and raw_path != ":memory:":
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    return storage


def _format_index_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _print_summary(
    result: dict[str, Any],
    output_path: Path,
    markdown_path: Path | None = None,
) -> None:
    best = result["best_trial"]
    oos = result["oos"]
    print(f"RegimeV2 optimization: {result['asset']} {result['timeframe']} profile={result['profile']}")
    print(f"Trials: {result['completed_trials']}/{result['n_trials']} complete, rejected={result['rejected_trials']}")
    print(f"Best trial: #{best['number']} value={best['value']:.6f}")
    print(f"OOS deployed={oos['deployed']} reasons={oos['rejection_reasons']}")
    if result.get("default_vs_tuned"):
        delta = result["default_vs_tuned"]
        print(f"OOS tuned-default score delta={delta['oos_score_delta']:.6f}")
    print(f"Audit JSON: {output_path}")
    if markdown_path is not None:
        print(f"Audit Markdown: {markdown_path}")


if __name__ == "__main__":
    main()
