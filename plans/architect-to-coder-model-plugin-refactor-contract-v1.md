---
goal: Refactor existing quantitative models in parallel toward a clean model-owned core plus thin DecisionModelPlugin adapter contract without coupling model packages to decision_app runtime internals
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, model-refactor, plugin, parallel-worktrees, decision-app]
---

# Architect-to-coder — parallel model plugin-interface refactor contract

## 1. Purpose

This is the reusable contract for **parallel model refactor worktrees** while `decision_app` D7/D8/D9 continue independently.

The goal is not to make every model import `decision_app`.

The target architecture is:

```text
model package
├── model-owned deterministic core/domain
├── model-owned config/parameter validation
├── optional batch/research adapter
└── thin runtime plugin adapter
       implements libs.contracts.decision.DecisionModelPlugin
```

The model core remains reusable for:

```text
research
batch backtests
optimization
unit tests
offline studies
runtime plugin execution
```

without being owned by the application runtime.

---

# 2. Yes, parallel work is authorized

Model refactors may run in parallel with decision-app D7 if:

1. every model/family uses its own isolated worktree;
2. one writer owns each model package at a time;
3. model worktrees do not edit `src/apps/decision_app`;
4. the D7 worktree does not refactor the same model concurrently;
5. integration happens only after an explicit review/merge/integration decision.

Recommended worktree ownership:

```text
worktree A: model/momentum-plugin-refactor
worktree B: model/mean-reversion-plugin-refactor
worktree C: model/regime-classification-plugin-refactor
...

existing decision-app-d0 worktree:
  D7/D8 decision runtime only
```

Do not import files across worktrees by path.

---

# 3. Canonical runtime-facing interface

Every plugin-ready model exposes the shared structural protocol from:

```text
libs.contracts.decision.DecisionModelPlugin
```

Conceptually:

```python
class DecisionModelPlugin(Protocol):
    spec: ModelSpec

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: ModelState = None,
    ) -> Sequence[DataRequirement]: ...

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: ModelState = None,
    ) -> ModelOutcome: ...
```

Do not create a second competing plugin protocol per model family.

Do not subclass an application runtime base class.

Structural conformance is sufficient.

---

# 4. ModelSpec is the plugin's intrinsic contract

Each plugin must expose one explicit `ModelSpec` describing only intrinsic model semantics:

```text
name
version
stateful
output_kind
produces_artifact_type
supported_trigger_modes
supported_timeframes where genuinely intrinsic
supported_trigger_timeframes where genuinely intrinsic
intrinsic_feature_requirements
intrinsic_data_requirements
dependency_requirements
warmup_requirements
state_reconstruction
```

Do not put into `ModelSpec`:

```text
Redis keys
DB tables
HTTP URLs
scraper names
risk profile
position sizing
order type
asset-specific operator wiring
publication stream
service lifecycle
```

Asset/lane wiring remains application-owned.

---

# 5. Core vs adapter boundary

Preferred shape:

```text
src/libs/models/<model>/
  domain.py / core.py / model.py     # model semantics
  config.py                          # typed deterministic parameters
  batch.py                           # optional batch/research path
  adapters/
    decision_plugin.py               # thin shared-runtime adapter
```

Exact filenames may follow the existing model package if ownership is already clear.

The **core should not consume `DecisionContext` directly** unless the model is already naturally expressed as a pure semantic context object and doing so would not couple it to app-specific contracts.

Preferred adapter responsibility:

```text
DecisionContext
  -> model-owned typed input
  -> core.evaluate/step
  -> model-owned result
  -> ModelArtifact / ModelDecision / proposed_next_state
```

For a very small stateless model, the adapter and core may be one short class if splitting would be ceremony. Still keep imports/application ownership clean.

---

# 6. Forbidden core dependencies

Model core/domain modules must not import:

```text
apps.decision_app
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
redis
valkey
asyncpg
sqlalchemy
FastAPI
httpx
requests
aiohttp
scraper clients
DBPoolManager
runtime schedulers/workers
```

A plugin adapter may import:

```text
libs.contracts.decision
its own model package
pure feature/math utilities
```

No infrastructure client may be passed through `DecisionContext`.

---

# 7. Retire legacy runtime coupling, not useful research APIs

Many current models inherit:

```text
BaseModel
ScoringModel
```

and consume:

```text
FeatureVector
ModelOutput
ScoringOutput
ModelRegistry
```

These are legacy runtime-facing abstractions.

Refactoring should remove them from the **new plugin path**.

