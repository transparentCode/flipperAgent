"""Command-line entry points for the network-free SR-V1.12 audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.models.sr.domain import ContractValidationError

from .artifacts import validate_audit_bundle
from .config import load_candidate_audit_config
from .runner import run_audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sr-v1.12-candidate-reinforcement-audit")
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
            bundle_id, path, audit = run_audit(
                args.config,
                repo_root=args.repo_root,
                implementation_commit=args.implementation_commit,
                output_root=args.output_root,
            )
            result = {
                "audit_id": audit.audit_id,
                "bundle_id": bundle_id,
                "disposition": audit.decision.disposition.value,
                "path": str(path),
            }
        else:
            config = load_candidate_audit_config(args.config)
            audit = validate_audit_bundle(
                args.bundle,
                config=config,
                repo_root=args.repo_root,
                implementation_commit=args.implementation_commit,
            )
            result = {
                "audit_id": audit.audit_id,
                "bundle_id": args.bundle.resolve().name,
                "disposition": audit.decision.disposition.value,
            }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except ContractValidationError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
