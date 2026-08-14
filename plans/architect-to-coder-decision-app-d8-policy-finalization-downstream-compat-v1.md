---
goal: Implement D8 lane-local DecisionPolicy, complete authoritative decision identity, deterministic legacy TradeSignal compatibility, and publication/state/watermark finalization semantics without starting runtime infrastructure
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d8, policy, finalization, publication-compat, risk-compat]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D8 DecisionPolicy, finalization, and downstream compatibility

## 1. Starting point

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved programme state:

```text
D0 architecture freeze                         APPROVED
D1 semantic contracts                          APPROVED
D2 static composition planner                  APPROVED
D3 causal market state                         APPROVED
D4 shared FeaturePlan / FeatureEngine           APPROVED
D5 semantic DataResolver LIVE/REPLAY             APPROVED
D6 ModelRuntime + state transaction + rewarm    APPROVED
D7A real stateful SR adapter                    APPROVED
D7B real stateless decision adapter             DEFERRED
```

D7B is not a blocker for D8 architecture. Use synthetic decision-capable plugins for signal-policy tests and the approved real SR adapter for real-model no-signal/state-finalization proof. Do not create a legacy `FeatureVector` bridge merely to obtain D7B coverage.

Do not commit, merge, push, switch branches, reset, restore, or start D9.

Expected terminal status:

```text
DECISION_APP_D8_POLICY_FINALIZATION_DOWNSTREAM_COMPAT_READY_FOR_REVIEW
```

---

# 2. D8 objective

D8 closes the **offline decision-to-downstream boundary** without adding real runtime I/O.

Target flow:

```text
D6 PreparedLaneExecution
        ↓
DecisionPolicy
        ↓
DecisionPolicyEvaluation
        ↓
final authoritative decision identity
        ↓
zero or one lane decision
        ├───────────────────────┐
        │                       │
     NO_SIGNAL                SIGNAL
        │                       │
        │                 pure legacy compatibility
        │                 SignalPublicationEnvelope
        │                       │
        │                 D9 later performs XADD
        │                       │
        │                 PublicationAck supplied
        │                       │
        └──────────────┬────────┘
                       ↓
                 DecisionFinalizer
                       ↓
              D6 commit_prepared()
                       ↓
              LaneCommitWatermark advance
```

D8 must prove:

1. policy selection/gating is lane-local and deterministic;
2. the final authoritative identity incorporates D2 + D4 + D5 material semantics;
3. zero or one authoritative signal intent exists per lane/as-of;
4. state proposals are committed only after final no-signal disposition or successful/idempotent publication acknowledgement;
5. publication conflict/failure leaves the lane watermark unchanged and forces D6 state rewarm through `abort_prepared()`;
6. legacy risk compatibility uses explicit **epoch seconds**, never seconds/ms guessing;
7. legacy `TradeSignal.model_name` carries the stable configured `risk_profile_key`, while contributing plugin identities remain provenance;
8. the actual Valkey publisher/read loop remains D9.

---

# 3. Hard architecture rules

Preserve these rules exactly:

```text
one lane -> zero or one policy decision at one market_as_of
risk sizing / SL / TP / exposure / order type remain downstream
policy never calls model.evaluate()
policy never resolves data/features
policy never performs I/O
publication identity is deterministic
market identity is market_as_of, never decision_ready_at
decision_ready_at is operational timing only
model raw scores are never implicitly compared
state commit follows final publication/no-signal disposition
LaneCommitWatermark advances only after D6 state commit succeeds
```

Do not add:

```text
generic workflow engine
policy DAG
rules DSL
actor framework
persistent transaction log
outbox framework
retry/backoff framework
Valkey client
Timescale client
FastAPI
Docker
AssetRuntime
input consumer
PriceRelay
real scheduler
real clock abstraction framework
```

A tiny explicit policy catalog and tiny in-memory finalization owner are sufficient.

---

# 4. Scope

Prefer production changes limited to:

```text
src/apps/decision_app/contracts.py            additive D8 output/finalization contracts
src/apps/decision_app/identity.py             additive final decision identity helpers
src/apps/decision_app/policy.py               policy definitions/catalog/engine
src/apps/decision_app/publication.py          pure compatibility envelope/ack helpers only
src/apps/decision_app/finalization.py         no-I/O state + watermark finalization
```

Minimal additive D6 exposure is allowed only if needed to preflight an already-approved prepared transaction before publication. Do not redesign D6.

Tests preferably:

```text
tests/decision/test_policy.py
tests/decision/test_publication_compat.py
tests/decision/test_finalization.py
```

Update existing identity/contracts/runtime tests only where additive D8 semantics require it.

No `configs/decision` in D8.

---

# 5. Important D8 distinction — model fusion vs DecisionPolicy

Do **not** turn DecisionPolicy into a second model framework.

V1 policy may select/gate existing `ModelDecision` values. If future composition requires genuine weighted mathematical fusion of model artifacts/scores, that belongs in an explicit decision-capable/fusion plugin wired through D2 dependencies.

Therefore D8 V1 policy should support only small non-ambiguous strategies that do not invent score comparability.

Required built-ins:

## 5.1 Passthrough policy

```text
policy name/version: explicit stable values
parameter: source_slot
```

Semantics:

- source slot must exist in the resolved lane;
- source binding must have `BindingExecutionResult.status == EXECUTED`;
- if its `ModelOutcome.decision` is present, select that exact `ModelDecision`;
- if its decision is absent, produce a final `NO_SIGNAL` result;
- unavailable/blocked/invalid source binding is **not** a no-signal; it is policy `BLOCKED`/`INVALID` and cannot advance the watermark.

## 5.2 Explicit priority policy

```text
parameters:
  source_slots: ordered unique list
  optional min_conviction per slot or one explicit global threshold
```

Semantics:

- evaluate configured slots in declared order only;
- select the first EXECUTED binding with a non-None ModelDecision satisfying the explicit threshold;
- EXECUTED + decision=None means that source contributes no candidate and evaluation continues;
- source binding UNAVAILABLE/BLOCKED may be treated according to one explicit policy parameter only if specified; default fail closed for required priority sources;
- INVALID always fails closed;
- if all valid executed sources produce no decision, final `NO_SIGNAL`;
- do not compare raw scores;
- do not synthesize a new ModelDecision from multiple models.

Keep this intentionally small. Do not add weighted-vote, optimizer, calibration, or policy inheritance unless an existing approved model requires it now. It does not.

---

# 6. Policy registry

Add a small app-owned explicit catalog, separate from model plugin catalogs.

Conceptually:

```text
DecisionPolicyDefinition
  name
  version
  evaluator/factory

DecisionPolicyCatalog
  exact (name, version) registration
  duplicate rejection
  deterministic order
  no discovery/import scanning
```

The resolved lane already owns:

```text
policy_name
policy_version
policy_parameters
```

The D8 engine must resolve exactly those values.

Policy callable identity/repr is not authoritative identity.

---

# 7. Policy evaluation contract

`DecisionPolicyResult` alone cannot distinguish a genuine final no-signal from a blocked/invalid policy evaluation. Add one small wrapper, approximately:

```text
DecisionPolicyEvaluation
  status:
    SIGNAL
    NO_SIGNAL
    BLOCKED
    INVALID
  result: DecisionPolicyResult | None
  selected_binding_id: optional
  contributing_binding_ids: tuple
  reason: optional stable code/text
```

Rules:

```text
SIGNAL   -> result exists and result.decision exists
NO_SIGNAL -> result exists and result.decision is None
BLOCKED/INVALID -> result is None
```

No finalization/watermark on BLOCKED or INVALID.

Policy evaluation must not mutate `PreparedLaneExecution` or D6 state.

---

# 8. Complete authoritative decision identity

