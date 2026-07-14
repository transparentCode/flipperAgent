# Architect → Coder: Trendline-Family Candidate Rejection Diagnosis Integrity v1

## Objective

Close the single blocking provenance gap in the external candidate-rejection diagnosis bundle.

The existing replay, diagnosis payload, source artifacts, and four generated diagnosis files are accepted and must remain byte-identical. Modify only the independent validator so it proves the complete source-binding chain rather than trusting a jointly rebound `source_binding.json` and `diagnosis_manifest.json`.

Confirmed attack against the current implementation:

1. Copy the four-file diagnosis bundle.
2. Alter a nested v2 trial-file SHA-256 inside `source_binding.json`.
3. Replace `source_binding_id` with a forged value.
4. Update only `diagnosis_manifest.source_binding_id` and `diagnosis_manifest.source_binding_sha256`.
5. Leave `rejection_diagnosis.json`, its diagnosis ID, and all conclusions unchanged.
6. Call `validate_diagnosis_bundle(...)`.

Current result:

```text
forged_source_binding_ACCEPTED
```

Required result after remediation:

```text
forged_source_binding_REJECTED
```

## Scope Boundaries

### In scope

- strict pure validation of the persisted source-binding semantic payload;
- rederivation of nested trial, approved-report, and config inventory identities;
- rederivation of `source_binding_id`;
- cross-binding the external source binding to the diagnosis JSON and manifest;
- adversarial regression tests using copied diagnosis bundles;
- read-only validation of the existing diagnosis bundle;
- broad non-interference tests and codebase-memory reindexing;
- one coder-to-review handoff.

### Out of scope

- provider replay or calling `build_rejection_diagnosis(...)` against the real bundle;
- regenerating or rewriting any diagnosis artifact;
- changing diagnosis schema, diagnosis ID, report content, metrics, contrasts, hypotheses, or conclusions;
- changing `capture_source_binding(...)` semantics unless required solely to share a pure canonical helper without changing output bytes;
- network or Binance access;
- Phase-I execution, evaluator execution, grid search, holdout access, density study, parameter study, or tracker work;
- canonical provider, pivot, fitting, optimizer, evidence-report, runtime, YAML, RegimeV2, signal, or selection changes.

## Fixed Existing Bundle

Validate, but do not rewrite:

```text
artifacts/trendline_family_candidate_diagnostics/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_binding.json
    rejection_diagnosis.json
    rejection_diagnosis.md
    diagnosis_manifest.json
```

Expected immutable identities:

```text
diagnosis ID:
trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf

source binding ID:
trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a

config file SHA-256:
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

Existing diagnosis file hashes must remain:

```text
source_binding.json:
96bcdd5ad07429e5021675326b344c1142318423bfcbe40929f72c047d600d7d

rejection_diagnosis.json:
8a17b8b514d04c7ce12410906d9ef3169723a7549fc872878429c505fdf96c3a

rejection_diagnosis.md:
a548e4815e9c0ca8d254199fce71c506c7f8a0bedd6ec176085bdfd94ff04fa3

