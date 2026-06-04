#!/usr/bin/env python
"""Diagnose RegimeClassification alpha-ladder JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.models.regime_classification.optimization.diagnostics import (
    diagnose_alpha_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose alpha-ladder policy stability and shuffled controls.",
    )
    parser.add_argument("paths", nargs="+", help="Alpha-ladder JSON artifacts")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    diagnostics = []
    for path_text in args.paths:
        path = Path(path_text)
        payload = json.loads(path.read_text())
        result = diagnose_alpha_payload(payload)
        result["path"] = str(path)
        diagnostics.append(result)

    output: dict[str, Any] = {"diagnostics": diagnostics}
    text = json.dumps(_compact(output) if args.compact else output, indent=2)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for diagnostic in payload["diagnostics"]:
        for report in diagnostic["reports"]:
            rows.append(
                {
                    "path": diagnostic["path"],
                    "asset": report["asset"],
                    "timeframe": report["timeframe"],
                    "folds": report["folds"],
                    "policy_stability": report["policy_stability"],
                    "failure_counts": report["gate_failures"]["failure_counts"],
                    "shuffled_best_rows": report["shuffled_control"]["best_rows"],
                    "validation_oos_decay": report["validation_oos_decay"],
                }
            )
    return {"reports": rows}


if __name__ == "__main__":
    main()
