---
goal: Validate lookback-dependent candidate quality against fixed-policy normalization formulas without execution or promotion.
stage: coder-to-review
date_created: 2026-07-13
last_updated: 2026-07-13
owner: Codex
status: Ready
tags: [handoff, quant, trendline-family, research, quality-normalization]
source_agent: Codex
target_agent: Quant Review
---

# Coder To Review: Candidate Quality Normalization Study v1

## Scope Executed

Created the isolated, read-only quality-normalization study and its evidence
bundle. It validates the approved diagnosis and density bundles, reconstructs
the exact matched candidate population, and evaluates only the declared
control plus fixed-horizon linear/saturating formulas.

Files created:

- `scripts/analyze_trendline_family_candidate_quality_normalization.py`
- `tests/scripts/test_trendline_family_candidate_quality_normalization.py`
- `artifacts/trendline_family_candidate_quality_normalization_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/source_binding.json`
- `artifacts/trendline_family_candidate_quality_normalization_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/quality_normalization_study.json`
- `artifacts/trendline_family_candidate_quality_normalization_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/quality_normalization_study.md`
- `artifacts/trendline_family_candidate_quality_normalization_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/study_manifest.json`
- `plans/coder-to-review-trendline-family-candidate-quality-normalization-study-v1.md`

## Changes Made

### Provenance And Artifact Safety

- Fixed source identity is `BTCUSDT` / `4h`, `732` rows, dataset hash
  `trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53`.
- Validated the approved diagnosis and density-study IDs and their source-binding IDs before analysis.
- Source binding contains strict four-file inventories for both bundles; paths, sizes, hashes, aggregate inventory hashes, and content-addressed binding ID are rederived.
- Bundle validator compares the external binding with live approved source bytes and independently rederives the entire study payload from those sources.
- Atomic writes are identical-only. A second generation was byte-identical.

### Matched Population And Current Method

- Reconciled `576` complete structural triplets: `288` support and `288` resistance, each matched over lookbacks `120`, `180`, and `240`.
- All `1,728` persisted current scores and coverage values satisfy
  `anchor_span_bars / (lookback_bars - 1)` within `1e-12` using `Decimal`.
- Raw anchor span is exact 4h-bar evidence. Candidate ID, role, ordered anchors,
  timestamps, and span are equal across every triplet.
- Path lengths and deltas are audit-only; formulas do not consume path length,
  recency, fold, role, outcomes, or empirical distributions.
- Current rank order is equal across lookbacks but absolute scores differ for all
  `576` triplets. Exact ratios are `179/119`, `239/119`, and `239/179`.

### Formula Evidence

- Formula catalog contains only `lookback_relative_anchor_span_coverage_v1`,
  plus `fixed_horizon_linear_v1` and `fixed_horizon_saturating_v1` for
  `H = 12, 24, 48, 96`.
- Fixed-horizon variants are bounded, monotonic, and exactly lookback invariant:
  `0` unequal score triplets for all eight variants.
- The control has `576` unequal-score triplets and fails only the structural
  lookback-invariance gate.
- Eligibility is architecture-only: eight fixed-policy instances are structurally
  eligible for a separately approved fresh unseen study. This is not a formula,
  horizon, threshold, lookback, finalist, or runtime selection.
- Deterministic distributions and exact-basis-point support curves include
  aggregate, fold, role, and fold-role evidence. They are descriptive only.

## Blast Radius Considered

Codebase-memory trace shows `build_candidate_quality_normalization_study(...)`
is called only by its script `main`; it has no production runtime caller. Its
only external dependencies are approved diagnosis/density validators and
canonical serialization contracts. No shared model, config, or runtime symbol
was edited.

## Validation Performed

- Focused quality study: `38 passed in 52.49s`.
- Optimization and research-lab regression: `54 passed in 21.00s`.
- Full trendline-family suite: `347 passed in 22.38s`.
- Trendline-family / RegimeV2 adapter / projected-runtime isolation: `375 passed in 26.95s`.
- RegimeV2, selection, and signals isolation: `175 passed in 16.60s` with one existing OpenTelemetry deprecation warning.
- Ruff and compileall passed.
- Read-only artifact validation passed; rerender was byte-identical.
- Protected inventories were identical before and after:
  v1 trial `1` file, v2 trial `30`, report `4`, diagnosis `4`, density `4`,
  and `configs/trendline_family.yaml` SHA remained
  `7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8`.
- Codebase-memory reindex: `46,860` nodes, `148,336` edges, `ready`.

## Evidence IDs And Hashes

- Quality source-binding ID:
  `trendline-family-candidate-quality-normalization-source-binding_483b0f334281e27e7d9d99bf41ce86c5d7839d90148a9d025e1c72ba35e62d94`
- Quality study ID:
  `trendline-family-candidate-quality-normalization-study_b45c8006cbe5304f36305fb1131e75173f32addc181d3e48e8d5bfd5cb71b0e3`
- `source_binding.json`:
  `413e08c7b604e0d9d065ebfdc7d1b9d631d8496ee3de06884a07bc3b01dea6f6`
- `quality_normalization_study.json`:
  `b5f1611524a268e770ec47cb275f47149371a63373695278cdb39736067b26e0`
- `quality_normalization_study.md`:
  `3dd4adf42f3f6349318343dfe082795f163576df8aa7a2343b13ff07aa461de1`
- `study_manifest.json`:
  `40eb8f53152ec9e330df93f9fa7c082fa31d8160ba9cd450b31727ce11bd64b8`

## Not Changed

No provider, pivot, fitter, evaluator, Phase-I, network, holdout, tracker,
runtime, YAML, RegimeV2, signal, selection, strategy, risk, execution, or
portfolio path was executed or changed. No canonical quality method, config,
parameter recommendation, or fresh-data trial was introduced.

## Risks Or Follow-Up Items

- All findings are post-diagnostic architecture evidence over already observed
  validation data. They are not OOS, alpha, or runtime evidence.
- Planned holdout remains sealed. Any comparison must use separately approved
  fresh unseen data and must not infer a selected formula or policy from this
  study.
- Review should confirm the large JSON audit is acceptable as a deterministic
  verification artifact and that no conclusion exceeds structural eligibility.

## Next Handoff

Independent review of this quality-normalization study only. Do not begin
canonical quality implementation, a fresh-data candidate trial, or tracker work
without separate approval.
