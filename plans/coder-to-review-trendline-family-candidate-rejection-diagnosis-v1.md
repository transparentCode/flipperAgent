# Coder To Review: Trendline-Family Candidate Rejection Diagnosis v1

## Scope Executed

Implemented the bounded, read-only candidate-rejection diagnosis specified by
`architect-to-coder-trendline-family-candidate-rejection-diagnosis-v1.md`.

- Rebuilt and verified the persisted 732-row BTCUSDT/4h input frame.
- Validated the approved external evidence report and verified Phase-I artifact bundle.
- Resolved current `configs/trendline_family.yaml` and required the persisted BTCUSDT/4h config hash.
- Replayed only the three persisted validation windows for baseline plus the six verified primary configurations.
- Ran exactly 2,016 actual canonical provider calls and 1,969 permitted low-quality diagnostic shadow calls.
- Wrote only an external, content-addressed diagnosis bundle.

No network request, Phase-I execution, future-outcome calculation, holdout access, configuration write, recommendation, or runtime work occurred.

## Files Changed

- `scripts/diagnose_trendline_family_candidate_rejection.py`
- `tests/scripts/test_trendline_family_candidate_rejection.py`
- `artifacts/trendline_family_candidate_diagnostics/btcusdt_4h_20250801_20251201_candidate_geometry_v2/source_binding.json`
- `artifacts/trendline_family_candidate_diagnostics/btcusdt_4h_20250801_20251201_candidate_geometry_v2/rejection_diagnosis.json`
- `artifacts/trendline_family_candidate_diagnostics/btcusdt_4h_20250801_20251201_candidate_geometry_v2/rejection_diagnosis.md`
- `artifacts/trendline_family_candidate_diagnostics/btcusdt_4h_20250801_20251201_candidate_geometry_v2/diagnosis_manifest.json`
- This handoff.

Generated codebase-memory index files were refreshed as required.

## Source Identity

- Dataset: `trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53`
- Resolved config hash: `da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`
- Phase-I run: `trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7`
- Evidence report: `trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41`
- Recommendation: `trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc`
- Diagnosis: `trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf`
- Source binding: `trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a`

## Source Immutability

Before/after canonical inventories match for:

- V1 trial root: 1 file.
- V2 trial root: 30 files.
- Approved report bundle: 4 files.
- `configs/trendline_family.yaml`: SHA-256 `7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8`.

The report-file hashes remain the approved values. The diagnosis output is outside every protected source root.

## Dataset And Fold Boundaries

- 732 complete UTC 4h bars, from `2025-08-01T00:00:00Z` through `2025-11-30T20:00:00Z`.
- Three expanding validation windows of 96 bars each: positions `252-347`, `360-455`, and `468-563`.
- Purge: 12 bars. Label horizon: 12 bars. Planned holdout: positions `636-731`.
- The maximum replayed position was 563; every replayed position was before the holdout boundary.

## Configuration Matrix

The canonical matrix was baseline plus the six persisted primary configurations:

- Baseline: lookback 180, quality 0.35.
- 120 / 0.30 and 120 / 0.40.
- 180 / 0.30 and 180 / 0.40.
- 240 / 0.30 and 240 / 0.40.

No new override value or grid enumeration was introduced.

## Replay Call Accounting

- Actual calls: 2,016 = 7 configurations x 288 validation positions.
- Diagnostic shadow calls: 1,969, exactly one for every actual `rejected_low_quality_candidates` result.
- Actual provider results and per-fold status totals exactly reconcile with the persisted Phase-I evidence.
- Shadow configuration changed only `candidate.min_candidate_quality` to `0.0`; every shadow candidate was below its actual threshold and matched the actual fitted-path count.

## Status Reconciliation

All 2,016 actual calls were either `rejected_low_quality_candidates` or `valid`.

- Baseline and five primary configurations: 288 low-quality rejections, 0 valid candidates.
- 120 / 0.30: 241 low-quality rejections and 47 valid candidates.
- `insufficient_data`, `no_confirmed_pivots`, `no_valid_fitted_paths`, and `provider_config_error`: 0 for every configuration and fold.

Therefore the observed scarcity was not caused by data sufficiency, causal pivots, fitting availability, or provider/config errors. It occurred at the minimum-quality gate.

## Low-Quality Decomposition

- Each low-quality bar exposed two shadow candidates, one support and one resistance.
- All candidate quality provenance was `anchor_span_coverage_v1`.
- The 120 / 0.30 configuration exposed 482 candidates behind 241 rejections. Its rejected quality maxima by fold were 0.142857, 0.226891, and 0.294118; only the final fold had near misses within 0.01 of the 0.30 threshold (15 candidates).
- Longer lookbacks had lower observed pre-threshold quality distributions. For example, 180 / 0.30 maxima were 0.201117, 0.245810, and 0.206704 across the folds.
- The full distributions, threshold gaps, near-miss counts, path lengths, anchor spans, roles, and quality method are in `rejection_diagnosis.json`.

