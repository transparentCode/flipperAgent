"""Run the disposable real-container C4A shadow certification."""

from __future__ import annotations

import asyncio
import hashlib
import json

from tests.combined.c4a_harness import (
    ARTIFACT_FILE,
    C4_SUCCESS_STATUS,
    run_c4a_certification,
    stable_artifact,
)


def _sha256_artifact() -> str:
    return hashlib.sha256(ARTIFACT_FILE.read_bytes()).hexdigest()


def main() -> int:
    evidence = asyncio.run(run_c4a_certification())
    ARTIFACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_FILE.write_text(
        json.dumps(stable_artifact(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"terminal_status={evidence['terminal_status']}")
    print(f"artifact_sha256={_sha256_artifact()}")
    print(f"identity_digest={evidence.get('identity_digest')}")
    print(f"evidence_digest={evidence.get('evidence_digest')}")
    return 0 if evidence["terminal_status"] == C4_SUCCESS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
