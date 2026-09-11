"""CLI for PA paper snapshot coverage reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_pa_paper_report import load_pa_paper_decisions
from libs.selection.regime_v2_pa_paper_snapshots import (
    build_pa_paper_snapshot_report,
    render_pa_paper_snapshot_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_pa_paper_decisions(args.log)
    report = build_pa_paper_snapshot_report(records)
    report["source_log"] = args.log
    report["invalid_record_count"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_snapshot_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build PA paper snapshot coverage report.")
    parser.add_argument("--log", default="logs/regime_v2_pa_asset_paper_decisions.jsonl")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_snapshots.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_snapshots.md")
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
