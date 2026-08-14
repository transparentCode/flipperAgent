---
goal: Prove the approved decision_app D0-D6 runtime against representative real model cores without importing legacy signal/strategy runtime architecture or starting DecisionPolicy/publication
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d7, real-model-adapters, sr, plugin]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D7 representative real-model adapters

## 1. Objective

D0-D6 now provide the complete generic offline decision engine core:

```text
D2 static lane/dependency plan
D3 causal market state
D4 shared FeaturePlan/FeatureEngine
D5 semantic DataPlan/DataResolver
D6 plugin execution + explicit state transaction + causal rewarm
```

D7 must prove that this architecture can host **real existing quantitative model cores** without importing the old `signal_app` / `strategy_app` runtime design or creating compatibility infrastructure that becomes the new foundation.

D7 is intentionally split into two narrow subpackages:

```text
D7A — immediate, mandatory
  real stateful analytical adapter: SR

D7B — integration gate
  first plugin-ready stateless decision/scoring model from the parallel model-refactor programme
  recommended first candidate: Momentum
```

D7A may start immediately in the existing cumulative worktree.

D7B must **not** refactor the chosen legacy model inside this decision-app worktree. It should integrate only a model that has already passed the parallel plugin-interface refactor gate and whose code is present on the D7 base. If no such model is available yet, stop after D7A with an explicit D7B dependency note rather than building a legacy `FeatureVector` bridge.

Expected final D7 terminal status only after both subpackages are complete:

```text
DECISION_APP_D7_REPRESENTATIVE_REAL_MODEL_ADAPTERS_READY_FOR_REVIEW
```

If D7A completes while D7B is not yet available, use:

```text
DECISION_APP_D7A_SR_REAL_ADAPTER_READY_FOR_REVIEW
```

Do not falsely claim full D7 closure.

Continue in:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

No commit, merge, push, branch switch, reset, restore, D8, or infrastructure work.

---

# 2. Hard D7 principles

1. **Adapters are thin boundaries, not replacement model engines.**
2. **Model cores must not import `apps.decision_app`.**
3. A model-side plugin adapter may import the shared pure contracts from `libs.contracts.decision`.
4. `decision_app` must not import legacy `FeatureVector`, legacy `ModelOutput`, `BaseModel`, `ScoringModel`, `ModelRegistry`, `StrategyModelV2`, or old signal/strategy runtime managers as its model interface.
5. Do not create a universal legacy compatibility bridge from `DecisionContext -> FeatureVector -> ModelOutput` as a D7 foundation.
6. Real model state must obey D6 explicit `state_snapshot -> proposed_next_state` semantics; hidden mutable object state that affects evaluation is not accepted as a stateful plugin implementation.
7. Training, batch optimization, notebooks, research evaluation, and offline model-specific APIs remain separate from the runtime plugin interface.
8. D7 does not reinterpret model scores into authoritative trading decisions. That is D8 `DecisionPolicy` work.
9. D7 introduces no physical data source ownership inside models.
10. No model is allowed to load Redis, Timescale, HTTP, scraper, files, YAML, or environment state during `evaluate()`.
11. Runtime factory construction may receive immutable binding parameters only; no import-time discovery or arbitrary service locator.
12. Preserve causal PIT semantics and exact D6 state continuity.

---

# 3. Why D7A uses SR

The existing SR model is the best first real stateful analytical proof because its core is already architecturally compatible with D6 principles:

```text
SREngine.step(previous_state, closed_bar, resolved_config)
  -> next_state
  -> SRSnapshot
  -> events
```

Properties already present:

- immutable `SRState`;
- deterministic one-bar transition;
- deterministic replay path through the same `SREngine.step`;
- typed configuration resolution;
- explicit UTC/timeframe identity;
- no signal direction required;
- no infrastructure ownership inside `SREngine`.

Do not rewrite `SREngine` merely to satisfy D7.

D7 should adapt the existing core.

Protected SR behavior must remain unchanged unless a genuine adapter integration defect proves otherwise.

---

# 4. D7A production scope

Preferred additions:

```text
src/libs/models/sr/adapters/decision_plugin.py
```

Optionally, one tiny model-owned semantic projection helper may be added under:

```text
src/libs/models/sr/adapters/
```

if it keeps the plugin adapter readable.

For the first real shared feature, prefer one small app-owned definition module such as:

```text
src/apps/decision_app/real_features.py
```

containing only the feature definition(s) actually required by D7 models.

Do not create:

```text
feature provider framework
indicator registry replacement
feature service
feature discovery layer
model adapter framework
adapter base class hierarchy
```

Existing `RuntimePluginCatalog` is sufficient for registration.

Tests should be concentrated in at most:

```text
tests/decision/test_real_sr_plugin.py
tests/decision/test_real_model_adapters.py   # D7B only when applicable
```

Existing SR tests must remain green.

---

# 5. SR plugin contract

Implement a real plugin adapter approximately:

```text
SRDecisionPlugin
  spec: ModelSpec
  data_requests(...)
  evaluate(...)
```

It must structurally satisfy `DecisionModelPlugin`.

Recommended `ModelSpec` semantics:

```text
name = stable SR plugin identity
version = explicit adapter/model semantic version
stateful = True
output_kind = analytical
produces_artifact_type = sr.snapshot.v1
supported_trigger_modes = (on_bar_close,)
intrinsic_feature_requirements = (ATR required,)
intrinsic_data_requirements = ()
dependency_requirements = ()
state_reconstruction.durable_pit_required = True
```

Do not add a `ModelDecision`; SR is analytical context.

Do not invent a trade direction from zones/events.

---

# 6. SR configuration ownership

The existing model owns its config semantics through:

```text
SRConfigResolver
ResolvedSRConfig
```

The plugin factory receives immutable binding parameters. Use those parameters only to carry deterministic SR configuration input/overrides needed to construct a resolver or equivalent pure model config object.

Do not read YAML/files inside `evaluate()`.

A clean approach is:

```text
binding.parameters
  -> validated immutable raw SR config / model parameters
  -> SRDecisionPlugin construction

context.asset + context.decision_timeframe
  -> SRConfigResolver.resolve(...)
  -> deterministic ResolvedSRConfig
```

The adapter may cache the resolved immutable configuration after checking that subsequent contexts use the same lane asset/timeframe identity.

No hidden per-market mutable model state may be created through config caching.

Material SR config must already participate in `binding_config_fingerprint` through binding parameters. Do not add a second runtime identity system.

---

# 7. SR runtime state representation

This is a hard boundary.

D6 `ModelState` accepts only the shared immutable semantic vocabulary. `SRState` is a custom domain object and must **not** be inserted directly into `ModelOutcome.proposed_next_state`.

Use the existing deterministic SR state codec:

```text
encode_state(SRState) -> str
decode_state(str) -> SRState
```

Plugin state semantics:

```text
state_snapshot is None
  -> create_initial_state(...)

state_snapshot is str
  -> decode_state(state_snapshot)

other type
  -> fail closed
```

After `SREngine.step`:

```text
proposed_next_state = encode_state(next_state)
```

This means D6 remains unaware of SR domain classes while SR preserves its canonical state representation.

Required proof:

```text
same initial state + same causal bars/config
  -> byte-identical encoded final state
```

and:

```text
D6 LIVE prepare
  -> encoded proposal not committed
commit_prepared
  -> encoded state becomes committed
```

---

# 8. Causal bar adaptation

SR `ClosedBar` requires:

```text
state_key
bar_id
closed_at
open/high/low/close
atr_at_close
```

The adapter translates from `DecisionContext` only.

Rules:

- D7A supports only closed decision bars for SR V1 adapter proof;
- reject projected `decision_bar_closed=False` unless the SR core has explicit projected semantics (it currently does not);
- `closed_at = context.market_as_of`;
- OHLC comes from `context.decision_bar`;
- asset/venue/timeframe comes from context;
- `bar_id` must be deterministic from canonical context identity/time, never Python hash or object id;
- ATR comes from the binding-visible `ATR` `FeatureSnapshot`;
- convert Decimal/numeric inputs deterministically and validate finite positive values before constructing SR `ClosedBar`.

Recommended bar-id semantics:

```text
sha256(canonical lane/model bar identity)
```

using the existing shared canonical SHA-256 helper or an SR-compatible deterministic string based only on:

```text
venue
asset/instrument identity as chosen explicitly
timeframe
market_as_of
```

Do not use wall clock.

---

# 9. First real shared feature: ATR

SR requires ATR-at-close.

D7A should prove one real D4 feature definition without building a general indicator integration framework.

