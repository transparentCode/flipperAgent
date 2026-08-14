---
goal: Remediate D5 DataResolver determinism and resolution trust-boundary defects without starting D6
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d5, data-resolver, remediation]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D5 DataResolver remediation

## 1. Objective and evidence

D5 is functionally close and the submitted suite is green, but independent adversarial review found one production-behavior blocker plus two trust-boundary/spec-alignment issues that must be resolved before D6 consumes `DataResolution`.

Continue in the existing isolated cumulative worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not commit, merge, push, switch branches, reset, restore, or start D6.

Independent validation before remediation:

```text
D1-D5 compatibility: 147 passed
Ruff check: passed
Ruff format: passed
git diff --check: passed
D5 infrastructure boundary: clean
```

The remediation must preserve all already-correct D5 behavior:

```text
DataPlan self-integrity
exact binding demand validation
canonical request-key validation
PIT/freshness/alignment rules
LIVE cache -> PIT -> at most one live ordering
REPLAY PIT-only enforcement
candidate contract corruption fail-closed
ordinary source error fallthrough
cancellation propagation
binding isolation
shared snapshot reuse
no model execution or infrastructure
```

Expected terminal status after remediation:

```text
DECISION_APP_D5_DATA_RESOLVER_LIVE_REPLAY_READY_FOR_REVIEW
```

---

## 2. BLOCKER — binding requiredness leaks into the physical source request

### Current defect

`required` is intentionally excluded from canonical physical request identity, which is correct. However `DataResolver.resolve()` currently groups equivalent requests and selects the **first input request object** as the representative passed to the source fetcher:

```python
first = entries[0][1]
...
unique_requests[request_key] = first
```

Because `DataRequest.required` remains on that object, reversing otherwise equivalent required/optional binding requests changes the source-facing request despite the same physical request key.

Direct independent proof:

```text
Binding A: OPEN_INTEREST required=True
Binding B: OPEN_INTEREST required=False
same canonical request_key
```

A synthetic source that returns a snapshot only when `request.required is True` produced:

```text
required-first:
  source saw required=True
  shared snapshot present
  A available=True
  B available=True

optional-first:
  source saw required=False
  shared snapshot absent
  A available=False
  B available=True
```

This violates D5 hard principles:

```text
equivalent requests share one physical acquisition/result
source precedence/result is deterministic
requiredness is binding availability semantics, not physical request identity
```

It also makes `DataResolution.requests[request_key].required` input-order dependent.

### Required remediation

Before any source call, materialize a **canonical shared physical request representation** whose source-visible fields are independent of binding request ordering.

Do not add a generic request framework.

Preferred simple options:

1. clone the representative `DataRequest` with a fixed neutral requiredness (recommended: `required=False`) for shared physical acquisition/evidence; or
2. introduce one very small internal helper that canonicalizes equivalent requests by stripping/normalizing only `required`.

Binding-specific required/optional semantics must remain only in the binding request/evidence path.

The canonical shared request must preserve exactly:

```text
request_key
concept
asset/scope
market_as_of
mode
resolver_knowledge_cutoff
replay_support_required
freshness_bound
max_available_lag
alignment
```

The source fetcher must receive identical `DataRequest` semantics for the same request key regardless of binding request order.

Do not change the request-key payload to include `required`.

### Required regressions

Add tests proving:

```text
required-first vs optional-first batch
  -> same request key
  -> source called once in both
  -> source receives identical DataRequest in both
  -> same shared snapshot/unavailable result
  -> same DataResolution.requests mapping
  -> binding A/B availability remains binding-local
```

Use an adversarial source that branches on `request.required`; the test must still produce identical physical behavior after canonicalization.

Also test permutation of three bindings with the same physical request.

---

## 3. HIGH — `BindingDataResolution` cannot self-validate required vs optional classification

### Current defect

`BindingDataResolution` stores:

```text
requested_request_keys
missing_required_requests
missing_optional_requests
```

