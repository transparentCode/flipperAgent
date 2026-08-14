---
goal: Implement the bounded causal market-state, readiness, and offline decision-view foundation for decision_app
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d3, bar-store, readiness, projection]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D3 causal market-state + offline lane foundation

## 1. Objective

Implement the **smallest offline causal market-state layer** on top of the approved D0–D2 architecture.

D3 is the first phase that processes sequences of market observations, but it remains completely offline and infrastructure-free.

It must provide:

```text
ResolvedDecisionPlan
+ explicit fixed-duration timeframe geometry
        ↓
bounded shared canonical BarStore capacity plan
        ↓
closed canonical bars appended by market-series identity
        ↓
pure lane market-readiness evaluation
        ↓
direct canonical decision view
or causal projected decision view
        ↓
immutable LaneMarketView
```

D3 performs **no model evaluation, no external-data resolution, no feature computation, no publication, and no I/O**.

Expected terminal status:

```text
DECISION_APP_D3_CAUSAL_MARKET_STATE_READY_FOR_REVIEW
```

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

D0, D1, and D2 are approved and are the source of truth. Do not start from plain `main`.

---

## 2. Approved semantic anchors

Preserve these decisions exactly:

1. `ingestion` remains the sole canonical OHLCV/ordinary-HTF authority.
2. Shared market history is stored once per market series, not copied per model.
3. `InputReadCursor`, `LaneCommitWatermark`, and `PriceRelayProgress` remain independent concepts.
4. A degraded decision lane cannot block shared market-state progression or unrelated lanes.
5. Arrival order across timeframes is not causal readiness.
6. Projected higher-timeframe views are explicit and causal; they must never include an unobserved future bucket end.
7. A projected decision view is ephemeral and must never be inserted as canonical history.
8. At an actual decision-timeframe close, canonical ingestion HTF is authoritative; D3 must not synthesize a competing closed HTF candle from lower-TF bars.
9. Model execution, model state, dependency artifacts, shared features, and external data are later phases.
10. Keep the 8 GiB / 4-core target in mind: bounded shared buffers, no Pandas/DataFrame copies, no one-history-per-model design.

---

## 3. Scope

### Preferred production files

Keep D3 small:

```text
src/apps/decision_app/market_state.py
src/apps/decision_app/readiness.py
src/apps/decision_app/view.py
```

Small edits to existing D1/D2 contracts are allowed only if implementation proves an unavoidable contract defect. Do not casually expand `contracts.py`, `planner.py`, or `libs/contracts/decision.py`.

If more than these three production modules appear necessary, stop and report the concrete ownership problem before adding a package hierarchy.

### Preferred tests

Add approximately:

```text
tests/decision/test_market_state.py
tests/decision/test_readiness.py
tests/decision/test_view.py
```

Existing D1/D2 tests remain mandatory compatibility coverage.

### Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

---

## 4. Explicit non-goals

D3 must not implement:

```text
Valkey/XREAD/XREADGROUP
InputReadCursor mutation/read loop
Timescale repository/warmup reader
CanonicalCandle transport adapter
scraper / DataResolver
FeaturePlan / FeatureEngine
model plugin instantiation
DecisionModelPlugin.data_requests()
DecisionModelPlugin.evaluate()
model dependency execution
DecisionPolicy
model state commit / rewarm
PriceRelay runtime/publication
TradeSignal publication
FastAPI/control plane
Docker/Compose
configs/decision
config loader
asset lifecycle supervisor
AssetRuntime orchestration
async task scheduling
thread/executor pools
real model migration
signal_app/strategy_app/risk_app/execution_app changes
session-calendar framework
cross-asset market-state dependencies
```

No new third-party dependency.

Do not commit, merge, push, branch-switch, reset, or restore.

---

# 5. Market-series identity

The BarStore must be shared by market identity, **not lane identity and not model identity**.

Add a tiny immutable key such as:

```text
MarketSeriesKey
  asset
  venue
  instrument_id
  timeframe
```

Rules:

- all fields are non-empty strings;
- deterministic/hashable;
- the same asset/venue/instrument/timeframe used by several lanes resolves to the same key;
- do not include `lane_id`, `binding_id`, policy, or model identity;
- do not import `apps.ingestion_app.domain.CanonicalCandle`.

D3 consumes the already-approved shared semantic `CausalBarView` contract. A later infrastructure phase will adapt canonical ingestion payloads into these views.

---

# 6. Explicit timeframe geometry

Do **not** use permissive timeframe parsing that silently defaults an unknown value to 60 seconds.

D3 needs explicit fixed-duration geometry to:

- calculate expected canonical closed cutoffs;
- align projected decision buckets;
- calculate bounded projection-source capacity.

Implement a very small immutable geometry object, e.g.:

```text
TimeframeGrid
  alignment_origin: UTC datetime
  durations: timeframe -> positive timedelta
```

No YAML/config loading in D3.

The caller supplies the mapping explicitly in tests/offline use. A later runtime phase will construct it from canonical configuration.

Required behavior:

```text
duration(timeframe)
expected_closed_cutoff(timeframe, market_as_of)
bucket_bounds(timeframe, instant)
is_boundary(timeframe, instant)
```

Use the same fixed-duration alignment formula already proven by ingestion:

```text
start = origin + ((instant - origin) // duration) * duration
```

Semantics:

- at an exact boundary `T`, `expected_closed_cutoff(tf, T) == T`;
- inside an open bucket, expected closed cutoff is that bucket's start, i.e. the latest completed bucket end;
- all datetime inputs must be timezone-aware UTC;
- durations must be positive;
- unknown timeframe fails explicitly;
- no fallback duration;
- no timezone conversion or magnitude inference.

D3 V1 supports the current canonical **fixed-duration continuous UTC** calendar only. Do not build equities/FX session-calendar abstractions here. The APIs should remain small enough that a future calendar-aware implementation can replace/extend cutoff calculation without changing model contracts.

Include a weekly-origin test using the ingestion canonical Monday-style alignment origin.

---

# 7. Shared bounded BarStore

Implement one small synchronous in-memory store.

Conceptually:

```text
BarStore
  capacity per MarketSeriesKey
  append(key, closed CausalBarView)
  append_many(key, ordered bars)
  bars_at(key, as_of, limit=None)
  latest_at_or_before(key, as_of)
  latest_cutoff(key)
  retained_count(key, as_of=None)
```

Use standard-library bounded storage (`deque` or similarly small structure). No Pandas, Polars, NumPy requirement, database, cache, or persistence.

## 7.1 Canonical-only invariant

`BarStore` stores only canonical **closed** bars.

Reject:

```text
CausalBarView.closed == False
```

Projected bars are `DecisionViewBuilder` outputs only and never enter canonical storage.

Also enforce:

```text
bar.timeframe == MarketSeriesKey.timeframe
```

## 7.2 Ordering

Within one series:

- newly appended bars must move forward in canonical interval order;
- overlap/backward insertion fails closed;
- input gaps are allowed at the generic BarStore level because D3 does not own a full exchange/session calendar;
- do not infer that wall-clock gaps necessarily mean missing trading data;
- cross-timeframe append order is irrelevant because each series is independent.

## 7.3 Duplicate/conflict semantics

Keep this simple and deterministic.

At minimum:

- exact repeat of the latest retained canonical interval with byte/field-equivalent semantic bar => idempotent duplicate/no mutation;
- same canonical interval with different OHLCV/timing => conflict/fail closed;
- older/backward non-latest insertion => fail closed rather than silently reordering live state.

A small enum/literal like:

```text
INSERTED
DUPLICATE
```

plus explicit exceptions for conflict/order failure is sufficient. Do not create a transaction framework.

## 7.4 Bounded retention

Each registered series has a strictly positive capacity.

