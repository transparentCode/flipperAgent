---
goal: Review the failed BTCUSDT 4h saturating-quality fresh-window attempt and define the required remediation boundary.
stage: review-to-architect
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Quant Review
status: Request Changes
tags: [handoff, quant, trendline-family, candidate, fresh-window, persistence, provenance]
source_agent: Quant Review
target_agent: Quant Architect
---

# Review To Architect: Saturating-Quality Fresh-Window Trial v1

## Review Scope

Reviewed:

```text
plans/architect-to-coder-trendline-family-saturating-quality-fresh-window-trial-v1.md
plans/coder-to-review-trendline-family-saturating-quality-fresh-window-trial-v1.md
scripts/run_trendline_family_saturating_quality_fresh_window_trial.py
tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py
artifacts/trendline_family_saturating_quality_trials/
  btcusdt_4h_20251201_20260401_saturating_quality_v1/
```

The review covered request consumption, raw and normalized input persistence, reload identity, dataset hashing, execution ordering, provider/holdout exposure, artifact provenance, tests, protected-source immutability, and whether the failed window remains eligible as fresh unseen evidence.

## Findings By Severity

### Blocking 1 — Decimal CSV is not lossless for the hash-bound dataset

`persist_normalized_input(...)` writes the full normalized frame using:

```python
to_csv(..., float_format="%.17g")
```

`load_normalized_input(...)` reloads through `pandas.read_csv(...)`.

The exact persisted bytes are hash-bound, but the reconstructed IEEE-754 values are not guaranteed to equal the pre-persistence values. The failure is independently reproduced:

```text
manifest / raw-renormalized dataset hash:
trendline-family-dataset_6e8da3e2931937132b3f56a24e2a6098ed51ccb5ee678cce3c49f81099b167b0

reloaded normalized CSV dataset hash:
trendline-family-dataset_cfd9d4936b4bce5300c6858ef9a2ba387c27c7ccf5176655f6736bc26d6cb79a
```

Four cells changed by one binary-float step after CSV parsing:

```text
volume / 2026-01-09T20:00:00Z:
9449.964 -> 9449.964000000002

volume / 2026-01-29T04:00:00Z:
9421.294 -> 9421.294000000002

taker_buy_base / 2025-12-16T08:00:00Z:
9459.08 -> 9459.080000000002

taker_buy_base / 2026-03-07T04:00:00Z:
9576.928 -> 9576.928000000002
```

`hash_historical_frame(...)` intentionally hashes every normalized column, not only OHLCV, so auxiliary normalized columns participate in dataset identity.

The normalized persistence format is therefore not suitable as the canonical replay source.

### Blocking 2 — Reload identity is not checked before provider generation

The architecture required normalized bytes to be reloaded before candidate generation. The runner does reload them, but `run_trial(...)` does not immediately require:

```text
reloaded_dataset_hash == input_manifest.dataset_hash
reloaded_dataset_hash == raw_renormalized_dataset_hash
```

The mismatch is checked only inside `validate_trial_bundle(...)`, after:

- 288 validation provider calls;
- validation result generation;
- finalist freeze;
- 96 holdout provider calls;
- holdout evaluation;
- decision/report/manifest persistence.

This ordering allowed invalid-input downstream artifacts to be generated before the identity defect was detected.

A dedicated pre-generation persisted-input gate is mandatory. No provider call may occur until it succeeds.

### Blocking 3 — The same window is no longer fresh unseen evidence

Although the generated bundle is invalid, the trial code already evaluated the validation data and opened the planned holdout:

```text
validation provider calls: 288
holdout provider calls:      96
total provider calls:       384
validation finalist:        H=12
persisted decision:         REJECT_HOLDOUT_GATE
```

The 2025-12-01 through 2026-04-01 BTCUSDT window has therefore been research-exposed. Fixing serialization and rerunning the same window cannot restore unseen confirmation status.

The failed window may be used only for persistence remediation fixtures or explicitly post-failure diagnostics. It must not be reused for formula/horizon selection, holdout confirmation, promotion, or tracker authorization.

### Major 1 — The invalid root is not self-identifying as failed

The root contains both:

```text
research_decision.json
bundle_manifest.json
```

Neither file includes a verified/failed/quarantined status. A later reader could mistake `REJECT_HOLDOUT_GATE` and the bundle manifest for verified trial evidence.

The existing root must remain byte-identical, but an external failed-attempt/quarantine record must bind its complete inventory and state that every downstream artifact is non-evidence.

Current failed-root identity:

```text
file count: 21
inventory SHA-256:
eed973298ea04fb5a78f89134ce78191252e5a7e651b4b8aa4664ba10b0f6e2b

failed-attempt semantic ID:
trendline-family-saturating-quality-failed-attempt_c691cecf8226f6dfc97703750c596c50dd1d22a631b96c9f64074a671382b04e
```