but does not retain the binding-specific required/optional request partition.

Therefore a directly constructed D5 output can relabel missingness while still passing validation.

Independent proof:

```text
DataRequest.required=True
BindingDataResolution marks same key as missing_optional
=> accepted; binding reports available=True

DataRequest.required=False
BindingDataResolution marks same key as missing_required
=> accepted; binding reports available=False
```

The resolver's normal path currently creates correct values, but D6 is intended to trust `DataResolution` as the complete D5 boundary. Follow the D4 precedent: exported resolution contracts should reject contradictory construction rather than rely on one producer implementation.

### Required remediation

Keep the output small. Add enough immutable binding-local request classification to self-validate requiredness.

Recommended shape:

```text
BindingDataResolution
  binding_id
  requested_request_keys
  required_request_keys
  optional_request_keys
  available
  snapshots
  missing_required_requests
  missing_optional_requests
```

Equivalent compact representation is acceptable if it gives the same guarantees.

Invariants:

```text
required_request_keys and optional_request_keys disjoint
required U optional == requested
snapshot keys subset requested
missing_required subset required
missing_optional subset optional
present and missing disjoint
every requested key exactly classified as present or missing
available iff missing_required is empty
```

The resolver must construct these fields from the original per-binding `DataRequest.required` values, not from the canonical shared request's normalized requiredness.

Do not add model objects or DataPlan objects to the output merely for validation.

### Required regressions

Reject direct construction where:

```text
required key is placed in missing_optional
optional key is placed in missing_required
required/optional partitions overlap
partition omits a requested key
partition contains unrequested key
```

Preserve valid required/optional dedup case.

---

## 4. HIGH — attempt evidence may contradict shared/unavailable outcome

### Current defect

`DataResolution.__post_init__` currently validates that attempt evidence covers every request, but does not validate outcome consistency.

Independent proofs currently accepted:

```text
shared snapshot exists
attempts = [MISS]
=> accepted

request unavailable
attempts = [ACCEPTED]
=> accepted
```

This makes audit/replay evidence untrustworthy even though the normal resolver producer currently emits sensible attempts.

### Required remediation

Add minimal deterministic attempt/final-result consistency checks in `DataResolution.__post_init__`.

For a shared snapshot:

```text
attempt tuple must be non-empty
exactly one ACCEPTED outcome
ACCEPTED must be the final attempt
accepted attempt source == snapshot.source
no attempts after ACCEPTED
```

For an unavailable request:

```text
no ACCEPTED attempt is permitted
empty attempts are allowed only for an explicitly empty route/no_allowed_source case
```

Avoid inventing a rich failure taxonomy. Existing stable reasons are enough.

`DataSourceAttempt` itself may also validate obvious outcome/reason contradictions if this stays simple, but do not build an evidence framework.

### Required regressions

Reject:

```text
shared snapshot + only MISS
shared snapshot + ACCEPTED followed by later attempt
shared snapshot + accepted source != snapshot.source
unavailable + ACCEPTED
more than one ACCEPTED
```

Accept:

```text
MISS -> REJECTED -> ACCEPTED
ERROR -> ACCEPTED
MISS/REJECTED/ERROR only -> unavailable
empty attempts + no_allowed_source -> unavailable
```

---

## 5. MEDIUM/HIGH — source kind and resolved capability are unnecessarily conflated

### Current implementation

`DataSourceDefinition.__post_init__` currently forces:

```text
cache => LIVE_ONLY
live  => LIVE_ONLY
```

and `ResolvedConceptDataRoute` repeats the same restriction.

### Approved D5 contract

The approved handoff deliberately modeled these as separate dimensions:

```text
kind: cache | pit | live
capability: LIVE_AND_REPLAY | LIVE_ONLY
```

Eligibility is mode-specific:

```text
REPLAY route:
  kind must be pit
  capability must be LIVE_AND_REPLAY
```

