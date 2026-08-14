---
goal: Implement the minimal executable semantic contract layer for decision_app from the approved D0 architecture
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d1, contracts]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D1 core semantic contracts

## 1. Objective and evidence

Implement the **smallest executable contract layer** required by the approved D0 architecture under `docs/architecture/decision_app/`.

D1 converts architecture semantics into typed, immutable, independently testable Python contracts. It does **not** implement the runtime.

The approved D0 package in this worktree is the source of truth:

```text
docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
docs/architecture/decision_app/decisions.md
docs/architecture/decision_app/catalog.yaml
plans/coder-to-orchestrator-decision-app-d0-architecture-freeze-v1.md
```

Continue in this exact isolated worktree because D0 is not yet integrated into `main`. Do not create a fresh D1 worktree from plain `main` and lose the approved contract artifacts.

Expected terminal status:

```text
DECISION_APP_D1_CORE_CONTRACTS_READY_FOR_REVIEW
```

## 2. Scope

### Allowed production scope

Create the minimal package/contracts needed for D1. Prefer this ownership split unless live-repo inspection reveals a concrete conflict:

```text
src/libs/contracts/decision.py
src/apps/decision_app/__init__.py
src/apps/decision_app/contracts.py
src/apps/decision_app/identity.py
```

The ownership rule is important:

- **plugin-facing semantic types** belong in `src/libs/contracts/decision.py`, so future `src/libs/models/*` plugins never need to import `apps.decision_app`;
- **application-owned runtime/progress/binding/policy types** belong in `src/apps/decision_app/contracts.py`;
- deterministic canonical identity/fingerprint helpers belong in `src/apps/decision_app/identity.py`.

Do not create additional production modules unless a type cannot be placed cleanly in these files without violating ownership. If more than these files appear necessary, stop and report the concrete reason rather than expanding the package speculatively.

### Allowed tests

Create a focused D1 test package, approximately:

```text
tests/decision/test_semantic_contracts.py
tests/decision/test_identity.py
tests/decision/test_plugin_contract.py
```

A fourth focused test file is acceptable only if it materially improves boundary/PIT coverage.

### Documentation

D0 architecture is frozen. Do not rewrite it during D1. A tiny correction is allowed only if implementation proves an actual contradiction in the approved D0 contract; if so, stop implementation and report the conflict for architect review instead of silently changing architecture.

## 3. Explicit non-goals

D1 must **not** implement or modify:

```text
Valkey consumers/read loops
InputReadCursor runtime behavior
BarStore implementation
DecisionLane runtime
FeaturePlan execution
DataResolver adapters
Timescale reads
scraper_service clients
model loading/discovery
model dependency planner/topological execution
DecisionPolicy logic
PriceRelay runtime
signal/price publication
FastAPI/control plane
observability runtime
Docker/Compose
configs/decision
real model migration/adapters
signal_app
strategy_app
risk_app
execution_app
ingestion_app behavior
checkpoint persistence
training/optimization
```

Do not add new dependencies to `pyproject.toml`.

Do not commit, merge, push, switch branches, reset, or restore.

## 4. Selected contract design

Use existing repository conventions. Pydantic v2 is already a project dependency; frozen dataclasses are also acceptable where they produce a smaller, clearer contract. Choose one coherent style rather than mixing frameworks casually.

The hard acceptance rule is **effective immutability at the plugin boundary**. A model must not be able to mutate shared context mappings/lists and thereby affect another model. Prove this with tests. Do not claim immutability merely because the outer Pydantic model uses `frozen=True` while nested dict/list objects remain mutable.

No contract may import infrastructure modules such as:

```text
asyncpg
valkey
redis
httpx
requests
apps.scraper_app
apps.ingestion_app runtime/service modules
DBPoolManager
ConfigManager
```

The contract layer may import standard-library types and other pure shared contract utilities where genuinely useful.

## 5. Plugin-facing semantic contracts

Implement in `src/libs/contracts/decision.py` the minimum types required by D0.

### 5.1 Causal bar view

Introduce one immutable bar-view contract suitable for canonical closed bars and intentionally projected bars.

