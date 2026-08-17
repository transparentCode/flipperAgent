---
goal: Deterministic ingestion to Decision Momentum cross-app stitch certification
stage: coder-to-orchestrator
date_created: 2026-08-17
last_updated: 2026-08-17
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, ingestion, decision-app, momentum, combined-certification, c1]
source_base: 498f0bf53311f98f11899b3444f67395fbe74b02
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c1
---

# Coder handoff — C1 deterministic ingestion → Decision/Momentum stitch

## Result

C1 composes the approved ingestion producer and Decision/Momentum consumer
contracts in a deterministic, test-owned persistence and broker harness. The
remediated terminal status is:

INGESTION_DECISION_C1_DETERMINISTIC_STITCH_REMEDIATION_READY_FOR_REVIEW

No production Decision source, ingestion source, Decision asset configuration,
Compose entry, real Timescale/Valkey state, or external service was changed.
C1 was not committed, merged, or pushed.

## Integration preflight

The approved M4 worktree was verified before integration. The approved M4
functional and resource artifacts matched their supplied hashes, and the
approved M4 surfaces were committed as:

~~~
commit: 498f0bf53311f98f11899b3444f67395fbe74b02
message: feat(decision): integrate certified momentum path
local main after fast-forward: 498f0bf53311f98f11899b3444f67395fbe74b02
push: not performed
~~~

A fresh detached C1 worktree was then created from that exact post-M4 SHA:

~~~
/Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c1
~~~

Production configs/decision/assets remains empty. M4 changed the approved
ingestion retention to 91 days; no additional retention or Decision config
change was made in C1.

## Files changed

C1-only certification surfaces:

- tests/combined/__init__.py
- tests/combined/c1_harness.py
- tests/combined/test_ingestion_decision_momentum_c1.py
- scripts/certify_ingestion_decision_momentum_c1.py
- artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json

Post-M4 certification-provenance normalization only:

- scripts/certify_momentum_features_m3.py
- scripts/certify_momentum_decision_m4.py
- tests/decision/certification/test_m3_momentum_feature_semantics.py
- tests/decision/certification/test_m4_certification.py

The protected M3 artifact is reproduced by an explicit historical source override
of 6feedc278db5fe077ac94a30dc72195e9fcafcc1; the protected M4 artifact is
reproduced by an explicit historical source override of
e7bce3d5ca2ea46772447cdf003c989124ea1847. Default M3/M4 generator execution
resolves the current checkout HEAD, so new certifications cannot silently claim
historical provenance. No model or runtime behavior changed.

## Protected evidence

All protected artifact bytes remained unchanged after C1:

~~~
M3:
6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c

M4 functional:
3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792

M4 resource:
e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4

D10:
2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
~~~

The generated C1 artifact is:

~~~
artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json
SHA-256:
386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4
identity_digest:
b30a8848496661e6a44f068707123e063db04ebd67056816b5801cc56830fedd
evidence_digest:
8833ca204cad91617dfce675d1f260b579e251484f8ca3183452e4e9050147f2
~~~

The generator runs the certification twice and rejects unequal evidence before
writing the artifact. Two independent generator invocations produced the same
C1 SHA and terminal status.

## Combined routes and producer/consumer contract

All three approved Momentum routes were active concurrently:

| route | startup history | live derived entries | input disposition | feature/Momentum parity |
|---|---:|---:|---|---|
| BTCUSDT / 1h | 544 | 4 | INSERTED | PASS |
| BTCUSDT / 4h | 544 | 1 | INSERTED | PASS |
| ETHUSDT / 4h | 544 | 1 | INSERTED | PASS |

The producer-generated events, not hand-shaped success fields, were sent
through the real OutboxPublisher and parsed by Decision. The canonical stream
identity and event contract were:

~~~
stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}
event_type     = candle.committed
schema_version = 1
producer       = ingestion
~~~

Derived HTF provenance was preserved as:

~~~
source_type      = derived
source_provider  = None
source_timeframe = 1m
~~~