Appending beyond capacity evicts oldest retained bars only.

Queries return immutable tuples and never references to a mutable internal container.

No model receives BarStore itself.

---

# 8. Capacity plan derived from D2

Implement a pure helper that compiles the minimum bounded BarStore capacity required by a `ResolvedDecisionPlan` plus `TimeframeGrid`.

Conceptually:

```text
compile_bar_store_capacities(plan, timeframe_grid)
  -> FrozenMapping[MarketSeriesKey, int]
```

For each lane:

1. decision timeframe requires at least one retained canonical bar;
2. trigger timeframe requires at least one retained canonical bar;
3. every `ModelSpec.warmup_requirements.bars_by_timeframe` contributes its requested count;
4. when `trigger_timeframe != decision_timeframe`, projection-source capacity must be large enough to retain one complete decision bucket from trigger bars.

For projection, require:

```text
trigger_duration < decision_duration
decision_duration is an integer multiple of trigger_duration
projection_source_capacity >= decision_duration / trigger_duration
```

If not, fail explicitly as an unsupported D3 timing geometry.

When several lanes use the same `MarketSeriesKey`, capacity is the **maximum required capacity**, not a sum and not multiple buffers.

Do not derive feature lookback capacity yet. D4 may extend/merge capacity requirements when shared feature definitions exist.

Do not reinterpret D1 warmup semantics beyond using the declared bar counts as a lower bound for retained history.

---

# 9. Canonical cutoff readiness requirements

Implement a small immutable lane market-requirements object or pure compiler, e.g.:

```text
LaneMarketRequirements
  lane_id
  market series -> minimum retained bars
  decision_series
  trigger_series
  projected_decision: bool
```

Compile it deterministically from `ResolvedLanePlan` + `TimeframeGrid`.

Required market series include:

- decision timeframe;
- trigger timeframe;
- every timeframe named in any binding's `warmup_requirements.bars_by_timeframe`.

No feature/data/model dependency requirements are added in D3.

---

# 10. Pure lane readiness evaluation

Implement a pure/synchronous evaluator, not a runtime worker.

Conceptually:

```text
LaneReadinessEvaluator.evaluate(
    resolved_lane,
    requirements,
    bar_store,
    timeframe_grid,
    market_as_of,
    input_read_cursor,
    lane_commit_watermark,
) -> LaneReadiness
```

No sleeps, retries, DB queries, or async I/O.

## 10.1 Expected canonical cutoff per timeframe

For every required canonical timeframe, calculate:

```text
expected_cutoff = timeframe_grid.expected_closed_cutoff(tf, market_as_of)
```

This handles arrival-order causality correctly.

Example:

```text
market_as_of = 11:00
required 4h context
latest expected closed 4h cutoff = 08:00
```

At:

```text
market_as_of = 12:00
```

expected 4h cutoff becomes:

```text
12:00
```

Therefore a lane that requires canonical 4h context at 12:00 cannot silently reuse 08:00.

## 10.2 Projected decision timeframe exception

For a projected lane (`trigger_timeframe != decision_timeframe`):

- canonical decision-timeframe history is required only through the latest completed decision bucket;
- while inside an open decision bucket, the current incomplete decision bar is built from trigger-timeframe source bars;
- at an exact decision-timeframe boundary, D3 must require the canonical decision-timeframe bar ending at that boundary rather than creating a synthetic closed projected bar.

This preserves ingestion as ordinary-HTF authority.

## 10.3 Readiness states used in D3

D3 should only *produce* the existing approved `LaneReadiness` contract. Do not add lifecycle states.

Suggested pure classification:

```text
WARMING
  required retained history count is not yet sufficient

DEGRADED
  history exists but an expected canonical cutoff or required projection-source coverage is missing

LIVE
  all D3 market-state conditions are satisfied
```

Do not synthesize `PAUSED`/`STOPPED`; those require control-plane lifecycle input later.