Do not necessarily delete them immediately if current research/backtest tooling still relies on them.

Preferred migration:

```text
model-owned core
   ↑              ↑
legacy adapter    DecisionModelPlugin adapter
(optional)        (new runtime)
```

Then legacy adapters can be retired later after cutover.

Do not make `FeatureVector` the internal universal model core contract.

---

# 8. Feature ownership

Model owns **semantic feature demand**.

Examples:

```text
FeatureRequirement("ATR")
FeatureRequirement("RSI")
FeatureRequirement("MACD")
FeatureRequirement("VOLATILITY")
```

The model does not choose the physical feature implementation class, cache, or app storage.

Decision rule:

```text
reusable across multiple models
  -> shared FeatureRequirement / app-owned shared definition

private, cheap, deterministic transform used only by one model
  -> keep inside model core/plugin
```

Do not push every arithmetic transform into the shared FeatureEngine.

Do not recreate one universal feature vector.

---

# 9. Bar/history ownership

Plugins receive bounded causal history through:

```text
DecisionContext.causal_bar_views
DecisionContext.decision_bar
```

Rules:

- no future bars;
- do not query BarStore directly;
- do not query Timescale directly;
- do not retain hidden mutable price history in stateless models;
- if the model is declared stateless, all needed history must come from context for every evaluation;
- warmup/history requirements must be explicit through `ModelSpec` and/or shared feature definitions.

Batch pandas DataFrames remain an offline adapter concern.

---

# 10. External data ownership

Models request semantic external data only through `DataRequirement`.

Examples:

```text
OPEN_INTEREST
BTC_DOMINANCE
LIQUIDATION_HEATMAP
ORDERBOOK_IMBALANCE
MARKET_BREADTH
```

Never request:

```text
table name
Redis key
URL
provider class
scraper implementation
```

`data_requests()` may select a subset of the plugin's declared `intrinsic_data_requirements`, but D6 requires exact requirement semantics for each returned concept.

Do not weaken requiredness/freshness/replay/alignment at runtime.

---

# 11. Dependency ownership

If one model semantically consumes another model's artifact, declare an intrinsic dependency slot:

```text
ModelDependencyRequirement(
  slot_name="boundary",
  artifact_type="boundary.v1",
)
```

The model adapter receives:

```text
DecisionContext.upstream_artifacts["boundary"]
```

It never names another binding ID itself.

Do not directly instantiate/call peer models inside a plugin.

Do not create cross-lane dependencies in V1.

---

# 12. Stateless model rules

A stateless plugin:

```text
spec.stateful = False
```

must satisfy:

```text
same context + same parameters -> same outcome
proposed_next_state == None
no evaluation-affecting mutable object state
```

Forbidden examples:

```text
self._rolling_buffer.append(...)
self._last_signal = ...
self._previous_value = ...
```

unless those values are non-semantic caches whose presence cannot change the result and are proven safe. Prefer avoiding them.

If rolling state changes output, the plugin is stateful or the rolling calculation must come from bounded context history.

---

# 13. Stateful model rules

A stateful model must make all evaluation-affecting state explicit:

```text
committed state_snapshot
  -> evaluate
  -> proposed_next_state
```

No hidden mutable deques/HMM state/regime state inside the plugin instance may affect output independently of `state_snapshot`.

State must be expressible using the D1 supported semantic vocabulary:

```text
None
bool/int/finite float/Decimal
str/bytes
datetime/timedelta
list/tuple -> frozen tuple
string-keyed mapping -> FrozenMapping
```

Custom model-domain objects should be encoded/projected deterministically, for example:

```text
canonical mapping
versioned JSON string
small immutable primitive tuple
```

Use existing model codecs where available.

Stateful specs require durable PIT reconstruction and all intrinsic external data requirements must be replay-support-required under the current D1/D2 contract.

---

# 14. Hidden mutable-state audit

Every model refactor must explicitly audit constructor/object fields that change during evaluation.

Search for patterns such as:

```text
deque
list append
rolling buffers
_prev_*
_last_*
state machine
HMM fitted object mutation
indicator.update
cached previous close
running variance
EMA internal state
```

Classify each:

```text
A. semantic runtime state
   -> move to explicit state_snapshot/proposed_next_state

B. derivable from bounded causal context
   -> remove hidden state and recompute deterministically

C. non-semantic performance cache
   -> prove output independence or remove initially
```

Do not label a model `stateless` while leaving category A hidden in the instance.

---

# 15. Output mapping

Every evaluation returns `ModelOutcome`.

