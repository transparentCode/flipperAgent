---
title: decision_app D9A reconstruction history-window remediation v1
status: architect_handoff
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
goal: Fix D9A stateful startup history planning so complete retained canonical history is never falsely reported as missing because of timeframe ratios or checkpoint age.
---

# Architect-to-coder — D9A reconstruction history-window remediation

D0–D8 are approved. D9A trust-boundary remediation for checkpoint save outcomes, canonical provenance, manifest D3/D4 series gating, and `configs/decision/global.yaml` is independently correct and MUST remain intact.

Do NOT start D9B.

## 1. Review blocker

Current `DecisionStartupCoordinator._load_history()` sizes every canonical series as roughly:

```text
steady_state_capacity + max_state_initialization_trigger_steps + 2
```

and explicitly leaves:

```python
ratio = 1
```

This is not sufficient for stateful reconstruction.

Two independent adversarial proofs reproduce false startup failure with COMPLETE durable history.

### A. Mixed-timeframe first inception

Configuration:

```text
stateful trigger              4h
initialization horizon        5 trigger steps
required shared feature       fixed 1h history
feature lookback              2 x 1h bars
canonical durable history     complete 40 x 1h + 10 x 4h bars
```

Expected:

```text
latest five 4h trigger transitions reconstruct successfully
1h feature prehistory is available for every replay cutoff
STARTUP_READY
```

Current result:

```text
STARTUP_BLOCKED
rewarm step failed for binding
```

Reason: the 1h series retains only about `2 + 5 + 2 = 9` latest bars. Five 4h transitions span ~20 hours, so the earliest replay steps have already lost their required 1h history.

### B. Valid checkpoint with longer downtime

Real SR proof:

```text
first startup history: bars 0..49
checkpoint cutoff:      bar 49
restart durable history: bars 0..99, complete and contiguous
```

Expected:

```text
load checkpoint at 49
replay bars 50..99 exactly
STARTUP_READY
checkpoint advances to 99
```

Current result:

```text
STARTUP_BLOCKED
"retained history cannot bridge checkpoint next trigger transition"
```

The transition exists in durable history. It was discarded only because D9A loaded the latest bounded tail before it knew the checkpoint replay interval.

This violates the frozen D9A rule:

```text
matching checkpoint C < resume R
-> replay EVERY required trigger transition C + trigger_duration ... R
-> fail closed only when durable retained history actually cannot bridge it
```

A cache truncation must never be mislabeled as a retention gap.

---

# 2. Required architecture correction

Keep two concerns separate:

```text
A. steady-state final BarStore tail
B. temporary lane reconstruction history
```

The final shared BarStore MUST remain bounded by approved D3+D4 steady-state capacities.

Stateful reconstruction MUST use a lane-specific causal window derived from the actual replay interval and each required series' timeframe/history need.

Do not solve this by loading all 90 days globally.
Do not add a generic replay/history framework.
Do not add checkpoints beyond the already-approved latest checkpoint.

A small D9A helper/data shape for one lane reconstruction window is acceptable if it reduces repeated arithmetic, but keep it local to startup.

---

# 3. Recommended execution sequence

Refactor startup conceptually to:

```text
compile D2/D4/D5 plans
capture stream tails
capture DB latest cutoffs
validate manifests

load final steady-state tails separately
    -> capacities only
    -> final shared BarStore

for each active stateful lane:
    determine exact LaneExecutionIdentity
    load exact checkpoint first
    determine replay interval
    derive per-series reconstruction start/cutoff/capacity
    fetch bounded range from canonical Timescale reader
    build temporary lane BarStore
    D6 REPLAY reconstruction
    persist checkpoint
    only accepted checkpoint save result -> expose runtime/watermark
```

Stateless lanes do not need the extended reconstruction range.

It is acceptable to construct the `LaneExecutionIdentity` directly from the already-resolved lane + D4 + D5 fingerprints rather than creating a populated ModelRuntime solely to learn the identity. Do not create a second identity formula.

---

# 4. Replay interval rules

## 4.1 No checkpoint — first state inception

Let:

```text
R = latest candidate trigger cutoff available at startup
N = explicit StateInitializationRequirement.trigger_steps
D = trigger duration
```

The intended transition window ends at `R` and needs `N` contiguous trigger cutoffs.