`INVALID` may be used only for an explicit impossible/corrupt market-state invariant if one is represented as data rather than raised. Prefer exceptions for programmer/input contract corruption and `DEGRADED` for missing causal market data.

`missing_dependencies` remains empty in D3 because model dependencies are not executed yet.

`last_rewarm_reason` remains `None` in D3.

## 10.4 Progress separation

Readiness must not imply that `LaneCommitWatermark` controls shared market-state progress.

A test must prove that:

```text
InputReadCursor.latest_market_as_of > LaneCommitWatermark.latest_market_as_of
```

is allowed and BarStore/readiness for unrelated lanes can still advance.

D3 does not mutate either progress object.

---

# 11. LaneMarketView

Add one small immutable lane-level market view, e.g.:

```text
LaneMarketView
  lane_id
  asset
  venue
  instrument_id
  market_as_of
  decision_timeframe
  trigger_timeframe
  trigger_mode
  decision_bar: CausalBarView
  decision_bar_closed: bool
  causal_bar_views: timeframe -> tuple[CausalBarView, ...]
  observed_cutoffs: timeframe -> datetime
  provenance: immutable semantic mapping
```

This is **not** `DecisionContext` yet because it is lane-level and not binding-specific and has no features, external data, upstream model artifacts, or binding ID.

D4/D5/D6 will progressively turn this market view into a complete per-binding `DecisionContext`.

Invariants:

- everything is causal through `market_as_of`;
- all nested mappings/tuples immutable using approved D1 vocabulary;
- `decision_bar.timeframe == decision_timeframe`;
- `decision_bar.market_as_of == market_as_of`;
- `decision_bar.closed == decision_bar_closed`;
- all causal bar views have `bar.market_as_of <= market_as_of`;
- observed cutoffs are UTC and cannot exceed the relevant available view cutoff.

No infrastructure handles.

---

# 12. DecisionViewBuilder — direct canonical path

For an evaluation cutoff exactly on a canonical decision-timeframe boundary:

```text
market_as_of == expected_closed_cutoff(decision_timeframe, market_as_of)
```

D3 must use the canonical closed decision bar whose:

```text
bar_close_at == market_as_of
```

The decision bar is:

```text
closed = True
market_as_of = bar_close_at
```

Do not derive this closed bar from the trigger timeframe even for a projected lane.

If the canonical decision bar has not arrived, view construction fails with a clear missing/not-ready result and readiness remains `DEGRADED`.

---

# 13. DecisionViewBuilder — projected path

Projection is allowed only when:

```text
trigger_timeframe != decision_timeframe
market_as_of is inside the current decision bucket, not at its end
trigger_duration < decision_duration
integer duration ratio
```

Determine current decision bucket using `TimeframeGrid`:

```text
bucket_start <= market_as_of < bucket_end
```

Use only **closed canonical trigger-timeframe bars** from the BarStore that fall inside:

```text
[bucket_start, market_as_of]
```

## 13.1 Projection-source completeness

A projected decision bar must not be built from a partial unknown source history.

For the current D3 fixed-duration continuous-UTC contract require:

- first source bar opens exactly at `bucket_start`;
- final source bar closes exactly at `market_as_of`;
- each source bar starts at the previous source bar's close;
- each source bar duration equals the configured trigger duration;
- no overlap, gap, duplicate, or future source bar;
- number of source bars matches the elapsed duration / trigger duration.

If coverage is incomplete, projection is unavailable and lane readiness is `DEGRADED` rather than silently creating the wrong OHLC.

Do not add session-calendar exceptions. That is a future extension when non-continuous calendars become an active ingestion contract.

## 13.2 Decimal aggregation

Preserve canonical precision:

```text
open   = first source open
high   = max source high
low    = min source low
close  = final source close
volume = Decimal sum
```

`taker_buy_base`:

- if every contributing source bar has a value, sum exactly with Decimal;
- if any contributing source bar has `None`, projected value is `None`;
- never convert missing taker volume to zero.

