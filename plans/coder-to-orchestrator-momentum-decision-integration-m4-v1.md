---
goal: Momentum Decision integration with certified RSI/MACD semantics
stage: coder-to-orchestrator
date_created: 2026-08-17
last_updated: 2026-08-17
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags:
  - momentum
  - decision-app
  - m4
  - integration
source_base: e7bce3d5ca2ea46772447cdf003c989124ea1847
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-momentum-decision-integration-m4
---

# Coder handoff — Momentum Decision integration M4 / M4R

## Outcome

M4 implements the certified, fixture-only Momentum integration boundary and
stops before production Decision asset activation or combined cutover testing.
The M4R remediation adds measured reconstruction, durable duplicate delivery,
phase-aware retention, compiler-derived resource decomposition, and fail-closed
functional gates. The required terminal status is:

`MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_READY_FOR_REVIEW`

The supplied precondition named `6feedc278db5fe077ac94a30dc72195e9fcafcc1`
as current `main`, but the approved M3/M3R worktree was already integrated into
local `main` at `e7bce3d5ca2ea46772447cdf003c989124ea1847`. The M3 worktree was
clean at that SHA. A fresh detached M4 worktree was created from that exact
post-M3 SHA; no M4 commit, merge, push, branch switch, reset, or external-state
operation was performed.

## Files changed

Production/config boundary:

- `src/apps/decision_app/features/momentum_integration.py`
- `src/apps/decision_app/composition.py`
- `src/apps/decision_app/settings.py`
- `configs/ingestion/global.yaml`

The ingestion candle retention is now 91 days. This is the minimum whole-day
configuration that guarantees the certified 544 four-hour ETH bars: 90 days
contains 540 four-hour bars, while 91 days contains 546. No production
`configs/decision/assets/*.yaml` file was added or activated.

Tests, fixtures, certification and evidence:

- `tests/decision/fixtures/momentum_m4/global.yaml`
- `tests/decision/fixtures/momentum_m4/assets/BTC.yaml`
- `tests/decision/fixtures/momentum_m4/assets/ETH.yaml`
- `tests/decision/integration/test_m4_momentum_integration.py`
- `tests/decision/certification/test_m4_certification.py`
- `tests/decision/certification/test_m3_momentum_feature_semantics.py`
- `tests/ingestion/config/test_settings.py`
- `scripts/certify_momentum_decision_m4.py`
- `artifacts/decision_m4/m4_momentum_decision_integration_certification.json`
- `artifacts/decision_m4/m4_momentum_resource_certification.json`

The M3 certification test assertion was updated to the current post-M3 source
SHA. The protected M3 artifact itself was not changed.

## Composition and binding contract

The app-owned Momentum envelope is strict, immutable and fixture-controlled.
It validates exact model/profile/certification keys, asset/timeframe identity,
the protected M3 artifact hash, and the route profile digest. Momentum is added
to the explicit production composition only when a supplied test configuration
contains Momentum bindings. The default composition remains SR-only.

For the three certified test routes:

| Route | Model parameters | RSI history | MACD history | Route profile lock |
|---|---|---:|---:|---|
| BTCUSDT/1h | long 70, short 34, MACD-positive, histogram 0.7 | 60 | 136 | `edb9f009b74877c39dcf620ea3786797379c76b135e18642e8e0d68d6a1a9c88` |
| BTCUSDT/4h | long 61, short 37, MACD-positive, histogram 0.35 | 120 | 272 | `145a9ad00fccf1ed23599fa85d28e988c952095985620e7411f5d9019479ceb2` |
| ETHUSDT/4h | long 55, short 45, MACD not required, histogram 0 | 208 | 544 | `0124642bf1a9f91ca01042375583f4aacc534f14af497329a2a6721c6d3ecdb3` |

The shared D4 definitions are exactly `RSI@1` and `MACD@1`, with maximum
histories RSI 208 and MACD 544. Physical compiled capacity is 544 bars for
each of the three route series, 1,632 retained bars in total. Each binding
receives its certified route-bounded tail rather than the shared maximum.

The composition contains `momentum@1` and `sr@1` only under the isolated
fixture configuration, with `ATR@1`, `MACD@1`, and `RSI@1` as the feature set.
No production Decision asset configuration was created.

## Parity and runtime evidence

- D4 RSI/MACD feature calculations match the certified pure M3 calculators.
- Momentum plugin outputs match the pure Momentum core and the route profile
  locks for all three routes.
- Startup with the full compiled history reaches `STARTUP_READY` for every
  route.
- The integration is stateless: stateful binding count is 0 and replay step
  count is 0. Historical reconstruction remains publication-suppressed.
- A missing or gapped required feature history fails closed and produces a
  blocked policy result rather than a fabricated feature value.
- Altering bars outside a route's certified tail does not change its feature
  result; altering a bar inside that tail does.

The isolated deterministic live proof adds one ETHUSDT/4h canonical candle and
exercises:

```text
SIGNAL
  -> PUBLISHED
  -> COMMITTED
```

The exact test stream is `signals:ETHUSDT:4h`, with explicit entry ID
`2888193600000-0`. Repeating the same envelope returns
`ALREADY_IDENTICAL`. A forced isolated publisher failure produces no stream
entry, `FAILED`, `ABORTED`, and a reconstruction-required lane state. These are
test doubles only; no real Valkey/Timescale or production signal stream was
used.

## M4R remediation evidence

Protected artifact hashes remain unchanged:

```text
M3 artifact:
6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c

D10 artifact:
2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
```

The regenerated M4 functional artifact is deterministic across two runs:

```text
functional artifact SHA-256:
3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792
deterministic_identity_sha256:
a625d6ffa448f5bdbcc12a091c0dbe9dd94484389fd038b435eb91895b738960
measurement_payload_sha256:
904a072b4911a4653ef3d0172abc47d3bc0342727cfb27d6667ac9341ea75c10
```

Measured route reconstruction evidence is present for all three routes. Each
route compares sequential live advancement with a fresh startup from the same
canonical cutoff; feature values, versions/cutoffs, artifact values/types and
decision evidence match exactly. Every route reports `PASS`, zero fresh
reconstruction publications, zero replay steps and a stateless runtime.

The duplicate path now redelivers the exact durable canonical candle with a
strictly forward input stream ID through `LiveDecisionRuntime`:

```text
first input       INSERTED -> SIGNAL -> PUBLISHED -> COMMITTED
redelivery        DUPLICATE -> lane LIVE, no second transaction
stream entries    1
envelopes         1
publisher retry   ALREADY_IDENTICAL
```

Forced publisher failure remains separately measured as `FAILED` / `ABORTED`
with zero signal entries. The functional gate evaluator consumes all of these
measurements and emits the remediation-ready status only when every gate is
true. A regression mutating reconstruction evidence fails the gate, and a
regression mutating evidence changes the measurement digest.

Retention coverage is derived from `TimeframeGrid` open-time geometry across
boundary, just-after, mid-bucket and just-before-next-boundary phases:

```text
required bars                 544 x 4h
worst phase requirement       2179.999999999722 hours
minimum whole days            91
configured retention          91 days / 2184 hours
90-day capacity               540 bars (fails phase coverage)
configured capacity           546 bars (passes all phases)
margin                        4.000000000277851 hours
```

Resource graph evidence is compiler/startup-derived rather than hard-coded:

```text
configured assets/lanes       2 / 3
final series capacities       BTCUSDT/1h=544, BTCUSDT/4h=544,
                              ETHUSDT/4h=544
steady retained bars          1,632
runtime instances              3
stateful bindings              0
startup fetch limits           544 per series
threads before/after           1 / 1
tasks before/after             1 / 1
thread/task leak gates         PASS / PASS
```

The fresh resource artifact SHA-256 and exact stored measurement values are:

```text
resource artifact SHA-256:
e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4
measurement_payload_sha256:
7825c8b64ddf4c43445b7a7a6dd3a98bb4e934ec50cdc900c16d20417bc7638a
process peak RSS              64,028,672 bytes
tracemalloc peak              3,983,223 bytes
CPU seconds / wall seconds    96.566052 / 100.313614
CPU core equivalent           0.962642
normal / hard memory gates    PASS / PASS
CPU gate                      PASS
resource status               PASS
```

## Validation

M4R focused and compatibility results:

```text
M4 integration + certification              18 passed
M3 certification + M4 focused               43 passed
complete tests/decision                    404 passed
Momentum / MI0 / config / ingestion slice  168 passed
fresh-process import isolation               8 passed
```

Static and boundary checks:

```text
Ruff check                                passed
Ruff format --check                       passed
compileall                                passed
git diff --check                          passed
fresh-process Momentum import isolation   passed
production Decision asset scan            zero files
repository cache cleanup                  zero decision caches
```

The functional artifact was regenerated twice and matched byte-for-byte. The
resource artifact was regenerated from a fresh process; its measurement values
and SHA are expected to vary between runs. The current final hashes and exact
resource values are recorded in the M4R evidence section above.

## Two-pass self-review

Pass 1 — quantitative/runtime correctness:

- Route parameters and histories are locked to the approved M3 artifact.
- Feature calculations use causal bounded bars only.
- Route-tail isolation, missing-history failure, startup readiness and
  measured sequential-vs-fresh reconstruction parity are covered for all
  three routes; fresh reconstruction publishes zero signals.
- Durable canonical duplicate delivery uses a strictly forward stream ID and
  produces no second policy/publication/finalization transaction.
- Retention evidence uses actual `TimeframeGrid` phase/open-time geometry.
- Resource decomposition and startup fetch limits come from compiler and
  recording-repository observations; task/thread leak gates are measured.
- The isolated signal path preserves D8 publication/finalization ordering and
  exact-ID idempotency.
- No production asset configuration or external transport state was touched.

Pass 2 — architecture/scope:

- Momentum integration is conditional and explicit; no discovery or generic
  adapter framework was added.
- No Decision runtime algorithm, risk/execution code, legacy app, Docker,
  PriceRelay, D11, or new model was added.
- The M4 harness is deterministic and separate from the resource measurement
  artifact.
- The only canonical retention change is the authorized 90-to-91-day coverage
  correction required by the certified ETH history.
- Functional readiness is fail-closed on the measured evidence; a tampered
  reconstruction result cannot retain a ready gate.

## Residual risks and deferred gates

- Production Decision asset activation remains intentionally deferred.
- Real Timescale/Valkey soak, cutover, and live external-state certification
  remain deferred.
- D11 combined ingestion-to-Decision certification remains deferred.
- Final model-mix resource recertification is required after the intended model
  set is integrated.
- The pre-existing `signal_app` sparse feature fallback discrepancy is recorded
  and was not modified by M4.

MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_READY_FOR_REVIEW
