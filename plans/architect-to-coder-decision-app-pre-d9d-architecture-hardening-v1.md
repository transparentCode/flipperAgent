---
goal: Restore the original D0 failure-isolation invariant and certify decision_app engineering simplicity before PriceRelay/D9D, while removing model-specific orchestration leakage and proven compatibility/dead surface without integrating any new model plugin
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, architecture, hardening, anti-overengineering, pre-d9d]
---

# Architect-to-coder — `decision_app` pre-D9D architecture hardening / anti-overengineering certification

## 1. Starting point

Use only the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved before this package:

```text
D0-D9C
D7A representative SR adapter
```

D9D / PriceRelay has **not** started.

The user has explicitly frozen model integration for now:

```text
DO NOT add any new model plugin.
DO NOT refactor/integrate Momentum or any other legacy model into decision_app.
Model-family refactors/integration will happen later, before actual integration.
```

Preserve the existing SR representative adapter as reviewed evidence. Do not alter SR mathematics, model outputs, thresholds, lifecycle semantics, or artifact content. The only permitted SR-related change in this package is moving the already-required SR initialization-horizon registration out of generic startup orchestration and into the existing explicit composition seam.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

Do not start D9D automatically.

---

# 2. Why this package exists

The programme-level architecture/anti-overengineering audit found that the macro architecture remains healthy:

```text
one decision_app process
explicit static plugin catalog
no model-per-process runtime
no actor/workflow/general DAG framework
no FeatureVector foundation
no PEL / consumer groups for decision input
no local HTF aggregation
no direct model infrastructure access
no risk / sizing / execution ownership creep
bounded BarStore
checkpoint-only decision DB writes
zero decision_app internal import cycles
one market task + one lifecycle task
```

However, before adding PriceRelay there is one material D0 drift and a bounded set of engineering-debt items worth correcting.

The objective is **not** to optimize for a LOC target.

The objective is:

```text
remove unnecessary concepts,
remove compatibility guessing,
remove duplicate ownership,
restore original failure isolation,
keep every causal / transaction / PIT invariant intact.
```

Do not broadly remove validation. Do not split large files merely because they are large. Do not introduce a generic validation/helper framework to deduplicate small local checks.

---

# 3. Blocking architecture correction — restore D0 failure isolation

## 3.1 Original invariant

D0 froze:

```text
lane failure / degradation
    must not roll back InputReadCursor
    must not stop healthy input streams
    must not stop unrelated lanes
    must not stop future PriceRelay
```

D9B itself largely satisfies this: a failed lane/series is marked fail-closed while independent streams/lanes can continue.

D9C subsequently added whole-generation automatic rebuild when any poll returns `RECONSTRUCTION_REQUIRED`.

That creates this current behavior:

```text
Lane A -> RECONSTRUCTION_REQUIRED
        ↓
DecisionService -> REBUILDING
        ↓
whole market loop stops while fresh generation is built
        ↓
Lane B and healthy streams stop too
```

Independent review reproduced that the old generation performs no further market polls while the generation rebuild is blocked.

This is simpler than lane-local recovery, but it violates the original failure-isolation contract and would also stop future PriceRelay.

## 3.2 Selected correction

Do **not** add a lane-recovery worker, task, queue, actor, supervisor, or generic recovery framework in this package.

Use the smaller design:

```text
D9B returns lane/input RECONSTRUCTION_REQUIRED
        ↓
DecisionService records DEGRADED evidence
        ↓
NO automatic whole-generation rebuild
        ↓
failed lane / blocked stream remains fail-closed
        ↓
same D9B generation continues poll_once()
        ↓
healthy streams continue
healthy unrelated lanes continue
```

Generation-wide rebuild remains allowed only for:

```text
1. authoritative lifecycle reconciliation
2. explicit manual resume/reconnect
3. initial startup
```

This restores isolation by **deleting automatic causal generation rebuilding**, not by replacing it with another subsystem.

A lane that requires reconstruction may remain `RECONSTRUCTION_REQUIRED` until a later explicit rebuild boundary. It must never resume from stale state automatically.

Manual `reconnect()` remains the explicit recovery tool and reconstructs from durable D9A inputs/checkpoints with publication suppressed.

A lifecycle reconciliation may also rebuild from current authoritative manifests.

