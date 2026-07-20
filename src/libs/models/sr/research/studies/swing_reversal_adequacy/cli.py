"""CLI facade for the frozen V2.2 study."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_study


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run frozen SR-V2.2 swing-reversal adequacy"
    )
    parser.add_argument("config_path", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bundle_id, path, study = run_study(args.config_path, repo_root=args.repo_root)
    print(f"{bundle_id} {study.study_id} {study.decision.disposition.value} {path}")


if __name__ == "__main__":
    main()
