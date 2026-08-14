---
goal: Implement the D1 core semantic contract foundation for decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d1, contracts]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator handoff — `decision_app` D1 core semantic contracts

## Result

D1 remediation 2 is complete as a small, runtime-free semantic contract
layer. The final hardening closes the remaining adversarial contract gaps
without changing the approved D0 architecture.
The work implements the approved D0 contracts without creating a decision
runtime, configuration, infrastructure client, model loader, or downstream
integration.

No D2 work was started.

## Starting checkout

```text
starting SHA: 4fc0de62515112dc371e08a6cde503746c54f7f7
worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
branch state: detached HEAD from main
starting status: approved D0 docs and D0 handoff were already untracked; D1 files were absent
```

The primary checkout was not modified. No commit, merge, push, branch switch,
reset, or restore was performed.

## Files created

Production contract surface:

```text
src/libs/contracts/decision.py
src/apps/decision_app/__init__.py
src/apps/decision_app/contracts.py
src/apps/decision_app/identity.py
```

Focused tests:

```text
tests/decision/test_semantic_contracts.py
tests/decision/test_identity.py
tests/decision/test_plugin_contract.py
```

Handoff:

```text
plans/coder-to-orchestrator-decision-app-d1-core-contracts-v1.md
```

No existing production application, configuration, Compose, signal,
strategy, risk, execution, portfolio, ingestion, or scraper file was changed.

## Contract ownership

`libs.contracts.decision` contains only plugin-facing semantic types and
standard-library helpers:

```text
CausalBarView
ModelRequestContext
DecisionContext
DataRequirement
DataRequest
DataSnapshot
WarmupRequirements
StateReconstructionRequirement
ModelSpec
ModelArtifact
ModelDecision
ModelOutcome
DecisionModelPlugin
FrozenMapping / deep_freeze / PIT validation
```

`apps.decision_app.contracts` contains application-owned data shapes only:

```text
ResolvedModelBinding
DecisionPolicyResult
InputReadCursor
LaneCommitWatermark
PriceRelayProgress
LaneReadiness
PriceRelayPlan
```

`apps.decision_app.identity` contains a deliberately small deterministic
canonicalizer and SHA-256 identity helpers for binding configuration,
binding IDs, lane revisions, and decision IDs.

## Implemented semantic guarantees

`CausalBarView` requires timezone-aware UTC datetimes, explicit open/close
boundaries, causal `market_as_of`, closed/projected consistency, valid OHLC
geometry, non-negative volume, and bounded `taker_buy_base`. Numeric seconds
and milliseconds are rejected as timestamps; no magnitude-based conversion is
present. Context bar sequences must be chronologically ordered and every bar
cutoff must be at or before the context cutoff.

`ModelRequestContext` and `DecisionContext` are immutable model inputs. They
do not expose `decision_ready_at`, infrastructure handles, or physical data
sources. `DecisionPolicyResult` is the post-evaluation boundary that carries
`decision_ready_at`, requires it to be at or after `market_as_of`, and retains
policy version and binding fingerprints. `ModelDecision` enforces
`signal_time == market_as_of`.

`DataRequirement` contains semantic demand only. `DataRequest` is explicitly
runtime-materialized, requires an explicit runtime-owned `LIVE` or `REPLAY`
mode, and requires a resolver-supplied knowledge cutoff at or after the market
cutoff; plugins cannot return runtime requests or choose resolver mode.
Snapshot validation rejects `UNAVAILABLE` capabilities in every mode and
enforces:

```text
event_time <= market_as_of
represented_end_at <= market_as_of, when supplied
available_at <= resolver_knowledge_cutoff
REPLAY requires resolved capability LIVE_AND_REPLAY
fetched_at is never used as historical-availability proof
```

Stateful `ModelSpec` values require durable PIT reconstruction and replay-safe
all declared external data requirements, including optional inputs. All
semantic boolean flags reject integer masquerading. Context validation requires
upstream artifacts to match the lane, asset, timeframes, and exact market
cutoff; external snapshot keys must match request keys and their event/window
bounds must not exceed the context cutoff. Causal bar sequences are ordered,
non-overlapping, and the decision bar timeframe must match the decision
timeframe. `ModelArtifact` supports analytical output with no trade decision
and carries immutable provenance. `ModelOutcome` carries optional decision
metadata and an immutable proposed next state, with full artifact/decision
identity agreement. `ResolvedModelBinding` requires non-empty binding,
configuration, and lane-revision identities and verifies plugin/spec name and
version agreement. One structural `DecisionModelPlugin` protocol supports
synthetic analytical, stateless, and stateful implementations without adding
lifecycle or infrastructure methods.

