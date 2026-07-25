"""Canonical command surface for trendlines workflow bounded contexts."""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from types import ModuleType
from typing import Sequence


COMMAND_MODULES = {
    "drift-monitor": "app.trendlines.workflows.monitoring.drift_monitor",
    "pipeline-opt": "app.trendlines.workflows.pipeline.workflow",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trendlines workflow command surface",
    )
    parser.add_argument("command", choices=tuple(COMMAND_MODULES))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def _load_command_module(command: str) -> ModuleType:
    module_path = COMMAND_MODULES[command]
    return import_module(module_path)


def main(argv: Sequence[str] | None = None) -> int | None:
    parser = build_parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]

    if not raw_args:
        parser.print_help()
        return 1

    parsed = parser.parse_args(raw_args)

    if not parsed.command:
        parser.print_help()
        return 1

    module = _load_command_module(parsed.command)
    if not hasattr(module, "main"):
        raise AttributeError(f"Command module {module.__name__} does not expose main()")

    forwarded_args = list(getattr(parsed, "args", []))
    original_argv = sys.argv[:]
    sys.argv = [parsed.command, *forwarded_args]
    try:
        return module.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())