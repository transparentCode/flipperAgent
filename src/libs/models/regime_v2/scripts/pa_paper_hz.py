"""CLI for PA paper horizon-slice validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_pa_paper_hz import build_pa_paper_horizon_report, render_pa_paper_horizon_markdown


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source = json.loads(Path(args.gate_search).read_text(encoding="utf-8"))
    report = build_pa_paper_horizon_report(
        source,
        long_horizons=tuple(args.long_horizon),
        short_horizons=tuple(args.short_horizon),
        require_long_all_pass=not args.allow_partial_long,
        require_short_failures_only=not args.allow_mid_failures,
    )
    report["source_gate_search"] = args.gate_search
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_horizon_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PA paper gate result by horizon slice.")
    parser.add_argument("--gate-search", default="research/regime_v2_pa_paper_gs.json")
    parser.add_argument("--long-horizon", action="append", type=int, default=None)
    parser.add_argument("--short-horizon", action="append", type=int, default=None)
    parser.add_argument("--allow-partial-long", action="store_true")
    parser.add_argument("--allow-mid-failures", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_hz.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_hz.md")
    args = parser.parse_args(argv)
    args.long_horizon = args.long_horizon or [12, 24]
    args.short_horizon = args.short_horizon or [3]
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
