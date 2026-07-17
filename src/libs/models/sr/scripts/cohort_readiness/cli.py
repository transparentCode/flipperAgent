"""Explicit command line entry point for SR-V1.7 cohort readiness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import evaluate_stage, prepare_source_stage, validate_evaluation_stage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SR-V1.7 development-only cohort-readiness protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-source")
    prepare.add_argument("--config", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--config", required=True)
    evaluate.add_argument("--source-bundle-id", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--evaluation-bundle", required=True)
    validate.add_argument("--source-bundle-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path.cwd()
    if args.command == "prepare-source":
        result = prepare_source_stage(args.config, repo_root=root)
    elif args.command == "evaluate":
        result = evaluate_stage(args.config, repo_root=root, source_bundle_id=args.source_bundle_id)
    else:
        result = validate_evaluation_stage(args.config, repo_root=root, evaluation_bundle_path=args.evaluation_bundle, source_bundle_id=args.source_bundle_id)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
