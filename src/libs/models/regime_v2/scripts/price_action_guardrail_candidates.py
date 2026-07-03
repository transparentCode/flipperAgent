"""Build offline PriceAction guardrail candidate rules from labeled outcomes.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.price_action_guardrail_candidates \
        --outcomes research/regime_v2_shadow_outcomes.jsonl \
        --min-support 10 \
        --min-bad-rate 0.55 \
        --output-json research/regime_v2_price_action_guardrail.json \
        --output-md research/regime_v2_price_action_guardrail.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_price_action_guardrail import (
    build_price_action_guardrail_report,
    render_price_action_guardrail_report_markdown,
)
from libs.selection.regime_v2_shadow_outcomes import load_labeled_shadow_outcomes


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_labeled_shadow_outcomes(args.outcomes)
    report = build_price_action_guardrail_report(
        records,
        min_support=args.min_support,
        min_bad_rate=args.min_bad_rate,
        min_avg_lift=args.min_avg_lift,
    )
    report["source_outcomes"] = args.outcomes
    report["source_invalid_outcome_records"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_price_action_guardrail_report_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build offline PriceAction guardrail candidate rules.")
    parser.add_argument("--outcomes", default="research/regime_v2_shadow_outcomes.jsonl")
    parser.add_argument("--min-support", type=int, default=10)
    parser.add_argument("--min-bad-rate", type=float, default=0.55)
    parser.add_argument("--min-avg-lift", type=float, default=0.0)
    parser.add_argument("--output-json", default="research/regime_v2_price_action_guardrail.json")
    parser.add_argument("--output-md", default="research/regime_v2_price_action_guardrail.md")
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
