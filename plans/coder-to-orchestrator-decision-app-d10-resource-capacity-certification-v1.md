---
goal: Certify the approved decision_app core runtime resource envelope, capacity, and boundedness
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d10, capacity, resources, boundedness]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# D10 resource / capacity certification

## Result

D10 completed as a measurement-only package in the cumulative isolated
worktree. The offline core certification passed:

```text
DECISION_APP_D10_RESOURCE_CAPACITY_CERTIFICATION_READY_FOR_REVIEW
```

No decision production source, model, executor, worker pool, sharding layer,
resource manager, production asset YAML, main module, port, Compose entry, or
D11+ work was added for D10. No commit, merge, push, branch switch, reset, or
restore was performed.

## Starting state and worktree

```text
starting SHA: 4fc0de62515112dc371e08a6cde503746c54f7f7
worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
branch: detached cumulative worktree
```

The checkout was already cumulatively dirty from D0-D9D. Unrelated changes
were preserved. D10 additions are limited to the certification facade, focused
tests, bounded artifact, architecture-doc refresh, and this handoff.

## Files added or updated

- `scripts/certify_decision_runtime_d10.py`
  - canonical YAML inventory derivation;
  - current-risk route derivation through `ConfigManager` and
    `discover_asset_timeframes`, without a second hard-coded route catalog;
  - deterministic generated history and direct-cursor/price transport doubles;
  - actual D9A startup, D9B live runtime, D9D PriceRelay, and D9C service
    boundary exercises;
  - standard-library RSS, tracemalloc, CPU, thread, and asyncio-task
    measurements;
  - fail-closed all-scenario RSS/task gates, atomic JSON artifact writing, and
    separate deterministic identity and measurement evidence digests;
  - SR reference measurement through the reviewed `SRDecisionPlugin` artifact
    projection rather than raw-engine snapshot serialization.
- `tests/decision/certification/test_d10_resource_capacity.py`
  - inventory, live risk-discovery, target, 7-route, 54-series, retention-edge,
    service-task, structural-guard, RSS-normalization, fail-closed resource,
    digest-tamper, SR-projection, and artifact-integrity regressions.
- `artifacts/decision_d10/d10_resource_capacity_certification.json`
  - fresh approved offline evidence artifact.
- `docs/architecture/decision_app/README.md`
  - refreshed D9D PriceRelay ownership and current serial V1 resource reality.

No D10 production change was made under `src/apps/decision_app/`.

## Canonical inventory and workload

The facade reads the current canonical ingestion YAML rather than maintaining a
second asset catalog. It derived:

```text
enabled assets       6: BNB BTC DOGE ETH SOL XRP
canonical timeframes 9: 1m 15m 30m 1h 4h 6h 12h 1d 1w
canonical series     54
current risk routes   7
retention edge   10,800 = 54 * 200
live batch size      10
price relay maxlen  200
```

The test-only relay configuration is relay-only (`lanes={}`), so no model
plugin is required to certify the current input/PriceRelay envelope. Relay
series use a `BarStore` capacity of exactly one in the absence of lane or
feature demand.

## Scenario evidence

The fresh artifact was generated at `2026-08-14T16:17:25.685285Z` from the
starting SHA above. Scenario resource measurements are process high-water RSS
and scenario-local tracemalloc peaks:

| Scenario | Result | Wall s | CPU s | CPU cores | RSS bytes | tracemalloc peak |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 7-route current-risk relay boundary | pass | 0.0302 | 0.0291 | 0.964 | 59,752,448 | 503,305 |
| service lifecycle boundedness | pass | 0.0284 | 0.0260 | 0.915 | 59,867,136 | 152,515 |
| full 54-series boundary | pass | 0.1065 | 0.0994 | 0.933 | 60,112,896 | 462,015 |
| 54 x 200 retention edge | pass | 11.0372 | 10.7138 | 0.971 | 77,873,152 | 7,879,081 |
| existing SR 1,000-step adapter reference | pass, diagnostic only | 65.5931 | 65.1767 | 0.994 | 321,880,064 | 115,216,890 |

The retention workload proved:

```text
20 reconciliation passes
<= 10 publications per relay per pass
<= 540 publications per pass
10,800 successful publications
all 54 relays CONTINUOUS
pending targets 0
input failures 0
idle post-drain publications 0
max logical stream entries per relay 200
max canonical-history in-flight 1
max PriceRelay XADD in-flight 1
maxlen/approximate calls: (200, true)
exact close-time ID sequence per relay: PASS
```

The current-risk and full-boundary scenarios proved one accepted/published
observation per configured route/series, no model lane, and one in-flight
history/publication operation. The service scenario proved:

```text
generations [1, 2, 3]
pause PAUSED/PAUSED
lifecycle rebuild remains PAUSED
resume RUNNING
paused PriceRelay publications 7
task count after start 2 (market + lifecycle)
task peak 2 (measured, no synthetic floor)
task count after stop 0
both service task references cleared after stop
Python thread count unchanged
```