diagnosis_manifest.json:
8530208d3a306e4ff802231e60eab53e4ca938cd7990564a43fa54b03045b389
```

Any mismatch must stop. Do not repair or rerender the bundle.

## Affected Symbols And Blast Radius

Expected implementation scope:

```text
scripts/diagnose_trendline_family_candidate_rejection.py
tests/scripts/test_trendline_family_candidate_rejection.py
plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-integrity-v1.md
.codebase-memory/
```

Primary existing symbol:

```python
validate_diagnosis_bundle(...)
```

Add one strict pure helper, named clearly, for example:

```python
validate_source_binding_payload(...)
```

Codebase-memory currently shows:

- `validate_diagnosis_bundle(...)` is called only by the diagnosis builder/main path;
- `capture_source_binding(...)` is used only by diagnosis source loading/building;
- no production runtime caller exists.

Before editing, rerun codebase-memory impact/trace for any existing symbol modified. Do not alter production runtime flows.

## Selected Design

### 1. Strict top-level source-binding schema

Require exactly:

```text
diagnosis_schema_version
trial_inventories
approved_report_inventory
config_inventory
source_binding_id
```

Require:

```text
diagnosis_schema_version == trendline_family_candidate_rejection_diagnosis_v1
```

Reject missing or extra fields.

### 2. Trial-inventory rederivation

Validate `trial_inventories` using the already approved source-inventory semantics from:

```python
scripts.build_trendline_family_candidate_evidence_report.validate_source_inventory_payload(...)
```

This must independently verify:

- exact top-level evidence-report inventory schema;
- exact v1/v2 entries and trial names;
- exact record fields;
- canonical sorted unique safe relative paths;
- non-negative non-boolean integer sizes;
- lowercase 64-character SHA-256 values;
- per-source inventory hashes;
- aggregate source-inventory ID.

Do not duplicate or weaken the approved trial-inventory validator. Wrap its contract errors as `RejectionDiagnosisError` when needed.

The persisted v1/v2 semantic payload must be retained exactly for source-binding ID rederivation.

### 3. Approved report-inventory validation

Require `approved_report_inventory` to contain exactly:

```text
source_name
root_name
files
inventory_sha256
```

Require:

```text
source_name == approved_report_bundle
root_name == btcusdt_4h_20250801_20251201_candidate_geometry_v2
```

Require exactly these sorted file paths:

```text
evidence_report.json
evidence_report.md
report_manifest.json
source_inventory.json
```

For each file record require exactly:

```text
relative_path
size_bytes
sha256
```

Validate:

- canonical safe POSIX relative path;
- exact sorted order and uniqueness;
- non-negative non-boolean integer size;
- lowercase 64-character hexadecimal SHA-256.

Rederive `inventory_sha256` from exactly the same semantic payload used by `_file_inventory(...)`:

```python
{
    "source_name": source_name,
    "root_name": root_name,
    "files": canonical_files,
}
```

Require equality with the persisted `inventory_sha256`.

Do not reread the live report files inside the independent bundle validator. This helper validates the persisted provenance semantics; live-byte comparison remains the separate source-immutability check.

### 4. Config-inventory validation

Require `config_inventory` to contain exactly:

```text
relative_path
size_bytes
sha256
```

Validate:

- canonical safe POSIX relative path;
- non-negative non-boolean integer size;
- lowercase 64-character SHA-256;
- SHA-256 equals the approved YAML byte hash:
  `7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8`.

For the persisted real diagnosis bundle require:

```text
relative_path == configs/trendline_family.yaml
```

Temporary copied-source generation tests may use an explicitly supplied expected config relative path. Do not silently accept arbitrary config paths. Prefer an optional validator argument whose default is the real canonical path, rather than weakening the real-bundle contract.

Do not change the existing config record or output bytes.

### 5. Source-binding ID rederivation

Construct the canonical semantic payload exactly as `capture_source_binding(...)` does:

```python
{
    "diagnosis_schema_version": DIAGNOSIS_SCHEMA_VERSION,
    "trial_inventories": validated_trial_inventories,
    "approved_report_inventory": validated_report_inventory,
    "config_inventory": validated_config_inventory,
}
```

Rederive:

```python
semantic_id(
    "trendline-family-candidate-rejection-source-binding",
    semantic_payload,
)
```

Require equality with `source_binding.json.source_binding_id`.

The helper should return the canonical validated source-binding payload and/or derived ID so callers cannot continue using unvalidated claims.

### 6. Cross-bind every source-binding claim

Inside `validate_diagnosis_bundle(...)`, after existing file-hash checks and strict source-binding validation, require the independently derived source-binding ID to equal all four claims:

```text
source_binding.json.source_binding_id
diagnosis_manifest.json.source_binding_id
rejection_diagnosis.json.diagnosis_identity.source_binding_id
rejection_diagnosis.json.source_and_execution_identity.source_binding_id
```

Require canonical equality between the validated external source binding and:

```text
rejection_diagnosis.json
  .source_and_execution_identity
  .source_inventories
