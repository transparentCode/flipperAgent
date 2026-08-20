"""Run the disposable D12B Decision-only topology certification."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.combined.d12_harness import (
    D12B_ARTIFACT_FILE,
    D12B_BASE_SHA,
    build_artifact,
    file_sha256,
    run_trial,
    stored_artifact_valid,
)


async def main() -> int:
    trial = await run_trial("trial_a")
    trial["source_sha"] = D12B_BASE_SHA
    artifact = build_artifact(trial)
    D12B_ARTIFACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    D12B_ARTIFACT_FILE.write_text(
        json.dumps(artifact, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    stored_artifact = json.loads(D12B_ARTIFACT_FILE.read_text(encoding="utf-8"))
    artifact_sha = file_sha256(D12B_ARTIFACT_FILE)
    print(f"artifact={D12B_ARTIFACT_FILE}")
    print(f"artifact_sha256={artifact_sha}")
    print(f"identity_digest={artifact['identity_digest']}")
    print(f"evidence_digest={artifact['evidence_digest']}")
    print(
        f"gates={sum(stored_artifact['gates'].values())}/{len(stored_artifact['gates'])}"
    )
    print(f"terminal_status={stored_artifact['terminal_status']}")
    return 0 if stored_artifact_valid(stored_artifact) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