Add an explicit app-owned `SharedFeatureDefinition` for semantic name:

```text
ATR
```

Use the existing deterministic ATR implementation/math where possible.

Requirements:

- versioned definition;
- fixed explicit period for this D7 proof, default 14 unless existing SR config/evidence requires a different approved period;
- exact bounded closed-bar history requirement sufficient for Wilder ATR initialization;
- pure calculator receives only `SharedFeatureContext`;
- returns a finite positive semantic scalar;
- no hidden mutable indicator instance across calls;
- no DataFrame;
- no BarStore mutation;
- no infrastructure.

Prefer batch/pure calculation from the exact supplied history rather than an incremental mutable `ATR` instance.

If reusing `_compute_atr_batch`, wrap it behind a tiny deterministic calculator and test parity against the existing indicator implementation.

Feature version must be material to D4 feature-plan fingerprint as already designed.

Do not register unrelated indicators in D7A.

---

# 10. SR artifact projection

`SRSnapshot` and SR event/zone domain objects must not leak as unsupported custom values through `ModelArtifact.value`.

Project the real model output into the shared semantic vocabulary.

At minimum the artifact should include deterministic analytical evidence such as:

```text
snapshot_id
config_hash
as_of
zone_count
event_count
zones: tuple of bounded semantic mappings
events: tuple of semantic mappings
```

Keep the projection useful but bounded.

For zones, include only stable context/risk-analysis fields needed by future consumers, for example:

```text
zone_id
side
geometry/price bounds
status
available/formed/updated timestamps as appropriate
touch/break lifecycle summary where canonical
```

For events:

```text
event_id
zone_id
event_type
timestamp
price
bar_id
```

Do not serialize arbitrary `__dict__`, repr, enums/custom objects, or internal caches.

Use stable primitive values and UTC datetimes.

`ModelArtifact.provenance` should minimally contain:

```text
adapter/model version
SR config hash
SR snapshot id
```

Do not include wall clock.

---

# 11. SR no external data / dependencies

For D7A:

```text
data_requests(...) -> ()
```

SR does not own external physical data in this adapter.

No same-lane dependencies.

This intentionally isolates the first real stateful proof to:

```text
canonical bars
+ shared ATR
+ explicit state
```

The D6 synthetic tests already prove the generic external-data/dependency paths.

---

# 12. D7A rewarm parity proof

D7A must prove that D6 causal rewarm through the adapter reproduces the authoritative SR core transition path.

Use one deterministic synthetic/fixture OHLC sequence and one resolved SR config.

Reference path:

```text
create_initial_state
for bar:
  SREngine.step(...)
```

Runtime path:

```text
LaneMarketView sequence
FeatureEngine ATR
ModelRuntime.rewarm(...)
SRDecisionPlugin.evaluate(...)
```

Compare at the same final cutoff:

```text
decode_state(D6 committed state) == reference final SRState
```

and preferably:

```text
final snapshot_id == reference final snapshot_id
```

where the runtime result exposes the final analytical artifact during a comparable evaluation step.

No publication.

Also prove:

- failed middle rewarm leaves real encoded state unchanged;
- exact next-trigger LIVE state proposal matches direct `SREngine.step` from the committed decoded state;
- abort does not alter encoded committed state;
- commit advances encoded state exactly once.

This is the main D7A acceptance gate.

---

# 13. D7B integration gate — first plugin-ready stateless decision model

D7B exists to prove a real direction/scoring model in addition to analytical SR.

Recommended first candidate:

```text
Momentum
```

because its current decision rule is small and easy to parity-test, but its current implementation still depends on legacy:

```text
FeatureVector
ModelOutput
BaseModel
ModelRegistry
```

Do **not** add a permanent D7 bridge that converts `DecisionContext` into this legacy runtime contract.

Instead D7B waits for the parallel model-refactor worktree to produce a plugin-ready model-side adapter/core satisfying the shared interface gate described in:

```text
plans/architect-to-coder-model-plugin-refactor-contract-v1.md
```

When such code is present on the D7 base, D7B should perform only:

1. explicit runtime factory registration;
2. required real shared feature definitions actually demanded by that model;
3. D6 end-to-end offline execution test;
4. parity against the model's own frozen reference/core behavior;
5. output identity/decision checks.

No second model runtime.

---