The live fixture used the real HTFAggregationService: final BTC 1m coverage
closed BTC 1h and BTC 4h, and final ETH 1m coverage closed ETH 4h. No signal
was produced from base 1m events. The three lanes reached LIVE; five signal
entries were produced on the active signal streams, with committed finalization
and stable route-isolated feature/Momentum parity.

## At-least-once outbox proof

The C1 retry case used a real producer event and the test-owned persistence
boundary:

~~~
outbox attempts       2
same event identity   true
producer stream IDs   1-0, 2-0
Decision dispositions INSERTED, DUPLICATE
Decision transactions 1
signal entries        1
~~~

The first XADD succeeded and the first mark-published operation failed. The
retry was accepted as an exact durable duplicate by Decision, with no second
policy/finalization/signal effect and no lane reconstruction.

## Recovery proof

One ETH 1m constituent was omitted from a closing 4h bucket. The real
HTFAggregationService returned htf_incomplete:4h and emitted no premature
derived event. The test HistoricalCandleProvider then supplied the missing
base candle through the real RecoveryEngine; reconciliation produced the
expected derived ETH 4h candle and Decision advanced once:

~~~
recovery request count    1
provider calls            1
recovered base count      1
premature derived count   0
derived close             178.3
source_type               derived
source_timeframe          1m
follow-up requests        0
~~~

The recovered lane finalized SIGNAL -> PUBLISHED -> COMMITTED.

The recovery evidence now includes an independently constructed uninterrupted
ETH 4h reference from the same startup seed and causal cutoff. Recovered and
reference evidence matched exactly for the derived candle identity/geometry,
OHLCV and provenance, Decision input disposition/cutoff, RSI, MACD line/signal/
histogram, Momentum direction/conviction/score, lane policy/finalization, and
signal identity. The structured `uninterrupted_reference_equal` gate is true;
the hard-coded close remains only a diagnostic value.

## Restart and cross-route evidence

The restart scenario retained the canonical persistence and broker state,
created a fresh Decision startup/runtime, and captured the existing stream
tail. Startup reconstructed the consumed history without publishing a stale
signal:

~~~
first startup                 STARTUP_READY
fresh startup                 STARTUP_READY
fresh startup publications    0
same input cutoffs            true
same lane results             true
same feature/Momentum values  true
same signal identities        true
~~~

After the next complete producer-generated HTF close, continuous and fresh
runtimes produced identical route results. BTC 1h, BTC 4h, and ETH 4h used
separate canonical histories, cursors, feature snapshots, and binding
identities; unrelated route activity did not alter another route's result.

The permanent cross-route perturbation starts all three routes, snapshots both
BTC lanes, advances only ETHUSDT/4h, and polls the real Decision runtime. Both
BTC watermarks, input cursors, feature/Momentum evidence, and binding identities
remain equal, and the ETH-only poll contains no BTC policy/publication/
finalization transaction.

## Validation

~~~
C1 focused tests                       7 passed
M3 certification + M4 certification  31 passed
complete tests/decision              406 passed
tests/models/momentum                 55 passed
affected ingestion/MI0/config slice 330 passed
~~~

The affected slice covered candle ingestion, HTF aggregation, RecoveryEngine,
stream keys, outbox contracts/publisher, ingestion settings/namespace,
MI0 import isolation, and config alignment, and completed 330 passed. No
provider/network or external broker test was forced.

The full `tests/ingestion` run was not used as the C1 acceptance gate: it
reported 499 passed, 14 skipped, and one final-certification test failure while
its Docker Compose preflight could not produce a valid config.
This C1 worktree did not add credentials, start infrastructure, or alter that
external-state harness.

Static and boundary checks:

~~~
Ruff check --no-cache                 passed
Ruff format --check                   passed
compileall                            passed
git diff --check                      passed
fresh-process Momentum import         passed
legacy bootstrap exact-order probe    passed
legacy bootstrap repeat-safe probe    passed
production Decision assets            empty
repo-local Python caches              removed
external Timescale/Valkey state      untouched
~~~