D2's `ResolvedLanePlan.effective_lane_revision` remains the **static lane/policy configuration revision**. Do not redefine it.

D8 introduces one additive final revision, use a clear name such as:

```text
decision_execution_revision
```

Compute canonically from material execution semantics:

```text
lane_id
D2 effective_lane_revision
D4 feature_plan_fingerprint
D5 data_plan_fingerprint
policy name
policy version
normalized policy parameters
```

Policy information is already represented by D2, but include the normalized policy identity explicitly here as defensive self-description; this remains deterministic and avoids hidden assumptions.

Use existing canonical SHA-256 helper.

Then:

```text
decision_id = decision_id(
    lane_id=lane_id,
    lane_revision=decision_execution_revision,
    market_as_of=market_as_of,
)
```

Do not include:

```text
decision_ready_at
wall clock
factory repr/object address
publication attempt count
transport response
```

Changing D4/D5 fingerprints must change the final decision identity even when the D2 lane revision is unchanged.

Add a pure helper such as:

```text
compute_decision_execution_revision(...)
```

and self-validation tests.

---

# 9. Extend DecisionPolicyResult minimally

Add explicit fields necessary to make the D8 boundary trustworthy. Prefer additive fields such as:

```text
base_lane_revision               # D2 effective_lane_revision
decision_execution_revision      # final D2+D4+D5+policy revision
feature_plan_fingerprint
data_plan_fingerprint
policy_name
risk_profile_key
```

Existing `effective_lane_revision` may remain as a compatibility alias/name for the D2 base revision if changing it would create unnecessary churn. Do not silently change its meaning.

Self-validation must prove:

```text
lane_id matches prepared identity
base revision matches D6 identity
feature/data fingerprints match D6 identity
policy name/version matches resolved lane
decision_id recomputes from final decision_execution_revision + market_as_of
binding_config_fingerprints exactly cover resolved lane bindings
decision_ready_at >= market_as_of
if decision exists:
  decision belongs to an EXECUTED binding in the prepared result
  exact outcome.decision equals selected decision
  decision market_as_of == policy market_as_of
```

Do not copy full model artifacts into the policy result.

---

# 10. `decision_ready_at`

D8 must not call `datetime.now()` inside policy logic.

Require the caller to supply an aware UTC:

```text
decision_ready_at
```

Validate:

```text
decision_ready_at >= market_as_of
```

It may appear in operational output metadata but must never affect:

```text
policy selection
decision_execution_revision
decision_id
TradeSignal idempotency identity
model inputs
```

Tests must prove changing only `decision_ready_at` leaves policy decision and decision ID unchanged.

---

# 11. State-commit eligibility gate

Before a policy outcome can be considered **finalizable**, D8 must respect D6 lane-level state transaction semantics.

If configured stateful bindings exist and:

```text
prepared.state_commit_eligible == False
```

then D8 must not prepare authoritative publication and must not finalize no-signal.

Return/raise an explicit blocked finalization condition and ensure any D6 pending state proposal is later aborted rather than left unresolved.

Do not publish a signal that cannot be followed by the required lane-level state commit.

---

# 12. Pure legacy TradeSignal compatibility adapter

D8 must create the current downstream `TradeSignal` shape without using Redis.

Input should include at least:

```text
ResolvedLanePlan
PreparedLaneExecution
DecisionPolicyResult with decision
LaneMarketView for the exact same lane/as-of
```

Validate all identities/cutoffs before projection.

## 12.1 Signal route

For an authoritative lane:

```text
stream_key = signals:{asset}:{decision_timeframe}
```

Reject publication-envelope creation for `authority != authoritative` in D8 V1.

## 12.2 Timestamp

This is a hard compatibility gate.

Current risk worker does:

```python
wall_now = time.time()
wall_now - signal.timestamp
```

Therefore D8 legacy `TradeSignal.timestamp` MUST be explicitly:

```text
market_as_of epoch seconds (float)
```

Never milliseconds.
Never infer based on magnitude.
Never reuse old ambiguous conversion helpers.

