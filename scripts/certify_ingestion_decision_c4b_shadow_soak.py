"""Run the disposable C4B shadow soak twice and write its evidence artifact."""

from __future__ import annotations

import asyncio
import json

from tests.combined.c4b_harness import (
    ARTIFACT_FILE,
    run_c4b_certification,
    stable_artifact,
)


async def _run() -> int:
    evidence = await run_c4b_certification()
    ARTIFACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_FILE.write_text(
        json.dumps(stable_artifact(evidence), sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT_FILE),
                "terminal_status": evidence["terminal_status"],
                "gates": evidence["gates"],
                "identity_digest": evidence["identity_digest"],
                "evidence_digest": evidence["evidence_digest"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if evidence["terminal_status"]
        == "INGESTION_DECISION_C4B_SHADOW_SOAK_RESOURCE_CERTIFICATION_READY_FOR_REVIEW"
        else 1
    )


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