Projected output:

```text
CausalBarView(
  timeframe=decision_timeframe,
  bar_open_at=bucket_start,
  bar_close_at=bucket_end,
  market_as_of=latest source close,
  closed=False,
  ...
)
```

The projected bucket end is metadata only; it is **not** the causal `market_as_of`.

## 13.3 No canonical writeback

Projection must never call `BarStore.append()` for the decision timeframe.

A test must prove the canonical decision series is byte/structurally unchanged before vs after projection construction.

---

# 14. Causal bar views supplied by LaneMarketView

For each required timeframe, provide bounded canonical history through its expected causal cutoff.

For projected decision timeframe:

- canonical historical decision bars remain in `causal_bar_views[decision_timeframe]`;
- the ephemeral current projected `decision_bar` is separate;
- do not append the projected current bar to canonical history in D3.

This separation is intentional. A later context builder may decide how a specific model combines historical closed bars with the current projected decision bar.

Do not mutate the canonical history tuple to sneak projection into it.

---

# 15. Cross-timeframe arrival-order determinism

D3 must explicitly prove that cross-timeframe transport arrival order does not alter the final causal market view.

For example, given the same canonical set:

```text
1h close @ 12:00
4h close @ 12:00
```

append in order:

```text
1h then 4h
```

and separately:

```text
4h then 1h
```

After both observations exist, readiness/view at `market_as_of=12:00` must be identical.

Within one market series, backward/out-of-order append remains invalid.

---

# 16. Tests — BarStore

Cover at least:

```text
series key is deterministic/hashable
same market series shared across multiple lanes
positive bounded capacity required
ordered closed append succeeds
projected/open bar insertion rejected
timeframe/key mismatch rejected
exact latest duplicate is idempotent
same-interval conflicting bar rejected
backward/overlapping append rejected
capacity evicts oldest only
bars_at excludes future bars
bars_at respects limit
latest_at_or_before is causal
returned history immutable
cross-series append order independent
```

No sleeps or asynchronous tests required.

---

# 17. Tests — timeframe geometry + capacity

Cover:

```text
UTC alignment origin required
positive duration required
unknown timeframe rejected
no fallback duration
exact boundary expected cutoff
inside-bucket expected cutoff
weekly Monday-origin alignment
1m -> 4h projection ratio = 240
trigger duration >= decision duration projection rejected
non-integral projection ratio rejected
shared series capacity uses max across lanes, not sum
warmup requirements raise capacity floor
```

---

# 18. Tests — readiness

Use synthetic D2 plans/specs only.

Cover:

```text
direct 1h lane with current canonical close => LIVE
insufficient retained history => WARMING
sufficient older history but expected current cutoff missing => DEGRADED
4h context at 11:00 accepts canonical 08:00 cutoff
4h context at 12:00 requires canonical 12:00 cutoff
projected 4h lane inside bucket can be LIVE with complete 1m source coverage
projected lane with missing source start/middle/end => DEGRADED
projected lane at exact 4h boundary requires canonical 4h close
lane commit watermark lag does not roll back shared input/readiness
missing_dependencies remains empty
```

---

# 19. Tests — direct/projected views

Cover:

```text
direct decision bar is canonical closed bar
projected market_as_of is latest observed trigger close, never bucket end
projected OHLC exact Decimal aggregation
projected volume exact Decimal sum
missing taker value propagates None
future trigger bars excluded by as_of
projection source completeness enforced
canonical decision history unchanged after projection
projected current bar not inserted into causal_bar_views canonical history
LaneMarketView nested data immutable
same canonical data under cross-timeframe arrival permutation => identical view
```

Include at least one 4h-from-1m synthetic case and one weekly alignment case.

---

# 20. Important failure semantics

D3 does not recover from missing data. It only identifies market-state readiness.

Use fail-closed behavior:

