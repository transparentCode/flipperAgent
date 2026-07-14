# Review → Architect: Trendline-Family Candidate Rejection Diagnosis v1

## Review Scope

Independent review of:

```text
scripts/diagnose_trendline_family_candidate_rejection.py
tests/scripts/test_trendline_family_candidate_rejection.py
artifacts/trendline_family_candidate_diagnostics/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-v1.md
```

The review covered source identity, validation-only replay boundaries, exact actual/shadow call accounting, persisted status reconciliation, shadow configuration isolation, diagnosis identity and manifest bindings, immutable source protection, and runtime/Regime isolation.

## Findings by Severity

### Blocking — `source_binding.json` is not semantically rederived or cross-bound during independent bundle validation

The diagnosis replay and conclusions are internally consistent, but `validate_diagnosis_bundle(...)` trusts a jointly rebound source-binding file and manifest.

Relevant implementation:

```text
scripts/diagnose_trendline_family_candidate_rejection.py:807-831
```

The validator currently verifies:

- the diagnosis payload's content-addressed diagnosis ID;
- diagnosis/report Markdown hashes;
- `manifest.source_binding_id == source_binding.source_binding_id`;
- the outer SHA-256 of `source_binding.json`.

It does not:

- recompute the v1/v2 trial-root inventory hashes from the persisted source-binding file;
- recompute the approved report-bundle inventory hash from its file records;
- validate the config inventory record;
- recompute `source_binding_id` from the complete canonical binding semantics;
- compare `source_binding.json` with `rejection_diagnosis.json`'s embedded `source_and_execution_identity.source_inventories`;
- compare the source-binding ID in the diagnosis payload with the independently derived binding ID.

Independent adversarial reproduction:

1. Copy the four-file diagnosis bundle to a temporary directory.
2. Forge one nested v2 source-file SHA-256 inside `source_binding.json`.
3. Replace `source_binding.source_binding_id` with a forged value.
4. Update only:
   - `diagnosis_manifest.source_binding_id`;
   - `diagnosis_manifest.source_binding_sha256`.
5. Leave `rejection_diagnosis.json`, its diagnosis ID, and every diagnosis conclusion unchanged.
6. Call `validate_diagnosis_bundle(...)`.

Observed result:

```text
forged_source_binding_ACCEPTED
```

This leaves the diagnosis conclusions unchanged but allows the external provenance file to describe different source bytes than the content-addressed diagnosis claims.

The required chain is:

```text
source-binding file records
→ per-root/report/config inventory hashes
→ source-binding ID
→ diagnosis embedded source binding
→ diagnosis ID
→ diagnosis manifest
```

Approval remains blocked until this chain is independently rederived and cross-bound.

## Positive Review Confirmations

The core diagnostic replay matches the approved architecture:

- exactly seven configurations;
- exactly 288 validation positions per configuration;
- exactly 2,016 actual provider calls;
- shadow calls occur only after actual `rejected_low_quality_candidates` statuses;
- the shadow clone changes only `candidate.min_candidate_quality` to `0.0`;
- actual per-fold provider statuses are reconciled against persisted Phase-I results;
- replay positions are bounded to the three validation windows and stop at position 563;
- planned holdout begins at position 636 and is not accessed;
- no future-outcome evaluator or Phase-I runner is imported or called;
- the productive-trial gate deficit is read from persisted evidence rather than recomputed;
- observations are separated from research hypotheses.

The reported structural diagnosis is supported:

```text
actual provider calls:  2,016
shadow provider calls:  1,969
actual valid results:   47
actual low-quality:     1,969
other provider statuses: 0
productive config:      lookback 120 / quality 0.30
reaction-quality sample count: 47
minimum required:       100
deficit:                53
```

## Required Bounded Remediation

Modify only the diagnosis bundle validator and focused tests.

Add a strict pure source-binding validator that:

1. Requires the exact top-level source-binding schema.
2. Validates the diagnosis schema version.
3. Validates and rederives the v1/v2 source inventories using the already approved external evidence-report inventory rules.
4. Validates the approved report inventory:
   - exact four expected relative paths;
   - canonical sorted unique paths;
   - non-negative integer sizes;
   - lowercase 64-character SHA-256 values;
   - deterministic aggregate inventory hash if persisted.
5. Validates the config inventory:
   - exact relative path `configs/trendline_family.yaml` for the real bundle;
   - non-negative integer size;
   - lowercase SHA-256;
   - expected approved config SHA-256.
6. Recomputes `source_binding_id` from exactly the canonical semantic binding payload used by `capture_source_binding(...)`.
7. Requires the derived source-binding ID to equal:
   - `source_binding.json.source_binding_id`;
   - `diagnosis_manifest.json.source_binding_id`;
   - `rejection_diagnosis.json.diagnosis_identity.source_binding_id`;
   - `rejection_diagnosis.json.source_and_execution_identity.source_binding_id`.
8. Requires canonical equality between the validated source-binding payload and the diagnosis payload's embedded `source_and_execution_identity.source_inventories`.
9. Preserves the existing diagnosis ID, file-hash, dataset, report, config, Phase-I run, and recommendation checks.

The existing four diagnosis files must validate unchanged after the fix. Do not regenerate or rewrite them.

Add adversarial tests covering at minimum:

- forged nested v2 source SHA plus rebound source-binding ID and outer manifest SHA;
- forged report-file record;
- forged config SHA or path;
- forged source-binding ID;
- mismatch between diagnosis embedded source binding and external source-binding file;
- missing/extra source-binding fields;
- duplicate/unsorted/unsafe paths;
- invalid sizes and malformed SHA-256 values.

## Blast Radius and Affected Flows

Expected remediation scope:

```text
scripts/diagnose_trendline_family_candidate_rejection.py
tests/scripts/test_trendline_family_candidate_rejection.py
plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-integrity-v1.md
.codebase-memory/
```

Must remain unchanged:

- v1 and v2 trial roots;
- approved four-file candidate evidence report;
- existing four-file rejection diagnosis bundle;
- `configs/trendline_family.yaml`;
- canonical provider, pivot, fitting, optimization, and report code;
- runtime, tracker, interaction, MTF, RegimeV2, signals, and selection paths.

No network request, provider replay, Phase-I rerun, holdout action, metric reinterpretation, density study, parameter recommendation, or tracker work is authorized.

## Validation Confirmations

Independently run:

```text
focused diagnosis tests: 8 passed
Ruff:                    passed
compileall:              passed
git diff --check:        passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   46,017
edges:   145,413
status:  ready
```

`validate_diagnosis_bundle(...)` has only diagnosis builder/main callers and no production runtime caller.

## Approval Status

**REQUEST CHANGES.**

The replay logic, call accounting, holdout isolation, and evidence-based conclusions are accepted. Approval is blocked only by the external diagnosis bundle's source-binding provenance validation.

## Recommended Handoff

Create and execute:

```text
plans/architect-to-coder-trendline-family-candidate-rejection-diagnosis-integrity-v1.md
```

Stop after the existing diagnosis bundle validates unchanged under the strengthened independent validator. Do not begin a new density study or tracker trial.
