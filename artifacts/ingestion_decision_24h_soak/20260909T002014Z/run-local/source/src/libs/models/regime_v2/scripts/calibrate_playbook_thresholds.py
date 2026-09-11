"""Calibrate RegimeV2 playbook thresholds from labeled shadow outcomes.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.calibrate_playbook_thresholds \
        --outcomes research/regime_v2_shadow_outcomes.jsonl \
        --floor 0.10 --floor 0.14 --floor 0.18 --floor 0.20 --floor 0.22 --floor 0.24 \
        --output-json research/regime_v2_playbook_calibration.json \
        --output-md research/regime_v2_playbook_calibration.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_playbook_calibration import (
    build_regime_v2_playbook_calibration,
    render_regime_v2_playbook_calibration_markdown,
)
from libs.selection.regime_v2_shadow_outcomes import load_labeled_shadow_outcomes


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_labeled_shadow_outcomes(args.outcomes)
    report = build_regime_v2_playbook_calibration(records, floors=tuple(args.floor))
    report["source_outcomes"] = args.outcomes
    report["source_invalid_outcome_records"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_regime_v2_playbook_calibration_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate RegimeV2 playbook thresholds from labeled outcomes.")
    parser.add_argument("--outcomes", default="research/regime_v2_shadow_outcomes.jsonl")
    parser.add_argument("--floor", action="append", type=float, default=None)
    parser.add_argument("--output-json", default="research/regime_v2_playbook_calibration.json")
    parser.add_argument("--output-md", default="research/regime_v2_playbook_calibration.md")
    args = parser.parse_args(argv)
    args.floor = args.floor or [0.10, 0.14, 0.18, 0.20, 0.22, 0.24]
    return args


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