```text
programmer/contract corruption
  -> explicit exception

missing expected canonical cutoff
  -> DEGRADED

insufficient warmup/history
  -> WARMING

incomplete projected source coverage
  -> DEGRADED
```

Do not sleep, retry, query Timescale, or fabricate an older substitute.

A later runtime phase will decide bounded wait / Timescale recovery behavior around this pure core.

---

# 21. Resource / overengineering constraints

D3 must preserve the small-host target.

Reject designs that create:

```text
one BarStore per model
one history copy per lane when market series are identical
DataFrames per evaluation
generic time-series database abstraction
generic event bus
calendar framework
observer pattern
actor model
runtime scheduler
async locks
graph engine
cache framework
copy-on-every-append full history
```

Prefer:

```text
dict[MarketSeriesKey, deque[CausalBarView]]
small immutable tuples returned on query
pure functions for cutoffs/capacity/readiness
```

Do not optimize with NumPy until profiling later demonstrates a need.

---

# 22. Validation

Use the primary repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D3 first:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_market_state.py \
  tests/decision/test_readiness.py \
  tests/decision/test_view.py
```

Then all decision tests:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q tests/decision
```

Then compatibility because D3 consumes D1/D2 contracts:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Run scoped:

```text
ruff check
ruff format --check
compileall
git diff --check
untracked whitespace checks where needed
infrastructure-import/boundary scan
```

Boundary scan must show no D3 production import of:

```text
redis
valkey
asyncpg
httpx
requests
fastapi
apps.scraper_app
apps.ingestion_app runtime/service/repository
DBPoolManager
ConfigManager
pandas
polars
```

Using existing small standard-library/common pure helpers is acceptable only when their semantics are strict enough. Do not use `timeframe_to_seconds(... default=...)` as the authority for D3 timing geometry.

No Docker, DB, Valkey, network, browser, FastAPI, or live-market validation.

---

# 23. Two-pass coder self-review

## Pass 1 — correctness / PIT

Adversarially check:

```text
future bar leakage
future projection leakage
projected market_as_of accidentally set to bucket_end
projected closed HTF synthesized at real boundary
projection written into canonical BarStore
missing first/middle source bar silently tolerated
Decimal -> float conversion
missing taker volume converted to zero
cross-timeframe arrival order affecting result
same-series backward append accepted
canonical cutoff at exact HTF boundary using stale previous HTF
warmup count/capacity under-allocation
unknown timeframe defaulting silently
lane commit watermark incorrectly constraining BarStore progress
```

If D3 reveals an actual D0–D2 architecture contradiction, stop with:

```text
DECISION_APP_D3_BLOCKED_ARCHITECTURE_CONFLICT
```

rather than silently rewriting approved contracts.

## Pass 2 — simplicity / scope

Remove or reject:

```text
runtime orchestration
AssetRuntime class before it is needed
I/O repositories
async machinery
calendar/session framework
feature computation
model execution
state management
publication
price relay
config loaders
DataFrames
third-party time-series libraries
generic event abstractions
unneeded base classes/interfaces
```

D3 should read as a small bounded data core plus pure readiness/view logic.

---

# 24. Coder handoff requirements

Create:

```text
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

Repository-compliant YAML front matter.

Include:

```text
scope executed / explicitly not executed
files/symbols changed
BarStore identity/capacity semantics
duplicate/conflict semantics
timeframe geometry semantics
capacity-plan evidence
readiness cutoff evidence
projected-view PIT/completeness evidence
canonical-no-writeback evidence
cross-timeframe arrival-order determinism evidence
validation commands + exact results
Pass 1 findings
Pass 2 findings
blockers/residual risks
```

Do not claim model execution, feature parity, DataResolver behavior, publication, runtime recovery, PriceRelay behavior, or live integration.

Final line exactly:

```text
DECISION_APP_D3_CAUSAL_MARKET_STATE_READY_FOR_REVIEW
```

Do not start D4 automatically.