So cache/live source **kind** being ineligible for REPLAY does not itself imply that a snapshot obtained during LIVE can never carry `LIVE_AND_REPLAY` capability.

This matters for `replay_support_required=True`: a LIVE cache can legitimately contain a snapshot whose underlying data is reconstructable/durable and therefore replay-safe. The current restriction forces every replay-required LIVE request to reject all cache candidates, creating unnecessary PIT I/O and conflating transport/source kind with data replay capability.

### Required remediation

Restore the approved separation:

```text
DataSourceDefinition.kind validates only cache|pit|live
DataSourceDefinition.capability validates only LIVE_AND_REPLAY|LIVE_ONLY
```

Do not force cache/live capability to `LIVE_ONLY` at registration.

Continue enforcing hard REPLAY route rules exactly:

```text
kind == pit
capability == LIVE_AND_REPLAY
```

Continue validating candidate snapshot capability equals source-definition capability.

This does **not** mean REPLAY may call cache/live. It may not.

### Required regressions

Prove:

```text
cache + LIVE_AND_REPLAY source definition is valid
live + LIVE_AND_REPLAY definition is valid if explicitly configured
REPLAY route containing cache LIVE_AND_REPLAY still rejected because kind != pit
REPLAY route containing live LIVE_AND_REPLAY still rejected because kind != pit
LIVE replay_support_required request may accept a LIVE_AND_REPLAY cache candidate
LIVE replay_support_required rejects LIVE_ONLY candidate and falls through
```

If coder finds a concrete contradiction with an approved D0/D5 invariant, stop and report rather than silently retaining the current restriction.

---

## 6. Scope

Prefer modifications only to:

```text
src/apps/decision_app/data.py
tests/decision/test_data_policy.py
tests/decision/test_data_resolver.py
plans/coder-to-orchestrator-decision-app-d5-data-resolver-live-replay-v1.md
```

`src/libs/contracts/decision.py` should not need changes unless a focused test proves otherwise.

Do not modify D4 FeaturePlan/FeatureEngine.
Do not add D6 model runtime/context assembly.
Do not add real cache/PIT/live adapters.

No new production module is required for this remediation.

---

## 7. Non-goals

Do not implement:

```text
DecisionModelPlugin.data_requests() invocation
DecisionModelPlugin.evaluate()
DecisionContext assembly
model dependency execution
state/state commit/rewarm
DecisionPolicy
publication
Valkey/Redis
Timescale adapters
HTTP/scraper clients
FastAPI
Docker
AssetRuntime
background workers
retry/backoff/timeouts
persistent resolver cache
cross-lane dedup
D6
```

---

## 8. Validation

Run focused D5 first:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_data_policy.py \
  tests/decision/test_data_resolver.py
```

Then cumulative compatibility:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then:

```bash
ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
git diff --check
```

Repeat the infrastructure-boundary scan from the D5 handoff.
Remove generated `__pycache__` directories after validation.

### Minimum new adversarial evidence

```text
required/optional request input permutations -> identical physical source request/outcome
binding required/optional missingness relabel rejected
attempt/final-result contradictions rejected
LIVE_AND_REPLAY cache accepted in LIVE but never callable in REPLAY
```

Perform two self-review passes:

1. PIT/determinism/fail-closed correctness;
2. simplicity/scope/overengineering.

---

## 9. Coder handoff update

Update the existing:

```text
plans/coder-to-orchestrator-decision-app-d5-data-resolver-live-replay-v1.md
```

Record:

```text
files/symbols changed
physical-request canonicalization choice
binding required/optional self-validation evidence
attempt consistency evidence
source-kind/capability separation evidence
new focused test count
new cumulative compatibility count
Ruff/format/compile/diff/import results
Pass 1 findings
Pass 2 findings
residual risks
```

No commit/merge/push.
No D6.

Final line exactly:

```text
DECISION_APP_D5_DATA_RESOLVER_LIVE_REPLAY_READY_FOR_REVIEW
```
