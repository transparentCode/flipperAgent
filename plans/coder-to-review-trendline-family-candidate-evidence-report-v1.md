# Coder To Review: Trendline-Family Candidate Evidence Report v1

## Scope Executed

Built one deterministic, read-only reviewer report from the existing verified
BTCUSDT 4h candidate/geometry v2 evidence. The report generator does not fetch
data, run an evaluator, open holdout, or modify either immutable trial root.

## Files Changed

- `scripts/build_trendline_family_candidate_evidence_report.py`
- `tests/scripts/test_trendline_family_candidate_evidence_report.py`
- `artifacts/trendline_family_candidate_reports/btcusdt_4h_20250801_20251201_candidate_geometry_v2/source_inventory.json`
- `artifacts/trendline_family_candidate_reports/btcusdt_4h_20250801_20251201_candidate_geometry_v2/evidence_report.json`
- `artifacts/trendline_family_candidate_reports/btcusdt_4h_20250801_20251201_candidate_geometry_v2/evidence_report.md`
- `artifacts/trendline_family_candidate_reports/btcusdt_4h_20250801_20251201_candidate_geometry_v2/report_manifest.json`

## Source Evidence

V1 and V2 inventories were captured before generation and compared after it.

- V1: 1 file; inventory SHA-256 `48ad089646b395641b5c7d28d75705a01490b7564248aed5231aba6ce602e892`.
- V2: 30 files; inventory SHA-256 `d5d02fa4537f334d36d2b84d92b820eb0e1677d150f1d9cd345fa169d471ace5`.
- Output source inventory ID: `trendline-family-candidate-source-inventory_2711380b554260b5ccff67ede6aa060faf124ed76b8369a97be54edb78dfd8d8`.

## Input Verification

Verified persisted input only:

- `BTCUSDT`, Binance USD-M Futures, `4h`.
- `2025-08-01T00:00:00Z` through `2025-12-01T00:00:00Z`.
- 732 complete, unique, four-hour-spaced rows from `2025-08-01T00:00:00Z` to `2025-11-30T20:00:00Z`.
- Normalized CSV SHA-256: `b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150`.
- Rebuilt immutable frame hash: `trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53`.
- The CSV uses IEEE-754 round-trip parsing so its persisted values reproduce the original audited frame hash exactly.

## Phase-I Verification

Loaded only through `load_verified_phase_i_artifacts(...)`.

- Candidate-only Phase-I run: `trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7`.
- Dataset and baseline config identities matched. Resolved config hash: `da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`.
- Six primary trials and twelve verified counterfactual results were present exactly once.
- No finalist, finalist freeze, holdout-open audit, baseline holdout, or finalist holdout evidence exists.

## Report Identity

- Report ID: `trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41`.
- JSON SHA-256: `07e50ea26318db77ecd034085bd068792227a165d5872cb71f9d818a2e533242`.
- Markdown SHA-256: `b68adbb22707097ea352b3fb8baa238c5b2a88542a7b24d9bc6744703c6a4cf0`.
- Source-inventory file SHA-256: `45197651e25e65561fdb16e2676117ac6409527e233dbb5c7055fcd27efcf6ab`.

`report_manifest.json` binds all report hashes, source inventories, dataset and
run identities, verified source artifact hashes, and recommendation ID.

## Dataset And Configuration

The persisted request was exactly `BTCUSDT`, `4h`, `since=1754006400000`,
`until=1764547200000`, `limit=1000`. The report records the persisted raw and
normalized manifests, request provenance, baseline candidate parameters, model
and config versions, and `yaml_changed: false`.

## Outcome Policy

Verified semantic inputs:

- `horizon_bars=12`, `atr_window=14`.
- `touch_tolerance_atr=0.25`, `survival_penetration_atr=0.75`.
- `reaction_threshold_atr=0.5`.
- `candidate_structural_outcome_btcusdt_4h_v1`.

## Fold And Holdout Evidence

The report contains all three expanding folds, each with 96 validation bars,
12 purge bars, 180-bar warmup, label horizon 12, and the planned 96-bar
holdout from `2025-11-15T00:00:00Z` to `2025-11-30T20:00:00Z`.

The holdout is a plan boundary only. Verified status is exactly: finalist
`None`; freeze, holdout-open audits, baseline holdout result, and finalist
holdout result all `absent`.

## Search Request Set

The complete fixed grid was retained: `candidate.lookback_bars` in `120, 180,
240`, and `candidate.min_candidate_quality` in `0.3, 0.4`; maximum six trials,
seed zero. The report sorts all primary evidence canonically by parameter
overrides then trial ID and records no missing or extra IDs.

## Baseline Evidence

Baseline completed but emitted zero candidates over 288 validation rows. All
three windows were invalid for the primary metric; provider status was
`rejected_low_quality_candidates: 288`. Its gate failed on maximum failure
rate, minimum fold coverage, and undefined primary metric.

## Primary Trial Evidence

All six primary results completed and are reported with per-fold metrics,
aggregate/worst-window metrics, provider statuses, exclusions, candidate
density/balance, touch/survival/reaction/penetration metrics, gate evidence,
and counterfactual IDs.

- `lookback_bars=120`, `min_candidate_quality=0.3` emitted 15.6667 average candidates and reaction quality `0.292929`; it still failed the minimum-sample gate.
- The other five configurations emitted zero candidates, had undefined reaction quality, and failed failure-rate, fold-coverage, and undefined-primary-metric gates.

No trial ranking beyond the canonical Phase-I decision is asserted.

## Counterfactual And Audit Evidence

All 12 marginal counterfactuals and parameter-effect audits are preserved.
Three audits detected their expected owned-stage change; nine did not. Every
audit reported `leakage_detected: false`. These audit decisions do not override
the persisted promotion decision.

## Recommendation

Verified canonical recommendation:

- Winner: `None`.
- Decision: `REJECT`.
- Rationale: `no_validation_trial_passed_stage_owned_gates`.
- Promotion gate: `false`.
- Recommendation ID: `trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc`.

## Bounded Interpretation

The bundle is internally verified, but no primary validation candidate passed
the stage-owned gates. There is therefore no finalist or holdout evaluation and
no support for configuration or runtime promotion. Structural evidence here
does not establish PnL, trade, or live utility. Any subsequent research needs a
separate approved plan.

## Source-Root Integrity

The V1/V2 byte-level inventories matched exactly before and after report
generation. The generator only created the four external report files and
refuses non-identical overwrites.

## Runtime And Regime Isolation

No network, Binance adapter, evaluator, holdout, YAML, runtime configuration,
tracker, interaction, MTF, RegimeV2, signal, selection, or canonical model code
was changed. `run_phase_i_evaluation` remains outside production runtime paths.

## Tests

- Focused report suite: `6 passed`.
- Optimization and research support: `54 passed`.
- Full trendline-family suite: `347 passed`.
- Trendline-family plus adapter/shadow isolation: `375 passed`.
- RegimeV2, selection, and signal isolation: `148 passed`; one existing third-party OpenTelemetry deprecation warning.
- Ruff, compileall, and `git diff --check` passed.

## Codebase-Memory

The graph MCP transport was unavailable, so the CLI fallback was used. The
repository was reindexed successfully: 45,598 nodes, 143,751 edges, status
`indexed`.

## Known Gaps

This report intentionally does not diagnose, repair, or rerun the rejected
candidate trial. It contains no holdout, PnL, or runtime evidence.

## Next Handoff

Independent review of the report implementation and immutable output bundle.
Do not start tracker work unless a separate approval decision authorizes it.
