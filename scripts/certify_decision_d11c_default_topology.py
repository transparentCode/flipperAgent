"""Run the two-trial D11C disposable default-topology certification."""

from __future__ import annotations

import asyncio
import json
import subprocess

from tests.combined.d11c_harness import (
    ARTIFACT_PATH,
    BLOCKED_STATUS,
    D11C_BASE_SHA,
    SUCCESS_STATUS,
    build_artifact,
    current_source_hashes,
    evaluate_artifact,
    production_config_hashes,
    protected_hashes,
)
from tests.combined.d11c_real import run_measured_certification


async def _run() -> dict[str, object]:
    raw = await run_measured_certification()
    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw["source_sha"] = result.stdout.strip()
    raw["base_sha"] = D11C_BASE_SHA
    raw["protected_hashes"] = protected_hashes()
    raw["production_config_hashes"] = production_config_hashes()
    raw["current_source_hashes"] = current_source_hashes()
    return raw


def exit_code_for_status(status: object) -> int:
    return 0 if status == SUCCESS_STATUS else 1


def main() -> int:
    raw = asyncio.run(_run())
    artifact = build_artifact(raw)
    stored_checks = evaluate_artifact(artifact)
    if not all(stored_checks.values()):
        artifact["terminal_status"] = BLOCKED_STATUS
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "terminal_status": artifact["terminal_status"],
                "gates": artifact["gates"],
            },
            sort_keys=True,
        )
    )
    return exit_code_for_status(artifact["terminal_status"])


if __name__ == "__main__":
    raise SystemExit(main())
