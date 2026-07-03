"""Phase 8D RegimeV2 safety report runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.runtime_safety_validator import (
    render_runtime_safety_markdown,
    run_runtime_safety_report,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_runtime_safety_report(
        selection_config_path=args.selection_config,
        orchestration_json_path=args.orchestration_json,
        stop_gate_json_path=args.stop_gate_json,
    )
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_runtime_safety_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 8D RegimeV2 safety report.")
    parser.add_argument("--selection-config", default="configs/selection.yaml")
    parser.add_argument("--orchestration-json", default="research/regime_v2_phase8a_playbook_orchestration_gate.json")
    parser.add_argument("--stop-gate-json", default="research/regime_v2_phase7z_transition_stop_gate.json")
    parser.add_argument("--output-json", default="research/regime_v2_phase8d_runtime_safety.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase8d_runtime_safety.md")
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
