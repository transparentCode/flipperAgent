"""CLI facade for the network-free SR-V2.0 evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_study


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen SR-V2.0 displacement-origin adequacy")
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    arguments = parser.parse_args(argv)
    bundle_id, path, study = run_study(
        arguments.config,
        repo_root=Path(arguments.repo_root),
    )
    print(f"bundle_id={bundle_id}")
    print(f"path={path}")
    print(f"study_id={study.study_id}")
    print(f"disposition={study.decision.disposition.value}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
