"""Render trendline diagnostics for RegimeV2 shadow logs.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.report_trendline_shadow_diagnostics \
        --log logs/regime_v2_shadow_decisions.jsonl \
        --output-json research/regime_v2_tl_shadow_diag.json \
        --output-md research/regime_v2_tl_shadow_diag.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_shadow_report import load_regime_v2_shadow_decisions
from libs.selection.regime_v2_trendline_shadow_diagnostics import (
    build_trendline_shadow_diagnostics,
    render_trendline_shadow_diagnostics_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_regime_v2_shadow_decisions(args.log)
    report = build_trendline_shadow_diagnostics(
        records,
        source_path=args.log,
        asset=args.asset,
        timeframe=args.timeframe,
    )
    report["source_invalid_shadow_records"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_trendline_shadow_diagnostics_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render trendline diagnostics for RegimeV2 shadow JSONL logs.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl")
    parser.add_argument("--asset", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--output-json", default="research/regime_v2_trendline_shadow_diagnostics.json")
    parser.add_argument("--output-md", default="research/regime_v2_trendline_shadow_diagnostics.md")
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
