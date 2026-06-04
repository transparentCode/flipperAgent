from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.regime.optimization.candidate_promotion import (
    DEFAULT_CANDIDATES,
    build_candidate_promotion_report,
    load_json_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare regime candidate overlays across breadth and HMM result sets.",
    )
    parser.add_argument(
        "--breadth-results",
        nargs="+",
        required=True,
        help="JSON result files produced by evaluate_current_regime.py with --breadth-variants",
    )
    parser.add_argument(
        "--hmm-results",
        nargs="+",
        required=True,
        help="JSON result files produced by evaluate_current_regime.py with --hmm-variants",
    )
    parser.add_argument(
        "--candidates",
        nargs="+",
        choices=sorted(DEFAULT_CANDIDATES),
        default=list(DEFAULT_CANDIDATES),
    )
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    breadth_rows = load_json_rows(args.breadth_results)
    hmm_rows = load_json_rows(args.hmm_results)
    report = build_candidate_promotion_report(
        breadth_rows,
        hmm_rows,
        candidate_names=tuple(args.candidates),
    )
    payload = json.dumps(report, indent=2)
    print(payload)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)


if __name__ == "__main__":
    main()
