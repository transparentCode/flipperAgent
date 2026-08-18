"""Run the deterministic C3B2 provider-recovery certification."""

from __future__ import annotations

import asyncio
import json

from tests.combined.c3b2_harness import run_certification, write_artifact


async def _main() -> None:
    evidence = await run_certification()
    write_artifact(evidence)
    print(
        json.dumps(
            {
                "artifact": "artifacts/combined_c3b2/"
                "c3b2_ingestion_decision_provider_recovery_disagreement_certification.json",
                "terminal_status": evidence["terminal_status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
