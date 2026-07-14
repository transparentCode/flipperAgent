# Coder To Review: Candidate Density Study v1

## Files Created

- `scripts/analyze_trendline_family_candidate_density.py`
- `tests/scripts/test_trendline_family_candidate_density.py`
- `artifacts/trendline_family_candidate_density_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/source_binding.json`
- `artifacts/trendline_family_candidate_density_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/candidate_density_study.json`
- `artifacts/trendline_family_candidate_density_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/candidate_density_study.md`
- `artifacts/trendline_family_candidate_density_studies/btcusdt_4h_20250801_20251201_candidate_geometry_v2/study_manifest.json`
- `plans/coder-to-review-trendline-family-candidate-density-study-v1.md`

## Fixed Source Identities

- Asset/timeframe: `BTCUSDT` / `4h`; confirmed rows: `732`.
- Dataset: `trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53`.
- Resolved config: `da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`.
- Phase-I/report/recommendation IDs match approved diagnosis.
- Diagnosis ID: `trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf`.
- Diagnosis source-binding ID: `trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a`.
- Study source-binding ID: `trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6`.
- Study ID: `trendline-family-candidate-density-study_a1160637adbf58bc9a3b8a40cd4b79aa817f2749235ca883c799e03b1b429941`.

## Source Immutability Evidence

Pre/post protected inventories match:

- v1 trial root: `1` file.
- v2 trial root: `30` files.
- Approved report bundle: `4` files.
- Approved diagnosis bundle: `4` files.
- `configs/trendline_family.yaml` SHA: `7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8`.

Study writes only external density artifact root. Existing diagnosis bundle was
validated through `validate_diagnosis_bundle(...)` before analysis.

## Canonical Exposure Reconciliation

For each lookback `120`, `180`, `240`, persisted `0.40` records reconstruct:

- `288` validation bars;
- `576` exposed candidates;
- `288` support and `288` resistance candidates;
- only `anchor_span_coverage_v1`;
- two candidates per bar, all below `0.40`.

Exact reconciliation passed:

- `120 / 0.30`: `47` candidates on `47` producing bars.
- `120 / 0.40`: `0`.
- `180 / 0.30`, baseline `180 / 0.35`, `180 / 0.40`: `0`.
- `240 / 0.30`, `240 / 0.40`: `0`.

## Threshold-Support Summary

Decimal threshold curves cover `0` through `4000` basis points in `100`-bps
steps. Counts and producing bars are monotonic non-increasing. Descriptive
minimum-sample frontiers cross below `100` at:

- lookback `120`: `1300` bps;
- lookback `180`: `900` bps;
- lookback `240`: `700` bps.

These are post-diagnostic support descriptions only. No threshold/lookback
selection, finalist, config patch, objective change, or promotion was created.

## Provenance Validation

Study validator rederives diagnosis inventory hash, study source-binding ID,
study ID, source/JSON/Markdown hashes, manifest claims, and external-versus-
embedded binding equality. It compares external provenance with current
validated diagnosis source bytes. Copied-bundle attacks with rebound manifest
claims reject.

## Artifact Hashes

- `candidate_density_study.json`: `ff199d197ce382a8da999b0d465827d6fed5fac89c327f7c5365f5fe20c25e28`
- `candidate_density_study.md`: `e6d8cf1fba5a576debe88990f3c6dec3b289f2bb35cc3858448542b2c55b05d3`
- `source_binding.json`: `0250a8a5723f3e5ad2e06c0858dae2d187bebb9583d882356a1814ba1a89bcfb`
- `study_manifest.json`: `fed6d24f334b2fa55faecfa7f4b54af755044869ac9a0fbb64424d17c2e29b4d`

Second generation was byte-identical. Independent study-bundle validation
passed read-only.

## Tests

- Focused density study: `33 passed`.
- Optimization/research support: `54 passed`.
- Full trendline-family: `347 passed`.
- Family/RegimeV2-adapter/projected-runtime isolation: `375 passed`.
- RegimeV2/selection/signals isolation: `148 passed`, one existing OpenTelemetry deprecation warning.
- Ruff, compileall, `git diff --check`: passed.

Architecture handoff referenced absent `tests/regime_v2` and `tests/selection`
directories. Current equivalent suites were used: `tests/models/regime_v2/adapters`,
`tests/test_regime_v2.py`, `tests/test_regime_v2_trendline_feature_producer.py`,
and `tests/test_selection_layer.py`.

## Codebase-Memory

Reindexed successfully: `46,435` nodes, `146,912` edges, status `ready`.
`build_candidate_density_study(...)` has only script `main` caller; no
production runtime caller.

## Known Gaps

Study is validation-only, post-diagnostic research. Planned holdout remains
sealed. Any follow-up must use separately approved fresh unseen data.

## Isolation Confirmation

No provider replay, evaluator, network, new data, Phase-I execution, holdout
access, tracker, interaction, MTF, RegimeV2, signal, selection, runtime, YAML,
or config work occurred.

## Next Handoff

Independent density-study review. Do not start fresh-data candidate or tracker
work without separate approval.
