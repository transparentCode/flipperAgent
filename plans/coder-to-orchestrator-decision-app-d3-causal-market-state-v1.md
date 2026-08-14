---
goal: Implement the bounded causal market-state and offline lane foundation for decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d3, bar-store, readiness, projection]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator handoff — `decision_app` D3 causal market state

## Result

D3 is implemented as a small synchronous, infrastructure-free market-state
core. It stores bounded canonical closed bars by shared market-series identity,
calculates explicit UTC fixed-duration cutoffs, evaluates pure lane readiness,
and builds immutable direct or ephemeral projected lane views.

No model is evaluated and no external service, persistence layer, transport,
runtime scheduler, or downstream application was changed.

## Scope and starting checkout

```text
starting SHA: 4fc0de62515112dc371e08a6cde503746c54f7f7
worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
branch state: detached HEAD from main
primary checkout: not modified
commit/merge/push/branch switch/reset/restore: none
```

The cumulative D0/D1/D2 artifacts were preserved. The D3 change is limited to
the three requested production modules, three focused test modules, and this
handoff.

## Files and symbols changed

```text
src/apps/decision_app/market_state.py
  MarketSeriesKey
  TimeframeGrid
  BarStore
  AppendResult
  compile_bar_store_capacities
  validate_canonical_bar_geometry
  explicit market-state errors

src/apps/decision_app/readiness.py
  LaneMarketRequirements
  compile_lane_market_requirements
  validate_lane_market_requirements
  LaneReadinessEvaluator
  evaluate_lane_readiness

src/apps/decision_app/view.py
  LaneMarketView
  DecisionViewBuilder
  MarketViewNotReadyError

tests/decision/test_market_state.py
tests/decision/test_readiness.py
tests/decision/test_view.py
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

## Shared BarStore and identity semantics

`MarketSeriesKey` is the hashable identity:

```text
asset + venue + instrument_id + timeframe
```

It contains no lane, binding, policy, or model identity. A single `BarStore`
registration therefore serves every lane that uses the same canonical market
series. Capacities are positive and stored immutably; each series uses one
bounded `deque`, and queries return tuples rather than internal containers.

Only closed `CausalBarView` values whose timeframe matches the key are accepted.
Forward gaps are allowed at this generic layer, while backward or overlapping
append attempts fail closed. An exact repeat of the latest retained interval is
an idempotent `DUPLICATE`; a different value for that interval raises
`BarConflictError`. Capacity eviction removes only the oldest retained bars.

All queries apply an explicit UTC cutoff, so future canonical bars are excluded.
Projected bars are not accepted by `BarStore` and no view-builder path calls
`append` for a projected decision bar.

## Timeframe geometry

`TimeframeGrid` requires an aware UTC alignment origin and an explicit positive
duration mapping. Unknown timeframes fail explicitly; there is no fallback
duration or unit inference. Bucket alignment uses:

```text
origin + ((instant - origin) // duration) * duration
```

At an exact boundary the expected closed cutoff is that boundary. Inside an
open bucket it is the aligned bucket start. Weekly alignment is supported by
the caller supplying the canonical Monday-style origin; no session-calendar
framework was added.

## Capacity plan evidence

`compile_bar_store_capacities(plan, grid)` derives the maximum required capacity
per shared `MarketSeriesKey` from every resolved lane. It includes one decision
and trigger bar, all declared model warmup floors, and the complete projection
source ratio when trigger and decision timeframes differ. A 1m-to-4h lane
therefore requires at least 240 retained 1m source bars. Shared series use the
maximum floor across lanes, never a sum or per-model copy.

Projection geometry rejects a trigger timeframe that is not shorter than the
decision timeframe or a non-integral duration ratio.

## Readiness and progress semantics

`LaneMarketRequirements` deterministically includes decision, trigger, and every
model-declared warmup timeframe. `LaneReadinessEvaluator` is pure and
synchronous. It calculates the expected canonical cutoff independently for
each required timeframe, so cross-timeframe arrival order does not determine
causality.

The only D3-produced readiness states are:

```text
WARMING  insufficient retained history
DEGRADED expected cutoff or complete projection source coverage is missing
LIVE     all required market-state conditions are satisfied
```

At an exact projected decision-timeframe boundary, the evaluator requires the
canonical decision-timeframe close and never treats lower-timeframe aggregation
as an authoritative closed HTF bar. Inside an open bucket, complete contiguous
trigger coverage is required for projection. `missing_dependencies` remains
empty and `last_rewarm_reason` remains `None` because execution/rewarm are out
of scope.

Input progress is not lane progress. The evaluator accepts an
`InputReadCursor` ahead of a `LaneCommitWatermark` and mutates neither object.
The readiness layer cannot roll back shared market-state progression for a
lagging lane.

## Direct and projected view evidence

`DecisionViewBuilder` first evaluates readiness, then builds an immutable
`LaneMarketView`.

The direct/exact-boundary path selects the canonical closed decision bar whose
close equals `market_as_of`. The projected/open-bucket path requires:

```text
bucket_start <= first source open
contiguous trigger intervals
last source close == market_as_of
no future source bars
market_as_of < bucket_end
```

Projection preserves `Decimal` OHLCV arithmetic:

```text
open   = first.open
high   = max(high)
low    = min(low)
close  = last.close
volume = exact Decimal sum
```

If any source taker-buy value is unknown, projected `taker_buy_base` is
`None`; it is never converted to zero. The projected bar carries the bucket
end as metadata, remains `closed=False`, and uses the latest source close as
its causal `market_as_of`. It is separate from canonical history and never
appears in `causal_bar_views` or the `BarStore`.

Nested view mappings, tuples, and provenance use the approved D1 immutable
semantic-value boundary. Cross-timeframe append permutations produce equal
views once the same canonical observations are present.

## Tests and validation

Focused tests cover:

```text
hashable/shared series identity
explicit UTC geometry and unknown timeframe failure
exact/inside-bucket and weekly cutoffs
ordered closed storage, duplicate/conflict/order rejection
bounded eviction, causal queries, immutable query results
projection ratio and shared-max capacity planning
direct readiness and exact canonical cutoffs
WARMING versus DEGRADED classification
complete and incomplete 1m-to-4h projection coverage
exact-boundary canonical HTF authority
independent input/lane progress
direct canonical view construction
Decimal projected OHLCV/taker semantics
future-trigger exclusion and no canonical writeback
immutable nested LaneMarketView values
cross-timeframe arrival-order determinism
```

## D3 remediation evidence

The follow-up adversarial review was closed without changing the D3 architecture.

```text
requirements bound to resolved lane/grid identity              rejected mismatch
understated warmup requirements                                rejected
wrong projected/direct mode                                    rejected
zero unrelated warmup                                          contributes no series/capacity
zero decision/trigger warmup                                   leaves baseline capacity 1
malformed duration/alignment                                   explicit TimeframeGeometryError
recent required warmup gap                                     DEGRADED history_gap
projected boundary with 4 prior bars for warmup 5              DEGRADED cutoff
projected boundary with 1 prior bar for warmup 5               WARMING history
shared capacity 20 / lane requirement 1                       view exposes exactly 1 bar
shared capacity 20 / lane requirement 20                      view exposes exactly 20 bars
```

`LaneReadinessEvaluator` now recompiles and compares canonical requirements
before querying `BarStore`; `DecisionViewBuilder` uses that same evaluator
validation path. Required canonical bars are checked against the explicit
timeframe duration and bucket alignment. Readiness checks only each lane's
recent required window for contiguous fixed-duration history, while projection
source completeness may inspect the full current bucket without enlarging the
lane-visible canonical history. Zero warmup entries are skipped rather than
converted to one.

## Explicitly not executed

No Valkey, Timescale, scraper, DataResolver, FeatureEngine, model execution,
dependency execution, DecisionPolicy, model state, rewarm runtime, PriceRelay,
publication, FastAPI, Docker, configuration loader, AssetRuntime, async worker,
signal/strategy/risk/execution change, live-market test, or downstream migration
was introduced or run.

## Pass 1 — correctness / PIT self-review

Reviewed future-bar filtering, exact-boundary HTF authority, open-bucket
projection cutoff, source completeness at first/middle/final intervals,
projected `market_as_of`, Decimal aggregation, missing taker propagation,
canonical no-writeback, cross-timeframe arrival independence, same-series
backward append rejection, exact lane/grid requirement binding, zero warmup,
canonical duration/alignment corruption, recent warmup gaps, projected-boundary
WARMING/DEGRADED classification, lane-local history exposure, explicit
unknown-timeframe failure, capacity floors, and independent input/lane
progress. No D0-D2 contradiction was found.

## Pass 2 — simplicity / scope self-review

Confirmed the implementation contains only standard-library bounded storage,
explicit timeframe geometry, pure readiness, and immutable view construction.
There is no runtime orchestration, I/O adapter, async machinery, calendar
framework, DataFrame, feature/model execution, state manager, publication,
PriceRelay runtime, config loader, generic event abstraction, or third-party
dependency.

## Blockers and residual risks

None for the authorized D3 offline market-state scope. Later phases must adapt
canonical ingestion payloads into `CausalBarView` values and decide how model
warmup/history policies extend the shared capacity plan; those concerns were
not implemented here.

## Validation results

```text
focused D3 tests:
  /Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
    tests/decision/test_market_state.py \
    tests/decision/test_readiness.py \
    tests/decision/test_view.py
  29 passed in 0.14s

all tests/decision plus D1/D2 compatibility:
  /Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
    tests/decision \
    tests/commons/test_model_runtime_contract.py \
    tests/models/test_strategy_model_v2.py
  99 passed in 3.05s

Ruff:
  ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
  All checks passed

format:
  ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
  17 files already formatted

compileall:
  /Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
    src/libs/contracts/decision.py src/apps/decision_app tests/decision
  passed

git diff --check:
  passed

infrastructure boundary:
  D3 production modules contain no redis/Valkey, asyncpg, HTTP/FastAPI,
  scraper/ingestion runtime, DB pool, pandas, or polars imports
  passed
```

DECISION_APP_D3_CAUSAL_MARKET_STATE_READY_FOR_REVIEW