```

Do not compare only IDs. The full validated semantic payload must match the embedded payload.

### 7. Preserve all existing integrity checks

Keep active:

- diagnosis content-addressed ID verification;
- manifest diagnosis schema and diagnosis-ID binding;
- source-binding outer file SHA-256;
- diagnosis JSON SHA-256;
- diagnosis Markdown SHA-256;
- dataset identity;
- config resolved identity;
- Phase-I run identity;
- evidence-report identity;
- recommendation identity.

Strengthen missing checks when already represented in the existing manifest/identity, but do not change any schema or persisted bytes.

### 8. No live replay during integrity validation

The integrity task must validate the existing bundle read-only by calling:

```python
validate_diagnosis_bundle(...)
```

Do not call:

```text
build_rejection_diagnosis
replay_validation_provider
NativeDeterministicLineProvider.generate
run_phase_i_evaluation
CandidateGeometryEvaluator
```

No provider calls are authorized for this remediation.

## Required Adversarial Tests

Use temporary copied diagnosis bundles. Never mutate the real bundle.

Add tests covering at minimum:

1. Existing real diagnosis bundle validates unchanged.
2. Forged nested v2 source-file SHA plus rebound:
   - v2 inventory hash;
   - trial source-inventory ID;
   - source-binding ID;
   - manifest source-binding ID;
   - manifest outer source-binding SHA;
   still rejects because the external source binding differs from the embedded diagnosis binding.
3. Forged nested v2 SHA with only outer manifest rebound rejects during trial-inventory validation.
4. Forged approved-report file SHA rejects when its aggregate report inventory hash is stale.
5. Fully rebound forged report inventory still rejects against the embedded diagnosis binding.
6. Forged config SHA rejects, including when source-binding and outer manifest claims are rebound.
7. Forged config path rejects under the real-bundle expected-path contract.
8. Forged source-binding ID rejects.
9. Mismatch between external source binding and embedded `source_inventories` rejects.
10. Mismatch in either diagnosis source-binding ID location rejects through diagnosis ID or explicit cross-binding.
11. Missing or extra source-binding top-level fields reject.
12. Missing or extra trial/report/config inventory fields reject.
13. Duplicate, unsorted, absolute, backslash, dot-segment, or parent-segment paths reject.
14. Negative, boolean, or string sizes reject.
15. Uppercase, short, long, or non-hex SHA-256 values reject.
16. Wrong report `source_name`, `root_name`, file membership, or file order rejects.
17. Existing diagnosis/report/trial/config bytes remain unchanged before and after all read-only validation.

Tests must assert specific fail-closed errors rather than generic exceptions where practical.

## Source And Output Immutability

Before implementation/testing, capture sorted relative-path, byte-size, and SHA-256 inventories for:

- V1 trial root — expected 1 file;
- V2 trial root — expected 30 files;
- approved evidence-report bundle — expected 4 files;
- rejection-diagnosis bundle — expected 4 files;
- `configs/trendline_family.yaml`.

After all work, capture them again and require canonical equality.

Do not write under any of those roots.

The existing diagnosis bundle must retain the exact four hashes listed in this handoff.

## Implementation Order

1. Read this handoff and `review-to-architect-trendline-family-candidate-rejection-diagnosis-v1.md`.
2. Run codebase-memory traces for `validate_diagnosis_bundle` and any existing helper modified.
3. Capture protected source/output inventories and exact diagnosis file hashes.
4. Add the strict pure source-binding validator.
5. Integrate derived source-binding checks into `validate_diagnosis_bundle(...)`.
6. Add adversarial copied-bundle tests.
7. Run focused tests.
8. Validate the existing real diagnosis bundle read-only; do not invoke the replay/build path.
9. Recheck all protected inventories and exact diagnosis hashes.
10. Run broad regression, isolation, lint, compile, and diff checks.
11. Reindex codebase-memory and verify no production runtime caller appeared.
12. Write the coder-to-review handoff and stop.

## Acceptance Criteria

- the confirmed forged-source-binding attack rejects;
- nested trial inventory semantics are independently rederived;
- approved report inventory semantics are independently rederived;
- config inventory semantics and approved YAML hash are independently validated;
- source-binding ID is independently recomputed;
- external binding equals the diagnosis-embedded binding;
- all source-binding ID claims cross-bind to the derived ID;
- existing diagnosis ID and all four diagnosis files remain unchanged;
- V1/V2/report/config sources remain unchanged;
- no provider replay, network, Phase-I, holdout, density, parameter, tracker, runtime, or Regime work occurs;
- focused and broad tests pass.

## Validation Checklist

Focused diagnosis tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_rejection.py \
  -q -p no:cacheprovider
```

Read-only real-bundle validation:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -c '
from scripts.diagnose_trendline_family_candidate_rejection import OUTPUT_ROOT, validate_diagnosis_bundle
bundle = validate_diagnosis_bundle(output_root=OUTPUT_ROOT)
print(bundle["rejection_diagnosis"]["diagnosis_identity"]["diagnosis_id"])
'
```

Optimization and research support:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider
```

Full trendline-family:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider
```

Integration isolation:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider
```

Static checks:

```bash
/Users/aloobhujia/.local/bin/ruff check \
  scripts/diagnose_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_rejection.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_diagnosis_integrity_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/diagnose_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_rejection.py

git diff --check
```

Codebase-memory:

```bash
codebase-memory-mcp cli index_repository '{"repo_path":"/Users/aloobhujia/flipperAgent"}'
codebase-memory-mcp cli index_status '{"project":"Users-aloobhujia-flipperAgent"}'
codebase-memory-mcp cli trace_path '{"project":"Users-aloobhujia-flipperAgent","function_name":"validate_diagnosis_bundle","direction":"both"}'
```

## Explicit Non-Goals

Do not:

- rerun the candidate rejection diagnosis;
- call the provider or evaluator;
- regenerate diagnosis artifacts;
- rewrite source/report/trial/config artifacts;
- alter diagnosis content or conclusions;
- fetch data;
- open holdout;
- change candidate parameters, gates, objective, grid, or outcome policy;
- start density, tracker, interaction, MTF, RegimeV2, signal, or runtime work.

## Mandatory Completion Report

Write:

```text
plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-integrity-v1.md
```

Include exactly these sections:

- Scope Executed
- Files Changed
- Confirmed Root Cause
- Source-Binding Validation
- Cross-Binding
- Adversarial Tests
- Existing Bundle Validation
- Source And Output Byte Integrity
- Runtime And Regime Isolation
- Tests
- Codebase-Memory
- Known Gaps
- Next Handoff

Stop after the existing diagnosis bundle validates unchanged under the strengthened validator. Do not begin a density study or tracker trial.
