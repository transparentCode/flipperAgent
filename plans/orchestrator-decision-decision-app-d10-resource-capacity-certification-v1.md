---
goal: Approve D10 resource/capacity certification after fail-closed harness remediation
stage: orchestrator-decision
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision-app, d10, capacity, resources, certification, approved]
---

# Decision

`DECISION_APP_D10_RESOURCE_CAPACITY_CERTIFICATION_APPROVED`

D10 is approved after independent review of the remediated certification harness and fresh artifact.

## Verified remediation closure

- The 8 GiB hard RSS gate evaluates all five certified scenarios, including the SR adapter reference.
- A synthetic 9 GiB SR scenario returns `BLOCKED_RESOURCE_ENVELOPE`.
- Service task evidence is measured directly without a synthetic minimum; forced zero-task evidence remains `0/0/0` and fails the scenario.
- Current risk asset/timeframe routes are derived through the same `ConfigManager` + `discover_asset_timeframes()` path used by `risk_app`.
- Artifact integrity separates stable workload identity from the full measurement/evidence digest; tampering RSS changes the measurement digest while identity remains stable.
- The 1,000-step SR diagnostic runs through `SRDecisionPlugin` and separately records internal model state growth and bounded decision artifact projection.
- No production decision runtime source, executor, thread/process pool, sharding, resource manager, new model/plugin, D11 work, production decision asset YAML, or deployment registration was introduced.

## Artifact integrity

- Artifact: `artifacts/decision_d10/d10_resource_capacity_certification.json`
- SHA-256: `2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459`
- Stored/recomputed deterministic identity SHA-256: `ce2e4750ad6fcf34e4f6d370cb49b3fa34f5e491ee39942de3a0ae8778e76302`
- Stored/recomputed measurement payload SHA-256: `2851062eed11fd82aaf9b5576dcc28181a0c2ee64abfbcc4e1af6939ffccf597`
- Artifact status: `APPROVED`

## Independent resource rerun

A fresh in-memory certification run, without rewriting the artifact, returned:

```text
status APPROVED
inventory 6 assets / 54 canonical series / 7 current risk routes

current_risk_relay_boundary
  RSS 55,967,744 bytes
  CPU core-equivalent 0.9872

service_lifecycle_boundedness
  RSS 56,033,280 bytes
  CPU core-equivalent 0.9539
  task counts start/peak/stop = 2 / 2 / 0

full_canonical_54_series_boundary
  RSS 56,262,656 bytes
  CPU core-equivalent 0.9717

retention_edge_54x200
  RSS 72,826,880 bytes
  CPU core-equivalent 0.9867
  10,800 publications / 20 passes

sr_reference_1000_steps
  RSS 314,458,112 bytes
  CPU core-equivalent 0.9981
  internal zone count max 116
  projected decision artifact zone count max 2
  configured max_active_zones 8
```

All resource gates were true:

- normal current-risk RSS < 5 GiB;
- retention RSS < 8 GiB;
- all five scenario RSS samples < 8 GiB;
- all scenario CPU core-equivalents <= 4;
- all scenario correctness gates true.

## Independent validation

- D10 focused certification: 15 passed.
- D9D focused: 34 passed.
- Complete `tests/decision`: 360 passed.
- Risk + signals/integration + commons + execution: 394 passed, one existing OpenTelemetry deprecation warning.
- Ingestion config/domain/provider/publication/service/storage/runtime/API/N3A/N3B slice: 428 passed; additional root application-bootstrap/canonical-namespace files: 9 passed.
- Scoped Ruff: passed.
- Ruff format check: passed.
- AST syntax validation: passed.
- `git diff --check`: passed.
- Static architecture scan: exactly two `asyncio.create_task` sites; no decision-side PEL/consumer groups; no executor/thread/process fan-out; no D10 production resource knobs; no D11/shadow/deployment leakage.

The coder handoff reported an affected-ingestion selector of 430 passed. The exact selector was not recorded, so independent review used a broader explicit affected-domain slice rather than manufacturing that count; all independently exercised ingestion tests were green.

## Environment limitation

`.env` remains absent. The optional live Timescale/Valkey resource probe therefore remains:

`LOCAL_INFRASTRUCTURE_RESOURCE_PROBE_BLOCKED_ENVIRONMENT`

No credentials were created or copied and no external state was mutated. This does not block the approved offline core certification.

## Carry-forward

D10 certifies the current fused core runtime and current representative SR boundary only. It does not certify the eventual selected production model set.

The following remain mandatory before authoritative shadow/cutover of the selected model mix:

- `FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED`
- `MODEL_STATE_RESOURCE_REVIEW_REQUIRED_DURING_MODEL_REFACTOR`

The SR diagnostic shows model-owned encoded state growth while the decision artifact projection remains bounded; this is correctly deferred to the model-refactor programme rather than redesigned in D10.

No D11 or model-refactoring implementation was started during review.
