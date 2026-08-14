---
goal: Implement D9A bounded decision startup capture, causal reconstruction, and exact lane-state checkpoints
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d9a, startup, reconstruction, checkpoint]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D9A startup/reconstruction handoff

## Scope and starting state

D0 through D8 and D7A were present in the cumulative isolated worktree. D7B
and D9B remain deliberately deferred. Work started from detached `HEAD` at:

```text
4fc0de62515112dc371e08a6cde503746c54f7f7
```

The worktree was already cumulative and dirty: approved decision-app
architecture, semantic, planner, causal-state, feature, data, runtime, policy,
and SR-adapter files were uncommitted, with the prior SR adapter export and
import-boundary edits tracked. No commit, merge, push, branch switch, reset, or
restore was performed, and the primary checkout was not modified.

## Files and symbols

Implemented D9A production surfaces:

```text
src/apps/decision_app/settings.py
  strict frozen Decision*Settings models
  DecisionConfig / CanonicalInstrument
  load_decision_config
  load_canonical_ingestion_contract

src/apps/decision_app/ingestion_input.py
  canonical_ingestion_stream_key
  parse_canonical_ingestion_event
  CanonicalMarketEvent

src/apps/decision_app/runtime_plugins.py
  StateInitializationRequirement
  RuntimePluginDefinition.initialization_requirement
  RuntimePluginCatalog.initialization_for

src/apps/decision_app/storage/state_codec.py
  deterministic tagged-JSON state codec

src/apps/decision_app/storage/checkpoints.py
  LaneStateCheckpoint
  CheckpointRepository / InMemoryCheckpointRepository
  CheckpointSaveResult

src/apps/decision_app/storage/market_history.py
  CanonicalMarketHistoryRepository
  InMemoryCanonicalMarketHistoryRepository

src/apps/decision_app/storage/schema.sql
src/apps/decision_app/storage/bootstrap.py
src/apps/decision_app/storage/__init__.py

src/apps/decision_app/startup.py
  capture_series_startup_positions
  DecisionStartupCoordinator
  DecisionStartupSnapshot / DecisionStartupResult
  SR initialization horizon helper
```

The SR adapter remains independent of `decision_app`; its D7A import boundary
was preserved while the SR initialization calculation is owned by the startup
coordinator. No production ingestion, signal, strategy, risk, execution, or
portfolio code was changed.

Focused D9A tests are:

```text
tests/decision/test_d9a_ingestion_input.py
tests/decision/test_d9a_checkpoints.py
tests/decision/test_d9a_settings_and_history.py
tests/decision/test_d9a_startup_reconstruction.py
tests/decision/test_d9a_real_sr_startup.py
```

## Decision configuration and identity split

The loader accepts the strict restart-time boundary:

```text
configs/decision/global.yaml
configs/decision/assets/*.yaml
root namespace: decision
asset namespace: decision.assets
```

All Pydantic models use frozen/extra-forbid validation, and nested parameters,
dependencies, bindings, lanes, and allowlists are deeply immutable. The
implementation intentionally does not invent a production SR asset file or
model parameters; deterministic test fixtures exercise the loader until an
approved decision configuration is supplied.

The canonical market contract is read through `ConfigManager` from the existing
ingestion configuration only. The loader consumes calendar type/timezone and
alignment origin, timeframe durations, and instrument venue/timeframe/provider
symbol fields. It requires continuous UTC geometry and constructs the D3
`TimeframeGrid`; it does not import the ingestion application.

The explicit mapping is preserved:

```text
manifest_asset = BTC
decision_asset = BTCUSDT
instrument_id  = BTC-USDT-PERP
venue          = binance
```

Decision lane compilation uses the approved D2/D4/D5/D6/D8 catalogs and plans.
Stateful runtime registrations require a bounded positive
`StateInitializationRequirement`. For SR, the app-owned formula is:

```text
max(lifecycle.max_age_bars, 2 * detection.pivot_span_bars + 1)
```

ATR feature history remains a D4 requirement and is not double-counted as SR
state transitions.

## Canonical ingestion event and history boundary

The decision-owned parser accepts only the exact transport shape:

```text
stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}
event_type       = candle.committed
schema_version   = 1
producer         = ingestion
```

It validates event/payload/stream identity, aware UTC ISO timestamps, closed
canonical geometry, finite Decimal OHLCV values, volume/taker bounds, and the
provider/derived source metadata rules (provider rows have a provider and no
source timeframe; derived rows have a source timeframe and no provider). It
performs no timestamp-unit guessing and has no ingestion-domain or storage
imports.

`CanonicalMarketHistoryRepository` is read-only and queries only the canonical
candle table for identity, cutoff, bounded history, and UTC/Decimal conversion.
When a limit is used, the SQL reads newest rows first and reverses them before
returning causal ascending order, avoiding the oldest-row truncation bug.

## Checkpoint contract

