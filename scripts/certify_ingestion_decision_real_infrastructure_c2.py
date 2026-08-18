"""Run the disposable two-trial C2 real-infrastructure certification."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.combined.c2_harness import (
    C2_SUCCESS_STATUS,
    run_c2_certification,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "combined_c2"
    / "c2_ingestion_decision_real_infrastructure_certification.json"
)


def _serialized(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")
        + b"\n"
    )


async def _run() -> dict[str, object]:
    return await run_c2_certification()


def main() -> int:
    evidence = asyncio.run(_run())
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(_serialized(evidence))
    print(
        json.dumps(
            {"artifact": str(ARTIFACT), "terminal_status": evidence["terminal_status"]},
            sort_keys=True,
        )
    )
    return 0 if evidence["terminal_status"] == C2_SUCCESS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
