"""Run the guarded C3B1 canonical-integrity certification."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.combined.c3b1_harness import run_c3b1_certification

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "combined_c3b1"
    / "c3b1_ingestion_decision_canonical_integrity_certification.json"
)


def main() -> int:
    evidence = asyncio.run(run_c3b1_certification())
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT),
                "terminal_status": evidence["terminal_status"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if evidence["terminal_status"]
        == "INGESTION_DECISION_C3B1_CANONICAL_INTEGRITY_READY_FOR_PROVIDER_RECOVERY_FAULTS"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