## 3.3 Service simplification

Because causal automatic generation rebuild is removed, simplify D9C state accordingly.

Remove if no longer required:

```text
CAUSAL_RECONSTRUCTION RebuildSource
_auto_rebuild_attempted
one-shot causal rebuild budget logic
queued causal rebuild request branches
related error strings/tests that exist only for global causal auto-rebuild
```

Keep only the minimum rebuild distinction necessary for:

```text
LIFECYCLE_RECONCILIATION
MANUAL
```

If an even smaller representation is possible without losing correctness, use it. Do not keep a three-kind framework for a removed behavior.

## 3.4 Required isolation proof

Use at least two independent market streams / lanes.

Example:

```text
Lane A depends on series A
Lane B depends on series B
both initially LIVE
```

Cause series/lane A to return `RECONSTRUCTION_REQUIRED` while B remains valid.

Prove:

```text
generation_id unchanged
service_state = DEGRADED
Lane A = RECONSTRUCTION_REQUIRED
Lane A watermark unchanged
series A cursor does not move past unsafe record

next healthy series B record is still read
series B InputReadCursor advances
Lane B evaluates/finalizes normally
Lane B watermark advances
no generation_factory call caused by Lane A reconstruction
```

If A and B share the same blocked canonical series, it is correct that both dependents are affected. The proof must use truly independent series so isolation is meaningful.

Then prove:

```text
manual reconnect
    -> fresh D9A generation
    -> generation_id advances
    -> affected lane can recover only if durable causal history/manifests are safe
```

Do not silently recover stale state inside the old lane.

---

# 4. Remove model-specific behavior from generic startup

## 4.1 Confirmed leak

Generic:

```text
src/apps/decision_app/startup.py
```

currently imports:

```text
libs.models.sr.config.SRConfigResolver
```

and contains:

```text
if binding.plugin_name == "sr":
    ...
```

for first-inception state initialization horizon.

That violates the ownership rule:

```text
model/integration owns intrinsic semantic initialization demand
decision_app startup owns generic reconstruction mechanics
```

It would invite future branches such as:

```text
if plugin == squeeze
if plugin == divergence
if plugin == regime
```

before model refactors are complete.

## 4.2 Existing seam to use

The repository already has exactly the correct small runtime seam:

```text
RuntimePluginDefinition.initialization_requirement
RuntimePluginCatalog.initialization_for(binding)
```

Do not add another registry/protocol.

Move the existing SR-specific requirement construction into the **existing explicit composition/integration seam** (for example `composition.py`) where SR is already explicitly registered.

It is acceptable for that explicit composition seam to know the currently reviewed SR adapter/config resolver. Generic startup/runtime/planner/service code must not.

After the change:

```text
DecisionStartupCoordinator._initialization_for(binding)
    -> RuntimePluginCatalog.initialization_for(binding)
    -> requirement or fail closed
```

No plugin-name branch.

If a stateful binding has no registered initialization requirement:

```text
StartupLaneError / fail closed
```

Do not invent a default horizon.

Do not add or integrate any other model.

---

# 5. Exact-contract cleanup — remove compatibility guessing

Production code currently contains several branches that accept multiple hypothetical client/factory shapes, mainly to tolerate flexible test doubles.

Examples include:

```text
inspect.signature(generation_factory)
0 / 1 / 2 positional argument fallbacks
keyword vs positional generation factory invocation

try:
    redis_call(... keyword form ...)
except TypeError:
    redis_call(... alternate positional form ...)

multiple local _maybe_await helpers allowing sync or async fakes
```

This weakens the original exact-contract rule.

## 5.1 GenerationFactory

Select one exact callable contract.

Prefer the simplest ordinary async callable, e.g. conceptually:

```text
async generation_factory(reason: str, generation_id: int)
    -> DecisionRuntimeGeneration
```

Use exactly one invocation shape everywhere.

Remove production `inspect.signature()` and arity guessing.

Update test factories to implement the exact contract.

Do not create a factory base class or generic invocation adapter.

## 5.2 Valkey/async boundaries

Use the actual installed async Valkey API contract consistently.

Production decision code should call the selected methods in one shape only:

```text
xread
xrange
xrevrange
xadd
```

