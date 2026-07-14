# Coder To Review: Candidate Rejection Diagnosis Integrity v1

## Scope Executed

Closed only the external rejection-diagnosis source-binding validation gap.
The implementation is pure validation over persisted payloads. It did not
replay providers, run Phase I, access the network, open holdout, or regenerate
the diagnosis bundle.

## Files Changed

- `scripts/diagnose_trendline_family_candidate_rejection.py`
- `tests/scripts/test_trendline_family_candidate_rejection.py`
- `plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-integrity-v1.md`

The required codebase-memory reindex refreshed its generated index files.

## Confirmed Root Cause

`validate_diagnosis_bundle(...)` checked only the external source-binding file
hash and its manifest claim. It neither rederived nested trial/report/config
inventory semantics nor bound the external semantic payload to the diagnosis
JSON. A forged nested source SHA could therefore be accepted after rebinding
the external manifest claims.

## Source-Binding Validation

Added `validate_source_binding_payload(...)`. It requires the exact source
binding schema and rederives:

- v1/v2 trial inventories through the approved evidence-report validator;
- the approved four-file report inventory, including ordered safe paths;
- the canonical config record and approved YAML SHA;
- the complete content-addressed source-binding ID.

Malformed/missing/extra fields, unsafe paths, duplicate or unsorted paths,
invalid sizes, invalid hashes, wrong report identity/file set, and config drift
reject fail-closed.

## Cross-Binding

The derived source-binding ID must equal the claims in `source_binding.json`,
`diagnosis_manifest.json`, `diagnosis_identity`, and
`source_and_execution_identity`. The validated external semantic binding must
canonically equal `source_and_execution_identity.source_inventories`.

Existing diagnosis ID, manifest schema/ID, file hashes, dataset, resolved
config, Phase-I run, report, and recommendation identity checks remain active.

## Adversarial Tests

Copied diagnosis bundles cover:

- nested v2 SHA attacks with stale and fully rebound inventory/binding claims;
- stale and fully rebound report inventories;
- forged config SHA/path and source-binding ID;
- external-versus-embedded source-binding mismatch;
- both diagnosis source-binding claim locations;
- missing/extra fields, unsafe/duplicate/unsorted paths;
- invalid sizes/hashes and report identity/file-membership failures.

No copied-bundle test invokes the diagnosis builder or provider replay.

## Existing Bundle Validation

Read-only validation passes unchanged for:

`trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf`

The verified source-binding ID remains:

`trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a`

## Source And Output Byte Integrity

Pre/post protected inventories match:

- v1 trial root: 1 file;
- v2 trial root: 30 files;
- approved report bundle: 4 files;
- diagnosis bundle: 4 files;
- `configs/trendline_family.yaml`: approved SHA unchanged.

Diagnosis SHA-256 values remain exactly:

- `source_binding.json`: `96bcdd5ad07429e5021675326b344c1142318423bfcbe40929f72c047d600d7d`
- `rejection_diagnosis.json`: `8a17b8b514d04c7ce12410906d9ef3169723a7549fc872878429c505fdf96c3a`
- `rejection_diagnosis.md`: `a548e4815e9c0ca8d254199fce71c506c7f8a0bedd6ec176085bdfd94ff04fa3`
- `diagnosis_manifest.json`: `8530208d3a306e4ff802231e60eab53e4ca938cd7990564a43fa54b03045b389`

## Runtime And Regime Isolation

No Binance/network access, provider replay, evaluator, Phase-I execution,
holdout access, artifact generation, YAML mutation, canonical model/optimizer,
runtime, signal, selection, RegimeV2, density, or tracker work occurred.

## Tests

- Focused diagnosis integrity: `39 passed`.
- Read-only existing bundle validation: passed.
- Optimization/research support: `54 passed`.
- Full trendline-family: `347 passed`.
- Trendline-family/RegimeV2-adapter/projected-runtime isolation: `375 passed`.
- RegimeV2/selection/signals isolation: `148 passed`, one existing OpenTelemetry deprecation warning.
- Ruff, compileall, and `git diff --check`: passed.

## Codebase-Memory

Reindexed successfully; index status is `ready`. The validator remains
reachable only from the diagnosis builder/main path; no production runtime
caller appeared.

## Known Gaps

The validator proves the persisted semantic provenance chain. It intentionally
does not reread live trial/report/config roots; that remains the separate
source-immutability audit.

## Next Handoff

Independent integrity review only. Do not regenerate diagnosis evidence or
begin density/tracker work without separate approval.
