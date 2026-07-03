"""Phase 8A playbook orchestration gate runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_orchestration_gate import (
    build_playbook_orchestration_frame,
    build_playbook_orchestration_gate_report,
    render_playbook_orchestration_gate_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(json.dumps(payload["report"]["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_playbook_orchestration_gate_markdown(payload["report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    stop_gate = _read_json(args.stop_gate_json)
    reports = []
    for asset in args.asset:
        ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=args.timeframe, limit=args.limit, since=None, until=None)
        series = RegimeV2Orchestrator.create(asset, args.timeframe).analyze_series(ohlcv)
        context = build_playbook_context_frame(series)
        states = build_playbook_state_frame(context)
        orchestration = build_playbook_orchestration_frame(states, stop_gate)
        reports.append(build_playbook_orchestration_gate_report(orchestration, stop_gate, asset=asset, timeframe=args.timeframe, source="binance_native"))
    report = _matrix_report(reports)
    return {"phase": "phase_8a_playbook_orchestration_gate_runner", "asset": args.asset, "timeframe": args.timeframe, "input_rows": args.limit, "report": report, "asset_reports": reports}


def _matrix_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(report.get("summary", {})) for report in reports]
    return {
        "phase": "phase_8a_playbook_orchestration_gate_matrix",
        "summary": {
            "assets": sorted({str(row.get("asset")) for row in rows}),
            "variant_count": len(rows),
            "row_count": sum(int(row.get("row_count") or 0) for row in rows),
            "routeable_count": sum(int(row.get("routeable_count") or 0) for row in rows),
            "transition_runtime_enabled_count": sum(int(row.get("transition_runtime_enabled_count") or 0) for row in rows),
            "transition_promotion_ready_count": sum(1 for row in rows if bool(row.get("transition_promotion_ready"))),
            "transition_postures": sorted({str(row.get("transition_posture")) for row in rows}),
            "recommended_next_step": "resume_base_playbook_orchestration_and_shadow_reporting",
        },
        "asset_summaries": rows,
    }


def _read_json(path: str | None) -> dict[str, Any] | None:
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 8A playbook orchestration gate.")
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--stop-gate-json", default="research/regime_v2_phase7z_transition_stop_gate.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase8a_playbook_orchestration_gate.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase8a_playbook_orchestration_gate.md")
    args = parser.parse_args(argv)
    args.asset = args.asset or ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    return args


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