Remove `except TypeError -> retry alternate signature` compatibility branches where they only support alternate fake/client invocation forms.

Update fakes to match the production API instead.

Likewise, where a repository boundary is explicitly async (`publish`, checkpoint `save/load`, generation factory, stream reads), use `await` directly rather than accepting synchronous stand-ins through local `_maybe_await` / `_await` wrappers.

Do **not** change the semantic behavior of ambiguous XADD reconciliation or exact-ID publication.

Do not alter Valkey protocol semantics.

## 5.3 Production dependency strictness

`build_generation_factory()` is the production composition seam.

It must not silently create a D9B runtime without a signal publisher merely because the supplied stream client lacks publication methods.

Require the production stream client to satisfy the market-input + signal-publication operations needed by the generation.

Construct `ValkeySignalPublisher` unconditionally after that validation.

Fail construction clearly if required production methods are absent.

Low-level `LiveDecisionRuntime` may retain narrow dependency injection useful for focused unit tests if needed; the **production factory** must not silently downgrade itself into a test configuration.

Do not add a formal transport interface hierarchy just for this check.

---

# 6. Remove proven dead aliases only

Do not conduct a broad API-minification exercise.

Remove aliases/wrappers that independent scan showed have no callers outside their definition/export.

At minimum review and remove when still unused:

```text
identity.py
  compute_binding_config_fingerprint = binding_config_fingerprint
  compute_effective_lane_revision = effective_lane_revision
  compute_decision_execution_identity = compute_decision_execution_revision
  make_decision_id = decision_id

live_input.py
  LiveInputReader = DirectCursorInput

model_runtime.py
  DecisionModelRuntime = ModelRuntime
  LaneModelRuntime = ModelRuntime
```

Also review these zero/near-zero convenience aliases and remove only if no real caller remains:

```text
ModelRuntime.rewarm_causally()  # startup can use rewarm() directly
FeaturePlan.feature_history_requirements property
evaluate_lane_readiness() functional wrapper
```

Keep meaningful domain types, error types, test fixtures, and explicit public contracts merely having few current callers.

Do not set a target for number of exports.

Do not rename working canonical types just to reduce vocabulary.

---

# 7. Remove the 50 ms service wake polling fallback

Current `DecisionService._wait_for_wake()` uses:

```text
asyncio.wait_for(_wake_event.wait(), timeout=0.05)
```

This causes periodic wakeups while PAUSED/ERROR/REBUILDING even when no state change occurred.

The existing service already sets `_wake_event` for relevant transitions:

```text
pause/resume/reconnect
rebuild request
stop
lifecycle request
```

Use event-driven waiting instead of a 20 Hz polling fallback.

Conceptually:

```text
await _wake_event.wait()
_wake_event.clear()
```

Preserve stop/cancellation semantics.

Add a deterministic test proving a paused/error market loop does not repeatedly spin/poll in the absence of a wake event, and that manual reconnect/stop still wakes it.

Do not add another condition variable, timer, scheduler, or backoff framework.

---

# 8. Do NOT over-correct validation duplication

The architecture audit found repeated small helpers such as:

```text
_require_non_empty
_normalize_names
_freeze_string_map
field identity validation
```

Do **not** respond by creating:

```text
validation_utils.py
BaseValidatedContract
GenericDomainValidator
UniversalFreezer
ValidatedBaseModel hierarchy
```

Small repeated local validation is preferred to a new cross-module abstraction.

Only consolidate logic when it represents one genuine canonical domain operation with repeated semantic implementation, not merely repeated syntax.

No broad validation deletion.

No mass conversion between dataclasses/Pydantic models.

No file splitting solely for line count.

---

# 9. Freeze dormant infrastructure; do not expand it

## 9.1 DataResolver

`data.py` is a substantial semantic subsystem, but production composition currently has no physical external-data sources.

Do not delete it in this package: it implements the already-frozen D0 semantic-demand/PIT/replay contract and future reviewed models may need it.

But do not add:

```text
new source kinds
new physical source implementations
new policy DSL
new retry/caching framework
new concepts
new scraper integration
```

Keep it frozen.

## 9.2 State codec

The state codec supports the semantic state vocabulary already frozen for future stateful model refactors:

```text
None
bool / int / finite float / Decimal
str / bytes
datetime / timedelta
list / tuple
string-key mapping
```

