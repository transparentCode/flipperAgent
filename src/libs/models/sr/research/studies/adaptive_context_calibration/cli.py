"""CLI for the immutable SR-V2.3 source and evaluation workflow."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from libs.models.sr.research.provenance.repository import repository_commit

from .artifacts import load_source_bundle, validate_evaluation_bundle
from .config import load_adaptive_context_calibration_config
from .runner import run_evaluation
from .source import fetch_and_publish_source_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SR-V2.3 adaptive context calibration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    source = subparsers.add_parser("source", help="fetch each approved 12h cohort once")
    source.add_argument("config_path", type=Path)
    source.add_argument("--repo-root", type=Path, default=Path.cwd())
    source.add_argument("--implementation-commit", type=str)

    evaluate = subparsers.add_parser("evaluate", help="evaluate from a published source bundle")
    evaluate.add_argument("config_path", type=Path)
    evaluate.add_argument("source_bundle_path", type=Path)
    evaluate.add_argument("--repo-root", type=Path, default=Path.cwd())
    evaluate.add_argument("--implementation-commit", type=str)

    validate = subparsers.add_parser("validate-evaluation", help="recompute an evaluation bundle")
    validate.add_argument("config_path", type=Path)
    validate.add_argument("source_bundle_path", type=Path)
    validate.add_argument("evaluation_bundle_path", type=Path)
    validate.add_argument("--repo-root", type=Path, default=Path.cwd())
    validate.add_argument("--implementation-commit", type=str)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "source":
        config = load_adaptive_context_calibration_config(str(args.config_path))
        commit = args.implementation_commit or repository_commit(args.repo_root)
        bundle_id, path = asyncio.run(
            fetch_and_publish_source_bundle(
                config,
                repo_root=args.repo_root,
                implementation_commit=commit,
            )
        )
        print(f"{bundle_id} {path}")
        return
    if args.command == "evaluate":
        bundle_id, path, study = run_evaluation(
            args.config_path,
            repo_root=args.repo_root,
            source_bundle_path=args.source_bundle_path,
            implementation_commit=args.implementation_commit,
        )
        print(f"{bundle_id} {study.study_id} {study.disposition.value} {path}")
        return
    config = load_adaptive_context_calibration_config(str(args.config_path))
    source_bundle = load_source_bundle(args.source_bundle_path)
    study = validate_evaluation_bundle(
        args.evaluation_bundle_path,
        config=config,
        source_bundle=source_bundle,
        implementation_commit=args.implementation_commit,
    )
    print(f"{study.study_id} {study.disposition.value} validated")


if __name__ == "__main__":
    main()