The existing SR adapter was measured only as a reference diagnostic. Through
`SRDecisionPlugin`, its encoded proposed state grew from 679 bytes to 78,188
bytes across the 1,000-step fixture. Internal snapshot zone count reached 116,
while the bounded projected artifact zone count reached 2 against the configured
maximum of 8. This is not extrapolated to the final model mix. It carries the
model-specific review item:

```text
MODEL_STATE_RESOURCE_REVIEW_REQUIRED_DURING_MODEL_REFACTOR
```

## Hard envelope and architecture gates

```text
normal current-risk RSS < 5 GiB       PASS
all five scenario RSS samples < 8 GiB  PASS
all measured CPU core-equivalents <=4 PASS
exact decision create_task sites = 2  PASS
executor/process/thread fan-out       0
decision-side consumer-group/PEL use  0
legacy signal/strategy runtime import  0
dynamic model discovery                0
```

The artifact records the optional live infrastructure probe as:

```text
LOCAL_INFRASTRUCTURE_RESOURCE_PROBE_BLOCKED_ENVIRONMENT
```

The worktree has no `.env`; no credentials were copied or fabricated and no
Timescale/Valkey external state was touched. The offline core certification is
not blocked by that optional probe.

## Artifact integrity

```text
artifact: artifacts/decision_d10/d10_resource_capacity_certification.json
SHA-256: 2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
deterministic identity SHA-256:
ce2e4750ad6fcf34e4f6d370cb49b3fa34f5e491ee39942de3a0ae8778e76302
measurement payload SHA-256:
2851062eed11fd82aaf9b5576dcc28181a0c2ee64abfbcc4e1af6939ffccf597
status: APPROVED
```

The artifact is written through a temporary file and `os.replace`, contains
bounded aggregate evidence only, rejects non-finite JSON values, and separates
stable workload identity from a digest that covers scenario measurements,
resource decisions, structural evidence, inventory, and targets. Tampering a
measurement changes the measurement payload digest while preserving workload
identity. The final selected model mix still requires:

```text
FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED
```

## Validation

Focused and cumulative results from this worktree:

```text
D10 focused certification tests      15 passed
tests/decision                       360 passed
D9D focused                         34 passed
SR non-research core/config/adapter 397 passed
risk + signals + commons + execution 388 passed, 1 existing warning
ingestion affected config/domain/provider/
  publication/service/storage/runtime/API/N3A/N3B 430 passed
```

The broader SR research-script collection remains excluded from this
non-research compatibility gate because the checkout lacks the separately
approved frozen research assets; those failures are pre-existing evidence
availability issues and were not touched by D10.

Static checks:

```text
scoped Ruff check                     passed
scoped Ruff format --check            passed
compileall                            passed
git diff --check                      passed
decision import/infrastructure scan  passed
repo-local cache cleanup              passed
```

The one signals warning is the existing OpenTelemetry deprecation warning.
No unavailable frozen SR research assets were required by the D10 reference
fixture.

## Two-pass self-review

Pass 1 — correctness/resource safety:

- verified current inventory derives from canonical ingestion files;
- verified 7-route and 54-series input/PriceRelay progression;
- verified 10,800 exact canonical close-time IDs and no skipped intervals;
- verified PriceRelay progress, pending-target, and failure-map bounds;
- verified input/history/publication seriality and task/thread behavior;
- verified pause/lifecycle/rebuild/stop evidence and no task leak;
- verified SR measurement is diagnostic only and carries model-state review;
- verified RSS/CPU gates against the frozen 5 GiB / 8 GiB / 4-core targets.
- verified the hard 8 GiB RSS gate evaluates every certified scenario,
  including the SR reference;
- verified task evidence records observed counts without a minimum floor and
  fails closed for synthetic zero/one/three-task observations;
- verified current risk routes come from the same ConfigManager/discovery path
  used by risk_app;
- verified measurement evidence tampering changes the measurement digest while
  stable workload identity remains stable;
- verified the SR diagnostic uses the reviewed bounded artifact projection and
  reports internal and projected zone counts separately.

Pass 2 — architecture scope:

- no executor, process pool, sharding, resource manager, or new knob;
- no new model/plugin or Momentum/D7B work;
- no model math, signal/risk/execution contract, PriceRelay, or D9C runtime
  changes;
- no production decision asset YAML, main module, port, or Compose entry;
- no benchmark dependency or unbounded certification ledger;
- artifact and test evidence remain bounded and deterministic where required;
- no production decision runtime source changed during the remediation.

## Carry-forward

This certifies the approved core runtime at its current representative model
boundary only. Before shadow/cutover with the selected model set:

```text
FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED
```

No D11 or model-refactoring package was started automatically.

DECISION_APP_D10_RESOURCE_CAPACITY_CERTIFICATION_READY_FOR_REVIEW
