---
goal: Restore decision_app failure isolation and remove proven compatibility and orchestration debt before PriceRelay/D9D
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, pre-d9d, architecture, hardening]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — Pre-D9D architecture hardening

## 1. Starting state and boundary

- Starting SHA: `4fc0de62515112dc371e08a6cde503746c54f7f7`.
- Worktree: `/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0`.
- The worktree was already a cumulative dirty D0–D9C checkout. The two
  pre-existing tracked modifications and all cumulative untracked programme
  files were preserved. No commit, merge, push, branch switch, reset, or
  restore was performed.
- This package did not start PriceRelay/D9D, add a model, add a production
  decision asset file, change signal_app/strategy_app, or alter external state.

## 2. Implemented hardening

### Lane-failure isolation

Before this package, a D9B `RECONSTRUCTION_REQUIRED` result could queue a
causal whole-generation rebuild. The service now records the affected lane/input
as degraded in the current generation and leaves the rebuild request unset.
`InputReadCursor`, `BarStore` progress, and healthy unrelated lanes continue;
the affected lane's watermark remains unchanged and it cannot continue from
stale state.

The independent-series regression proves:

```text
lane A reconstruction-required
    -> generation unchanged, service DEGRADED
    -> lane A remains fail-closed
    -> lane B cursor/evaluation/watermark continue
    -> no generation-factory call
```

Manual resume/reconnect and authoritative lifecycle reconciliation remain the
explicit fresh-generation D9A boundaries. The removed causal budget and
`CAUSAL_RECONSTRUCTION` source are not retained.

### Explicit model integration seam

`startup.py` no longer imports SR code and has no plugin-name branch. Stateful
startup initialization resolves only through
`RuntimePluginCatalog.initialization_for(binding)`. The reviewed SR
initialization horizon is registered in the existing explicit composition
registration, using the canonical asset prefix of the resolved `lane_id` and
the resolved SR configuration. No new plugin or adapter framework was added.

### Exact async and construction contracts

- `GenerationFactory` is an explicit async protocol with keyword-only
  `reason` and `generation_id`; there is no `inspect.signature()` or arity
  guessing.
- Direct XREAD/XRANGE/XREVRANGE/XADD calls use one awaited client shape.
  Keyword/positional `TypeError` retries and sync/async `_maybe_await`/`_await`
  compatibility wrappers were removed from the affected boundaries.
- Production composition requires `xread`, `xrange`, `xrevrange`, and `xadd`
  and constructs `ValkeySignalPublisher` unconditionally after that check.
- D9B exact-ID publication, ambiguity reconciliation, D8 finalization, state
  commit, watermark, and checkpoint ordering were not changed.

### Dead aliases and event-driven control

Removed the reviewed dead surfaces:

```text
4 identity compatibility exports
LiveInputReader
DecisionModelRuntime
LaneModelRuntime
FeaturePlan.feature_history_requirements
evaluate_lane_readiness
ModelRuntime.rewarm_causally
```

That is 10 alias/wrapper surfaces in total. A final source scan found zero
matches for the retired names. `DecisionService._wait_for_wake()` now waits on
the existing event rather than using a 50 ms timeout loop. The new regression
proves a paused service does not poll-spin without a control wake.

## 3. Permanent guardrails

Added:

```text
tests/decision/test_architecture_guardrails.py
```

The guard suite checks that active decision production code has:

- no legacy application runtime imports;
- no `FeatureVector`/ModelManager/legacy runtime-runner surface;
- no XREADGROUP/XACK/XAUTOCLAIM/XGROUP/PEL consumer machinery;
- no dynamic plugin discovery;
- no generic-module `libs.models.*` imports;
- no model-specific branches in generic orchestration;
- no factory signature guessing or sync/async compatibility fallback;
- no retired aliases.

The guards intentionally do not forbid the approved D1 `PriceRelayPlan` and
`PriceRelayProgress` semantic contract types; no PriceRelay runtime or
`price_update:*` implementation was added.

