---
goal: Remediate D8 policy and finalization trust boundaries before D9
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d8, remediation]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# D8 trust-boundary remediation

Continue only in the existing cumulative worktree. D0-D7A remain approved. Do not start D9, add infrastructure, or commit/merge/push.

Independent review reproduced the green normal-path surface:

```text
D8 focused: 21 passed
tests/decision: 202 passed
non-research SR core subset: 394 passed
Ruff/format/diff/import boundary: passed
```

Four issues must be fixed before D8 approval.

## 1. BLOCKER — finalizer must validate the exact canonical signal envelope

`build_signal_envelope()` validates lane, prepared execution, policy result and `LaneMarketView` correctly. `LaneFinalizer.preflight_signal()` currently does not repeat that validation; it mostly checks the `decision_id`.

Independent probe showed that a caller-created envelope with the correct decision ID but different asset/timeframe/route/timestamp/price could receive a matching acknowledgement and still commit D6 state and advance the lane watermark.

Required fix:

- add one pure `validate_signal_envelope_against(...)` helper, or equivalent;
- inputs must include `ResolvedLanePlan`, `PreparedLaneExecution`, `DecisionPolicyEvaluation`, the exact `LaneMarketView`, and the envelope;
- simplest acceptable implementation is to rebuild the canonical envelope with existing `build_signal_envelope(...)` logic and require exact equality;
- `LaneFinalizer.preflight_signal()` / `finalize_signal()` must use that validation before a publication acknowledgement can authorize commit;
- D9 later must call the same pure preflight before its transport action.

This must cover all builder-owned semantics: route, stream entry ID, signal asset/timeframe/timestamp/direction/conviction/price/model_name/idempotency/metadata and payload fingerprint.

Add adversarial tests where envelope fields are changed and the payload fingerprint + acknowledgement are recomputed. At minimum prove a BTCUSDT/1h prepared lane cannot finalize an ETHUSDT/4h envelope carrying the same decision ID.

Preserve canonical `PUBLISHED` and `ALREADY_IDENTICAL` success behavior.

## 2. BLOCKER — do not manufacture conviction

The frozen D8 rule is:

```text
direction = selected ModelDecision.direction_hint
conviction = selected ModelDecision.conviction
```

Current code maps `decision.conviction is None` to `TradeSignal.conviction = 1.0`.

Independent probe confirmed a direction-bearing decision with `conviction=None` becomes maximum conviction `1.0`.

Required fix:

- do not change the legacy `TradeSignal` contract;
- because the legacy field is required numeric, `build_signal_envelope()` must fail closed when the selected decision has `conviction=None`;
- do not default to 1.0, 0.0, score, or a policy-derived value;
- explicit 0.0 must remain exactly 0.0; explicit 0.75 must remain 0.75.

Policy may still classify a direction-bearing no-conviction outcome as SIGNAL when no threshold forbids it; the compatibility envelope is the boundary that cannot represent it.

## 3. BLOCKER — DecisionPolicyCatalog must be immutable

The catalog currently stores a mutable dict. Independent review changed `passthrough@1` to priority semantics in place and obtained a different selected trade under the same decision ID.

Required fix:

- make the catalog immutable after construction, following D2/D5/D6 catalog precedent;
- immutable backing mapping;
- reject item mutation and attribute reassignment/deletion that changes catalog state;
- preserve exact lookup and deterministic construction;
- no new registry framework.

Policy name/version remain the semantic version identity; do not put object IDs or callable repr into decision identity.

Add a regression proving catalog semantics cannot change in place under one policy version/decision identity.

## 4. HIGH — FinalizationReceipt must reject contradictory evidence

Direct construction currently permits mismatched finalization cutoff, watermark cutoff/disposition, and state-commit receipt cutoff/disposition.

Strengthen `FinalizationReceipt.__post_init__`.

For `COMMITTED` require:

```text
state receipt lane == receipt lane
state receipt market_as_of == receipt market_as_of
state receipt disposition == receipt disposition
watermark.latest_market_as_of == receipt market_as_of
watermark.last_disposition == receipt disposition
published -> envelope exists
no_signal -> envelope is None
```

For `ABORTED` require:

```text
disposition is None
state_commit_receipt is None
watermark must not claim the aborted market_as_of as newly committed
```

A prior watermark earlier than the aborted cutoff is valid. Publication-failure abort may carry the attempted envelope; policy-failure abort may omit it.

Add direct-construction regressions for wrong lane/cutoff/disposition/watermark/envelope combinations.

## Preserve these semantics

Do not change:

```text
matching PUBLISHED         -> commit state -> watermark advance
matching ALREADY_IDENTICAL -> commit state -> watermark advance
matching CONFLICT          -> abort prepared -> watermark unchanged
matching FAILED            -> abort prepared -> watermark unchanged
ACK identity mismatch      -> hard fail before state mutation
success ACK + unexpected D6 commit failure -> hard invariant error, watermark unchanged
```

ACK mismatch is indeterminate; do not add automatic abort/retry behavior in D8.

## Scope

Prefer only:

```text
src/apps/decision_app/policy.py
src/apps/decision_app/publication.py
src/apps/decision_app/finalization.py
tests/decision/test_policy.py
tests/decision/test_publication_compat.py
tests/decision/test_finalization.py
coder D8 handoff
```

Touch shared contracts only if necessary for the existing `FinalizationReceipt` ownership. No D7B, Valkey, FastAPI, Docker, runtime worker, retry framework, or D9 work.

## Validation

Run:

```text
focused policy/publication/finalization tests
complete tests/decision
existing non-research SR gate used by D8
legacy/downstream risk compatibility tests
Ruff check
Ruff format --check
compileall
git diff --check
D8 import-boundary scan
cache cleanup
```

Two-pass review must explicitly verify:

```text
canonical envelope is revalidated before finalization
altered envelope cannot commit state
missing conviction never becomes a fabricated numeric value
policy catalog cannot change semantics in place
FinalizationReceipt is self-consistent
D2+D4+D5 identity stays unchanged
SR NO_SIGNAL path stays green
PUBLISHED/ALREADY_IDENTICAL stay green
CONFLICT/FAILED still abort correctly
no D9/infrastructure scope
```

Update:

```text
plans/coder-to-orchestrator-decision-app-d8-policy-finalization-downstream-compat-v1.md
```

Do not start D9 automatically.

Final line exactly:

```text
DECISION_APP_D8_POLICY_FINALIZATION_DOWNSTREAM_COMPAT_READY_FOR_REVIEW
```
