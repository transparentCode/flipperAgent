"""CLI for the three explicit SR-V1.6 calibration stages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import evaluate_holdout_stage, prepare_source_stage, select_development_stage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SR-V1.6 ATR calibration protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare-source", "select-development", "evaluate-holdout"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", required=True, help="immutable V1.6 YAML configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare-source":
        result = prepare_source_stage(args.config, repo_root=Path.cwd())
    elif args.command == "select-development":
        result = select_development_stage(args.config, repo_root=Path.cwd())
    else:
        result = evaluate_holdout_stage(args.config, repo_root=Path.cwd())
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
