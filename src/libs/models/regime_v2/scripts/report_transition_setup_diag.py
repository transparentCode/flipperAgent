"""Phase 7Q diagnostics over Phase 7P setup-transition output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_setup_diag import (
    build_setup_transition_diag_report,
    render_setup_transition_diag_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    report = build_setup_transition_diag_report(
        payload,
        min_active_support=args.min_active_support,
        min_passed_splits=args.min_passed_splits,
    )
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_setup_transition_diag_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Phase 7P setup-transition matrix output.")
    parser.add_argument("--input-json", default="research/regime_v2_phase7p_transition_setup.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase7q_transition_setup_diag.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7q_transition_setup_diag.md")
    parser.add_argument("--min-active-support", type=int, default=30)
    parser.add_argument("--min-passed-splits", type=int, default=4)
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
