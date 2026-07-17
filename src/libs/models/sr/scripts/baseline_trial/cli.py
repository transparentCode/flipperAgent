"""Command-line entry point for the frozen SR-V1.5 baseline trial."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .runner import run_trial_from_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SR-V1.5 baseline trial")
    parser.add_argument(
        "--config",
        required=True,
        help="path to the immutable trial YAML configuration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result, publication = asyncio.run(
        run_trial_from_config(args.config, repo_root=Path.cwd())
    )
    summary = {
        "trial_name": result.trial.trial_name,
        "bundle_id": publication.bundle_id,
        "output_path": str(publication.output_path),
        "raw_row_count": result.atr.raw_bar_count,
        "warmup_row_count": result.atr.warmup_count,
        "model_row_count": result.atr.model_bar_count,
        "trace_id": result.trace.trace_id,
        "diagnostics_id": result.diagnostics.diagnostics_id,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the live command
    raise SystemExit(main())


__all__ = ["main"]