It must preserve explicit UTC semantics and raw market precision. Reuse the canonical ingestion principles rather than the legacy seconds/milliseconds payload convention.

At minimum it must represent:

```text
timeframe
bar_open_at
bar_close_at
market_as_of
open
high
low
close
volume
taker_buy_base
closed
```

Use a precision-preserving numeric type for raw OHLCV values consistent with canonical ingestion (`Decimal` is the current canonical representation). Do not reintroduce float/millisecond ambiguity at the raw-bar contract boundary.

Required invariants include:

- all times are timezone-aware UTC;
- `bar_close_at > bar_open_at`;
- `bar_open_at < market_as_of <= bar_close_at`;
- `closed=True` requires `market_as_of == bar_close_at`;
- `closed=False` permits only a causal projected view with `market_as_of < bar_close_at`;
- OHLC geometry is valid;
- volume is non-negative;
- `taker_buy_base`, when present, is non-negative and must not exceed volume.

Do not import `apps.ingestion_app.domain.CanonicalCandle`; this is a shared semantic view contract, not an app-to-app class dependency.

### 5.2 Model request/base context

D0 deliberately describes `data_requests(base_context, state)` before the complete external-data context exists. Implement a small immutable pre-resolution context, named clearly (for example `ModelRequestContext`), containing only information legitimately available before external request resolution:

```text
asset
venue
instrument_id
lane_id
binding_id
market_as_of
trigger_timeframe
decision_timeframe
trigger_mode
decision_bar
decision_bar_closed
causal_bar_views
shared_features
upstream_artifacts
provenance
```

It must not contain `decision_ready_at`.

### 5.3 `DecisionContext`

`DecisionContext` is the complete immutable model-evaluation input. It should extend/contain the pre-resolution context and add only resolved external data:

```text
external_data: semantic request key -> DataSnapshot
```

It must not contain:

```text
decision_ready_at
DB/Valkey/HTTP clients
repositories
schedulers
physical data-source handles
```

### 5.4 Data semantics

Implement the semantic contracts described by D0:

```text
DataRequirement
DataRequest
DataSnapshot
```

Keep model demand separate from physical policy.

`DataRequirement` may describe only semantic needs such as:

```text
concept
required
replay_support_required
freshness bound(s)
alignment: exact | at_or_before | bounded_window
```

It must not contain physical source names, tables, keys, URLs, source allow-lists, or resolved capability claims.

`DataRequest` is runtime-materialized and includes explicit:

```text
request_key
concept
scope/asset where applicable
market_as_of
required
mode: LIVE | REPLAY
resolver_knowledge_cutoff
```

Use unambiguous duration types (`timedelta`) where possible rather than undocumented numeric-second fields.

`DataSnapshot` carries at least:

```text
request_key
concept
payload
event_time
available_at
fetched_at
source
resolved_capability
provenance
```

Implement a small pure validation function/method that validates a snapshot against a request. It must enforce the D0 PIT rules, including:

```text
event_time <= request.market_as_of
represented window end, when supplied, <= request.market_as_of
available_at <= request.resolver_knowledge_cutoff
fetched_at is never used as proof of historical availability
```

If the contract carries a represented window end explicitly, validate it. Do not infer one from arbitrary payload contents.

`LIVE_AND_REPLAY`, `LIVE_ONLY`, and `UNAVAILABLE` are **resolved datasource capabilities**, not model-owned source choices.

### 5.5 Model specification

Implement `ModelSpec` with only intrinsic plugin semantics required by D0:

```text
name
version
stateful
output_kind: analytical | predictive | decision_capable
supported trigger modes/timeframes as needed by the approved contract
intrinsic shared-feature requirements
intrinsic semantic data requirements
warmup requirements
state reconstruction requirement
```

Do not put asset-specific configuration, physical source routing, risk policy, execution behavior, or infrastructure clients into `ModelSpec`.

Represent warmup requirements with an explicit typed structure rather than an ambiguous untyped integer if multiple timeframes are involved. Keep it small; do not create a general warmup framework.

For stateful V1 specs, required external inputs must be declared as replay-support-required. Runtime resolved-capability enforcement happens later, but D1 should prevent a stateful spec from declaring required external state inputs that explicitly do not require replay support.