# 14. D7B Momentum target semantics (for later integration)

The plugin-ready Momentum model should ultimately declare semantic demand approximately:

```text
FeatureRequirement("RSI", required=True)
FeatureRequirement("MACD", required=True)
```

or a deliberately versioned set of finer semantic features if the refactor contract chooses that cleanly.

It should be:

```text
stateful = False
output_kind = decision_capable
```

and return:

```text
ModelArtifact
+ optional ModelDecision
+ proposed_next_state=None
```

D7 must not assume raw Momentum score is authoritative policy output.

Direction/conviction are model output only; D8 decides publication.

If Momentum refactoring is not ready, another plugin-ready stateless model may substitute only if it passes the same gate and requires less architecture compromise.

Document the substitution and rationale in the coder handoff.

---

# 15. No adapter contamination of model cores

For every D7 real adapter enforce an import boundary:

Core model modules must not import:

```text
apps.decision_app
Valkey/Redis
asyncpg/SQLAlchemy
FastAPI
HTTP/scraper clients
signal_app
strategy_app
risk_app
execution_app
```

The adapter may import:

```text
libs.contracts.decision
its own model core/domain
small pure feature/model utilities
```

`decision_app` runtime modules should not gain direct dependencies on SR internals or Momentum internals. Runtime sees only `DecisionModelPlugin`.

Concrete plugin registration in tests/composition code may of course import the adapter class/factory explicitly.

---

# 16. Batch/research interface must remain separate

Do not delete or fold existing model-specific batch/research paths into the plugin interface merely to make D7 pass.

For a refactored model, preferred shape is:

```text
model core/domain
  deterministic semantic calculation

plugin adapter
  DecisionModelPlugin runtime boundary

batch/research adapter
  vectorized pandas/numpy/offline path where useful
```

The plugin contract is not the research API.

No `batch_evaluate()` method belongs on `DecisionModelPlugin`.

---

# 17. D7 runtime construction

Use existing:

```text
RuntimePluginCatalog
ModelRuntime
```

Do not modify D6 plugin factory semantics unless a real adapter demonstrates a genuine blocker and the smallest compatible change is proven by tests.

For SR the factory can receive immutable raw SR config/binding parameters and build `SRDecisionPlugin`.

Do not add auto-discovery.

Do not instantiate plugin globally at import.

One plugin instance per binding remains mandatory.

---

# 18. D7 identity and provenance

Do not invent `d7_model_adapter_fingerprint` unless there is a real semantic input not already represented by:

```text
plugin name/version
binding parameters/binding_config_fingerprint
feature_plan_fingerprint
data_plan_fingerprint
```

The adapter's semantic version is part of `ModelSpec.version` / plugin identity.

Material adapter behavior changes must bump the version.

D8 still owns final authoritative identity composition.

---

# 19. D7A tests — plugin structure

Cover:

```text
SRDecisionPlugin satisfies DecisionModelPlugin
spec is stateful analytical
spec produces exact sr artifact type
spec requires ATR feature
spec requests no external data
factory is deterministic and performs no I/O
wrong SR config parameters fail during construction/resolution
projected decision bar rejected
missing/invalid ATR fails closed
wrong state_snapshot type fails closed
encoded SR state round-trip accepted
```

Do not use network/files.

---

# 20. D7A tests — core parity

Using a fixed SR config + bar fixture:

```text
direct SREngine step path
vs
D6 runtime rewarm/plugin path
```

Prove:

```text
same final decoded state
same final config hash
same zone identities/statuses
same event identities
same snapshot identity where comparable
```

Also prove order/cutoff sensitivity correctly rejects altered causal ordering.

---

# 21. D7A tests — state transaction

After rewarm:

```text
prepare_live(next cutoff)
```

must produce a state transition containing encoded SR next state while committed state remains unchanged.

Then:

```text
commit_prepared(...)
```

must install exactly that encoded state.

Abort path:

```text
prepare_live
abort_prepared
```

must preserve committed encoded state and require rewarm per D6.

No LaneCommitWatermark mutation.

---

# 22. D7A tests — ATR feature

Prove:

```text
ATR definition exact history bound
causal no-future bars
calculator deterministic
calculator output finite positive once ready
known fixture parity with existing ATR implementation
same feature semantic inputs -> same snapshot
feature plan identity changes if ATR definition version/history changes
```

Do not rewrite D4.