Do not shrink that vocabulary merely because current SR state uses a versioned string.

Do not expand it either.

No custom-object serialization framework.

---

# 10. Config ownership

Do not add new configuration knobs in this package.

Current production construction already consumes:

```text
decision.live_input.batch_size
decision.live_input.block_ms
decision.signal_publication.stream_maxlen
decision.signal_publication.stream_approximate
feature_policy when configured
```

Preserve these as production authority.

Do not add config for:

```text
reconstruction retry count
recovery worker count
wake polling interval
lane recovery queue
model integration
PriceRelay
```

The lifecycle read batch size may remain a small implementation bound unless there is existing config ownership; do not invent a user knob merely because a literal exists.

Do not add production decision asset YAML.

---

# 11. Architecture documentation refresh

Update the current architecture docs only where they are now materially stale.

At minimum refresh:

```text
docs/architecture/decision_app/README.md
```

The current header still says D0-only/future runtime and describes an `AssetRuntime` as though a concrete runtime object must exist.

Document accurately:

```text
D0 remains the frozen architecture contract
implementation currently exists through approved D9C
asset availability semantics are implemented through manifest gating + runtime generations/lanes
there is no requirement to create a concrete AssetRuntime actor/class
configs/decision/global.yaml exists
production configs/decision/assets/*.yaml remain intentionally absent until reviewed models are refactored/integrated
lane-local RECONSTRUCTION_REQUIRED remains fail-closed in-place; it does not trigger a whole-generation automatic rebuild
manual reconnect and authoritative lifecycle reconciliation are current full-generation reconstruction boundaries
PriceRelay remains next and not implemented
```

Do not rewrite historical phase handoffs.

Do not change D0's core failure-isolation invariant to legitimize the previous D9C simplification.

---

# 12. Permanent anti-overengineering / architecture guardrails

Add one small focused static regression file, e.g.:

```text
tests/decision/test_architecture_guardrails.py
```

Keep it simple AST/text inspection; do not create a generic repository-lint framework.

Prove at minimum:

## 12.1 App boundaries

Production `src/apps/decision_app` must not import production runtime code from:

```text
apps.ingestion_app
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
```

Shared contracts/common libraries remain allowed.

## 12.2 Legacy runtime patterns absent

Decision production source must not reintroduce:

```text
FeatureVector
ModelManager
ScoringModelManager
UnifiedModelManager
SignalRuntimeRunner
StrategyRuntimeRunner
```

## 12.3 No decision PEL/consumer-group machinery

For decision market/lifecycle input, production source must not contain calls for:

```text
xreadgroup
xack
xautoclaim
xgroup
```

Do not forbid direct `xread`.

## 12.4 No dynamic plugin discovery

Production decision source must not use broad dynamic model discovery mechanisms such as:

```text
pkgutil
importlib-based package scanning
entry_points model discovery
```

Explicit composition/catalogs remain required.

## 12.5 Generic orchestration is model-agnostic

Generic modules such as:

```text
startup.py
live_runtime.py
model_runtime.py
service.py
planner.py
data.py
```

must not import `libs.models.*`.

The explicit production composition seam is allowed to register the currently reviewed representative model integration. No new model is added in this package.

Also assert no generic orchestration branch of the form:

```text
if binding.plugin_name == "<model>"
```

for model-specific behavior.

## 12.6 Exact factory contract

Production service code must not use `inspect.signature()` / factory arity guessing after cleanup.

Do not freeze implementation details that PriceRelay legitimately needs next (for example do not permanently forbid `price_update`).

---

# 13. Required behavioral regression matrix

Add focused tests covering all of these, not only static scans.

## 13.1 D0 failure isolation restoration

```text
lane A reconstruction-required
lane B healthy and independent
same generation continues
B input cursor advances
B evaluation/finalization continues
generation_factory not called for A failure
A state/watermark never advances stale
```

## 13.2 Manual recovery

```text
service DEGRADED due A reconstruction-required
manual reconnect
fresh generation built
historical replay publication suppressed
no stale decision publication
```

## 13.3 Lifecycle still authoritative

```text
same degraded generation
configured lifecycle notification
fresh generation reconciliation still occurs
current manifest authority remains decisive
```

