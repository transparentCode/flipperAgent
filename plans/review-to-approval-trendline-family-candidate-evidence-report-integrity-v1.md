# Review To Approval: Candidate Evidence Report Integrity v1

## Reviewed Scope

Independent review of the bounded source-inventory integrity remediation in:

```text
scripts/build_trendline_family_candidate_evidence_report.py
tests/scripts/test_trendline_family_candidate_evidence_report.py
plans/coder-to-review-trendline-family-candidate-evidence-report-integrity-v1.md
```

The review covered strict source-inventory semantics, forged-inventory rejection, cross-binding to the evidence report and report manifest, preservation of existing report identities, source/report byte immutability, and runtime isolation.

## Resolved Findings

The prior blocking provenance gap is closed.

`validate_source_inventory_payload(...)` now independently requires and verifies:

- exact report schema and exact `v1`/`v2` source membership;
- source key, source name, and fixed trial-name identity;
- exact source and file-record fields;
- non-empty, canonical, sorted, unique and safe POSIX relative paths;
- non-negative non-boolean integer file sizes;
- lowercase 64-character SHA-256 values;
- each per-source `inventory_sha256` from canonical source semantics;
- the aggregate `source_inventory_id` from canonical source-inventory semantics.

`validate_report_bundle(...)` now cross-binds the independently derived `{v1, v2}` inventory hashes to both:

```text
evidence_report.report_identity.source_inventory_hashes
report_manifest.source_inventory_hashes
```

The previously accepted attack now fails closed: changing a nested source-file SHA and recomputing only the outer source-inventory file SHA is rejected by the per-source inventory hash check.

## Remaining Non-Blocking Follow-Ups

None for this integrity remediation.

The validator intentionally proves the persisted external inventory semantic chain. It does not reread live source-root files during standalone report validation; source-root immutability was separately proven during report generation and this remediation.

The verified candidate result remains `REJECT`. No validation trial passed stage-owned gates, no finalist exists, and no holdout evidence exists. Tracker evaluation must not begin from this result.

## Blast Radius Confirmation

Changed behavior is limited to the standalone evidence-report validator and its focused tests.

Codebase-memory trace confirms:

```text
validate_report_bundle
→ build_candidate_evidence_report
→ main
```

No production runtime caller exists.

Unchanged:

- V1 trial root: 1 file;
- V2 trial root: 30 files;
- generated report bundle: 4 files;
- canonical trendline-family model and optimization semantics;
- Binance adapter and network behavior;
- YAML/runtime configuration;
- tracker, interaction, MTF, RegimeV2, signal and selection paths.

Verified report hashes remain:

```text
source_inventory.json  45197651e25e65561fdb16e2676117ac6409527e233dbb5c7055fcd27efcf6ab
evidence_report.json   07e50ea26318db77ecd034085bd068792227a165d5872cb71f9d818a2e533242
evidence_report.md     b68adbb22707097ea352b3fb8baa238c5b2a88542a7b24d9bc6744703c6a4cf0
report_manifest.json   7c6bd0d76501296dde5353d389daa5a0695a986468f59bb205298c84aae5378d
```

## Validation Evidence Summary

Independent validation:

```text
focused report/integrity suite:          25 passed
optimization + research support:         54 passed
full trendline-family:                  347 passed
family + adapter/projected isolation:   375 passed
RegimeV2 + selection + signals:         148 passed, 1 existing warning
Ruff:                                   passed
compileall:                             passed
git diff --check:                       passed
```

Existing report validates read-only with:

```text
report ID: trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41
v1 inventory hash: 48ad089646b395641b5c7d28d75705a01490b7564248aed5231aba6ce602e892
v2 inventory hash: d5d02fa4537f334d36d2b84d92b820eb0e1677d150f1d9cd345fa169d471ace5
decision: REJECT
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   45,667
edges:   143,970
status:  ready
```

## Recommended Approval Status

**APPROVE.**

The external candidate evidence report and its integrity validator are approved. This approval does not promote candidate parameters, authorize a new data request, open holdout, or authorize tracker work.

The next research phase should diagnose candidate scarcity and gate failure using the verified evidence before designing any new candidate/geometry trial.
