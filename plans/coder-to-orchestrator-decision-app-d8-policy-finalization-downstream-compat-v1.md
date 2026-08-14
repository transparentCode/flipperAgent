---
goal: Implement D8 lane-local policy, deterministic decision finalization, and pure downstream signal compatibility
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d8, policy, finalization, compatibility]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D8 policy/finalization handoff

## Scope and starting state

D0 through D7A were present and approved in the cumulative isolated worktree.
D7B remains deliberately deferred. This change stayed offline and pure: no
Valkey, Timescale, HTTP, publication client, runtime loop, Docker, or D9 work
was added. The worktree remains uncommitted and on detached `HEAD` at:

```text
4fc0de62515112dc371e08a6cde503746c54f7f7
```

No commit, merge, push, branch switch, reset, or restore was performed.

## Files and symbols

Implemented/extended:

```text
src/apps/decision_app/identity.py
  compute_decision_execution_revision
  compute_decision_execution_identity

src/apps/decision_app/contracts.py
  DecisionPolicyResult D8 identity/provenance fields and self-validation

src/apps/decision_app/model_runtime.py
  ModelRuntime.validate_prepared_commit

src/apps/decision_app/policy.py
  DecisionPolicyDefinition
  DecisionPolicyCatalog
  DecisionPolicyEvaluation
  DecisionPolicy
  PASSTHROUGH_V1 / PRIORITY_V1

src/apps/decision_app/publication.py
  SignalPublicationEnvelope
  SignalPublicationAck
  build_signal_envelope
  validate_signal_envelope_against
  signal_idempotency_key
  signal_payload_fingerprint

src/apps/decision_app/finalization.py
  FinalizationReceipt
  LaneFinalizer
```

Focused coverage was added in:

```text
tests/decision/test_policy.py
tests/decision/test_publication_compat.py
tests/decision/test_finalization.py
```

The existing plugin-boundary assertion was narrowed to distinguish pure
plugin-facing contracts from the app-owned D8 contract module; the
infrastructure-import prohibition remains enforced for all covered modules.

## Policy semantics

The explicit catalog resolves exact `(name, version)` registrations and rejects
duplicates/unknown registrations. V1 supports only:

```text
passthrough
priority
```

Passthrough selects one executed binding. Priority scans the configured ordered
slots and applies only explicit conviction thresholds; it never compares raw
scores or performs mathematical fusion. Policy evaluation returns exactly one
of:

```text
SIGNAL / NO_SIGNAL / BLOCKED / INVALID
```

An analytical SR result with no decision is proven as a genuine final
`NO_SIGNAL`, not as a blocked or invalid result. Invalid policy configuration,
unavailable sources, non-tradable directions, and ineligible state commits fail
closed according to the D8 status contract.

## Final decision identity

`decision_execution_revision` is a canonical SHA-256 fingerprint over:

```text
lane_id
D2 effective lane revision
D4 feature_plan_fingerprint
D5 data_plan_fingerprint
policy name/version
normalized policy parameters
```

`decision_id` derives from that final revision and `market_as_of`. The policy
result validates the complete identity when D8 fields are supplied. Changing
any material D2/D4/D5/policy input changes the execution revision; changing
only `decision_ready_at` does not. `decision_ready_at` is required to be aware
UTC and at or after `market_as_of`, but never enters identity or model inputs.

## Downstream compatibility envelope

`build_signal_envelope` is pure and authoritative-lane-only. It validates the
prepared execution, exact lane/view/result identity, executed selected binding,
and state-commit eligibility before constructing the legacy `TradeSignal`.

The compatibility evidence is:

```text
stream key       signals:{asset}:{decision_timeframe}
timestamp        market_as_of epoch seconds, explicitly marked as seconds
price            exact causal LaneMarketView.decision_bar.close
model_name       resolved lane risk_profile_key
idempotency      deterministic SHA-256 derived from decision_id
entry ID         market_as_of epoch milliseconds + "-0"
ATR              exported only from selected binding, finite and positive
```

The adapter performs the explicit Decimal-to-legacy-float conversion only at
this boundary and does not import strategy/risk runtime code. Selected and
contributing plugin identities remain bounded metadata; risk-profile identity
is not impersonated by a constituent plugin. No XADD or other transport call is
made.