The progress contracts keep `InputReadCursor`, `LaneCommitWatermark`, and
`PriceRelayProgress` independent. D1 contains no runtime behavior, but the
shapes cannot imply rollback of shared input progress when a lane fails.

## Immutability evidence

The contract boundary recursively freezes the supported semantic-value
vocabulary: scalars, UTC datetimes/timedeltas, string-keyed mappings, and
lists/tuples. `FrozenMapping` also rejects normal backing-attribute
reassignment, so its mapping proxy cannot be replaced after construction.
Unsupported custom or mutable objects are rejected rather than retained by
reference. Tests attempt nested mutations, backing-attribute reassignment,
and custom mutable-object injection across context, artifacts, binding
configuration, and outcome state. The public `freeze_model_state` helper
applies the same boundary to opaque incoming model state before a future
runtime supplies it to a plugin.

## Identity evidence

Canonical identity serialization:

```text
mapping keys are sorted
list/tuple configuration is normalized consistently
UTC datetimes use one microsecond ISO representation
Decimal values are represented explicitly
non-finite numbers, unordered sets, naive datetimes, and unsupported objects fail
SHA-256 fingerprints use the complete hexadecimal digest
```

Configuration and policy changes produce different fingerprints/revisions;
equivalent insertion order and repeated construction produce stable values.
Decision identity includes the lane revision and canonical UTC market cutoff.

## Validation

All commands ran in the D0 worktree using the primary repository interpreter
where Python was required:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q tests/decision
30 passed in 0.10s

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
42 passed in 3.35s

/Users/kajukatli/.local/bin/ruff check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
All checks passed.

/Users/kajukatli/.local/bin/ruff format --check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
7 files already formatted.

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
  src/libs/contracts/decision.py src/apps/decision_app
passed

git diff --check
passed
```

Because the D1 files are new and therefore untracked in this cumulative
worktree, the same whitespace check was also run with
`git diff --no-index --check /dev/null` against every new Python file; it
reported no whitespace errors.

The AST/import boundary scan over the three D1 production modules found zero
imports of `asyncpg`, Valkey/Redis clients, HTTP clients, scraper or
ingestion application modules, `DBPoolManager`, or `ConfigManager`. No new
dependency, `configs/decision`, runtime loop, database access, or
infrastructure adapter was introduced.

## Final remediation evidence

The seven adversarial cases from the independent D1 review are covered by
focused regressions:

```text
FrozenMapping backing-attribute reassignment       rejected
DataRequest mode omission                          rejected
empty binding identities                            rejected
plugin/ModelSpec name and version mismatch         rejected
overlapping causal bars                            rejected
decision-bar timeframe mismatch                    rejected
UNAVAILABLE snapshot validation                    rejected
non-bool semantic flags                            rejected
```

The focused D1 suite now reports 30 passing tests. The compatibility command
reports 42 passing tests after adding these regressions. Ruff check, Ruff
format check, compileall, the infrastructure-import boundary scan, and
whitespace checks all pass after the hardening.

## Two-pass self-review

### Pass 1 — semantic correctness

Reviewed UTC enforcement and explicit timestamp typing, closed/projected bar
cutoffs, chronological/cutoff validation for context inputs, PIT
event/window/availability inequalities, explicit live resolver timing,
`fetched_at` separation, explicit request mode, unavailable capability
rejection, stateful replay requirements, semantic-only plugin requests,
analytical-vs-decision output separation, `signal_time` identity, strict
boolean typing, non-overlapping causal history, decision-bar timeframe
identity, nested immutability including backing-attribute and custom-object
rejection, resolved-binding identity agreement, output identity agreement,
and deterministic configuration identity. No unresolved D0 contradiction was
found.

### Pass 2 — simplicity and scope

Confirmed the implementation contains no runtime services, consumer loop,
BarStore, dependency planner, model registry, DataResolver adapter, policy
engine, PriceRelay runtime, persistence, custom serialization framework, or
new dependency. The implementation remains limited to the four requested
production modules and three focused test modules.

## Deferred work and residual risk

Runtime resolution of physical data policy/capability, binding loading,
same-lane dependency planning, causal BarStore progression, lane execution,
publication, PriceRelay recovery, and downstream integration remain deferred
to later authorized phases. D1 intentionally provides only their immutable
semantic boundaries. No production runtime behavior was certified or changed
in this package.

## Final status

DECISION_APP_D1_CORE_CONTRACTS_READY_FOR_REVIEW
