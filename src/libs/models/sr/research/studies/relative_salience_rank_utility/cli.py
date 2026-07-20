"""Explicit V2.4 source and evaluation commands; no implicit provider access."""

from __future__ import annotations

import argparse
from pathlib import Path

from libs.models.sr.research.provenance.repository import repository_commit

from .artifacts import load_source_bundle, publish_evaluation_bundle, publish_source_bundle, validate_evaluation_bundle
from .config import load_relative_salience_rank_config
from .runner import compute_study
from .source import fetch_and_freeze_source_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SR-V2.4 causal relative-salience rank utility")
    parser.add_argument("command", choices=("prepare-source", "evaluate", "validate"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default="configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    parser.add_argument("--source")
    parser.add_argument("--evaluation")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    config = load_relative_salience_rank_config(str(root / args.config))
    commit = repository_commit(root)
    if args.command == "prepare-source":
        bundle = fetch_and_freeze_source_sync(config, repo_root=root, implementation_commit=commit)
        bundle_id, _ = publish_source_bundle(bundle, output_root=root / config.payload["artifact"]["output_root"])
        print(bundle_id)
        return 0
    if args.source is None:
        parser.error("--source is required")
    source = load_source_bundle(root / args.source)
    if args.command == "evaluate":
        study = compute_study(config, source_bundle=source, implementation_commit=commit)
        bundle_id, _ = publish_evaluation_bundle(study, config=config, output_root=root / config.payload["artifact"]["output_root"])
        print(bundle_id)
        return 0
    if args.evaluation is None:
        parser.error("--evaluation is required for validate")
    study = validate_evaluation_bundle(root / args.evaluation, config=config, source_bundle=source, implementation_commit=commit)
    print(study.study_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
