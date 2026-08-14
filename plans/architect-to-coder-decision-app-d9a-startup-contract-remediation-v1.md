---
goal: Remediate D9A startup trust-boundary gaps without starting D9B or redesigning the approved D0-D8 architecture
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: Quant Architect
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9a, remediation, startup, checkpoint, ingestion-contract, manifests]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D9A startup contract remediation

## 1. Review status

D9A remains structurally sound but is **not approved yet**.

The submitted deterministic suites are green, but independent adversarial review found three production-blocking startup contract gaps plus one small scope correction:

1. checkpoint `CONFLICT` / `REJECTED_OLDER` is recorded as evidence but still allows `STARTUP_READY`;
2. the ingestion stream adapter rejects valid canonical derived HTF events because it incorrectly requires `source_timeframe == target timeframe`, while canonical ingestion uses source/base timeframe such as `1m` for derived `15m/1h/...` candles;
3. ingestion manifest activation checks only decision/trigger timeframes and can activate a lane while another compiled canonical series required by D3/D4 is STOPPED;
4. D9A was the first phase instructed to materialize `configs/decision/global.yaml`, but no `configs/decision/` namespace exists in the worktree. Production SR asset config remains deliberately deferred.

Do not start D9B until this remediation is reviewed and approved.

---

# 2. Preserve approved D9A architecture

Do not redesign:

```text
D2 static lane plan
D3 causal BarStore/readiness
D4 FeaturePlan/FeatureEngine
D5 DataResolver
D6 ModelRuntime/state/rewarm
D7A SR adapter
D8 policy/publication/finalization contracts
D9A tail-before-DB startup capture
D9A latest-only checkpoint model
D9A publication-free reconstruction
```

Still forbidden in this remediation:

```text
continuous XREAD / XREADGROUP
consumer groups / PEL
signal XADD
PriceRelay
FastAPI
Docker/Compose decision service
asset:lifecycle continuous consumer
retry/backoff framework
checkpoint framework/history browser
generic transaction manager
legacy signal_app / strategy_app changes
canonical ingestion production behavior changes
D9B+
```

No commit, merge, push, branch switch, reset, or restore.

---

# 3. BLOCKER A — checkpoint persistence outcome must be authoritative

## 3.1 Current defect

`DecisionStartupCoordinator._reconstruct_lane()` currently does:

```text
reconstruct state
-> create checkpoint at resume cutoff
-> checkpoint_repository.save(...)
-> record save_result in evidence
-> build final runtime
-> STARTUP_READY
```

without checking whether `save_result` is safe.

Independent proof with a repository seam returning `CheckpointSaveResult.CONFLICT` produced:

```text
overall status      STARTUP_READY
lane status         STARTUP_READY
checkpoint result   CONFLICT
runtime present     True
```

This contradicts the D9A freeze:

```text
same cutoff + different payload -> CONFLICT / fail closed
older cutoff -> reject
```

A durable checkpoint conflict means D9A no longer knows which reconstructed state is authoritative for the exact D6 `LaneExecutionIdentity`.

## 3.2 Required behavior

After `save()`:

```text
INSERTED   -> safe
UPDATED    -> safe
IDENTICAL  -> safe
CONFLICT   -> fail lane startup closed
REJECTED_OLDER -> fail lane startup closed
```

For `CONFLICT` / `REJECTED_OLDER`:

- raise a stable `StartupLaneError` or equivalent before returning the final `ModelRuntime`;
- do not create/return an active runtime for that lane;
- do not create a baseline `LaneCommitWatermark` for that lane;
- lane startup evidence must be BLOCKED/INVALID according to existing small vocabulary, with a stable semantic reason;
- overall startup must not be `STARTUP_READY` if this is an active configured lane;
- do not silently reload the newer checkpoint and continue;
- do not retry in D9A;
- do not overwrite the conflicting durable row.

This is a fail-closed restart integrity boundary, not a transient retry policy.

Validate that repository return values are actual `CheckpointSaveResult` values; fail closed on an unsupported result rather than stringifying arbitrary values.

## 3.3 Evidence cleanup

