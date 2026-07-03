"""Validate PA paper rollout config safety."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from libs.selection.regime_v2_pa_paper_safety import (
    render_pa_paper_rollout_safety_markdown,
    validate_pa_paper_rollout_config,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    report = validate_pa_paper_rollout_config(
        config,
        expected_asset=args.asset,
        expected_timeframe=args.timeframe,
        require_enabled=args.require_enabled,
    )
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_rollout_safety_markdown(report), encoding="utf-8")
    return 0 if report["summary"]["safe"] else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PA paper rollout config safety.")
    parser.add_argument("--config", default="configs/selection.yaml")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--require-enabled", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_safety.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_safety.md")
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
