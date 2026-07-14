# Trendline Family Model — Phase A Approval

Date: 2026-07-11
Status: APPROVED
Mode: quant-approval

## Decision

Phase A — Foundation, Contracts, and Configuration is approved.

Phase B — Native Candidate Generation may begin.

## Approved Scope

The approved Phase-A implementation includes:

- independent canonical package under `src/libs/models/trendline_family`,
- exact timestamp-space line geometry,
- causal anchor contracts,
- deterministic canonical serialization and IDs,
- immutable published family/snapshot contracts,
- strict layered configuration resolution,
- field provenance and deterministic resolved config hashes,
- in-memory snapshot repository with lineage checks,
- recursive metadata freezing,
- root-discoverable tests,
- static import and YAML-read boundaries.

## Final Review Evidence

Commands rerun during approval review:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
39 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed

codebase-memory-mcp cli index_status '{"project":"Users-aloobhujia-flipperAgent"}'
ready: 36,291 nodes / 107,071 edges
```

Adversarial regression checks confirmed:

- `FamilyMember` without two anchors is rejected,
- invalid BIRTH versioning is rejected,
- non-BIRTH version jumps are rejected,
- duplicate transition IDs are rejected,
- first-snapshot family version greater than one is rejected,
- nested caller mutation does not change resolver output.

## Architecture Conformance

Confirmed:

- no runtime imports from `libs.trendlines`, `libs.models.trendlines_old`, or `app.trendlines`,
- YAML access remains confined to `config_loader.py`,
- exact line geometry remains distinct from interaction zones and uncertainty,
- no pivot, fitter, provider, tracker, RegimeV2, MTF, or optimization logic entered Phase A,
- published state remains immutable,
- geometry remains separate from trading policy.

## Residual Risks

- Full root pytest collection is still blocked by the unrelated missing `apps.tv_scraper` import in `tests/test_tv_browser_backfill.py`.
- Phase B must preserve all Phase-A tests and must not weaken current contracts to fit copied legacy algorithms.
- Existing trendline packages remain offline references only; Phase-B runtime code must be fully self-owned.

## Approved Next Handoff

Implement Phase B only from:

- `plans/trendline-family-codex-phase-execution-plan.md`
- `plans/trendline-family-model-architecture-plan.md`
- this approval record

Phase B must add native causal candidate generation and stop before matching/tracking.