Do not stringify missing checkpoint evidence into the literal string `"None"`.

For a stateless lane / no checkpoint save:

```text
checkpoint_save_result = None
```

should remain actual `None`.

## 3.4 Tests

Add focused startup regressions:

```text
checkpoint save INSERTED -> STARTUP_READY
checkpoint save UPDATED -> STARTUP_READY
checkpoint save IDENTICAL -> STARTUP_READY
checkpoint save CONFLICT -> STARTUP_BLOCKED, no runtime/watermark
checkpoint save REJECTED_OLDER -> STARTUP_BLOCKED, no runtime/watermark
unsupported checkpoint save result -> fail closed
```

Use deterministic repository seams. No database is required for these tests.

---

# 4. BLOCKER B — mirror the canonical ingestion provider/derived provenance contract exactly

## 4.1 Current stream defect

`parse_canonical_ingestion_event()` currently rejects a derived event when:

```text
source_timeframe != payload timeframe
```

The current D9A test therefore uses an invalidly convenient fixture:

```text
target timeframe = 1h
source_type       = derived
source_timeframe  = 1h
```

Canonical ingestion does **not** use that rule.

Authoritative ingestion evidence already proves:

```text
derived 15m / 30m / 1h / ... candle
source_type       = derived
source_provider   = None
source_timeframe  = 1m
```

Examples are already asserted in:

```text
tests/ingestion/services/test_htf_aggregation.py
tests/ingestion/certification/test_htf_publisher_scale.py
```

Production `CanonicalCandle` itself freezes only:

```text
provider:
  source_provider non-empty
  source_timeframe is None

derived:
  source_provider is None
  source_timeframe non-empty
```

It does not require derived source timeframe to equal the target timeframe.

## 4.2 Required decision-owned external-contract validation

The decision production adapter must remain independent of `apps.ingestion_app` imports, but it must mirror the canonical source-provenance contract exactly.

Use one small decision-owned validation helper or equivalent concise logic:

```text
provider:
  source_type == provider
  source_provider = non-empty text
  source_timeframe = None

derived:
  source_type == derived
  source_provider = None
  source_timeframe = non-empty text
```

Do **not** require:

```text
source_timeframe == target timeframe
```

Do not infer or rewrite `source_timeframe`.

If a `TimeframeGrid` is present, target candle geometry remains validated against the target series exactly as today. Do not reinterpret the source timeframe as target geometry.

Do not invent a stronger source/target ratio rule unless it already exists in the canonical ingestion contract; D9A is a consumer, not a second ingestion validator.

## 4.3 Timescale path must validate the same provenance

`CanonicalMarketHistoryRepository` selects:

```text
source_type
source_provider
source_timeframe
```

but currently discards them without validation. The existing D9A DB test even uses:

```text
source_type = test
source_provider = test
source_timeframe = 1h
```

and is accepted.

That violates the D9A acceptance criterion:

```text
DB row conversion parity with stream conversion
```

Before constructing `CausalBarView`, validate DB provenance with the exact same provider/derived rules as the stream adapter.

The returned `CausalBarView` need not grow provenance fields; this validation is a trust check at the external boundary.

Preserve existing:

```text
UTC checks
Decimal precision
OHLC geometry
volume >= 0
taker_buy_base bounds
TimeframeGrid alignment
```

## 4.4 Cross-contract tests

Correct the D9A derived fixture to represent canonical reality, e.g.:

```text
target timeframe = 1h
source_type       = derived
source_provider   = None
source_timeframe  = 1m
```

Add at least:

```text
stream provider provenance accepted
stream derived target 1h/source 1m accepted
stream malformed provider provenance rejected
stream malformed derived provenance rejected
DB provider provenance accepted
DB derived target 1h/source 1m accepted
DB unknown source_type rejected
DB malformed source metadata rejected
```

Add one **test-only** cross-contract fixture using the actual canonical ingestion `CanonicalCandle` / `build_candle_committed_event` or another authoritative ingestion contract helper, then parse it through D9A. It is acceptable for tests to import ingestion contracts. Production `decision_app` code must remain ingestion-app independent.