Add metadata/provenance:

```text
timestamp_unit = "seconds"
market_as_of_utc = canonical UTC text
```

The canonical D8 policy/model contracts remain UTC datetime; only this legacy adapter converts to epoch seconds.

## 12.3 Price

`TradeSignal.price` is the causal lane decision price:

```text
LaneMarketView.decision_bar.close
```

Validate the view's lane identity and `market_as_of` exactly match the prepared/policy result.

For projected decision bars, this is the causal projected close at market_as_of, never the unobserved future bucket close.

## 12.4 Direction/conviction

Copy from the selected `ModelDecision` only:

```text
direction = direction_hint
conviction = conviction
```

A final SIGNAL requires a non-None direction hint and it must be `-1` or `1` for legacy TradeSignal publication. Treat `0`/None as no tradable signal rather than publishing a flat trade.

Do not translate score into direction or conviction.

## 12.5 Risk profile compatibility

Current risk profile resolution uses:

```text
TradeSignal.model_name
```

For decision_app publication set:

```text
TradeSignal.model_name = resolved_lane.risk_profile_key
```

This is deliberate compatibility naming, not model ownership.

Include actual contributing model information in metadata:

```text
selected_binding_id
selected_slot
selected_plugin_name
selected_plugin_version
contributing_binding_ids
contributing_plugin_names
decision_id
decision_execution_revision
base_lane_revision
feature_plan_fingerprint
data_plan_fingerprint
risk_profile_key
policy_name
policy_version
```

No constituent model should impersonate the lane risk profile.

## 12.6 Risk metadata features

Current risk logic optionally consumes `signal.metadata["ATR"]` for ATR-based sizing/SL.

Do not copy arbitrary shared features into TradeSignal metadata.

For D8 V1, allow a tiny explicit compatibility whitelist:

```text
ATR
```

Only export ATR when it is present in the **selected binding's** D4 feature resolution and is a finite positive numeric scalar.

If ATR is absent, omit it. Current risk code already has defined fallback behavior. Do not manufacture ATR.

Preserve bar high/low in metadata only as bounded compatibility/observability fields if already useful:

```text
bar_high
bar_low
```

Do not move SL/TP logic upstream.

---

# 13. Signal idempotency and deterministic publication envelope

Do not reuse the legacy strategy idempotency key based only on model/asset/timeframe/timestamp because it omits D4/D5 identity.

Create a deterministic D8 helper based on the authoritative decision identity, e.g.:

```text
signal_idempotency_key = SHA-256("decision-signal" + decision_id)
```

Use full stable hash or a clearly versioned deterministic representation. Do not use Python hash.

Create a pure immutable envelope, approximately:

```text
SignalPublicationEnvelope
  decision_id
  stream_key
  stream_entry_id
  signal: TradeSignal
  payload_fingerprint
```

`payload_fingerprint` is canonical over the semantic TradeSignal payload.

For D8 V1 stream entry identity use one deterministic explicit Valkey-compatible timestamp ID per lane/as-of:

```text
stream_entry_id = <market_as_of epoch milliseconds>-0
```

Rules:

- derive from canonical `market_as_of` only;
- no wall clock;
- zero/one authoritative signal per lane/as-of makes `-0` sufficient within its stream;
- do not call XADD in D8.

D9 will use this envelope to implement lookup/compare/XADD idempotency.

---

# 14. Publication acknowledgement contract

Add a tiny immutable acknowledgement supplied by the future D9 publisher:

```text
SignalPublicationAck
  decision_id
  stream_key
  stream_entry_id
  payload_fingerprint
  outcome:
    PUBLISHED
    ALREADY_IDENTICAL
    CONFLICT
    FAILED
  reason optional
```

Semantics:

```text
PUBLISHED         -> finalization may commit state
ALREADY_IDENTICAL -> idempotent success; finalization may commit state
CONFLICT          -> fail closed, abort D6 prepared state, watermark unchanged
FAILED            -> abort D6 prepared state, watermark unchanged
```

