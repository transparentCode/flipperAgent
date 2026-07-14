# Review → Architect: Trendline-Family Candidate Evidence Report v1

## Review Scope

Independent review of:

```text
scripts/build_trendline_family_candidate_evidence_report.py
tests/scripts/test_trendline_family_candidate_evidence_report.py
artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
plans/coder-to-review-trendline-family-candidate-evidence-report-v1.md
```

The review covered source-root immutability, normalized-input and Phase-I cross-binding, report identity, report/manifest hashes, deterministic rerendering, complete candidate evidence, no-finalist/no-holdout semantics, and runtime isolation.

## Findings by Severity

### Blocking — source inventory semantics are not independently rederived or cross-bound

`validate_report_bundle()` validates the outer SHA-256 of `source_inventory.json` against `report_manifest.json`, but does not validate the semantic contents of the inventory itself.

Relevant implementation:

```text
scripts/build_trendline_family_candidate_evidence_report.py:623-660
```

The validator currently:

- hashes the complete inventory file and compares it with `source_inventory_sha256`;
- compares inventory hashes claimed by the evidence report with hashes claimed by the manifest;
- checks only that `source_inventory_id` is non-null.

It does not:

- recompute each source's `inventory_sha256` from its `source_name`, `trial_name`, and file records;
- recompute and verify `source_inventory_id`;
- derive the v1/v2 inventory hashes from `source_inventory.json` and compare them to `report_identity.source_inventory_hashes` and `report_manifest.source_inventory_hashes`;
- validate canonical/unique inventory file membership.

Independent adversarial reproduction:

1. Copy the generated external report bundle to a temporary directory.
2. Replace one nested v2 source-file SHA-256 in `source_inventory.json` with forged content.
3. Recompute only `report_manifest.source_inventory_sha256` for the altered inventory file.
4. Leave `evidence_report.json`, its content-addressed report ID, and the inventory hashes claimed there unchanged.
5. Call `validate_report_bundle(...)`.

Observed result:

```text
forged_source_inventory_ACCEPTED
```

This breaks the required provenance chain:

```text
source inventory contents
→ per-source inventory hashes
→ source inventory identity
→ evidence report identity
→ report manifest
```

The generated bundle is presently correct, but its independent validator can accept a jointly altered inventory file and outer manifest hash. Approval therefore remains blocked.

## Required Bounded Remediation

Modify only the external report validator and focused tests.

Add a strict source-inventory validation helper that:

1. Requires the top-level report schema version and exactly the expected `v1` and `v2` source entries.
2. Requires each source key to match its `source_name` and expected trial name.
3. Validates file records as canonical, sorted, unique relative paths with non-negative integer sizes and lowercase 64-character SHA-256 values.
4. Recomputes each `inventory_sha256` from exactly:

```python
{
    "source_name": source_name,
    "trial_name": trial_name,
    "files": canonical_files,
}
```

5. Recomputes `source_inventory_id` from exactly the canonical source-inventory semantic payload and requires equality.
6. Derives `{v1: inventory_sha256, v2: inventory_sha256}` from the validated inventory file.
7. Requires those derived hashes to equal both:

```text
evidence_report.report_identity.source_inventory_hashes
report_manifest.source_inventory_hashes
```

Do not change report semantics, report ID, source roots, or existing output bytes. The existing generated report bundle should validate after the fix without regeneration.

Add an adversarial regression test matching the independent attack: alter a nested source file hash, recompute the outer inventory-file SHA in the manifest, and require rejection. Also cover forged per-source `inventory_sha256`, forged `source_inventory_id`, duplicate/unsorted paths, and mismatched v1/v2 source names when practical.

## Blast Radius and Affected Flows

Expected remediation scope:

```text
scripts/build_trendline_family_candidate_evidence_report.py
tests/scripts/test_trendline_family_candidate_evidence_report.py
plans/coder-to-review-trendline-family-candidate-evidence-report-integrity-v1.md
.codebase-memory/
```

Must remain unchanged:

- both v1 and v2 candidate trial roots;
- all four generated report files;
- canonical trendline-family and optimization code;
- Binance adapter and network behavior;
- YAML and runtime configuration;
- tracker, interaction, MTF, RegimeV2, signal, and selection paths.

No data request, Phase-I rerun, report regeneration, holdout action, metric reinterpretation, or tracker work is authorized.

## Validation Confirmations

The following independently passed before identifying the blocker:

```text
focused report tests:                    6 passed
optimization + research lab:            54 passed
full trendline family:                  347 passed
family + adapter/projected isolation:   375 passed
RegimeV2 + selection + signals:         148 passed
Ruff:                                   passed
compileall:                             passed
git diff --check:                       passed
```

One existing OpenTelemetry deprecation warning remains.

Independent positive checks:

```text
source roots unchanged after rerender:  true
report files unchanged after rerender:  true
primary trials:                         6
counterfactual results:                12
parameter-effect audits:               12
winner:                                 None
decision:                               REJECT
rationale:                              no_validation_trial_passed_stage_owned_gates
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   45,598
edges:   143,751
status:  ready
```

## Approval Status

**REQUEST CHANGES.**

The report's semantic conclusions and immutable source evidence are accepted, but the external bundle cannot be approved until source-inventory semantics are independently rederived and cross-bound.

## Recommended Handoff

Create and execute:

```text
plans/architect-to-coder-trendline-family-candidate-evidence-report-integrity-v1.md
```

The task must be validator/test-only and must stop after the existing report bundle passes the strengthened independent validation.