## 4. Documentation/configuration

Updated:

```text
docs/architecture/decision_app/README.md
```

It now states that D0 is frozen, D9A–D9C are the current approved
implementation, there is no required concrete `AssetRuntime` actor/class,
manifest gating and generations express asset availability, and lane-local
reconstruction failure does not trigger a global automatic rebuild. Manual
reconnect and lifecycle reconciliation are explicit generation boundaries.
PriceRelay/D9D is explicitly next and not implemented.

The existing `configs/decision/global.yaml` carries the approved D9C
live-input/publication settings. `configs/decision/assets/*.yaml` remains
intentionally absent; no production decision graph was invented.

## 5. Structural inventory

Final measured decision production inventory:

```text
Python modules                         37
production source LOC                  14,328
internal import cycles                 0
long-lived service create_task sites   2
retired alias matches                  0
```

The available D9C inventory was also 37 modules; no LOC target was used as an
acceptance criterion. The hardening removed compatibility concepts while
retaining the large causal/PIT/state/publication validation surfaces. The
targeted compatibility scan is zero for `inspect.signature`, `_maybe_await`,
the affected alternate-signature `TypeError` fallbacks, and retired consumer
group APIs.

## 6. Validation evidence

```text
focused D9C + guardrail tests                         36 passed
complete tests/decision                              319 passed
non-research SR core/config/lifecycle/replay slice   349 passed
SR import/research-boundary slice                    25 passed
commons config/connections/manifest slice            50 passed
ingestion lifecycle/outbox/HTF contract slice       144 passed, 1 skipped
risk + signal compatibility slice                   242 passed, 1 warning
Ruff check (decision + SR adapter scope)             passed
Ruff format --check                                  71 files already formatted
compileall                                           passed
git diff --check                                     passed
scoped trailing-whitespace scan                     0 matches
no-network decision import smoke                     37 modules imported
D2 validation                                         3/3 passed
catalog YAML parse                                    passed
decision architecture SVG presence/non-empty        3/3 passed
local Markdown link check                             0 missing links
```

The complete decision suite includes the D9A/D9B/D9C, D8, D7A, and D1–D6
compatibility surfaces. The focused SR slice intentionally excludes research
tests requiring unavailable frozen bundles/capsules; those artifacts are not
needed for this hygiene package.

No repository `.env` exists in this worktree, so local Timescale/Valkey
validation remains:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

No credentials were created or copied and no external/shared signal state was
mutated. Repo-local `__pycache__` directories were removed after validation.

## 7. Two-pass self-review

### Pass 1 — architecture/correctness

Verified:

- reconstruction-required lane failure is isolated from healthy streams/lanes;
- no stale state continuation was introduced;
- manual/lifecycle rebuilds still reconstruct fresh state;
- startup SR behavior remains through the explicit runtime registration seam;
- D8 exact-ID publication and checkpoint ordering remain untouched;
- InputReadCursor and LaneCommitWatermark remain independent;
- no new model behavior or production model configuration was added.

### Pass 2 — anti-overengineering

Verified:

- no lane recovery worker/task/queue or new supervisor/framework;
- no dynamic discovery or multiple-signature factory adapter;
- no sync/async compatibility shim at the cleaned boundaries;
- only proven dead aliases were removed;
- no DataResolver/state-codec expansion, new config knob, PriceRelay runtime,
  new model, or production asset YAML;
- no large file split was performed for aesthetics.

## 8. Residual risks / carry-forward

- Local Timescale/Valkey integration remains environment-gated by the missing
  `.env`; it was not forced with copied credentials.
- PriceRelay continuity and downstream risk missed-price semantics remain the
  separately reviewed D9D gate.
- D7B/Momentum remains deliberately deferred.
- The existing SR research asset failures remain outside this package's focused
  non-research evidence.

No D9D work was started. The worktree is ready for independent orchestrator
review.

DECISION_APP_PRE_D9D_ARCHITECTURE_HARDENING_READY_FOR_REVIEW