## Publication acknowledgement and finalization

`SignalPublicationAck` accepts only exact envelope identity and payload
fingerprint matches. `PUBLISHED` and `ALREADY_IDENTICAL` are success outcomes;
`CONFLICT` and `FAILED` abort the prepared D6 state and leave the watermark
unchanged. Ack mismatch fails before state mutation.

The D8 trust-boundary remediation added four fail-closed protections:

- `LaneFinalizer.preflight_signal()` now rebuilds the canonical envelope from
  the resolved lane, prepared execution, policy evaluation, and exact causal
  `LaneMarketView`; an internally self-consistent envelope for another asset or
  timeframe cannot authorize commit or watermark advancement.
- A selected decision with missing conviction is rejected at the legacy
  compatibility boundary; no numeric conviction is manufactured.
- `DecisionPolicyCatalog` uses an immutable backing mapping and rejects item or
  attribute mutation, so policy semantics cannot change under one identity.
- `FinalizationReceipt` self-validates committed cutoff, lane, disposition,
  state-receipt, watermark, and envelope evidence, while aborted receipts may
  only carry an earlier watermark and no committed disposition/state receipt.

`LaneFinalizer` enforces the approved ordering:

```text
policy final disposition / matching publication acknowledgement
    -> D6 commit_prepared
    -> LaneCommitWatermark advance
```

No-signal finalization uses `disposition="no_signal"`. Successful signal
finalization uses `disposition="published"`. The watermark is strictly
advancing, in-memory only, and never advances on blocked/invalid policy,
publication failure/conflict, stale cutoff, or commit-preflight failure.

The real SR adapter proves causal rewarm, one subsequent prepared transition,
analytical `NO_SIGNAL`, encoded state commit, one-step cutoff advancement, and
absence of a publication envelope. Synthetic decision-capable plugins prove
published/idempotently-already-published signal paths and conflict/failure
handling.

## Validation evidence

```text
D8 focused policy/publication/finalization tests   25 passed
complete tests/decision                            206 passed
SR core/config/lifecycle/replay/adapter subset     431 passed
commons/config + risk compatibility subset          182 passed
Ruff check (decision scope)                         passed
Ruff format --check (decision scope)               passed
compileall (decision + shared SR adapter)          passed
git diff --check                                   passed
D8 AST infrastructure-import boundary              passed
```

The SR validation was deterministic and offline. No live network/data or
external publication was used. Repository-local caches generated by test and
compile validation were removed by the repository test cleanup and the final
bounded cleanup pass.

## Self-review

Pass 1 — correctness:

```text
policy status/no-signal distinction                 checked
selected binding and prepared identity               checked
D2+D4+D5 final identity                              checked
seconds timestamp and causal price                  checked
risk_profile_key and ATR compatibility               checked
ack identity and payload matching                    checked
canonical envelope revalidation before finalization  checked
altered envelope cannot commit or advance watermark  checked
missing conviction fails closed                      checked
policy catalog mutation is rejected                  checked
finalization receipt evidence is self-consistent     checked
publication -> state commit -> watermark ordering   checked
failure/conflict -> abort and unchanged watermark    checked
real SR no-signal state progression                  checked
```

Pass 2 — architecture/simplicity:

```text
no raw-score fusion or policy framework              checked
no model execution in policy                         checked
no real publisher/client or infrastructure           checked
no risk semantics moved upstream                     checked
no D9 runtime loop                                   checked
no D7B compatibility bridge                          checked
no second publication/idempotency framework          checked
D8 trust-boundary scope only                          checked
```

## Residual risks and deferred work

D8 does not claim actual Valkey publication or runtime recovery; D9 owns the
transport/read-loop integration and serial publication/finalization boundary.
D7B remains required before production shadow/cutover confidence is complete,
but it is not required to freeze D8 policy and publication semantics. The
existing downstream risk contract remains unchanged; only its established
epoch-seconds `TradeSignal` compatibility shape is produced.

No D9 work was started.

DECISION_APP_D8_POLICY_FINALIZATION_DOWNSTREAM_COMPAT_READY_FOR_REVIEW