Mandatory:

```text
artifact: ModelArtifact
```

Optional:

```text
decision: ModelDecision
proposed_next_state
```

Analytical model:

```text
output_kind="analytical"
decision=None
```

Decision/scoring model:

```text
output_kind="predictive" or "decision_capable"
```

may return a `ModelDecision` but does not publish it.

Never put authoritative:

```text
position size
leverage
portfolio exposure
order type
SL/TP ownership
```

into the core plugin decision contract.

Risk remains downstream.

---

# 16. Artifact identity

Choose one explicit versioned artifact type per plugin semantics, for example:

```text
momentum.signal.v1
mean_reversion.score.v1
sr.snapshot.v1
regime.probabilities.v1
```

Artifact values use only shared supported semantic values.

Do not expose model-domain objects directly if `deep_freeze` cannot validate them.

Project them into stable mappings/tuples/scalars.

Material artifact schema changes require version changes.

---

# 17. Decision semantics

`ModelDecision` is a model-level hint/output, not final lane policy.

Use:

```text
direction_hint = -1 | 0 | 1 | None
score = finite model-native score when meaningful
conviction = [0,1] when model has a defined confidence measure
```

Do not make scores from unrelated models implicitly comparable.

Do not add ensemble weighting to the model adapter.

D8 policy will own normalization/composition.

---

# 18. Config and parameters

All runtime-relevant model parameters must be deterministic and included through binding parameters/configuration so D2 binding identity changes when behavior changes.

Do not:

```text
read YAML during evaluate
read env vars during evaluate
use module globals as mutable config
load latest artifacts dynamically
pick defaults based on wall clock
```

Factory construction may validate/freeze parameters.

Training artifacts, if later required, need explicit immutable version/hash identity; do not add this speculatively during simple model refactors.

---

# 19. Batch/research preservation

The refactor must not destroy efficient existing batch paths merely because live runtime changed.

A model may keep:

```text
batch_evaluate(DataFrame)
NumPy/Numba kernels
optimization tooling
research metrics
```

but these should call/reuse the same semantic core where practical or have explicit parity tests.

Do not force D6 `DecisionContext` into batch optimization code.

---

# 20. Reference parity gate

Before changing model structure, freeze representative reference behavior from the current model on deterministic fixtures.

For simple stateless models, capture:

```text
inputs
parameters
model-native output
```

Then require plugin-ready core parity for:

```text
direction/score
conviction
important metadata
missing-input behavior
parameter boundary behavior
```

Do not use live provider data.

For a refactor that intentionally changes semantics, stop and classify it as a **model redesign**, not a plugin-interface refactor. That requires separate authorization/research evidence.

---

# 21. Recommended migration order

Current repo suggests this order based on complexity:

```text
Tier 1 — simple stateless rules
  Momentum
  TrendFollowing
  MeanReversion (after choosing clean score semantics)

Tier 2 — stateless but larger feature demand
  KyleTFI
  VPINKyle
  regime-relative/pullback scorers

Tier 3 — currently hidden mutable state
  DivergenceEdge
  SqueezeBreakout
  regime classification/HMM families

Tier 4 — complex research/latent state families
  regime_v2 / regime_prob_v1
  only after explicit architecture/research decision
```

SR is handled by D7A in the decision-app programme because it is the immediate real stateful runtime proof. Avoid a second SR refactor writer unless coordinated.

Trendline families remain governed by their separate migration/refactor programme; do not mix them into generic model-interface cleanup without explicit ownership.

---

# 22. Momentum first-refactor target

Momentum is the recommended first parallel model refactor.

Current legacy rule depends on:

```text
RSI
MACD histogram
optional MACD line sign gate
```

Target plugin semantics approximately:

```text
ModelSpec:
  stateful=False
  output_kind=decision_capable
  produces_artifact_type=momentum.signal.v1
  FeatureRequirement("RSI")
  FeatureRequirement("MACD")
  no external data
  no dependencies
```

Model core should own only the threshold decision math.

Adapter extracts the exact semantic RSI/MACD snapshot structure and creates `ModelArtifact`/`ModelDecision`.

Keep existing batch path initially if useful, but parity-test it against the new core on fixtures.

Do not have the core construct `FeatureVector`.

---

# 23. MeanReversion target

Current MeanReversion is a continuous scoring model using:

```text
RSI
BB position
KAMA/ATR deviation
ADX scaling
```

Target:

```text
stateful=False
output_kind=predictive or decision_capable
artifact=mean_reversion.score.v1
```

