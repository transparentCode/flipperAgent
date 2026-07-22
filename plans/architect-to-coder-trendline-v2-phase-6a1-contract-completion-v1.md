---
goal: complete Phase 6A provider contracts before algorithm work
stage: architect-to-coder
date_created: 2026-07-22
last_updated: 2026-07-22
owner: Quant Orchestrator
status: Ready
source_agent: Quant Orchestrator
target_agent: quant-coder
tags: [handoff, quant, trendline-v2, phase-6a1]
---

# Trendline V2 Phase 6A.1 Contract Completion

## Authorization

Phase 6A is approved. Implement only these contract completions. Do not begin
Phase 6B provider implementation, Phase 6V viewer work, or Phase 7 Numba work.

```text
PHASE_6A.1_CONTRACT_COMPLETION: AUTHORIZED
PHASE_6B_PROVIDER_IMPLEMENTATION: NOT_AUTHORIZED
PHASE_6V_TVLC_VIEWER: NOT_AUTHORIZED
PHASE_7_NUMBA: NOT_AUTHORIZED
```

## Objective

Close three blocking contract gaps in the existing Trendline V2 provider
boundary without changing candidate algorithms or universal evidence:

1. Bind provider evidence into `ProviderResult`.
2. Add typed workload-limit outcomes.
3. Classify the selected history-horizon mode as invariant while retaining
   numeric duration and scope as unresolved.

## Scope

Primary files:

```text
src/libs/models/trendline_v2/discovery/contracts.py
src/libs/models/trendline_v2/discovery/provider_evidence.py
src/libs/models/trendline_v2/configuration/field_policy.py
src/libs/models/trendline_v2/discovery/__init__.py  # only if public export is needed
tests/models/trendline_v2/test_provider.py
tests/models/trendline_v2/test_extrema_pair_contracts.py
plans/trendline-v2-extrema-pair-contract-v1.md
plans/trendline-v2-extrema-pair-config-policy-v1.md
```

Do not modify unrelated packages, runtime configuration, YAML, legacy
trendline systems, RegimeV2, signal, selection, research, optimization, or
protected Trendline Family implementation.

## Required contract decisions

### 1. Provider evidence binding

`ProviderResult` must carry required immutable evidence, not expose it through
provider state, a secondary method, or a side channel.

Use one deterministic collection aligned with `candidates` order:

```text
evidence: tuple[ProviderEvidence, ...]
```

The provider-neutral evidence protocol/contract must expose enough for result
validation and serialization: `candidate_id`, `evidence_id`, `schema_version`,
`validate_against(ProviderInput)`, and `to_dict()`. Existing
`ConfirmedExtremaPairEvidence` must satisfy it without weakening its immutable
typed validation.

`ProviderResult` must enforce:

- success: non-empty candidates and exactly one evidence item per candidate;
- abstention/failure: no candidates and empty evidence;
- candidate IDs and evidence candidate IDs are the same unique set;
- evidence order matches candidate order deterministically;
- each evidence validates against request input, including causal positions;
- every evidence schema version equals the request provider evidence schema;
- evidence IDs are unique and content-derived;
- serialized result includes evidence in canonical order.

Malformed, duplicated, missing, reordered, future-position, mismatched-schema,
and mismatched-candidate evidence must raise `ContractValidationError`.

### 2. Typed workload-limit outcomes

Add explicit `ProviderReason` values:

```text
HYPOTHESIS_LIMIT_EXCEEDED = "hypothesis_limit_exceeded"
OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
```

These are expected deterministic workload abstentions, not vague provider
failures. Encode and test reason/status semantics explicitly:

- `HYPOTHESIS_LIMIT_EXCEEDED` -> `ProviderStatus.ABSTAINED`
- `OUTPUT_LIMIT_EXCEEDED` -> `ProviderStatus.ABSTAINED`
- `PROVIDER_FAILURE` -> `ProviderStatus.FAILED`
- existing expected input/config/no-candidate reasons retain explicit,
  documented status semantics and reject incompatible status values.

Do not add silent truncation or a generic fallback mapping.

### 3. History policy classification

`lookback_duration_seconds_v1` is the selected and invariant history-horizon
mode. Update field policy and both Phase 6A documents so:

- `provider.history_horizon`: `INVARIANT`, global scope, hash-bound, YAML-off;
- `provider.lookback_duration_seconds`: `UNRESOLVED`, allowed scope remains
  global/timeframe/asset/asset-timeframe, hash-bound, YAML-off.

State clearly that numeric duration and scope remain fixture/request-only until
scope evidence exists. Add a regression assertion for this distinction.

## Non-goals

- no confirmed-extrema scanner;
- no pair enumeration or candidate generation;
- no provider class, registry, kernel, Numba, viewer, or runtime integration;
- no new provider parameters beyond typed evidence/result semantics and the two
  typed reason values;
- no changes to universal `CandidateEvidence`;
- no YAML provider values or promotion behavior.

## Acceptance tests

Add focused tests proving:

- successful result requires one evidence record per candidate;
- empty result requires empty evidence;
- evidence candidate IDs, ordering, uniqueness, schema, causal positions, and
  input binding are enforced;
- serialized result round-trip contains deterministic evidence;
- workload reasons are typed and incompatible statuses reject;
- history mode is invariant while duration remains unresolved;
- existing provider request/config identity behavior is unchanged;
- existing provider and evidence tests remain green.

## Validation

Run from repository root:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_v2/test_provider.py \
  tests/models/trendline_v2/test_extrema_pair_contracts.py -q

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
ruff check src/libs/models/trendline_v2 tests/models/trendline_v2
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2
git diff --check
```

Refresh codebase-memory after implementation. Return a coder handoff with
changed files, contract decisions, test counts, index status, residual risks,
and explicit confirmation that Phase 6B remains unauthorized.

## Known baseline

Before this task:

```text
Trendline V2: 59 passed
Trendline Family: 399 passed
codebase-memory: indexed
```

The implementation must preserve these baselines.