## 13.4 Hard faults unchanged

```text
MALFORMED / CONFLICT / INVALID / HALTED
    -> no automatic whole-generation causal rebuild
    -> service remains operator-visible degraded/error as already frozen
```

## 13.5 Exact production composition

Prove generic startup has no SR special-case and production runtime catalog provides the SR initialization requirement through the explicit registration seam.

No new model registration.

## 13.6 Exact async transport contracts

Focused fakes implement the one canonical async signatures and all D9A/D9B/D9C transport/publication behavior remains green.

## 13.7 Event-driven service sleep

Prove no periodic 50 ms wake loop is required for pause/error/control behavior.

---

# 14. Validation

Run focused hardening tests first.

Then at minimum:

```text
complete tests/decision
D9A startup/reconstruction surface
D9B live-input/live-runtime/signal transport surface
D9C service/lifecycle/API surface
D8 policy/publication/finalization/downstream compatibility
D7A representative SR adapter/runtime/replay surface
relevant non-research SR core/config/lifecycle/replay/serialization tests
commons config/connections/asset-manifest tests
canonical ingestion lifecycle/outbox/provenance/HTF contract tests
risk/signal compatibility slice
```

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
trailing whitespace
new architecture-guard test
AST production import boundary
no `inspect.signature` in decision production runtime
no decision PEL / consumer-group calls
no generic-module `libs.models.*` import
no model-specific branch in generic orchestration
no D9D / PriceRelay implementation leakage
repo-local __pycache__ cleanup
```

Also run a no-network import smoke test for all production decision modules.

Record before/after structural inventory, but **do not use a numeric LOC reduction as acceptance criterion**:

```text
production LOC
module count
internal import-cycle count
removed alias count
removed compatibility branches
long-lived task creation sites
```

The expected direction is less compatibility/conceptual surface, but correctness wins over line-count reduction.

Local Timescale/Valkey is not required merely for this hygiene package. If the worktree still lacks `.env`, record the existing environment gate. Do not create/copy credentials or mutate external/shared runtime state.

---

# 15. Two-pass coder self-review

## Pass 1 — architecture/correctness

Explicitly verify:

```text
D0 lane-failure isolation restored
healthy streams/lanes continue after unrelated reconstruction-required lane
no stale state continuation
manual reconnect remains publication-suppressed reconstruction
lifecycle reconciliation still rebuilds from current manifests
PIT/time/identity semantics unchanged
D8 exact-ID publication unchanged
checkpoint ordering unchanged
InputReadCursor and LaneCommitWatermark independence unchanged
no new model behavior
no model-specific generic orchestration
```

## Pass 2 — anti-overengineering

Verify:

```text
no lane recovery worker/task/queue added
no new supervisor/actor/framework
no generic validation utility hierarchy
no dynamic plugin discovery
no multiple-signature factory adapter
no sync-or-async compatibility wrappers where exact async contract exists
proven dead aliases removed
no large file split done only for aesthetics
DataResolver not expanded
state codec not expanded
no new config knobs
no PriceRelay
no new model plugin
no production decision asset YAML
```

---

# 16. Handoff back to orchestrator

Create/update:

```text
plans/coder-to-orchestrator-decision-app-pre-d9d-architecture-hardening-v1.md
```

Record:

```text
files/symbols changed
D0 failure-isolation before/after behavior
removed causal whole-generation auto-rebuild state/branches
healthy-lane continuation proof
manual reconnect proof
lifecycle-reconciliation proof
generic startup model-decoupling evidence
exact factory/Valkey async contract cleanup
removed dead aliases inventory
event-driven wake evidence
architecture guardrail test inventory
config ownership evidence
architecture doc refresh summary
before/after structural metrics
focused/cumulative compatibility counts
static/import/no-network/cache evidence
local infrastructure availability
Pass 1 findings
Pass 2 findings
residual risks
PriceRelay/D9D carry-forward
```

Do not claim:

```text
PriceRelay implemented
automatic lane-local reconstruction implemented
new model plugins integrated
production decision graph configured
resource certification complete
shadow parity complete
cutover readiness
```

Do not start D9D automatically.

Final line exactly:

```text
DECISION_APP_PRE_D9D_ARCHITECTURE_HARDENING_READY_FOR_REVIEW
```