A conservative earliest replay cutoff is:

```text
F = R - (N - 1) * D
```

Actual trigger bars/readiness still decide whether those cutoffs exist. Missing/gapped canonical trigger bars must continue to fail closed.

`state_inception_at` remains the first supplied replay transition, as already approved.

## 4.2 Existing checkpoint

Let:

```text
C = checkpoint.market_as_of
R = latest startup resume candidate
D = trigger duration
```

If `C == R`:

```text
install checkpoint
no replay transitions
```

If `C < R`:

```text
first required transition F = C + D
last required transition       = R
```

All trigger transitions between F and the final resolved resume cutoff must be present and contiguous.

Do not cap this interval by the model's first-inception initialization horizon. The checkpoint is the state baseline; downtime can be longer than `trigger_steps` while still being reconstructable from retained durable history.

If the canonical DB genuinely no longer retains `F`, fail closed exactly as before.

---

# 5. Per-series history window

For every canonical `MarketSeriesKey` required by the lane through existing D3/D4 plans:

```text
D3 LaneMarketRequirements
+
D4 FeaturePlan.history_requirements
```

compute enough history for EVERY replay cutoff.

Do not use a hardcoded `ratio = 1`.

At minimum account for:

```text
trigger duration
series timeframe duration
steady per-cutoff history capacity/lookback
first replay cutoff
final replay/resume cutoff
```

A robust simple approach is range-based rather than guessed counts:

1. For the first replay market cutoff `F`, use `TimeframeGrid.expected_closed_cutoff(series_tf, F)` to get the series cutoff visible at that instant.
2. Use the compiled D3+D4 capacity for that series as the maximum required per-cutoff lookback.
3. Back up enough series-duration bars so the FIRST replay cutoff has its full required history.
4. Fetch causally from that earliest open time through the series' captured durable warm cutoff / replay end.
5. Load that bounded range into the temporary lane store in ascending order.

Conceptually:

```text
first_visible_series_cutoff = expected_closed_cutoff(series_tf, F)
earliest_open = first_visible_series_cutoff - capacity(series) * duration(series)
fetch start >= earliest_open through required final cutoff
```

Adjust inclusive/exclusive details to the existing repository's `open_time >= start` and `close_time <= through` contract. Prove them by tests rather than adding magic `+1/-1` bars.

For a 4h trigger with a 1h feature series, the fetched 1h span must naturally cover all 1h bars needed across the 4h replay interval.

For a 1h trigger with a 4h feature series, do not invent unavailable future 4h bars; use `expected_closed_cutoff` exactly as D4 does.

Do not duplicate feature-specific formulas. The compiled capacities/history requirements remain authoritative.

---

# 6. Temporary BarStore capacity

The temporary reconstruction BarStore must be large enough to retain the fetched reconstruction range while replay walks from the earliest transition forward.

Current:

```text
steady_capacity + initialization_trigger_steps
```

is insufficient for checkpoint catch-up longer than initialization horizon and for lower-timeframe series.

Set each temporary series capacity from the actual bounded fetched reconstruction inventory/range (or an exactly equivalent deterministic count), not from one global trigger-step scalar.

The FINAL shared BarStore must still use only `merge_bar_store_capacities(D3, D4)`.

Do not let restart catch-up permanently enlarge steady-state memory.

---

# 7. Avoid false retention-gap classification

A retention gap may be claimed only after querying the canonical range that should contain the exact next required transition.

Checkpoint case:

```text
expected_next = checkpoint.market_as_of + trigger_duration
```

If DB query over the required reconstruction range contains that transition and all following required trigger transitions, startup must not call it a retention gap merely because a previous tail cache omitted it.

True gap remains:

```text
checkpoint C
canonical retained trigger history begins after C + D
-> BLOCKED
-> no runtime
-> no watermark
-> checkpoint unchanged
```

---

# 8. Preserve already-remediated D9A semantics

Do not regress:

```text
checkpoint INSERTED / UPDATED / IDENTICAL -> eligible for STARTUP_READY
checkpoint CONFLICT / REJECTED_OLDER / unsupported -> BLOCKED before runtime/watermark
canonical provider provenance
canonical derived provenance with source timeframe e.g. 1m for target HTF
stream + DB use the same provenance validator
D3 + D4 required canonical series drive manifest gating
required STOPPED feature timeframe -> inactive/no runtime
unused STOPPED timeframe -> does not block
configs/decision/global.yaml == minimal non-speculative namespace
publication suppressed throughout startup
captured stream tail IDs are not recaptured after DB warmup
final LaneCommitWatermark baseline last_disposition=None
```

