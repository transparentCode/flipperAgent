---
goal: Remediate D3 causal market-state invariants before D4
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d3, remediation, pit]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D3 causal market-state remediation

## 1. Objective and evidence

Remediate the independently reproduced D3 causal/readiness defects without broadening D3 into runtime or D4 feature work.

The submitted D3 implementation remains structurally sound: bounded canonical `BarStore`, explicit `TimeframeGrid`, pure readiness, and ephemeral direct/projected views. The remediation is limited to contract hardening and lane-local deterministic history exposure.

Independent validation before remediation passed:

```text
92 passed
Ruff check: passed
Ruff format: passed
compileall: passed
git diff --check: passed
```

Direct adversarial probes reproduced these defects:

```text
cross_asset_requirements_accepted = LIVE BTC-labelled view built from ETH series
malformed_1h_bar_accepted = LIVE with a 30-minute interval labelled 1h
boundary_insufficient_warmup_state = DEGRADED when it should remain WARMING
zero_warmup_requirements = extra 4h series with count 1
gappy_warmup_accepted = LIVE
short-lane required 1 bar but view exposed 3 bars because another lane enlarged shared capacity
```

D4 must not start until these are closed.

## 2. Scope and non-goals

Prefer changing only:

```text
src/apps/decision_app/market_state.py
src/apps/decision_app/readiness.py
src/apps/decision_app/view.py
tests/decision/test_market_state.py
tests/decision/test_readiness.py
tests/decision/test_view.py
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

Do not change D0/D1/D2 architecture or planner semantics unless a focused regression proves an unavoidable contradiction.

Still forbidden:

```text
Valkey/Redis
Timescale I/O
scraper/DataResolver
FeatureEngine/D4
model execution
state runtime/rewarm orchestration
DecisionPolicy
PriceRelay
publication
FastAPI
Docker
configs/decision
AssetRuntime/async workers
signal/strategy/risk/execution changes
```

## 3. BLOCKER — bind market requirements to the resolved lane

`LaneReadinessEvaluator` currently validates only `requirements.lane_id == resolved_lane.lane_id`. A caller can therefore construct requirements for another asset/venue/instrument using the same lane ID and obtain a BTC-labelled view from ETH market state.

Fail closed before any BarStore query unless requirements are exactly compatible with the resolved lane and grid.

At minimum validate:

```text
requirements.decision_series == MarketSeriesKey(
    lane.asset, lane.venue, lane.instrument_id, lane.decision_timeframe
)
requirements.trigger_series == MarketSeriesKey(
    lane.asset, lane.venue, lane.instrument_id, lane.trigger_timeframe
)
requirements.projected_decision == (lane.trigger_timeframe != lane.decision_timeframe)
```

Also prevent a caller from understating warmup/history counts. Prefer a small pure validator comparing the supplied requirements with the canonical result of `compile_lane_market_requirements(resolved_lane, timeframe_grid)` (series set and minimum counts), rather than duplicating a second compilation algorithm.

Both readiness evaluation and view construction must rely on this validation path.

Required regressions:

```text
BTC lane + ETH requirements with same lane_id => reject
correct identity but understated warmup count => reject
wrong projected_decision flag => reject
canonical compiled requirements => accept
```

## 4. HIGH — lane-local history must not depend on unrelated lane capacity

The shared BarStore correctly uses maximum capacity across lanes, but `DecisionViewBuilder._canonical_views()` currently returns all retained bars. Therefore adding an unrelated long-warmup lane changes the history visible to a short-warmup lane.

This violates compositional determinism.

For each required series, expose only the lane's own required recent history:

```text
bar_store.bars_at(
    key,
    expected_cutoff,
    limit=requirements.minimum_bars_by_series[key],
)
```

Projection-source completeness may still inspect the full current decision bucket directly from BarStore; do not inflate `causal_bar_views` merely because projection capacity or another lane retained more bars.

Required regression:

```text
Lane A warmup 1
Lane B same market series warmup 20
shared BarStore capacity = 20
Lane A view exposes exactly 1 canonical history bar
Lane B view exposes exactly 20
adding/removing B does not change A's view contents
```

## 5. HIGH — zero warmup must remain zero

D1 permits `WarmupRequirements(bars_by_timeframe={tf: 0})`. D3 currently turns an unrelated zero-bar warmup entry into a required series with capacity/count 1 via `max(1, bars)`.

Do not reinterpret zero as one.

Rules:

- decision and trigger series still have their independent baseline requirement of one canonical bar;
- an additional warmup timeframe with `bars == 0` contributes no series and no capacity;
- if the zero entry is for decision/trigger timeframe, the existing baseline one remains, but zero must not raise it.

Apply consistently to both `compile_bar_store_capacities()` and `compile_lane_market_requirements()`.

Required regressions:

```text
warmup {'4h': 0} on a 1h lane => no extra 4h MarketSeriesKey
warmup {'1h': 0} on a 1h lane => baseline 1 only
```

## 6. HIGH — validate required canonical geometry against TimeframeGrid

A `CausalBarView(timeframe='1h')` whose actual interval is only 30 minutes can currently satisfy readiness if it ends at the expected cutoff.

`BarStore` may remain generic and gap-tolerant, but a lane must not become `LIVE` from canonical history that contradicts the D3 fixed-duration continuous-UTC grid.

Before declaring required history ready, validate every bar used by the lane against its series/grid:

```text
bar.timeframe == key.timeframe
bar.bar_close_at - bar.bar_open_at == timeframe_grid.duration(key.timeframe)
bar.bar_open_at == aligned bucket start for key.timeframe
bar.bar_close_at == aligned bucket end
```

Malformed/off-grid canonical geometry is contract corruption; prefer an explicit `TimeframeGeometryError`/`MarketStateError` rather than silently degrading.

Projection-source validation should continue to enforce the same trigger-duration/alignment semantics.

Required regressions:

```text
30m interval labelled 1h and ending on 1h cutoff => reject/fail closed
1h-duration bar shifted off the configured grid => reject/fail closed
valid aligned canonical bar => accept
```

Do not add another calendar framework.

## 7. HIGH — required recent warmup history must be contiguous under D3 continuous UTC

Generic BarStore gaps are allowed, but D3 readiness operates under the explicitly frozen continuous-UTC fixed-duration calendar. A model requiring the latest N canonical bars must not become `LIVE` from N bars with a missing interval inside the recent required window.

For each required series, inspect the lane-local recent window through its expected cutoff. Once count is sufficient, require the N bars to form the expected fixed-duration sequence ending at that cutoff.

Suggested behavior:

```text
count < minimum => WARMING
count sufficient but latest expected cutoff/required interval is missing => DEGRADED
malformed/off-grid bar geometry => explicit corruption exception
complete contiguous recent window => ready
```

A gap older than the lane's required recent N-bar window is irrelevant.

Required regression:

```text
warmup=3
bars: 00-01, missing 01-02, 02-03, 03-04
market_as_of=04
=> not LIVE; DEGRADED with deterministic history-gap/cutoff reason
```

## 8. MEDIUM — projected boundary WARMING vs DEGRADED classification

At an exact projected decision-timeframe boundary, the current special case removes the decision-series `:history` warming reason whenever trigger history is sufficient. That can misclassify a lane with genuinely insufficient decision warmup as `DEGRADED`.

Preserve the semantic distinction:

- if all required historical decision bars except the just-missing current canonical bar are present contiguously, classify missing current bar as `DEGRADED`;
- if even arrival of the current bar would still leave warmup/history below the required minimum, remain `WARMING`;
- once warmup is sufficient but the boundary canonical bar alone is missing, `DEGRADED` is correct.

Examples for decision warmup 5 at a 4h boundary:

```text
4 contiguous prior bars + missing current 4h => DEGRADED
1 prior bar + missing current 4h => WARMING
```

Do not change the rule that D3 must never synthesize a closed projected bar at the boundary.

## 9. Preserve existing D3 invariants

The remediation must keep:

```text
BarStore canonical closed bars only
projected bars never written back
exact-boundary decision bar comes from canonical ingestion history
projection uses complete trigger coverage only
Decimal OHLCV aggregation
None taker volume propagates as None
cross-timeframe append arrival order independent
InputReadCursor independent from LaneCommitWatermark
bounded shared capacity uses max across lanes
unknown timeframe fails explicitly
weekly origin alignment
```

## 10. Validation

Use the primary repo interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D3 tests first, then the existing decision compatibility set:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_market_state.py \
  tests/decision/test_readiness.py \
  tests/decision/test_view.py

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then:

```text
ruff check
ruff format --check
compileall
git diff --check
untracked whitespace check where required
infrastructure-import boundary scan
cache cleanup verification
```

No Docker/network/Valkey/Timescale validation is required.

## 11. Two-pass self-review

Pass 1 — correctness/PIT:

```text
cross-asset requirements substitution
understated requirements
unrelated-lane capacity changing view contents
zero warmup reinterpretation
canonical duration/alignment corruption
recent warmup history gaps
projected boundary warmup classification
projection completeness
future leakage
canonical projection writeback
```

Pass 2 — simplicity/scope:

```text
no session-calendar framework
no generic history engine
no feature lookback logic
no model execution
no runtime lifecycle
no I/O
no additional app hierarchy
```

## 12. Coder handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

Include exact remediation evidence and validation counts. Do not claim D4 or live-runtime certification.

Final line exactly:

```text
DECISION_APP_D3_CAUSAL_MARKET_STATE_READY_FOR_REVIEW
```

Do not start D4 automatically.