Ack must match the exact prepared envelope identity/fingerprint. A success ack for another payload is rejected.

No retries in D8.

---

# 15. No-signal finalization

A genuine policy `NO_SIGNAL` is a final disposition.

Sequence:

```text
PreparedLaneExecution
  -> policy NO_SIGNAL
  -> preflight finalization
  -> D6 commit_prepared(..., disposition="no_signal")
  -> LaneCommitWatermark advances to market_as_of / no_signal
```

No publication envelope exists.

Use the approved D7A SR real adapter to prove this path with real encoded state:

```text
SR causal rewarm
  -> prepare next LIVE SR step
  -> passthrough policy sees analytical decision=None
  -> final NO_SIGNAL
  -> state commit
  -> watermark advance
```

Verify SR state advances exactly one trigger and no signal envelope is produced.

---

# 16. Signal finalization

For SIGNAL:

```text
PreparedLaneExecution
  -> policy SIGNAL
  -> publication envelope
  -> external publisher returns matching ack
  -> only PUBLISHED / ALREADY_IDENTICAL are success
  -> D6 commit_prepared(..., disposition="published")
  -> LaneCommitWatermark advances to market_as_of / published
```

D8 does not call the publisher itself unless using a tiny injected test seam with no infrastructure. Prefer explicit separate steps so D9 can own transport.

On `CONFLICT`/`FAILED`:

```text
D6 abort_prepared(prepared, reason)
LaneCommitWatermark unchanged
stateful transition-bearing bindings DEGRADED
next LIVE state transition requires causal rewarm
```

For stateless lanes the watermark still remains unchanged on publication failure.

---

# 17. Pre-publication state-commit preflight

A signal must not be published when its D6 prepared state transaction is already stale/invalid.

If D6 currently lacks a small public pure check, add one minimal method such as:

```text
validate_prepared_commit(prepared) -> None
```

It may expose the existing approved D6 validation logic without mutation.

Before envelope handoff/publication, D8 finalization preparation must verify:

```text
prepared is the current pending D6 transaction where stateful
identity matches
state_commit_eligible
exact next cutoff still valid
base state records are current
```

Do not commit state before publication.

Do not add generic transaction versions/locks.

D9's worker will execute publication and immediate finalization serially.

---

# 18. LaneCommitWatermark owner

D8 is the first phase allowed to advance the lane commit watermark.

Use one very small in-memory owner, approximately:

```text
LaneFinalizer
  current LaneCommitWatermark
```

or equivalent pure input/output API.

Rules:

```text
watermark lane_id == resolved lane
first finalization allowed at any valid prepared cutoff
later market_as_of must advance strictly
watermark advances only after D6 commit receipt succeeds
last_disposition exactly published | no_signal
BLOCKED/INVALID policy -> unchanged
publication FAILED/CONFLICT -> unchanged
```

Do not persist it in D8. D9 restart/runtime reconstruction will own persistence/reconstruction semantics.

Repeated attempt at a cutoff already committed must not rerun stateful evaluation. D8 should reject stale finalization inputs. D9 input/watermark gating handles retries before evaluation.

---

# 19. Atomicity ordering

D0 requires:

```text
publication success/no-signal final disposition
  -> state commit
  -> watermark advance
```

Implement exactly this order.

Before performing the irreversible publication in D9, D8 provides all pure preflight validation possible. In D8 tests, a matching success ack represents the irreversible publication step.

After success ack:

1. validate ack/envelope/result/prepared coherently;
2. call D6 `commit_prepared()`;
3. only if commit succeeds, advance the watermark.

Never advance watermark first.

If commit unexpectedly fails after a success ack, raise a hard finalization error and leave watermark unchanged. Do not pretend the transaction is complete. Record this as an invariant breach for D9 operational handling; do not build a recovery framework in D8.

---

# 20. Authoritative vs shadow lanes