No external Timescale/Valkey operation is required if the worktree still lacks `.env`.

---

# 9. Required regressions

Add at least:

## 9.1 Mixed-timeframe first inception succeeds with complete history

```text
trigger/decision TF = 4h
state initialization = 5 steps
required feature = fixed 1h, lookback >= 2
complete aligned canonical histories supplied
```

Assert:

```text
STARTUP_READY
exactly 5 replay transitions
checkpoint persisted at final 4h resume cutoff
no publication
```

Also prove the temporary 1h history spans back far enough for the first 4h replay cutoff.

## 9.2 Mixed-timeframe true prehistory gap fails closed

Remove one bar required for the first replay cutoff's 1h feature history.

Assert:

```text
STARTUP_BLOCKED
no runtime/watermark
```

Do not silently shorten inception to avoid the missing data.

## 9.3 Checkpoint catch-up may exceed initialization horizon

Use real SR if practical:

```text
first startup -> checkpoint around bar 49
restart -> complete contiguous history through bar 99
```

Assert:

```text
STARTUP_READY
checkpoint_loaded=True
replay_step_count=50 (or exact expected transition count)
final checkpoint cutoff=bar 99
```

Compare final encoded state with one uninterrupted causal reconstruction over the equivalent state path if feasible. At minimum prove exact sequential cutoff advancement and final state equality against an independently reconstructed runtime.

## 9.4 Genuine post-checkpoint retention gap still blocks

Checkpoint at C, but remove `C + trigger_duration` from durable history while retaining later bars.

Assert:

```text
STARTUP_BLOCKED
reason identifies inability to bridge exact next transition
checkpoint not reset/replaced
no runtime/watermark
```

## 9.5 Final BarStore remains bounded

After a long checkpoint catch-up, assert final returned BarStore capacities/visible inventories remain the approved D3+D4 steady-state bounds, not the temporary reconstruction size.

---

# 10. Scope

Expected primary changes:

```text
src/apps/decision_app/startup.py
tests/decision/test_d9a_startup_reconstruction.py
tests/decision/test_d9a_real_sr_startup.py
plans/coder-to-orchestrator-decision-app-d9a-startup-reconstruction-v1.md
```

Touch `storage/market_history.py` only if a tiny range-read correction is actually required. Its current `start`/`through` API should already be sufficient.

Do NOT change:

```text
D6 state transaction semantics
D8 policy/publication/finalization
checkpoint identity/schema unless a demonstrated defect requires it
canonical provenance rules
manifest ownership rules
model cores
SR quantitative logic
risk/execution
```

Do NOT add:

```text
D9B continuous reader
XREAD/XREADGROUP
PEL
signal XADD
PriceRelay
FastAPI
Docker/Compose service
scheduler/workflow framework
generic history planner framework
new checkpoint framework
```

---

# 11. Validation

Run:

```text
new history-window adversarial tests
all D9A-focused tests
complete tests/decision
commons config validator slice
canonical ingestion provenance/HTF contract slice
non-research SR gate relevant to D7A/D9A
```

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
D9A import/scope scan
cache cleanup
```

If local Timescale/Valkey remains unavailable because `.env` is absent, keep that as the same environment-dependent follow-up. Do not copy/create environment secrets solely for this phase.

Two-pass self-review must explicitly verify:

```text
mixed 4h-trigger/1h-feature first inception succeeds with complete history
checkpoint catch-up longer than initialization horizon succeeds with complete history
true missing next checkpoint transition still blocks
no history cache truncation is mislabeled as retention loss
final steady-state BarStore remains bounded
checkpoint conflict/provenance/manifest remediation stays green
no D9B scope
```

Update:

```text
plans/coder-to-orchestrator-decision-app-d9a-startup-reconstruction-v1.md
```

Do not start D9B automatically.

Final line exactly:

```text
DECISION_APP_D9A_STARTUP_RECONSTRUCTION_READY_FOR_REVIEW
```