This test should make future ingestion/decision drift visible immediately.

---

# 5. BLOCKER C — ingestion manifest LIVE gate must cover every compiled canonical series used by the lane

## 5.1 Current defect

`_active_manifest_assets()` currently validates only:

```text
lane.decision_timeframe
lane.trigger_timeframe
```

But D9A has already compiled a larger exact canonical demand surface from D3/D4:

```text
compile_lane_market_requirements(...)
  -> decision + trigger + ModelSpec warmup timeframes

FeaturePlan.history_requirements
  -> effective shared feature history series
  -> may include fixed additional timeframes
```

Independent proof constructed:

```text
lane decision/trigger = 1h
shared feature F requires fixed 4h history
asset manifest        = LIVE
1h timeframe manifest = LIVE
4h timeframe manifest = STOPPED
canonical 1h/4h DB history present
```

D9A returned:

```text
STARTUP_READY
lane STARTUP_READY
runtime present
```

This violates ingestion lifecycle ownership. Durable rows existing in Timescale do not mean a configured canonical series is currently lifecycle-LIVE.

## 5.2 Required behavior

Manifest activation must use the **compiled canonical series demand**, not manually reconstruct a smaller list.

For each configured decision asset, derive all required timeframes from the already-approved compiled objects for its lanes:

1. D3 `LaneMarketRequirements.minimum_bars_by_series` for each resolved lane;
2. D4 `FeaturePlan.history_requirements` for effective/allowed shared features.

This naturally includes:

```text
decision timeframe
trigger timeframe
ModelSpec warmup timeframes
fixed shared-feature history timeframes
```

Do not include unused catalog features or speculative timeframes.

Before an asset may be added to `active_manifest_assets`, every required timeframe manifest must:

```text
exist
symbol == manifest_asset
source == ingestion
enabled == True
desired_state == LIVE
```

If any required canonical timeframe is not LIVE:

- configured asset/lane remains explicit `INACTIVE` (or existing equivalent non-running startup evidence);
- no lane runtime is constructed;
- no state reconstruction/checkpoint write occurs for that inactive lane;
- do not silently use retained Timescale rows as lifecycle authority.

The configured graph remains static; the manifest still cannot invent extra models/timeframes.

## 5.3 Keep one source of required-series truth

Prefer factoring the already-existing `_required_series(...)` / compiled lane+feature-plan logic so both:

```text
startup stream/history capture
manifest lifecycle validation
```

consume the same canonical demand calculation.

Avoid a second manually maintained timeframe catalog.

## 5.4 Tests

Add deterministic manifest-store regressions:

```text
all compiled required timeframe manifests LIVE -> asset active
fixed D4 4h feature history STOPPED -> asset/lane INACTIVE, no runtime
ModelSpec warmup-only timeframe STOPPED -> INACTIVE, no runtime
required timeframe manifest missing -> INACTIVE
unrequested/unused timeframe STOPPED -> does not block
wrong manifest source/symbol -> inactive
```

The test that proves fixed 4h feature history is mandatory.

---

# 6. Scope correction — materialize the minimal decision global namespace

The D9A architect handoff explicitly froze:

```text
configs/decision/global.yaml
configs/decision/assets/{MANIFEST_ASSET}.yaml
```

and explicitly prohibited inventing a production SR asset configuration.

The worktree currently has no `configs/decision/` directory at all.

Add only the minimal global namespace file needed to materialize the approved boundary without speculative knobs.

Prefer the smallest valid form, e.g. conceptually:

```yaml
decision: {}
```

or a similarly minimal approved global feature-policy block **only if it is already required by the implemented loader and uses already-approved semantics**.

Do not invent:

```text
production lane bindings
SR parameters
runtime concurrency knobs
retry knobs
PriceRelay settings
publisher settings
D9B worker settings
```

Do **not** add `configs/decision/assets/BTC.yaml` unless an approved production decision/SR model config already exists. The current architect instruction explicitly allows deterministic test fixtures until that configuration is approved.

Update tests to prove:

