"""Phase 8B orchestration-posture shadow report runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_orchestration_shadow_report import (
    render_orchestration_shadow_report_markdown,
    run_orchestration_shadow_report,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = run_orchestration_shadow_report(
        args.log,
        orchestration_json_path=args.orchestration_json,
        asset=args.asset,
        timeframe=args.timeframe,
    )
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_orchestration_shadow_report_markdown(payload), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 8B orchestration shadow report.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl")
    parser.add_argument("--orchestration-json", default="research/regime_v2_phase8a_playbook_orchestration_gate.json")
    parser.add_argument("--asset", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--output-json", default="research/regime_v2_phase8b_orchestration_shadow_report.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase8b_orchestration_shadow_report.md")
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
