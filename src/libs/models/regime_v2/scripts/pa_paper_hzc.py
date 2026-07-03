"""CLI for PA paper long-horizon candidate descriptor validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from libs.selection.regime_v2_pa_paper_hzc import (
    build_pa_paper_horizon_candidate_report,
    render_pa_paper_horizon_candidate_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    horizon = json.loads(Path(args.horizon_report).read_text(encoding="utf-8")) if args.horizon_report else {}
    report = build_pa_paper_horizon_candidate_report(config, horizon, asset=args.asset, timeframe=args.timeframe)
    report["source_config"] = args.config
    report["source_horizon_report"] = args.horizon_report
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_horizon_candidate_markdown(report), encoding="utf-8")
    return 0 if report.get("summary", {}).get("safe") else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate disabled PA long-horizon candidate descriptor.")
    parser.add_argument("--config", default="configs/selection.yaml")
    parser.add_argument("--horizon-report", default="research/regime_v2_pa_paper_hz.json")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_hzc.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_hzc.md")
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