The only persistence added is the latest state checkpoint per exact D6
`LaneExecutionIdentity`:

```text
decision.state_checkpoints(
    lane_id,
    effective_lane_revision,
    feature_plan_fingerprint,
    data_plan_fingerprint,
    market_as_of,
    state_inception_at,
    state_payload,
    state_payload_sha256,
    created_at,
    updated_at
)
```

The primary key is the full execution identity. State is an atomic
binding-id-to-model-state map. The small tagged-JSON codec supports only the
approved semantic vocabulary (including Decimal, UTC datetime, timedelta,
bytes, mappings, tuples, and lists), rejects unsupported/custom/cyclic values,
and canonicalizes mapping order. Load/save validates payload decoding, binding
coverage, and SHA-256 integrity.

Same-cutoff behavior is deterministic:

```text
same payload + same inception     -> IDENTICAL
same cutoff, different state      -> CONFLICT
same cutoff, different inception  -> CONFLICT
older checkpoint                  -> REJECTED_OLDER
newer checkpoint                  -> UPDATED
```

Corrupt or mismatched durable rows fail closed as `CheckpointCorruptionError`.

## Startup sequence and baseline semantics

`DecisionStartupCoordinator.start()` performs one bounded startup pass:

```text
compile D2/D4/D5/D8 plans
→ validate exact policy registrations
→ capture each canonical stream tail with bounded XREVRANGE
→ read canonical DB latest cutoffs
→ reject DB older than a valid captured tail
→ load a bounded final-store tail
→ reconstruct state through D6 REPLAY with publication suppressed
→ save/load exact latest checkpoints
→ fill a final bounded shared BarStore
→ return immutable startup evidence and runtime owners
```

The original stream tail ID is retained in `InputReadCursor`; the accepted
warm cutoff may be newer when durable history is ahead of the stream. The
cursor is not recaptured after warmup. Startup establishes a baseline
`LaneCommitWatermark` at the resume cutoff with `last_disposition=None`; this
does not claim a historical signal or no-signal finalization.

First inception selects the latest contiguous bounded trigger-step window and
records its first cutoff as `state_inception_at`. A matching checkpoint loads
the exact state identity and replays every contiguous trigger after its cutoff.
If the next required transition is absent because retention created a gap,
startup blocks instead of resetting or skipping state. Stateless lanes build a
latest ready view without checkpoint replay. Active manifests require the
canonical source, enabled state, LIVE desired state, and required timeframe
manifest state when a manifest store is supplied.

The reconstruction history is separate from the final bounded BarStore. A
stateful lane resolves its exact checkpoint first, derives the actual
inception/catch-up interval, and fetches a lane-specific range for every D3/D4
required series. The first visible cutoff is backed up by the compiled
per-cutoff capacity using the series timeframe duration; the fetched inventory
determines only the temporary replay-store capacity. The returned shared store
is filled from the independent D3/D4 steady-state tail and is never enlarged
by checkpoint downtime. No continuous reader, consumer group, PEL handling,
publication, PriceRelay, FastAPI, Docker service, or D9B runtime was added.

## D9A trust-boundary remediation

The startup boundary now treats checkpoint persistence as authoritative. Only
`INSERTED`, `UPDATED`, and `IDENTICAL` save outcomes permit the reconstructed
lane to become `STARTUP_READY`; `CONFLICT`, `REJECTED_OLDER`, and unsupported
repository results block the lane before a runtime or baseline watermark is
created. Missing checkpoint evidence remains `None`, not the string `"None"`.

The stream and Timescale history adapters now share the canonical ingestion
provenance rule: provider candles require a non-empty provider and no source
timeframe, while derived candles require a source timeframe and no provider.
Derived source timeframes are not compared with the target candle timeframe.
The stream regression uses the canonical ingestion event builder for both
provider and derived events; DB rows are validated by the same decision-owned
rule before becoming causal bars.

Manifest activation now derives required timeframes from the compiled D3 lane
market requirements plus D4 feature history requirements. Every required
canonical series must have a LIVE ingestion timeframe manifest; an unused
stopped timeframe does not block the lane. The minimal strict global decision
namespace is materialized at `configs/decision/global.yaml` as `decision: {}`;
no speculative asset graph was added.

## D9A reconstruction history-window remediation

The prior one-tail replay approximation (`steady capacity + one global
initialization-step scalar`) was removed. Final-store loading now requests only
the compiled steady-state capacity. Stateful reconstruction uses a separate
lane-local range:

```text
checkpoint C < resume R:
    first replay cutoff = C + trigger duration

no checkpoint:
    first replay cutoff = R - (initialization steps - 1) * trigger duration

per series:
    first visible cutoff = expected_closed_cutoff(series timeframe, first replay)
    start = first visible cutoff - steady capacity * series duration
    fetch through the captured durable series cutoff
```

