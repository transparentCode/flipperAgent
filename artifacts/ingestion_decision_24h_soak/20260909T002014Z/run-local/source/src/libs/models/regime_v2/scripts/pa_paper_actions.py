"""CLI for PA paper action comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_pa_paper_actions import (
    build_pa_paper_action_report,
    render_pa_paper_action_markdown,
)
from libs.selection.regime_v2_pa_paper_report import load_labeled_pa_paper_outcomes


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_labeled_pa_paper_outcomes(args.outcomes)
    report = build_pa_paper_action_report(records, scales=tuple(args.scale), changed_only=not args.all_paper_active)
    report["source_path"] = args.outcomes
    report["invalid_record_count"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_action_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare PA paper action variants.")
    parser.add_argument("--outcomes", default="research/regime_v2_pa_paper_outcomes.jsonl")
    parser.add_argument("--scale", action="append", type=float, default=None)
    parser.add_argument("--all-paper-active", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_actions.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_actions.md")
    args = parser.parse_args(argv)
    args.scale = args.scale or [0.25, 0.5, 0.75]
    return args


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
