# Architect → Coder: Trendline-Family Candidate Evidence Report Integrity v1

## Objective

Close the single blocking provenance-integrity defect in the external candidate evidence bundle validator.

The existing generated bundle is semantically correct and must remain byte-identical:

```text
artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_inventory.json
    evidence_report.json
    evidence_report.md
    report_manifest.json
```

Strengthen `validate_report_bundle(...)` so it independently rederives and cross-binds the semantic contents of `source_inventory.json` instead of trusting only its outer file SHA-256.

The required provenance chain is:

```text
canonical source file records
→ per-source inventory hashes
→ source inventory identity
→ evidence report inventory hashes/report ID
→ report manifest inventory hashes/file hashes
```

The existing report bundle must pass after the code-only fix without report regeneration or artifact mutation.

## Scope Boundaries

### In scope

- one strict source-inventory validation helper in the standalone report script;
- integration of that helper into `validate_report_bundle(...)`;
- focused adversarial and positive tests;
- read-only validation of the existing generated report bundle;
- byte-inventory proof that both candidate trial roots and all four report files remain unchanged;
- focused and broad regression checks;
- coder-to-review handoff and codebase-memory reindex.

### Out of scope

- regenerating any existing report output;
- changing report payload, report schema, report ID, manifest schema, or source inventory schema;
- changing report interpretation, candidate metrics, recommendation, or holdout statements;
- changing the report builder except where necessary to share canonical inventory-validation helpers;
- any network request or Binance adapter work;
- Phase-I rerun, evaluator execution, holdout opening, artifact repair, or artifact rewrite;
- changes to canonical trendline-family model or optimization semantics;
- tracker, interaction, MTF, RegimeV2, signal, selection, strategy, risk, execution, or portfolio work;
- YAML or runtime configuration changes.

## Approved Files

Modify only:

```text
scripts/build_trendline_family_candidate_evidence_report.py
tests/scripts/test_trendline_family_candidate_evidence_report.py
```

Create:

```text
plans/coder-to-review-trendline-family-candidate-evidence-report-integrity-v1.md
```

Generated codebase-memory index files may change only through reindexing.

Must remain byte-identical:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/

artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_inventory.json
    evidence_report.json
    evidence_report.md
    report_manifest.json
```

## Confirmed Defect

The current validator checks:

```text
sha256(source_inventory.json bytes)
== report_manifest.source_inventory_sha256
```

and compares inventory-hash claims in the evidence report and manifest.

It does not independently verify that the nested inventory content actually produces those inventory hashes and the persisted `source_inventory_id`.

Confirmed exploit:

1. Copy the generated report bundle.
2. Forge one nested file SHA inside `source_inventory.json`.
3. Recompute only `report_manifest.source_inventory_sha256`.
4. Leave `evidence_report.json`, its report ID, and claimed source inventory hashes unchanged.
5. Call `validate_report_bundle(...)`.

Current observed result:

```text
forged_source_inventory_ACCEPTED
```

The remediation must make this fail closed.

## Selected Design

Add a pure helper such as:

```python
def validate_source_inventory_payload(
    source: Mapping[str, Any],
) -> Mapping[str, str]:
    ...
```

The exact name may differ, but it must return only independently derived inventory hashes after validating the complete payload.

### Top-Level Contract

Require:

```text
report_schema_version == trendline_family_candidate_evidence_report_v1
sources keys exactly == {"v1", "v2"}
source_inventory_id present and valid
no unknown top-level semantic keys beyond the existing schema
```

The helper must validate the current persisted schema, not introduce a new one.

### Source Identity Contract

For each entry:

```text
key: v1
source_name: v1
trial_name: btcusdt_4h_20250801_20251201_candidate_geometry_v1