Preserve model-native continuous edge score.

Do not threshold it into final trade direction merely to fit the plugin.

A `ModelDecision` may carry score/conviction with `direction_hint=None` if that best preserves semantics; D8 policy can interpret/normalize later.

---

# 24. Stateful legacy-model caution

Models like SqueezeBreakout/DivergenceEdge currently maintain internal rolling buffers.

Do not simply wrap those classes as `stateful=True` while leaving buffers hidden.

Refactor must first extract a versioned explicit state mapping.

Example:

```text
SqueezeState
  close_buffer
  high_buffer
  low_buffer
  delta_buffer
  previous_momentum...
```

represented as supported immutable semantic state.

The plugin instance itself should then be behaviorally immutable across evaluations.

If this is too invasive, defer the model rather than weakening D6 state guarantees.

---

# 25. Regime/HMM caution

Regime classification families may contain fitted HMM objects and incremental statistical state.

Before plugin migration distinguish:

```text
trained immutable model artifact
vs
runtime evolving state
```

Do not retrain in live `evaluate()`.

Runtime evolving HMM/filter state must be explicit/replayable if it affects output.

Training/calibration remains offline.

Do not migrate these models until that boundary is explicit.

---

# 26. Tests every model refactor must add

At minimum:

```text
plugin satisfies DecisionModelPlugin
ModelSpec identity exact
factory parameters immutable/validated
no app/infrastructure imports in core
same fixture -> same output
reference parity with pre-refactor behavior
binding-visible feature isolation
no undeclared external data
artifact identity correct
stateless proposed_next_state=None
stateful state is explicit and immutable
wrong/missing input fails closed according to spec
```

For stateful models additionally:

```text
same state + same causal input -> same proposal
proposal does not mutate input state
replay sequence deterministic
hidden-state audit regression
```

---

# 27. No silent semantic changes

A plugin-interface refactor must preserve model behavior unless the user explicitly authorizes redesign.

Examples of semantic changes that require separate research approval:

```text
new thresholds
new indicators
new feature normalization
new regime gates
new ensemble weights
new lookback
new trade direction logic
new state transition logic
```

Do not hide these inside cleanup.

---

# 28. No overengineering

Do not create:

```text
ModelAdapterBase
PluginBase
GenericFeatureTranslator
UniversalModelInput
UniversalModelResult
ProviderAwareModel
ModelService
ModelActor
ModelDAG
ModelContextBuilder framework
adapter registry separate from existing explicit runtime catalog
```

A few small repeated explicit adapters are preferable until real common structure is proven.

---

# 29. Worktree process

For each model/family:

1. create isolated worktree from the intended reviewed base;
2. write a model-specific `architect-to-coder` child handoff referencing this master contract;
3. freeze pre-refactor behavior fixtures;
4. refactor one model/family only;
5. run focused model tests;
6. run shared plugin contract tests;
7. run affected compatibility tests;
8. Ruff/format/compile/diff/import scan;
9. produce coder-to-orchestrator handoff;
10. stop before merge.

Do not bulk-refactor all model families in one enormous branch.

---

# 30. Child handoff template

Every model-specific plan should state:

```text
model/family
current legacy runtime dependencies
current hidden mutable state audit
intended stateful/stateless classification
semantic feature requirements
semantic external data requirements
dependencies/artifact types
model output_kind
reference parity fixtures
production files allowed
production files forbidden
focused tests
compatibility tests
terminal status
```

Suggested terminal status pattern:

```text
<MODEL>_PLUGIN_INTERFACE_REFACTOR_READY_FOR_REVIEW
```

---

# 31. Decision-app integration gate

A model is **plugin-ready** only when the orchestrator has approved:

```text
clean ModelSpec
DecisionModelPlugin conformance
no hidden semantic state
no physical I/O ownership
reference parity
supported semantic state/output vocabulary
import boundaries
focused tests
```

Only then should D7/D9 register it into a decision runtime composition.

Do not integrate a model merely because it has a method named `evaluate`.

---

# 32. Final architectural rule

The future system should read conceptually:

```text
decision_app owns:
  causal scheduling
  bars
  shared features
  external data resolution
  dependency execution
  state transaction ownership
  policy/publication

model plugin owns:
  quantitative semantics
  intrinsic feature/data/dependency demand
  model-native artifact/decision
  proposed explicit state
```

That boundary is the purpose of this refactor programme.

Do not collapse it back into either:

```text
models that own infrastructure
```

or:

```text
decision_app that contains model-specific quantitative logic
```
