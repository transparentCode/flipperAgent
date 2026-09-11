"""CLI for PA paper disable recommendations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_pa_paper_disable import (
    build_pa_paper_disable_report,
    render_pa_paper_disable_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    monitor_report = json.loads(Path(args.monitor).read_text(encoding="utf-8"))
    report = build_pa_paper_disable_report(
        monitor_report,
        min_changed_rows=args.min_changed_rows,
        action_windows_hours=tuple(args.action_window_hours),
        include_all_time_for_disable=not args.exclude_all_time,
    )
    report["source_path"] = args.monitor
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_disable_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build PA paper disable recommendation from monitor report.")
    parser.add_argument("--monitor", default="research/regime_v2_pa_paper_monitor.json")
    parser.add_argument("--min-changed-rows", type=int, default=None)
    parser.add_argument("--action-window-hours", action="append", type=int, default=None)
    parser.add_argument("--exclude-all-time", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_disable.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_disable.md")
    args = parser.parse_args(argv)
    args.action_window_hours = args.action_window_hours or [24, 168]
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
