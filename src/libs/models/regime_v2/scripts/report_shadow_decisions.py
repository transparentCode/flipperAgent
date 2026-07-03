"""Render Phase 5 RegimeV2 shadow-decision replay reports.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.report_shadow_decisions \
        --log logs/regime_v2_shadow_decisions.jsonl \
        --output-json research/regime_v2_phase5_shadow_report.json \
        --output-md research/regime_v2_phase5_shadow_report.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_shadow_report import (
    render_regime_v2_shadow_report_markdown,
    run_regime_v2_shadow_report,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = run_regime_v2_shadow_report(
        args.log,
        asset=args.asset,
        timeframe=args.timeframe,
    )
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_regime_v2_shadow_report_markdown(payload), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render RegimeV2 Phase 5 shadow-decision replay report.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl", help="RegimeV2 shadow JSONL log path.")
    parser.add_argument("--asset", default=None, help="Optional asset filter, e.g. BTCUSDT.")
    parser.add_argument("--timeframe", default=None, help="Optional timeframe filter, e.g. 1h or 4h.")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