### Major 2 — The round-trip fixture is not representative

The focused test fixture contains simple integral-like volume values and omits `taker_buy_base`. It therefore does not exercise the precision-sensitive Binance auxiliary decimals that caused the production failure.

A remediation test must include at least the four failing decimal values above and prove:

1. exact pre-persistence and post-reload dataset identity;
2. exact column order and dtypes/schema;
3. provider call count remains zero on any identity mismatch;
4. raw-renormalized, manifest, and persisted-reload hashes all agree before evaluation.

## Confirmed Correct Behavior

The following behavior was correct and should be preserved:

- exactly one authorized Binance request was consumed;
- raw response evidence was persisted before normalization;
- raw data normalized to exactly 726 confirmed bars;
- first/last timestamps matched the frozen contract;
- no retry, pagination, fallback, or alternate source was used;
- final bundle validation failed closed;
- protected prior evidence remained canonically byte-identical;
- no canonical trendline-family, YAML, runtime, tracker, MTF, RegimeV2, signal, selection, or application path was modified.

Protected source status:

```text
v1 candidate trial:  1 file
v2 candidate trial: 30 files
report bundle:        4 files
diagnosis bundle:     4 files
density bundle:       4 files
quality bundle:       4 files
config SHA-256:
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

## Required Architecture Remediation

The next phase must be persistence/gating remediation only. It must not execute a new market-data trial.

### Canonical normalized representation

Select a lossless, deterministic source-of-truth representation for normalized frames without changing global `hash_historical_frame(...)` semantics.

Preferred design:

- persist a canonical schema with ordered columns and explicit dtypes;
- encode float64 cells losslessly, for example IEEE-754 hexadecimal strings decoded through `float.fromhex`, or another independently proven bit-exact representation;
- keep a decimal CSV only as optional human-readable evidence, never as the replay identity source;
- bind source bytes, schema, column order, row count, timestamp boundaries, and reconstructed dataset hash in the input manifest.

Do not solve this by globally rounding or weakening dataset hash equality. Do not ignore auxiliary columns after the fact without a separately versioned canonical preprocessing/schema decision.

### Mandatory pre-generation gate

Add one pure gate that executes immediately after normalized persistence and reload. It must require all of:

```text
persisted normalized source byte hash matches manifest
reloaded normalized schema matches manifest
reloaded dataset hash matches manifest dataset hash
raw response re-normalization hash matches manifest dataset hash
row count is 726
first/last timestamps match
config and research-config hashes match
request identity matches
```

Only the dataset returned by this gate may be passed to fold construction or provider generation.

### Failed-attempt quarantine

Do not alter the 21-file v1 root. Create an external content-addressed quarantine record that binds:

- trial name and root relative path;
- exact 21-file inventory;
- request consumed once;
- raw/manifest/reloaded dataset hashes;
- failure reason `normalized_input_roundtrip_identity_drift`;
- `verified_trial_evidence: false`;
- `validation_artifacts_usable: false`;
- `holdout_artifacts_usable: false`;
- `window_freshness_consumed: true`;
- prohibition on same-window confirmation reuse.

### Test boundary

Use existing persisted raw bytes or a bounded copied fixture only. The remediation phase must perform:

```text
network requests: 0
provider calls:   0
evaluator calls:  0
holdout access:   0
```

## Blast Radius

Expected future remediation scope should be limited to:

```text
scripts/run_trendline_family_saturating_quality_fresh_window_trial.py
tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py
an external failed-attempt/quarantine artifact root
plans/coder-to-review-trendline-family-normalized-input-roundtrip-remediation-v1.md
.codebase-memory/
```

Do not modify:

- `src/libs/models/trendline_family/optimization/folds.py` or global dataset-hash semantics;
- canonical fitter/provider/tracker code;
- YAML/runtime configuration;
- any approved prior evidence bundle;
- the failed 21-file trial root;
- RegimeV2 or downstream runtime paths.

## Validation Evidence

Independently confirmed:

```text
focused runner tests: 14 passed
Ruff:                  passed
compileall:            passed
git diff --check:      passed
bundle validation:     failed as expected
codebase-memory:       48,175 nodes / 150,870 edges / ready
```

Direct validation failure:

```text
FreshWindowTrialError: input manifest identity drift
```

## Approval Status

**REQUEST CHANGES.**

The network stop/no-retry behavior is accepted, but the trial is not approved and none of its validation, holdout, decision, report, or bundle artifacts are admissible as research evidence.

## Recommended Handoff

Create:

```text
plans/architect-to-coder-trendline-family-normalized-input-roundtrip-remediation-v1.md
```

That handoff must authorize only lossless persistence, the immediate pre-provider identity gate, representative regression tests, and external failed-attempt quarantine.

After the remediation is independently approved, design a separate trial against a genuinely unobserved source/window. Do not authorize a same-window retry and do not begin tracker work.
