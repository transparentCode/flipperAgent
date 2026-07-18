"""CLI exposing only V1.9 evaluate and validate actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .artifacts import validate_evaluation_bundle
from .config import load_baseline_adequacy_config
from .runner import run_study


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SR-V1.9 baseline adequacy study")
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
        result = run_study(args.config, repo_root=root).to_payload()
    else:
        config = load_baseline_adequacy_config(args.config)
        study = validate_evaluation_bundle(args.bundle, config=config, repo_root=root)
        result = {"bundle_id": Path(args.bundle).name, "study_id": study.study_id, "disposition": study.decision.disposition.value}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