key: v2
source_name: v2
trial_name: btcusdt_4h_20250801_20251201_candidate_geometry_v2
```

Require source key and `source_name` equality. Require exact expected trial names.

Reject missing, additional, swapped, or duplicated source identities.

### File-Record Contract

Each source must contain a non-empty list/tuple of file records. Every record must contain exactly the existing fields:

```text
relative_path
size_bytes
sha256
```

Validate:

- `relative_path` is a non-empty canonical POSIX relative path;
- no absolute paths;
- no empty segments, `.` segments, or `..` traversal;
- no backslashes;
- paths are strictly sorted lexicographically;
- paths are unique;
- `size_bytes` is an integer, not bool, and is non-negative;
- `sha256` is lowercase hexadecimal with exactly 64 characters;
- no unknown file-record fields.

Do not access or rehash the actual v1/v2 source files inside `validate_report_bundle(...)`; this validator proves the external bundle’s internal semantic bindings. The report-generation path already performs live source-root inventory checks.

### Per-Source Hash Derivation

For each validated source, rebuild exactly:

```python
semantic = {
    "source_name": source_name,
    "trial_name": trial_name,
    "files": canonical_files,
}
```

Derive:

```python
sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
```

Require equality with persisted `inventory_sha256`.

Do not change the hashing algorithm or canonical serialization.

### Aggregate Source Inventory Identity

Rebuild exactly:

```python
semantic = {
    "report_schema_version": REPORT_SCHEMA_VERSION,
    "sources": {
        "v1": validated_v1_source_payload,
        "v2": validated_v2_source_payload,
    },
}
```

The source payloads must preserve the same semantic shape used by `capture_source_inventories(...)`, including their verified `inventory_sha256` fields.

Derive:

```python
semantic_id(
    "trendline-family-candidate-source-inventory",
    semantic,
)
```

Require equality with persisted `source_inventory_id`.

### Cross-Binding Contract

From the validated source inventory derive:

```python
{
    "v1": validated_v1_inventory_sha256,
    "v2": validated_v2_inventory_sha256,
}
```

Require exact equality with both:

```text
evidence_report.report_identity.source_inventory_hashes
report_manifest.source_inventory_hashes
```

Continue requiring:

```text
sha256(source_inventory.json bytes)
== report_manifest.source_inventory_sha256
```

All existing report-ID, JSON, Markdown, dataset, Phase-I, recommendation, and verified-source-artifact bindings must remain enforced.

## Test Requirements

Extend the focused report suite with temporary copied report bundles only. Never mutate real source or report roots.

### Mandatory positive tests

1. Existing generated report bundle passes strengthened validation unchanged.
2. Idempotent report generation still produces identical bytes.
3. Valid source inventory derives the persisted v1/v2 inventory hashes and source inventory ID.

### Mandatory adversarial tests

1. **Confirmed exploit regression**
   - forge one nested file SHA;
   - recompute only `report_manifest.source_inventory_sha256`;
   - require `validate_report_bundle(...)` rejection.

2. Forge one per-source `inventory_sha256`, update outer inventory-file SHA, require rejection.

3. Forge `source_inventory_id`, update outer inventory-file SHA, require rejection.

4. Duplicate a relative path, recompute outer inventory-file SHA, require rejection.

5. Make file paths unsorted, recompute outer inventory-file SHA, require rejection.

6. Use an invalid path such as `../escape`, `/absolute`, `a\\b`, or `a/./b`, require rejection.

7. Swap or mismatch `v1`/`v2` source names or trial names, recompute outer inventory-file SHA, require rejection.

8. Add an unexpected source key or remove one required source, require rejection.

9. Use invalid `size_bytes` or malformed uppercase/short/non-hex SHA, require rejection.

Where multiple malformed cases share one parameterized test, keep failure messages specific enough for review.

### Existing security tests that must still pass

- normalized input tampering rejection;
- Phase-I artifact/recommendation tampering rejection;
- evidence Markdown hash rejection;
- report-ID/content binding;
- canonical trial ordering;
- non-identical output overwrite rejection;
- network/stage-runner boundary scan.

## Implementation Order

1. Read:
   - `plans/review-to-architect-trendline-family-candidate-evidence-report-v1.md`;
   - this handoff;
   - the current report script and focused tests.
2. Confirm codebase-memory is ready and inspect the `validate_report_bundle` flow before modification.
3. Capture SHA-256 inventories of:
   - v1 trial root;
   - v2 trial root;
   - all four existing report files.
4. Add the pure strict inventory validator.
5. Integrate its derived hashes into `validate_report_bundle(...)` cross-binding.
6. Add mandatory positive and adversarial tests.
7. Run focused tests and static checks.
8. Validate the existing real report bundle read-only.
9. Recalculate source/report inventories and prove byte-for-byte identity.
10. Run broader regression and isolation suites.
11. Reindex codebase-memory.
12. Write the coder-to-review handoff and stop.

## Acceptance Criteria

- the confirmed forged-inventory exploit rejects;
- nested source inventory content is independently canonicalized and rehashed;
- persisted per-source hashes are verified;
- persisted `source_inventory_id` is verified;
- inventory-derived v1/v2 hashes are cross-bound to both evidence report and manifest;
- duplicate, unsorted, unsafe, or malformed file records reject;
- existing report bundle validates without rewriting any output;
- all four report files remain byte-identical;
- v1/v2 trial roots remain byte-identical;
- report schema, report ID, recommendation, and interpretation are unchanged;
- no network, Phase-I, holdout, runtime, YAML, RegimeV2, or tracker work occurs;
- focused and broad validation passes.

## Validation Checklist

Focused report tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_evidence_report.py \
  -q -p no:cacheprovider
```

Optimization and research support:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider
```

Full trendline-family:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider
```

Integration isolation:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity \
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
  scripts/build_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_integrity_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/build_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py

git diff --check
```

Read-only real-bundle validation:

```python
validate_report_bundle(
    output_root=Path(
        "artifacts/trendline_family_candidate_reports/"
        "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
    )
)
```

Verify codebase-memory is reindexed and ready. Confirm no production caller or runtime import of the reporting script appears.

## Explicit Non-Goals

Do not:

- regenerate or rewrite any existing report file;
- mutate v1/v2 source roots;
- fetch market data;
- run Phase I or any evaluator;
- open holdout;
- alter recommendation or metrics;
- change report schema or IDs;
- modify canonical trendline-family or optimizer code;
- edit YAML/runtime paths;
- begin tracker, interaction, MTF, or RegimeV2 work.

## Mandatory Completion Report

Return exactly these sections:

- Scope Executed
- Files Changed
- Root Cause
- Source Inventory Validation
- Cross-Binding
- Adversarial Tests
- Existing Bundle Validation
- Source And Report Byte Integrity
- Runtime And Regime Isolation
- Tests
- Codebase-Memory
- Known Gaps
- Next Handoff

Write:

```text
plans/coder-to-review-trendline-family-candidate-evidence-report-integrity-v1.md
```

Stop after this integrity remediation. Do not begin tracker work.