D8 V1 publication envelope creation is authoritative-only.

```text
authoritative -> SIGNAL may produce legacy publication envelope
shadow         -> cannot produce authoritative signals:* envelope
```

Policy evaluation itself may remain usable for shadow/research comparisons.

Do not add a new shadow commit disposition in D8. D11 may use an explicit shadow sink/finalization harness after reviewing concrete shadow-state needs. Do not reopen the D1 `CommitDisposition` vocabulary speculatively.

---

# 21. Failure handling

Freeze simple behavior:

```text
policy source UNAVAILABLE/BLOCKED -> PolicyEvaluation BLOCKED
policy source INVALID             -> PolicyEvaluation INVALID
bad policy config                 -> fail closed
bad DecisionPolicyResult identity -> fail closed
bad LaneMarketView identity       -> fail closed
non-tradable direction 0/None     -> NO_SIGNAL, not TradeSignal
missing/invalid risk_profile_key on authoritative lane -> fail closed
publication ack mismatch          -> fail closed
publication CONFLICT/FAILED       -> abort prepared; no watermark advance
```

Do not silently downgrade INVALID to NO_SIGNAL.

---

# 22. Tests — policy

Use synthetic prepared executions and existing D6 fixtures.

Cover:

```text
exact policy catalog resolution
unknown/duplicate policy failure
passthrough selects exact ModelDecision
passthrough analytical decision=None -> NO_SIGNAL
passthrough unavailable/blocked -> BLOCKED
passthrough invalid -> INVALID
priority deterministic ordered selection
priority no raw-score comparison
priority all executed/no decisions -> NO_SIGNAL
priority invalid source fail closed
policy input order does not affect configured priority order
policy result complete binding fingerprints
decision_ready_at change does not change selection or identity
```

No model evaluation inside policy tests unless using D6 fixture to produce the prepared object first.

---

# 23. Tests — final identity

Prove:

```text
same D2/D4/D5/policy/as_of -> same decision_execution_revision + decision_id
D4 fingerprint change -> decision_execution_revision changes
D5 fingerprint change -> changes
D2 lane revision change -> changes
policy name/version/params change -> changes
market_as_of change -> decision_id changes
decision_ready_at change -> decision_id unchanged
wall clock never enters identity
```

Tampered direct construction must fail where contracts carry recomputable identity.

---

# 24. Tests — legacy TradeSignal compatibility

Cover:

```text
signal stream key = signals:{asset}:{decision_tf}
authoritative lane only
TradeSignal.timestamp == market_as_of.timestamp() epoch SECONDS
no ms magnitude guessing
metadata timestamp_unit == seconds
price == exact causal LaneMarketView.decision_bar.close
projected bar uses causal projected close
model_name == lane.risk_profile_key
selected/contributing actual plugin identities remain metadata
idempotency changes when decision execution revision changes
stream_entry_id deterministic from market_as_of ms + -0
same decision -> same payload fingerprint/envelope
ATR exported only from selected binding when valid
ATR absent -> omitted, not fabricated
invalid ATR -> fail closed or omit according to one explicit safe rule; prefer fail closed if present-but-malformed
bar_high/bar_low deterministic if included
flat/None direction -> no publication envelope
```

Add a compatibility assertion against current risk staleness semantics showing epoch seconds are the expected unit:

```text
wall_now_seconds - signal.timestamp_seconds
```

Do not modify risk_app in D8.

---

# 25. Tests — finalization

Cover both stateful and stateless lanes.

## Real SR no-signal proof

Use D7A:

```text
rewarm SR
prepare next step
policy NO_SIGNAL
state remains uncommitted before finalizer
finalize_no_signal
SR encoded state advances exactly one step
LaneCommitWatermark advances with no_signal
no publication envelope
```

## Synthetic signal proof

```text
D6 prepared decision
policy SIGNAL
build envelope
matching PUBLISHED ack
state commit succeeds
watermark advances published
```

Also:

```text
ALREADY_IDENTICAL ack -> same success semantics
CONFLICT -> D6 abort + watermark unchanged
FAILED -> D6 abort + watermark unchanged
ack wrong decision_id -> reject before state mutation
ack wrong payload fingerprint -> reject
commit stale after ack -> hard error, watermark unchanged
policy BLOCKED/INVALID -> watermark unchanged
state_commit_eligible=False -> no publication/no finalization
second watermark cutoff <= current -> reject
no partial watermark/state mutation on preflight failure
```

---

# 26. D7B interaction

Do not implement D7B inside D8.

If a reviewed plugin-ready Momentum (or other stateless decision model) becomes available during D8, do not merge/refactor it opportunistically unless explicitly instructed. D8 synthetic signal tests are sufficient for architecture.

Record carry-forward:

```text
D7B remains required before production shadow/cutover confidence is complete,
but it is not required to freeze D8 policy/publication semantics.
```

---

# 27. Infrastructure/import boundary

D8 production modules may use standard library plus approved app/shared contracts.

Must not import/instantiate:

```text
redis
valkey
asyncpg
sqlalchemy
httpx
requests
aiohttp
FastAPI
DBPoolManager
ConfigManager
ingestion runtime
risk worker
execution worker
strategy_app publisher
```

It is acceptable to import the **shared `TradeSignal` contract** for the legacy compatibility projection. Do not import strategy_app runtime/publication code.

Do not call `valkey_encode` in D8 unless a pure payload-fingerprint test proves necessary; prefer canonicalizing the TradeSignal semantic dict directly.

---

# 28. Validation

Use the repository interpreter and actual Ruff executable available in the environment.

Run focused D8 first:

```text
tests/decision/test_policy.py
tests/decision/test_publication_compat.py
tests/decision/test_finalization.py
```

Then cumulative:

```text
tests/decision
relevant D7A SR boundary tests
tests/commons/test_model_runtime_contract.py
tests/models/test_strategy_model_v2.py
```

Also run current risk compatibility tests relevant to:

```text
risk profile resolver
signal staleness/timestamp expectations
ATR sizing/stop-loss metadata behavior
```

Do not alter risk behavior merely to make D8 pass.

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
AST/import boundary scan
repo-local __pycache__ cleanup
```

No Docker, broker, database, network, or live market operation in D8.

---

# 29. Two-pass coder self-review

## Pass 1 — correctness

Explicitly verify:

```text
policy status vs final no-signal distinction
selected binding identity
final D2+D4+D5 decision identity
risk_profile_key compatibility
seconds timestamp compatibility
causal price projection
ATR metadata ownership
publication ack identity
state commit ordering
watermark ordering
publication failure -> abort
real SR no-signal state progression
```

## Pass 2 — architecture/simplicity

Verify:

```text
no policy framework overengineering
no raw score fusion
no model execution in policy
no real publisher/client
no risk semantics moved upstream
no D9 runtime loop
no D7B legacy bridge
no duplicated identity system
no mutable/unbounded artifact copying
```

---

# 30. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d8-policy-finalization-downstream-compat-v1.md
```

Record:

```text
files/symbols changed
policy strategies implemented
policy evaluation status semantics
decision_execution_revision payload
DecisionPolicyResult additive fields
legacy TradeSignal timestamp unit proof
risk_profile_key/model_name compatibility proof
ATR compatibility metadata rule
signal idempotency + stream entry identity
publication ack contract
real SR no-signal finalization evidence
synthetic signal success/failure finalization evidence
watermark/state ordering evidence
focused/cumulative/risk compatibility counts
Ruff/format/compile/diff/import results
Pass 1 findings
Pass 2 findings
residual risks
D7B deferred status
```

Do not claim actual Valkey publication. D9 owns transport/runtime integration.

Do not start D9 automatically.

Final line exactly:

```text
DECISION_APP_D8_POLICY_FINALIZATION_DOWNSTREAM_COMPAT_READY_FOR_REVIEW
```