```text
ConfigManager can register the materialized decision global namespace
unknown/extra global keys still fail strict validation when supplied
absence of production asset files remains an explicit safe no-production-graph condition
```

If the current `load_decision_config()` deliberately requires at least one asset, retain that fail-closed requirement; do not create a dummy production asset merely to make the default repository load succeed.

---

# 7. Preserve validated D9A behaviors

Do not regress:

```text
tail captured before DB cutoff
DB-ahead-of-stream startup position
InputReadCursor captured tail + warm cutoff split
publication-free rewarm
checkpoint exact LaneExecutionIdentity
checkpoint payload hash validation
checkpoint exact stateful binding set
first bounded SR inception
checkpointed SR restart replay only after checkpoint
retention gap after checkpoint -> blocked
final BarStore steady-state boundedness
baseline LaneCommitWatermark.last_disposition = None
manifest_asset != decision_asset identity split
canonical ingestion timeframe/alignment source of truth
no D8 signal finalization during startup
```

No local infrastructure availability claim is required if the worktree still lacks its required `.env`. Do not create or copy secrets merely to force integration tests.

---

# 8. Validation

Run the D9A-focused surface including new adversarial tests first.

At minimum:

```text
tests/decision/test_d9a_checkpoints.py
tests/decision/test_d9a_ingestion_input.py
tests/decision/test_d9a_settings_and_history.py
tests/decision/test_d9a_startup_reconstruction.py
tests/decision/test_d9a_real_sr_startup.py
```

Then:

```text
complete tests/decision
existing D1-D8 compatibility slice
non-research SR core/config/lifecycle/replay/adapter gate
canonical ingestion domain/service/outbox/HTF contract tests relevant to source provenance
full ingestion suite excluding only genuinely environment/Compose-blocked harness gates as already documented
```

Specifically include authoritative ingestion tests that prove derived source timeframe semantics:

```text
tests/ingestion/services/test_htf_aggregation.py
tests/ingestion/certification/test_htf_publisher_scale.py
```

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
trailing-whitespace check
D9A import/scope scan
repo-local __pycache__ cleanup
```

No external broker/database mutation unless the repository environment becomes explicitly usable. If `.env` remains absent, record the local integration gate as environment-blocked exactly as before.

---

# 9. Two-pass coder self-review

## Pass 1 — correctness

Explicitly verify:

```text
checkpoint CONFLICT cannot return STARTUP_READY
checkpoint REJECTED_OLDER cannot return STARTUP_READY
no runtime/watermark is emitted for checkpoint-save failure
canonical derived target HTF/source 1m parses correctly
stream and DB provenance validation agree
DB invalid source provenance fails closed
compiled D3/D4 required series drive manifest lifecycle gate
stopped required fixed-feature timeframe blocks activation
unused stopped timeframe does not block
SR first inception/restart parity unchanged
retention gap fail-closed unchanged
```

## Pass 2 — architecture/simplicity

Verify:

```text
no ingestion production import in decision adapters
no duplication of ingestion timeframe geometry
no second required-timeframe catalog
no checkpoint retry framework
no checkpoint history/version graph
no D9B stream loop
no signal XADD
no PriceRelay
no FastAPI/Docker
no invented production model config
minimal global decision namespace only
```

---

# 10. Coder handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d9a-startup-reconstruction-v1.md
```

Record:

```text
files/symbols changed
checkpoint save-result finalization rule
canonical provider/derived source contract
cross-contract ingestion fixture evidence
DB/stream provenance parity evidence
compiled-series manifest gating rule
fixed-feature/warmup manifest regressions
minimal decision global namespace choice
D9A focused count
complete decision count
compatibility count
non-research SR count
ingestion contract/full-suite count
local Timescale/Valkey availability status
Ruff/format/compile/diff/import/cache evidence
Pass 1 findings
Pass 2 findings
residual risks
D9B/PriceRelay carry-forward
```

Do not start D9B automatically.

Final line exactly:

```text
DECISION_APP_D9A_STARTUP_RECONSTRUCTION_READY_FOR_REVIEW
```
