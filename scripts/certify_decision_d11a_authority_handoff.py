"""Generate the deterministic D11A authoritative handoff certification."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.combined.d11a_harness import (
    D11A_ARTIFACT,
    D11A_BASE_SHA,
    EXPECTED_LANES,
    EXPECTED_PROTECTED_HASHES,
    current_source_hashes,
    evaluate_artifact,
    file_sha256,
    load_d11a_config,
    m4_route_identity,
    protected_hashes,
    run_trial,
    sha256_fingerprint,
    strategy_relinquishment_evidence,
)


def _fixture_hashes() -> dict[str, str]:
    fixture_root = ROOT / "tests/combined/fixtures/d11a"
    return {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in sorted(fixture_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _production_scope() -> dict[str, object]:
    assets_root = ROOT / "configs/decision/assets"
    assets = (
        sorted(str(path.relative_to(ROOT)) for path in assets_root.rglob("*"))
        if assets_root.exists()
        else []
    )
    models_yaml = ROOT / "configs/models.yaml"
    return {
        "decision_assets": assets,
        "models_yaml_sha256": file_sha256(models_yaml),
        "root_compose_sha256": file_sha256(ROOT / "docker-compose.yml"),
        "observer_active": "momentum_regression_observer"
        in "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "configs/decision").glob("*.yaml")
        ),
    }


def _normalize_trial(raw: dict[str, object]) -> dict[str, object]:
    startup = raw.get("startup", {})
    live = raw.get("live", {})
    restart = raw.get("restart", {})
    live_no_signal = live.get("no_signal_window", {}) if isinstance(live, dict) else {}

    def compact_progress(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "lane_id": item.get("lane_id"),
                "market_as_of": item.get("market_as_of"),
                "last_disposition": item.get("last_disposition"),
            }
            for item in value
            if isinstance(item, dict)
        ]

    def compact_signals(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "stream": item.get("stream"),
                "entry_id": item.get("entry_id"),
                "market_as_of": item.get("market_as_of"),
                "idempotency_key": item.get("idempotency_key"),
                "model_name": item.get("model_name"),
                "direction": item.get("direction"),
                "conviction": item.get("conviction"),
            }
            for item in value
            if isinstance(item, dict)
        ]

    return {
        "schema_upgrade": raw.get("schema_upgrade"),
        "startup": {
            "no_historical_signals": startup.get("no_historical_signals"),
            "signals": compact_signals(startup.get("signals")),
            "progress": compact_progress(startup.get("progress")),
            "active_lane_count": startup.get("runtime", {}).get("active_lane_count"),
            "ready": startup.get("health", {}).get("status") == "ready",
        },
        "live": {
            "materialized": live.get("materialized"),
            "signals": compact_signals(live.get("signals")),
            "progress": compact_progress(live.get("progress")),
            "shadow_keys": live.get("shadow_keys", []),
            "no_signal_window": {
                "progress": compact_progress(live_no_signal.get("progress")),
                "signals": compact_signals(live_no_signal.get("signals")),
                "btc_1h": live_no_signal.get("btc_1h"),
            },
            "oracle_policy_statuses": live.get("oracle_policy_statuses", {}),
        },
        "restart": {
            "materialized_while_down": restart.get("materialized_while_down"),
            "progress_while_down": compact_progress(restart.get("progress_while_down")),
            "signals": compact_signals(restart.get("signals")),
            "progress": compact_progress(restart.get("progress")),
            "catchup_before_new_input": restart.get("catchup_before_new_input"),
        },
        "crash_windows": raw.get("crash_windows"),
        "unsupported_backlog": raw.get("unsupported_backlog"),
        "cleanup": raw.get("cleanup"),
    }


def _identity_payload(
    *,
    protected: dict[str, str],
    source_hashes: dict[str, str],
    fixture_hashes: dict[str, str],
    routes: list[dict[str, object]],
    strategy: dict[str, object],
    m4_identity: dict[str, object],
) -> dict[str, object]:
    return {
        "source_base_sha": D11A_BASE_SHA,
        "c4b_integration_commit": D11A_BASE_SHA,
        "protected_hashes": protected,
        "source_hashes": source_hashes,
        "fixture_hashes": fixture_hashes,
        "routes": routes,
        "strategy": strategy,
        "m4_config_identity": m4_identity,
        "effect_progress_contract": {
            "physical_table": "decision.shadow_progress",
            "dispositions": [None, "shadow", "published", "no_signal"],
            "identity_fields": [
                "lane_id",
                "effective_lane_revision",
                "feature_plan_fingerprint",
                "data_plan_fingerprint",
            ],
        },
    }


async def _run() -> dict[str, object]:
    if os.environ.get("INGESTION_DECISION_RUN_D11A") != "1":
        raise RuntimeError(
            "set INGESTION_DECISION_RUN_D11A=1 for disposable real infrastructure"
        )
    config = load_d11a_config()
    protected = protected_hashes()
    if protected != EXPECTED_PROTECTED_HASHES:
        raise RuntimeError("protected evidence hash mismatch")
    trials = [
        _normalize_trial(await run_trial("trial_a")),
        _normalize_trial(await run_trial("trial_b")),
    ]
    m4_identity = m4_route_identity(config)
    routes = [
        {
            "lane_id": lane.lane_id,
            "asset": lane.asset,
            "decision_timeframe": lane.decision_timeframe,
            "trigger_timeframe": lane.trigger_timeframe,
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
            "m4_parameters": m4_identity["d11a"][lane.lane_id]["parameters"],
        }
        for lane in config.lane_specs()
    ]
    strategy = await strategy_relinquishment_evidence()
    source_hashes = current_source_hashes()
    fixture_hashes = _fixture_hashes()
    production_scope = _production_scope()
    identity_payload = _identity_payload(
        protected=protected,
        source_hashes=source_hashes,
        fixture_hashes=fixture_hashes,
        routes=routes,
        strategy=strategy,
        m4_identity=m4_identity,
    )
    evidence_payload = {
        "trials": trials,
        "production_scope": production_scope,
        "protected_hashes": protected,
        "source_hashes": source_hashes,
        "fixture_hashes": fixture_hashes,
        "strategy": strategy,
        "m4_config_identity": m4_identity,
    }
    artifact: dict[str, Any] = {
        "schema_version": "decision.d11a.authority_handoff.v1",
        "source_base_sha": D11A_BASE_SHA,
        "c4b_integration_commit": D11A_BASE_SHA,
        "protected_hashes": protected,
        "source_hashes": source_hashes,
        "fixture_hashes": fixture_hashes,
        "authoritative_lanes": EXPECTED_LANES,
        "routes": routes,
        "strategy": strategy,
        "m4_config_identity": m4_identity,
        "effect_progress_contract": identity_payload["effect_progress_contract"],
        "production_scope": production_scope,
        "trials": trials,
        "identity_digest": sha256_fingerprint(identity_payload),
        "evidence_digest": sha256_fingerprint(evidence_payload),
    }
    gates, status = evaluate_artifact(artifact)
    artifact["gates"] = gates
    artifact["terminal_status"] = status
    artifact["evidence_digest"] = sha256_fingerprint(
        {**evidence_payload, "gates": gates}
    )
    D11A_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    D11A_ARTIFACT.write_text(
        json.dumps(artifact, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


if __name__ == "__main__":
    result = asyncio.run(_run())
    print(
        json.dumps(
            {
                "artifact": str(D11A_ARTIFACT),
                "identity_digest": result["identity_digest"],
                "evidence_digest": result["evidence_digest"],
                "terminal_status": result["terminal_status"],
            },
            sort_keys=True,
        )
    )
