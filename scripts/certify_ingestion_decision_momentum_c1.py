from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from tests.combined.c1_harness import run_c1_certification

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "combined_c1"
    / ("c1_ingestion_decision_momentum_certification.json")
)


def _serialized(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"


async def _build_twice() -> dict[str, object]:
    first = await run_c1_certification()
    second = await run_c1_certification()
    if first != second:
        raise SystemExit("C1 certification was not deterministic across fresh runs")
    return first


def main() -> None:
    artifact = asyncio.run(_build_twice())
    if artifact["terminal_status"] != (
        "INGESTION_DECISION_C1_DETERMINISTIC_STITCH_REMEDIATION_READY_FOR_REVIEW"
    ):
        raise SystemExit(artifact["terminal_status"])
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialized(artifact)
    ARTIFACT.write_bytes(payload)
    print(f"artifact={ARTIFACT}")
    print(f"sha256={hashlib.sha256(payload).hexdigest()}")
    print(f"status={artifact['terminal_status']}")


if __name__ == "__main__":
    main()
