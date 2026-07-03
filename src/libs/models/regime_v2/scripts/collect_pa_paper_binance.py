"""Collect PA paper-guardrail logs from an offline Binance replay.

This script enables the BNBUSDT|1h paper guardrail only inside the local replay
object. It does not edit runtime config and does not enable live selection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.candidate_export import (
    TrendCandidateExportConfig,
    export_builtin_trend_candidates,
)
from libs.models.regime_v2.evaluation.comparison import RegimeComparisonConfig, run_regime_comparison
from libs.models.regime_v2.scripts.collect_shadow_binance import (
    _feature_vector_from_row,
    _outputs_from_candidates,
)
from libs.models.regime_v2.scripts.compare_binance_native import _parse_millis, fetch_binance_native_ohlcv
from libs.selection.regime_v2_pa_paper_report import render_pa_paper_report_markdown, run_pa_paper_report
from libs.selection.selection_layer import SelectionLayer

_DEFAULT_LOG_PATH = "logs/regime_v2_pa_asset_paper_decisions.jsonl"
_DEFAULT_MODELS = (
    "Momentum",
    "TrendFollowing",
    "PriceAction",
    "RegimePullbackScorer",
    "SqueezeBreakout",
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.report_json or args.report_md:
        report = run_pa_paper_report(args.log_path)
        report_text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
        if args.report_json:
            Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_json).write_text(report_text + "\n", encoding="utf-8")
        if args.report_md:
            Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_md).write_text(render_pa_paper_report_markdown(report), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    log_path = Path(args.log_path)
    if args.reset_log and log_path.exists():
        log_path.unlink()
    summary = await collect_pa_paper_logs(
        asset=args.asset,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
        horizon_bars=args.horizon_bars,
        warmup_bars=args.warmup_bars,
        max_records=args.max_records,
        log_path=str(log_path),
        models=tuple(args.model or _DEFAULT_MODELS),
    )
    return {
        "phase": "phase_6l_pa_paper_binance_collection",
        "log_path": str(log_path),
        "summary": summary,
    }


async def collect_pa_paper_logs(
    *,
    asset: str,
    timeframe: str,
    limit: int,
    since: int | None,
    until: int | None,
    horizon_bars: int,
    warmup_bars: int,
    max_records: int | None,
    log_path: str,
    models: tuple[str, ...],
) -> dict[str, Any]:
    """Replay one pair and write paper-only decisions."""
    ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=timeframe, limit=limit, since=since, until=until)
    if ohlcv.empty:
        return {"asset": asset, "timeframe": timeframe, "status": "empty_ohlcv", "paper_records_attempted": 0}

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
            "paper_records_attempted": 0,
        }

    candidates_by_ts = {key: frame for key, frame in candidates.groupby("timestamp")}
    layer = SelectionLayer(asset, timeframe)
    layer._config = _paper_replay_config(layer._config, asset=asset, timeframe=timeframe, log_path=log_path)
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
        feature_vec = _feature_vector_from_row(
            comparison.loc[timestamp],
            ohlcv.loc[timestamp],
            asset=asset,
            timeframe=timeframe,
            timestamp=timestamp,
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
        "paper_records_attempted": int(attempted),
        "selected_total": int(selected_total),
        "missing_candidate_bars": int(missing_candidate_bars),
        "skipped_warmup_or_horizon": int(skipped_warmup_or_horizon),
        "models": list(models),
    }


def _paper_replay_config(config: dict[str, Any], *, asset: str, timeframe: str, log_path: str) -> dict[str, Any]:
    """Return an in-memory config that enables only the paper overlay."""
    out = dict(config or {})
    overlays = dict(out.get("overlays") or {})
    trend_gate = dict(overlays.get("regime_v2_trend_gate") or {})
    trend_gate.update({"enabled": False, "shadow_enabled": False, "shadow_persist_enabled": False})
    overlays["regime_v2_trend_gate"] = trend_gate
    overlays["regime_v2_pa_asset_guardrail"] = {
        "paper_enabled": True,
        "paper_log_enabled": False,
        "paper_persist_enabled": True,
        "paper_persist_path": log_path,
        "model_name": "PriceAction",
        "asset": asset,
        "timeframe": timeframe,
        "direction": 1,
    }
    out["overlays"] = overlays
    return out


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect PA paper logs from Binance replay.")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--warmup-bars", type=int, default=220)
    parser.add_argument("--max-records", type=int, default=180)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--log-path", default=_DEFAULT_LOG_PATH)
    parser.add_argument("--reset-log", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_collect_summary.json")
    parser.add_argument("--report-json", default="research/regime_v2_pa_paper_report.json")
    parser.add_argument("--report-md", default="research/regime_v2_pa_paper_report.md")
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    if isinstance(value, tuple):
        return [_json_safe(val) for val in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