### 5.6 Model artifact/outcome/decision

Implement:

```text
ModelArtifact
ModelDecision
ModelOutcome
```

`ModelArtifact` must support analytical outputs that have no trading direction.

`ModelDecision` supports decision-capable/predictive outputs and includes explicit:

```text
binding_id
asset
decision_timeframe
trigger_timeframe
market_as_of
signal_time
direction_hint: -1 | 0 | 1 | absent
score: optional finite numeric score
conviction: optional normalized confidence in [0, 1]
metadata
```

For V1, `signal_time` must equal `market_as_of`; reject contradictory values in the core contract rather than carrying ambiguity forward.

`ModelOutcome` contains:

```text
artifact
optional decision
metadata
proposed_next_state
```

The outer outcome is immutable. The runtime commit behavior is not implemented in D1.

### 5.7 Plugin protocol

Define one small structural protocol, for example `DecisionModelPlugin`, that exposes no infrastructure concepts.

Conceptually:

```text
spec

data_requests(base_context, state_snapshot)
    -> semantic requirements/requests for the one bounded request phase

evaluate(complete DecisionContext, state_snapshot)
    -> ModelOutcome
```

Do not add lifecycle callback proliferation (`on_start`, `on_pause`, `on_disconnect`, `on_checkpoint`, etc.).

Use synthetic test plugins to prove both stateless and stateful structural conformance. Do not migrate a real model in D1.

## 6. App-owned semantic/runtime contracts

Implement in `src/apps/decision_app/contracts.py` only the application-owned shapes needed to make D0 executable later.

At minimum:

```text
ResolvedModelBinding
DecisionPolicyResult
InputReadCursor
LaneCommitWatermark
PriceRelayProgress
LaneReadiness
PriceRelayPlan
```

These are data contracts only; no runtime methods/I/O.

### `ResolvedModelBinding`

Must carry the D0 identity/provenance fields, including:

```text
lane_id
slot_name
plugin_name
plugin_version
parameters
binding_config_fingerprint
binding_id
effective_lane_revision
trigger_timeframe
decision_timeframe
trigger_mode
dependencies: named dependency slot -> binding_id
effective feature/data requirements
risk_profile_key
publication_authority
```

Keep parameters/config values immutable at the contract boundary.

Do not implement model loading or dependency resolution yet.

### Progress contracts

Freeze the separation approved in D0:

```text
InputReadCursor
    canonical input identity
    latest observed stream position
    latest accepted canonical market cutoff

LaneCommitWatermark
    lane_id
    latest committed market_as_of

PriceRelayProgress
    relay plan identity
    latest successfully handled market_as_of
    continuity/gap state
```

These types must not imply that lane failure rolls back input progress.

`LaneReadiness` uses only the states approved by D0:

```text
WARMING
LIVE
DEGRADED
INVALID
PAUSED
STOPPED
```

No new lifecycle states.

### Decision policy result

`DecisionPolicyResult` must contain post-evaluation timing (`decision_ready_at`) and effective lane/policy identity/provenance. It must not move risk/sizing/SL/TP/execution semantics into D1.

## 7. Deterministic identity and fingerprints

Implement in `src/apps/decision_app/identity.py` a deliberately small canonical identity layer.

Required semantics:

```text
binding_config_fingerprint = SHA-256(canonical binding parameters + runtime binding)
binding_id = deterministic identity including lane, slot, plugin/version, binding fingerprint
effective_lane_revision = SHA-256(canonical effective lane + DecisionPolicy configuration)
decision_id = deterministic identity including lane revision + canonical market_as_of
```

Requirements:

- dictionary insertion order cannot change fingerprints;
- equivalent tuple/list configuration representations must be handled deterministically or rejected consistently;
- unsupported/non-finite configuration values fail explicitly rather than hashing unstable representations;
- UTC datetimes use one canonical representation;
- parameter/policy change changes the appropriate fingerprint/revision;
- same effective configuration produces the same identity across repeated construction;
- use full SHA-256 hex for fingerprints unless a shorter display-only representation is separately derived; do not weaken collision resistance for authoritative identity.

