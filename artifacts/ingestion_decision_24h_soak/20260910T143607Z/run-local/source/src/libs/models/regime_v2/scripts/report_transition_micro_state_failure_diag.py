"""Phase 7X failure-window diagnostics over 7W robustness output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_micro_state_failure_diag import (
    build_transition_micro_state_failure_diag_report,
    render_transition_micro_state_failure_diag_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    report = build_transition_micro_state_failure_diag_report(payload, min_tail_loss=args.min_tail_loss)
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_transition_micro_state_failure_diag_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7X transition micro-state failure diagnostics.")
    parser.add_argument("--input-json", default="research/regime_v2_phase7w_transition_micro_state_robust.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase7x_transition_micro_state_failure_diag.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7x_transition_micro_state_failure_diag.md")
    parser.add_argument("--min-tail-loss", type=float, default=0.02)
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
