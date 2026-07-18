"""Command-line entry points for the network-free V1.11 utility."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.models.sr.domain.contracts import ContractValidationError

from .artifacts import validate_lifecycle_bundle
from .config import load_lifecycle_utility_config
from .runner import run_study


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sr-v1.11-lifecycle-utility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("config", type=Path)
    evaluate.add_argument("--repo-root", type=Path, default=Path.cwd())
    evaluate.add_argument("--implementation-commit")
    evaluate.add_argument("--output-root", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("config", type=Path)
    validate.add_argument("bundle", type=Path)
    validate.add_argument("--repo-root", type=Path, default=Path.cwd())
    validate.add_argument("--implementation-commit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            bundle_id, path, study = run_study(args.config, repo_root=args.repo_root, implementation_commit=args.implementation_commit, output_root=args.output_root)
            result = {"bundle_id": bundle_id, "study_id": study.study_id, "disposition": study.decision.disposition.value, "resolution_count": len(study.resolutions), "path": str(path)}
        else:
            config = load_lifecycle_utility_config(args.config)
            study = validate_lifecycle_bundle(args.bundle, config=config, repo_root=args.repo_root, implementation_commit=args.implementation_commit)
            result = {"bundle_id": args.bundle.resolve().name, "study_id": study.study_id, "disposition": study.decision.disposition.value, "resolution_count": len(study.resolutions)}
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except ContractValidationError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