## Parameter Contrasts

These are descriptive fixed-dataset contrasts only.

- Raising the threshold from 0.30 to 0.40 at lookback 120 changed 47 bars from valid to low-quality rejected and removed 47 accepted candidates. It did not change pre-threshold quality.
- The same threshold contrast at lookbacks 180 and 240 changed no status because neither setting produced a valid candidate at 0.30.
- Moving from lookback 120 / 0.30 to 180 / 0.30 or 240 / 0.30 changed 47 bars from valid to low-quality rejected and removed 47 accepted candidates. The mean maximum exposed-quality deltas were -0.049763 and -0.074540 respectively.
- Baseline 180 / 0.35 exactly matched both 180 / 0.30 and 180 / 0.40 on this validation replay: no status, accepted-count, or exposed-quality difference.

## Productive-Trial Gate Deficit

The only configuration with defined persisted `reaction_quality` was 120 / 0.30.

- Trial/result: `trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb` / `trendline-family-trial-result_64c2b7ef5ecd1ea872a1fd057856543163109317dda1a6b5b437d07cd66fcc64`.
- Aggregate reaction quality: 0.292929; per-fold values: 0.333333, 0.0, 0.545455.
- Sample count: 47; required minimum: 100; deficit: 53.
- Defined folds: 3/3; fold coverage: 1.0; failure rate: 0.0.
- Outcome-horizon exclusions: 19.
- Accepted/producing bars and candidates: 47 / 47.
- Sole objective-gate rejection: `minimum_sample_count_not_met`.

## Evidence-Based Observations

- On the approved validation evidence, all candidate-generation paths survived to the quality filter; none abstained for missing data, pivot scarcity, fitting failure, or provider configuration.
- The only productive setting was 120 / 0.30. Its accepted population was insufficient for the already-fixed minimum-sample gate, despite full fold coverage and zero failed windows.
- The shadow evidence uses an exact causal provider replay and is diagnostic-only. It does not create objective metrics, trial ranking, a recommendation, or a runtime implication.

## Diagnosis Bundle Identity

The external bundle validates independently and uses atomic, non-identical-overwrite-rejecting writes.

- `source_binding.json`: SHA-256 `96bcdd5ad07429e5021675326b344c1142318423bfcbe40929f72c047d600d7d`
- `rejection_diagnosis.json`: SHA-256 `8a17b8b514d04c7ce12410906d9ef3169723a7549fc872878429c505fdf96c3a`
- `rejection_diagnosis.md`: SHA-256 `a548e4815e9c0ca8d254199fce71c506c7f8a0bedd6ec176085bdfd94ff04fa3`
- `diagnosis_manifest.json`: SHA-256 `8530208d3a306e4ff802231e60eab53e4ca938cd7990564a43fa54b03045b389`

## Runtime And Regime Isolation

- The diagnosis runner has no network, market-data adapter, Phase-I runner, evaluator, holdout, or tracker boundary.
- It does not import or call RegimeV2, signal, selection, runtime, or YAML-write paths.
- Codebase-memory has no production runtime caller for `build_rejection_diagnosis`.

## Tests

- Focused diagnosis tests: 8 passed.
- Trendline-family optimization and research-lab tests: 54 passed.
- Full trendline-family suite: 347 passed.
- Trendline-family plus RegimeV2 adapter and projected-runtime isolation: 375 passed.
- RegimeV2, trendline feature producer, selection, and signals: 148 passed; one existing OpenTelemetry deprecation warning.
- Ruff, compileall, `git diff --check`, independent diagnosis-bundle validation, and canonical source-inventory equality passed.

## Codebase-Memory

Reindexed successfully after implementation.

- Project: `Users-aloobhujia-flipperAgent`
- Status: ready/indexed.
- Nodes: 45,996.
- Edges: 145,393.

Scope review found this runner has no production runtime caller. Existing unrelated dirty files remain outside this task and were not modified.

## Known Gaps

- This diagnosis is intentionally not a new optimization trial and does not recommend a parameter change.
- It does not answer whether a different data window, structural-density protocol, or objective sample gate should be approved. Those are separate planner decisions.
- No PnL, signal, or live-runtime claim is supported by this evidence.

## Next Handoff

Planner review only. Decide whether to authorize a separately bounded research plan addressing either structural candidate density, the observed quality distribution, or validation-sample support. Do not begin a new candidate or tracker trial from this handoff alone.