The temporary BarStore retains the complete fetched lane range, so a valid
checkpoint catch-up is not capped by the model's first-inception horizon.
True missing transitions still fail closed at the exact next required cutoff;
history omitted only by the old startup tail is no longer classified as a
retention gap. The final shared BarStore remains at its D3/D4 capacity.

## Evidence

Deterministic D9A unit/integration evidence:

```text
D9A-focused remediation suite              49 passed
complete tests/decision                    255 passed
commons config validator slice              23 passed
canonical ingestion contract slice         118 passed
non-research SR core/config suite          440 passed
```

The real-SR startup regression proves first inception and checkpointed restart:

```text
50 deterministic 1h bars
first startup       STARTUP_READY, 20 replay steps, checkpoint INSERTED
restart at bar 54   STARTUP_READY, checkpoint loaded, 5 replay steps
restart at bar 99   STARTUP_READY, checkpoint loaded, 50 replay steps
baseline disposition None; publication-free in both runs
```

The mixed-timeframe regression supplies complete 40-bar 1h and 10-bar 4h
history for a five-step 4h stateful lane with a two-bar fixed 1h feature. It
proves the lane range begins at the required earlier 1h cutoff while the final
store retains only two 1h bars and one 4h bar. Removing that first replay
prehistory blocks startup without shortening inception. The real SR regression
then catches up from bar 49 through bar 99 (50 transitions), beyond its
20-step initialization horizon, while retaining only the approved 15-bar
final store.

The existing D7A real-SR tests additionally cover direct/runtime parity,
encoded state, replay, abort/commit, and bounded artifact projection. The D9A
synthetic startup tests cover the DB-ahead-of-stream race (captured tail at
bar 3, durable cutoff at bar 4), exact next-transition replay, exact binding
coverage, and retention-gap fail-closed behavior.

The fresh history-window remediation run adds the mixed-timeframe lower-TF
prehistory and long checkpoint-catch-up regressions described above. The
focused D9A set is now 49 passed; the complete decision suite is 255 passed.
The complementary commons/config, canonical HTF/provenance, and SR import
boundary slice is 45 passed, 1 skipped.

The repository does not provide a usable local infrastructure fixture in this
isolated worktree: `docker compose config --format json` fails before startup
because the worktree has no `.env`. No Timescale/Valkey process was started,
no external provider was contacted, and no external state was mutated. Real
local infrastructure certification remains an environment-dependent follow-up
when the repository harness supplies its required environment.

## Validation

Passed:

```text
Ruff check (decision_app + decision contracts/tests) passed
Ruff format --check                                 passed
compileall (D9A/decision scope)                     passed
git diff --check                                    passed
AST import boundary                                 clean across 27 decision modules
```

Fresh remediation validation also passed:

```text
Ruff check / format --check                         passed
compileall (decision scope)                         passed
git diff --check and untracked whitespace scan      passed
decision infrastructure import scan                 clean
repo-local cache cleanup                            completed
```

The full ingestion suite was also attempted. Excluding the unrelated
Compose-dependent FINAL harness file, it completed:

```text
487 passed, 14 skipped, 2 warnings
```

The full command produced one environment-only failure in
`tests/ingestion/test_final_program_certification.py`: its mocked gate-order
test reaches the FINAL helper's Compose preflight, which cannot resolve the
missing worktree `.env`. This is not a D9A production or decision-suite
failure; the complete D9A/decision and relevant ingestion contract suites are
green.

## Two-pass self-review

Pass 1 — causal correctness:

```text
tail captured before DB warmup                         checked
DB-ahead cutoff retained without tail recapture        checked
canonical cutoff from closed durable bars              checked
exact checkpoint identity and payload hash             checked
explicit first-inception state horizon                 checked
mixed-timeframe replay window spans lower-TF history  checked
checkpoint restart replays next contiguous triggers   checked
checkpoint catch-up exceeds initialization horizon     checked
true checkpoint/prehistory gap cannot be bridged        checked
final BarStore remains capacity-bounded                 checked
startup watermark suppresses stale finalization        checked
no publication during replay                            checked
```

Pass 2 — simplicity/scope:

```text
one latest checkpoint per identity; no generic framework checked
no duplicate ingestion domain model                     checked
no production app-to-app imports                         checked
no consumer groups/PEL/live reader loop                  checked
no XADD/PriceRelay/FastAPI/Docker                        checked
no D7B bridge and no D9B work                            checked
```

## Residual risks and carry-forward

D9A does not claim continuous stream consumption, signal publication,
PriceRelay recovery, asset lifecycle subscription, or live soak behavior. D9B
must attach a direct-cursor reader after the captured stream IDs, classify
events already represented by startup history, and integrate publication only
after the D8 finalization boundary. PriceRelay/risk compatibility remains a
separate downstream gate. Local Timescale/Valkey integration evidence is
pending a usable test environment.

No D9B/D9C/D9D work was started.

DECISION_APP_D9A_STARTUP_RECONSTRUCTION_READY_FOR_REVIEW