---

# 23. D7B acceptance tests

When a plugin-ready stateless model is available:

- runtime factory creates exact model plugin;
- `data_requests()` and feature requirements remain within declared spec;
- D6 executes it through the same request-before-evaluate path;
- no custom state proposal;
- artifact/decision identity exactly matches lane/as-of;
- analytical/predictive/decision-capable rules respected;
- fixed reference input produces parity with the refactored model's model-owned reference behavior;
- changing binding parameters changes binding identity and expected behavior, not runtime architecture.

Do not use old signal_app output as the sole oracle. The model core/reference should be authoritative for model semantics.

---

# 24. Regression protection

D7 must run the complete D1-D6 decision suite plus focused real-adapter tests.

SR package regression should include the canonical SR architecture/contract/lifecycle/replay suite relevant to touched files.

Do not regenerate protected SR research evidence or publication artifacts unless the adapter unexpectedly touches those contracts and the orchestrator explicitly authorizes it.

No fresh provider calls.

---

# 25. Parallel-model-refactor coordination

D7 and model refactors may run concurrently, but enforce one writer per checkout/worktree.

Recommended ownership:

```text
decision-app-d0 worktree
  D7A SR adapter + decision runtime integration only
  do not refactor Momentum/MeanReversion/etc here

parallel model worktrees
  one model/family per worktree
  refactor model core/plugin boundary
  no edits to decision_app runtime
```

Do not have two worktrees edit the same model package concurrently unless the user explicitly assigns ownership.

For D7B, consume a reviewed plugin-ready model only after its branch/worktree result is intentionally integrated into the D7 base by the orchestrator/user. Do not reach across worktrees with filesystem imports.

---

# 26. D7 explicit non-goals

Do not implement:

```text
DecisionPolicy
TradeSignal publication
signal stream adapters
price publication
risk compatibility
Valkey/Redis
Timescale adapter
HTTP/scraper
FastAPI
Docker
AssetRuntime
input consumer
service lifecycle
model auto-discovery
generic adapter framework
universal FeatureVector bridge
universal ModelOutput bridge
all-model migration
model retraining
model optimization
new research claims
```

D8 remains separate.

---

# 27. Validation

Use repository interpreter/tests and actual Ruff executable available in the environment.

Focused D7A target approximately:

```bash
python -m pytest -q \
  tests/decision/test_real_sr_plugin.py \
  tests/decision/test_state_rewarm.py \
  tests/decision/test_model_runtime.py
```

Also run the relevant SR tests for lifecycle/replay/config/state codec.

Then cumulative:

```bash
python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

When D7B is available, add its focused adapter/model parity tests.

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
AST/import boundary scan
cache cleanup
```

No external I/O.

---

# 28. Required adversarial probes before handoff

D7A coder must explicitly attempt and record:

```text
future/projected bar into SR adapter -> rejected
wrong encoded state/config identity -> rejected
missing ATR -> binding unavailable/fail closed, no SR step
malformed ATR -> invalid/fail closed
out-of-order replay -> rejected by D6/SR continuity
same state/bar/config twice -> deterministic identical proposal
abort then next LIVE without rewarm -> blocked
adapter artifact containing unsupported SR object -> contract rejects (regression guard)
```

D7B must attempt:

```text
legacy FeatureVector dependency in plugin path -> forbidden
stateless plugin proposes state -> rejected
wrong model decision identity -> rejected
```

---

# 29. Coder handoff

Update/create:

```text
plans/coder-to-orchestrator-decision-app-d7-representative-real-model-adapters-v1.md
```

Record:

```text
exact adapters added
exact core files changed (prefer none for SR core)
real feature definitions added
ModelSpec semantics
state encoding choice
SR direct-vs-runtime parity evidence
D6 state transaction evidence
D7B plugin-ready model source/refactor dependency
focused counts
cumulative counts
SR regression counts
Ruff/format/compile/diff/import evidence
Pass 1 correctness findings
Pass 2 scope findings
residual risks
```

If only D7A is completed, say so explicitly and terminate with:

```text
DECISION_APP_D7A_SR_REAL_ADAPTER_READY_FOR_REVIEW
```

Only after D7A + D7B pass use:

```text
DECISION_APP_D7_REPRESENTATIVE_REAL_MODEL_ADAPTERS_READY_FOR_REVIEW
```
