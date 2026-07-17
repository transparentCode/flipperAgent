"""CLI for the two approved V1.8 actions: evaluate and validate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .artifacts import validate_evaluation_bundle
from .runner import run_study


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SR-V1.8 geometry sensitivity study")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--config", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--bundle", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path.cwd()
    if args.command == "evaluate":
        result = run_study(args.config, repo_root=root)
    else:
        from .config import load_geometry_config

        config = load_geometry_config(args.config)
        study = validate_evaluation_bundle(args.bundle, config=config, repo_root=root)
        result = {"bundle_id": Path(args.bundle).name, "study_id": study.study_id, "disposition": study.disposition.value, "selected_candidate_id": study.selected_candidate_id}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
