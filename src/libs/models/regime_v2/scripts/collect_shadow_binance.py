"""Collect RegimeV2 shadow-selection JSONL logs from on-demand Binance candles.

This script bypasses Docker/runtime streams. It fetches OHLCV from Binance,
computes offline RegimeV2 evidence and candidate families, routes each bar
through ``SelectionLayer``, and writes the same JSONL rows as runtime shadow
persistence.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.collect_shadow_binance \
        --pair BTCUSDT:4h --pair ETHUSDT:4h \
        --limit 1000 \
        --output-json research/regime_v2_shadow_collect_summary.json \
        --report-json research/regime_v2_phase5_shadow_report.json \
        --report-md research/regime_v2_phase5_shadow_report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.contracts.signal import FeatureVector, ModelOutput, ScoringOutput
from libs.models.regime_v2.evaluation.candidate_export import (
    TrendCandidateExportConfig,
    export_builtin_trend_candidates,
)
from libs.models.regime_v2.adapters.trendline_feature_producer import (
    TrendlineFeatureConfig,
    compute_trendline_context_features,
)
from libs.models.regime_v2.evaluation.comparison import RegimeComparisonConfig, run_regime_comparison
from libs.models.regime_v2.scripts.compare_binance_native import _parse_millis, fetch_binance_native_ohlcv
from libs.selection.regime_v2_shadow_report import (
    render_regime_v2_shadow_report_markdown,
    run_regime_v2_shadow_report,
)
from libs.selection.selection_layer import SelectionLayer
from libs.trendlines.boundary import TrendlineSnapshotHistory

_DEFAULT_PAIRS = (
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "4h"),
    ("SOLUSDT", "4h"),
    ("BNBUSDT", "1h"),
)
_DEFAULT_MODELS = (
    "Momentum",
    "TrendFollowing",
    "PriceAction",
    "RegimePullbackScorer",
    "SqueezeBreakout",
)
_DEFAULT_LOG_PATH = "logs/regime_v2_shadow_decisions.jsonl"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")

    if args.report_json or args.report_md:
        report = run_regime_v2_shadow_report(args.log_path)
        report_text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
        if args.report_json:
            Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_json).write_text(report_text + "\n", encoding="utf-8")
        if args.report_md:
            Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_md).write_text(render_regime_v2_shadow_report_markdown(report), encoding="utf-8")

    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    log_path = Path(args.log_path)
    if args.reset_log and log_path.exists():
        log_path.unlink()

    since = _parse_millis(args.since)
    until = _parse_millis(args.until)
    pairs = _parse_pairs(args.pair)
    models = tuple(args.model or _DEFAULT_MODELS)
    pair_summaries: list[dict[str, Any]] = []

    for asset, timeframe in pairs:
        try:
            summary = await collect_pair_shadow_logs(
                asset=asset,
                timeframe=timeframe,
                limit=args.limit,
                since=since,
                until=until,
                horizon_bars=args.horizon_bars,
                warmup_bars=args.warmup_bars,
                max_records=args.max_records_per_pair,
                models=models,
                include_trendline_context=bool(args.include_trendline_context),
                trendline_min_bars=int(args.trendline_min_bars),
                trendline_history_limit=int(args.trendline_history_limit),
                shadow_log_path=str(log_path),
            )
        except Exception as exc:
            summary = {
                "asset": asset,
                "timeframe": timeframe,
                "status": "failed",
                "error": str(exc),
                "shadow_records_attempted": 0,
            }
        pair_summaries.append(summary)

    total_attempted = sum(int(item.get("shadow_records_attempted", 0)) for item in pair_summaries)
    return {
        "phase": "phase_5_shadow_binance_collection",
        "log_path": str(log_path),
        "pairs": pair_summaries,
        "summary": {
            "pair_count": len(pair_summaries),
            "successful_pair_count": sum(1 for item in pair_summaries if item.get("status") == "ok"),
            "failed_pair_count": sum(1 for item in pair_summaries if item.get("status") == "failed"),
            "shadow_records_attempted": total_attempted,
        },
    }


async def collect_pair_shadow_logs(
    *,
    asset: str,
    timeframe: str,
    limit: int,
    since: int | None,
    until: int | None,
    horizon_bars: int,
    warmup_bars: int,
    max_records: int | None,
    models: tuple[str, ...],
    include_trendline_context: bool = False,
    trendline_min_bars: int = 80,
    trendline_history_limit: int = 5,
    shadow_log_path: str | None = None,
) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=asset,
        timeframe=timeframe,
        limit=limit,
        since=since,
        until=until,
    )
    if ohlcv.empty:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "empty_ohlcv",
            "ohlcv_rows": 0,
            "candidate_rows": 0,
            "shadow_records_attempted": 0,
        }

    comparison = run_regime_comparison(
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=horizon_bars,
            include_legacy_regime=False,
            include_regime_classification=False,
        ),
    ).frame
    candidates = export_builtin_trend_candidates(
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        config=TrendCandidateExportConfig(models=models, min_abs_edge=0.0, include_flat=False),
    )
    if candidates.empty:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "empty_candidates",
            "ohlcv_rows": int(len(ohlcv)),
            "candidate_rows": 0,
            "shadow_records_attempted": 0,
        }

    candidates_by_ts = {key: frame for key, frame in candidates.groupby("timestamp")}
    layer = SelectionLayer(asset, timeframe)
    if shadow_log_path:
        _force_shadow_persistence(layer, shadow_log_path)
    trendline_history = TrendlineSnapshotHistory(maxlen=max(int(trendline_history_limit) + 2, 3))
    trendline_config = TrendlineFeatureConfig(
        fitter="ensemble",
        min_bars=max(int(trendline_min_bars), 2),
        include_native_signals=True,
        record_snapshot=True,
        history_limit=max(int(trendline_history_limit), 1),
    )
    attempted = 0
    selected_total = 0
    missing_candidate_bars = 0
    skipped_warmup_or_horizon = 0

    for idx, timestamp in enumerate(comparison.index):
        if idx < warmup_bars or idx >= len(comparison) - horizon_bars:
            skipped_warmup_or_horizon += 1
            continue
        if max_records is not None and attempted >= max_records:
            break
        candidate_rows = candidates_by_ts.get(timestamp)
        if candidate_rows is None or candidate_rows.empty:
            missing_candidate_bars += 1
            continue
        trendline_features = None
        if include_trendline_context:
            trendline_features = compute_trendline_context_features(
                ohlcv.iloc[: idx + 1],
                asset=asset,
                timeframe=timeframe,
                config=trendline_config,
                snapshot_history=trendline_history,
            )
        feature_vec = _feature_vector_from_row(
            comparison.loc[timestamp],
            ohlcv.loc[timestamp],
            asset=asset,
            timeframe=timeframe,
            timestamp=timestamp,
            trendline_features=trendline_features,
        )
        model_outputs, scoring_outputs = _outputs_from_candidates(candidate_rows)
        selected = layer.select(model_outputs, scoring_outputs, feature_vec)
        attempted += 1
        selected_total += len(selected)

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "ohlcv_rows": int(len(ohlcv)),
        "candidate_rows": int(len(candidates)),
        "comparison_rows": int(len(comparison)),
        "shadow_records_attempted": int(attempted),
        "selected_total": int(selected_total),
        "missing_candidate_bars": int(missing_candidate_bars),
        "skipped_warmup_or_horizon": int(skipped_warmup_or_horizon),
        "models": list(models),
        "trendline_context_enabled": bool(include_trendline_context),
        "trendline_snapshots_recorded": int(trendline_history.count(asset, timeframe)) if include_trendline_context else 0,
    }


def _force_shadow_persistence(layer: SelectionLayer, shadow_log_path: str) -> None:
    overlays = layer._config.setdefault("overlays", {})
    if not isinstance(overlays, dict):
        overlays = {}
        layer._config["overlays"] = overlays
    gate = overlays.setdefault("regime_v2_trend_gate", {})
    if not isinstance(gate, dict):
        gate = {}
        overlays["regime_v2_trend_gate"] = gate
    gate["shadow_enabled"] = True
    gate["shadow_persist_enabled"] = True
    gate["shadow_persist_path"] = shadow_log_path
    gate.setdefault("shadow_log_enabled", False)


def _outputs_from_candidates(frame: pd.DataFrame) -> tuple[list[ModelOutput], list[ScoringOutput]]:
    model_outputs: list[ModelOutput] = []
    scoring_outputs: list[ScoringOutput] = []
    for row in frame.to_dict(orient="records"):
        source_type = str(row.get("source_type") or "scoring")
        direction = int(row.get("direction") or 0)
        edge_score = float(row.get("edge_score") or 0.0)
        conviction = float(row.get("conviction") or 1.0)
        if direction == 0:
            continue
        if source_type == "threshold":
            model_outputs.append(
                ModelOutput(
                    model_name=str(row["model_name"]),
                    asset=str(row["asset"]),
                    timeframe=str(row["timeframe"]),
                    timestamp=_timestamp_value(row["timestamp"]),
                    direction=direction,
                    conviction=max(0.0, min(1.0, conviction)),
                )
            )
        else:
            scoring_outputs.append(
                ScoringOutput(
                    model_name=str(row["model_name"]),
                    asset=str(row["asset"]),
                    timeframe=str(row["timeframe"]),
                    timestamp=_timestamp_value(row["timestamp"]),
                    edge_score=float(direction) * abs(edge_score),
                    conviction=max(0.0, min(1.0, conviction)),
                )
            )
    return model_outputs, scoring_outputs


def _feature_vector_from_row(
    comparison_row: pd.Series,
    ohlcv_row: pd.Series,
    *,
    asset: str,
    timeframe: str,
    timestamp: Any,
    trendline_features: dict[str, Any] | None = None,
) -> FeatureVector:
    evidence = {
        "trend_direction": _string_value(comparison_row.get("regime_v2_trend_direction"), "neutral"),
        "confidence": _float_value(comparison_row.get("regime_v2_confidence"), 0.0),
        "uncertainty": _float_value(comparison_row.get("regime_v2_uncertainty"), 1.0),
        "breakout_direction": _string_value(comparison_row.get("regime_v2_breakout_direction"), "neutral"),
    }
    policy = {
        "allow_trend_following": _bool_value(comparison_row.get("regime_v2_policy_allow_trend_following")),
        "allow_breakout": _bool_value(comparison_row.get("regime_v2_policy_allow_breakout")),
        "allow_mean_reversion": _bool_value(comparison_row.get("regime_v2_policy_allow_mean_reversion")),
        "trend_score": _float_value(comparison_row.get("regime_v2_policy_trend_score"), 0.0),
        "breakout_score": _float_value(comparison_row.get("regime_v2_policy_breakout_score"), 0.0),
        "mean_reversion_score": _float_value(comparison_row.get("regime_v2_policy_mean_reversion_score"), 0.0),
    }
    features: dict[str, Any] = {"regime_v2": {"evidence": evidence, "policy": policy}}
    if trendline_features:
        features["trendline"] = dict(trendline_features)
    return FeatureVector(
        asset=asset,
        timeframe=timeframe,
        timestamp=_timestamp_value(timestamp),
        features=features,
        bar_data={
            "open": _float_value(ohlcv_row.get("open"), 0.0),
            "high": _float_value(ohlcv_row.get("high"), 0.0),
            "low": _float_value(ohlcv_row.get("low"), 0.0),
            "close": _float_value(ohlcv_row.get("close"), 0.0),
            "volume": _float_value(ohlcv_row.get("volume"), 0.0),
        },
    )


def _parse_pairs(raw_pairs: list[str] | None) -> tuple[tuple[str, str], ...]:
    if not raw_pairs:
        return _DEFAULT_PAIRS
    pairs: list[tuple[str, str]] = []
    for raw in raw_pairs:
        if ":" not in raw:
            raise ValueError(f"Pair must use SYMBOL:TIMEFRAME format, got {raw!r}")
        symbol, timeframe = raw.split(":", 1)
        pairs.append((symbol.strip().upper(), timeframe.strip()))
    return tuple(pairs)


def _timestamp_value(value: Any) -> float:
    if isinstance(value, pd.Timestamp):
        return float(value.timestamp())
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    return float(value)


def _float_value(value: Any, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _string_value(value: Any, default: str) -> str:
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    text = str(value).strip()
    return text if text else default


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect RegimeV2 shadow logs from on-demand Binance candles.")
    parser.add_argument("--pair", action="append", default=None, help="SYMBOL:TIMEFRAME pair. Repeatable. Defaults to Phase 5D rollout pairs.")
    parser.add_argument("--limit", type=int, default=1000, help="Binance kline limit, usually capped around 1500.")
    parser.add_argument("--since", default=None, help="Start time: epoch ms or ISO datetime.")
    parser.add_argument("--until", default=None, help="End time: epoch ms or ISO datetime.")
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--warmup-bars", type=int, default=120)
    parser.add_argument("--max-records-per-pair", type=int, default=None)
    parser.add_argument("--model", action="append", default=None, help="Candidate model name. Repeatable.")
    parser.add_argument("--log-path", default=_DEFAULT_LOG_PATH)
    parser.add_argument("--reset-log", action="store_true", help="Delete existing log path before collection.")
    parser.add_argument("--output-json", default=None, help="Optional collection summary JSON.")
    parser.add_argument("--report-json", default=None, help="Optional Phase 5C report JSON after collection.")
    parser.add_argument("--report-md", default=None, help="Optional Phase 5C report Markdown after collection.")
    parser.add_argument("--include-trendline-context", action="store_true", help="Attach read-only trendline_* context to shadow FeatureVectors/logs.")
    parser.add_argument("--trendline-min-bars", type=int, default=80, help="Minimum lookback bars before trendline context becomes valid.")
    parser.add_argument("--trendline-history-limit", type=int, default=5, help="Rolling trendline snapshot history passed to temporal context.")
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