## C1R evidence-integrity remediation

The exact producer geometry is derived once from the 240-minute fixture window:

~~~
BTCUSDT/1h  = 4
BTCUSDT/4h  = 1
ETHUSDT/4h  = 1
parsed events = 6
~~~

Every parsed event has the canonical ingestion stream identity and derived
provenance `source_type=derived`, `source_provider=None`, and
`source_timeframe=1m`. `evaluate_c1_gates(evidence)` recomputes the functional
gates from measured evidence, including recovery/reference equality, raw
restart operands, raw cross-route snapshots, exact retry dispositions, and
signal evidence. It does not trust stored gate booleans. Evidence-only tamper
tests fail the HTF, retry, recovery, restart, cross-route, and signal gates.

Identity and evidence payloads are separate. `identity_digest` covers only the
stable source/protected-artifact/route/stream identity, while `evidence_digest`
covers deterministic measured evidence, derived gates, and terminal status. The
current values are distinct and measurement tampering changes only the evidence
payload digest.

The certification generator executes twice before writing and the stored JSON
matches the current canonical serialization byte-for-byte. No production code,
configuration, Docker, external database, or broker state was changed.

Fresh-process plugin import loaded only the approved Momentum plugin/core/config
footprint and did not load pandas, signal contracts, registries, BaseModel,
StrategyModelV2, or unrelated concrete model packages. Explicit legacy bootstrap
reproduced the exact ordered inventories and was idempotent:

~~~
ModelRegistry:
DivergenceEdgeScorer, KyleTFI, MeanReversion, Momentum, PriceAction,
RegimeClassification, RegimePullbackScorer, RegimeRelativeValueScorer,
SqueezeBreakout, SqueezeBreakoutScorer, TrendFollowing, VPINKyle

StrategyModelRegistry:
DivergenceEdgeV2, KyleTFIV2, MeanReversionV2, MomentumV2, PriceActionV2,
RegimePullbackV2, SqueezeBreakoutV2, VPINKyleV2
~~~

## Two-pass self-review

### Pass 1 — quant/runtime correctness

- All live bars were closed, UTC-aligned, and causal.
- HTFs were materialized only from complete 1m constituents.
- Producer event identity, schema, stream key, Decimal payload and derived
  provenance were consumed through the real application boundaries.
- D4 RSI/MACD and pure Momentum outputs matched per route at the causal cutoff.
- At-least-once producer retry produced one logical Decision effect.
- Recovery blocked the incomplete HTF, repaired it through RecoveryEngine, and
  converged exactly to an independently built uninterrupted reference and one
  Decision transaction.
- Fresh restart reconstructed durable history without historical publication;
  the next producer transition matched the continuous runtime.
- ETH-only perturbation left BTC 1h and BTC 4h histories, cursors, features,
  outputs, identities, and transactions unchanged.

### Pass 2 — scope and architecture

- The C1 implementation is test/certification-only apart from the narrow
  M3/M4 certification provenance normalization described above.
- No Decision production module, ingestion production module, model math,
  production asset YAML, Compose service, or external adapter was added.
- No generic DB/broker emulator, PEL/group abstraction, retry framework, or
  cross-app production abstraction was introduced.
- Existing M3, M4, and D10 artifacts remain byte-for-byte unchanged.
- No C2 real infrastructure, C3 fault matrix, C4 container soak, or D11 work
  was started.

## Residual risks and next gate

C1 uses deterministic in-memory persistence and broker seams. It proves the
cross-app domain/event/delivery semantics but does not certify SQL atomicity,
real Valkey behavior, reconnects, container lifecycle, or production external
state. Those remain C2/C3/C4 gates. Production Decision assets remain inactive.

No .env credentials were copied or fabricated, and no external Timescale or
Valkey state was touched.

INGESTION_DECISION_C1_DETERMINISTIC_STITCH_REMEDIATION_READY_FOR_REVIEW
