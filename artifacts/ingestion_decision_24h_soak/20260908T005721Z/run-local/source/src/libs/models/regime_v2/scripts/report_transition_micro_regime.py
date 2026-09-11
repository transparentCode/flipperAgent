"""Phase 7T micro-regime diagnostics over transition matrix output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_micro_regime import (
    build_transition_micro_regime_report,
    render_transition_micro_regime_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    report = build_transition_micro_regime_report(
        payload,
        min_split_active=args.min_split_active,
        direction_skew_threshold=args.direction_skew_threshold,
        max_worst_loss=args.max_worst_loss,
    )
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_transition_micro_regime_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7T transition micro-regime diagnostics.")
    parser.add_argument("--input-json", default="research/regime_v2_phase7r_transition_setup_prune.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase7t_transition_micro_regime.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7t_transition_micro_regime.md")
    parser.add_argument("--min-split-active", type=int, default=3)
    parser.add_argument("--direction-skew-threshold", type=float, default=0.75)
    parser.add_argument("--max-worst-loss", type=float, default=0.0010)
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
