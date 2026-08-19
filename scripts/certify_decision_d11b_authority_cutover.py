"""Generate the deterministic D11B authority-cutover certification artifact."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.combined.d11b_harness import ARTIFACT_PATH, build_artifact_from_measured
from tests.combined.d11b_real import run_measured_certification


def main() -> None:
    if os.environ.get("INGESTION_DECISION_RUN_D11B") != "1":
        raise SystemExit(
            "D11B certification requires INGESTION_DECISION_RUN_D11B=1 and "
            "fresh disposable measured trials"
        )
    artifact = build_artifact_from_measured(asyncio.run(run_measured_certification()))
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT_PATH),
                "identity_digest": artifact["identity_digest"],
                "evidence_digest": artifact["evidence_digest"],
                "terminal_status": artifact["terminal_status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