Do not create a database registry or generic object-serialization framework. A small canonical JSON-like normalizer + SHA-256 is enough.

## 8. Timing and PIT acceptance criteria

D1 tests must prove:

- timezone-naive datetime rejected;
- non-UTC offset datetime rejected where the contract requires UTC;
- closed/projected bar cutoff rules;
- no magnitude-based timestamp inference exists in the new contracts;
- `decision_ready_at` is absent from `DecisionContext` and present only in post-decision/application output contracts;
- `signal_time == market_as_of` in V1 model decisions;
- external event/window time cannot exceed `market_as_of`;
- replay `available_at` cannot exceed the resolver knowledge cutoff;
- `fetched_at` does not substitute for `available_at`;
- stateful specs cannot rely on required non-replayable semantic data requirements.

## 9. Immutability acceptance criteria

Tests must demonstrate that plugin-visible contracts cannot be mutated in place in ways that affect shared runtime state.

At minimum attempt mutations of:

```text
DecisionContext.shared_features
DecisionContext.external_data
DecisionContext.upstream_artifacts
DecisionContext.causal_bar_views
ResolvedModelBinding.parameters
ResolvedModelBinding.dependencies
ModelArtifact/ModelOutcome metadata where shared
```

The chosen representation must reject mutation or expose immutable snapshots/copies.

Do not implement a heavyweight immutable-collections framework. Use the standard library and/or Pydantic features already available.

## 10. Boundary acceptance criteria

D1 must prove:

- `src/libs/contracts/decision.py` does not import `apps.decision_app`;
- plugin-facing contracts import no infrastructure clients;
- no new package dependency is added;
- no `configs/decision` is created;
- no runtime/read loop/DB/scraper/publication code exists;
- no existing `signal_app`, `strategy_app`, `risk_app`, `execution_app`, or ingestion runtime behavior changes;
- existing shared contract imports remain working.

## 11. Validation

The D0 worktree has no local `.venv`. Use the primary repository interpreter explicitly:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

or the correct equivalent resolved from this worktree. Do not create another environment.

Run focused validation first:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q tests/decision
```

Then run a small compatibility set covering the existing model/shared-contract surfaces that D1 could accidentally disturb, chosen from the live repository after inspection. At minimum include the existing canonical strategy-model contract tests if present.

Run scoped static checks on every new/changed Python file:

```text
ruff check
ruff format --check
compileall
git diff --check
```

Also run an import/boundary scan proving no infrastructure imports entered the shared decision contracts.

D1 does not require Docker, Valkey, Timescale, scraper, FastAPI, or network validation.

## 12. Two-pass coder self-review

### Pass 1 — semantic correctness

Review:

```text
UTC/time semantics
PIT inequalities
closed/projected bar invariants
stateful replay-support rule
DataRequirement vs DataPolicy ownership
plugin context completeness
model artifact vs model decision separation
signal_time semantics
config fingerprint determinism
identity changes under config/policy changes
immutability
```

If implementation requires changing an approved D0 semantic rule, stop and return `DECISION_APP_D1_BLOCKED_ARCHITECTURE_CONFLICT` rather than redesigning it locally.

### Pass 2 — simplicity and scope

Remove/flag:

```text
framework base classes not required by the protocol
generic registries
dependency graph execution
runtime services
I/O adapters
custom serialization frameworks
config loaders
unused enums/types
lifecycle callback proliferation
premature performance machinery
real model adapters
```

The final D1 implementation should look intentionally small.

## 13. Coder handoff

Create:

```text
plans/coder-to-orchestrator-decision-app-d1-core-contracts-v1.md
```

Use repository-compliant YAML front matter and include:

```text
scope executed / explicitly not executed
files and symbols created
contract ownership split
validation commands + exact results
PIT/timing evidence
immutability evidence
identity/fingerprint evidence
boundary/import evidence
compatibility tests
Pass 1 findings
Pass 2 findings
blockers / residual risks
```

Do not claim D2/runtime/data/model parity in D1; those are later phases.

Final line exactly:

```text
DECISION_APP_D1_CORE_CONTRACTS_READY_FOR_REVIEW
```
