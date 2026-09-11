"""Phase 7Z transition stop-gate runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_stop_gate import (
    build_transition_stop_gate_report,
    render_transition_stop_gate_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    robust = json.loads(Path(args.robust_json).read_text(encoding="utf-8"))
    context = json.loads(Path(args.context_json).read_text(encoding="utf-8"))
    report = build_transition_stop_gate_report(
        robust,
        context,
        min_support_ready_assets=args.min_support_ready_assets,
        require_context_tag=args.require_context_tag,
        require_runtime_disabled=args.require_runtime_disabled,
    )
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_transition_stop_gate_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7Z transition stop-gate.")
    parser.add_argument("--robust-json", default="research/regime_v2_phase7w_transition_micro_state_robust.json")
    parser.add_argument("--context-json", default="research/regime_v2_phase7y_transition_micro_state_context_diag.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase7z_transition_stop_gate.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7z_transition_stop_gate.md")
    parser.add_argument("--min-support-ready-assets", type=int, default=2)
    parser.add_argument("--require-context-tag", action="store_true", default=True)
    parser.add_argument("--require-runtime-disabled", action="store_true", default=True)
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
