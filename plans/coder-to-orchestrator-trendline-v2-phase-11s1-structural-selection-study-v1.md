# Coder Handoff: Trendline V2 Phase 11S.1 Structural Selection V2

## Status

`REMEDIATION_APPLIED_PENDING_REVIEW`

Offline study only. No commit, runtime selector change, promotion, provider
execution, network request, holdout evaluation, tracking change, interaction
change, YAML change, or viewer change.

## Scope

- Branch: `research/trendline-v2-phase-11s1-structural-selection-study-v1`
- Base: `fad0ffc0f51953cd83fc6cb08af63751f36140f5`
- Git files changed: exactly three
  - `scripts/analyze_trendline_v2_structural_selection.py`
  - `tests/scripts/test_trendline_v2_structural_selection.py`
  - `plans/coder-to-orchestrator-trendline-v2-phase-11s1-structural-selection-study-v1.md`
- No file under `src/` changed.
- Generated study artifacts remain outside Git.

## Contract

- Schema: `trendline_v2_phase_11s1_structural_selection_study_v1_contract`
- Contract ID: `41c6054577193d64e4bf2ff985d40571e9f75427bfbf47508e3b673ee9e32b54`
- Exact payload is persisted in `study_contract.json` and re-derived by the
  offline verifier.
- Checkpoint policy: 336-hour warmup, daily checkpoints, candidate availability
  no later than checkpoint, future evaluation strictly after checkpoint, and
  24h/48h/96h horizons.
- Structural eligibility: at least 96 hours between anchors, causal exact-side
  validity through checkpoint, exact candle-range contact, and no future fields
  used for membership.
- Redundancy: same-role shared-anchor suppression or <=25 bps projected-price
  distance with <=10 bps/day slope distance, applied greedily in rank order.
- Budgets: 4, 6, and 8 per role.

## Frozen sources

Phase 9C.2 validation/holdout bundle:

- Root: `/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701`
- Decision: `4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c`
- Manifest: `beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81`
- Output inventory: `ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532`
- Underlying Phase 9C.1 source inventory: `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be`
- Validation datasets: BTCUSDT 1h/4h and ETHUSDT 1h/4h.
- Locked holdout datasets: SUIUSDT 1h/4h.

Phase 10C.2 temporal bundle:

- Root: `/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401`
- Replay contract: `166b156a471f06dcc2d4fbf09196df95c4648e4b60cac52d1d315f7e7794af96`
- Decision: `ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6`
- Manifest: `4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5`
- Output inventory: `64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c`
- Underlying Phase 10C.1 source inventory: `872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f`
- Five BTCUSDT 4h checkpoints were not opened because no validation finalist
  existed.

Source inventories were captured before and after study execution and matched
the pinned identities. Prior generated Phase 11S.1 bundles were preserved under
`/tmp/trendline_v2_phase11s1_structural_selection_superseded/` and are not
canonical evidence.

## Selector set

Diagnostic-only baseline:

- `latest_valid_predecessor_v1`; no budget; cannot win.

Matched controls:

- `hash_order_matched_budget_v1`: `candidate_structure_id`, then `candidate_id`.
- `nearest_projection_matched_budget_v1`: current distance ascending, span
  descending, structure ID, candidate ID.

Structural contenders, each at budgets 4/6/8:

- `span_prominence_clearance_v1`
- `prominence_span_clearance_v1`
- `contact_span_prominence_v1`
- `multiswing_balanced_v1`

All rankings are exact lexicographic order. No weighted score was introduced.
Stability uses `candidate_structure_id`, never observation-bound `candidate_id`.

## Dense baseline evidence

Phase 10C.2 checkpoint 1, 2025-12-01T00:00:00Z:

- Raw candidates: `2697`.
- Available records: `2697`.
- Latest predecessors: `321`.
- Support/resistance: `153 / 168`.
- Effective prefix: `732` rows.
- Raw candidates/bar: `3.6844262295081966`.
- Selected latest-predecessor lines/bar: `0.4385245901639344`.
- Active segment crowding: min `0`, median `2.0`, p95 `4.0`, max `5`.
- Anchor-span bars: min `2`, median `4`, max `39`.
- Span `<=4`: `200`; span `<=8`: `300`; span `>=24`: `2`.
- Full span distribution is persisted in `decision.json` under
  `dense_diagnostic_baseline.anchor_span_bars.distribution`.
- Baseline ID: `7b746548c44ac231e09a35a0f2957683e52979a6a3c04e7b6322d27441f15d66`.

## Validation result

Decision status:

`NO_STRUCTURAL_SELECTION_FINALIST`

Validation lock:

- Lock ID: `fc2efdd33f0d6de8bd4006da7a175b19e144a639cde5a3cb0e1df7eac542b48a`
- `locked_finalist: null`
- Holdout membership was not loaded.
- Temporal membership was not loaded.

All 12 contender-budget variants failed validation. Main evidence:

| contender | budget | pooled 48h survival delta | pooled 96h survival delta | pooled 96h contact+survival delta | worst-dataset 96h survival delta |
|---|---:|---:|---:|---:|---:|
| span_prominence_clearance_v1 | 4 | -0.057995 | -0.076773 | -0.004550 | -0.121898 |
| span_prominence_clearance_v1 | 6 | -0.042340 | -0.056947 | -0.003800 | -0.088764 |
| span_prominence_clearance_v1 | 8 | -0.043269 | -0.059829 | -0.002306 | -0.080723 |
| prominence_span_clearance_v1 | 4 | -0.031186 | -0.045685 | -0.002679 | -0.112583 |
| prominence_span_clearance_v1 | 6 | -0.033510 | -0.054228 | -0.001010 | -0.076262 |
| prominence_span_clearance_v1 | 8 | -0.032567 | -0.052987 | -0.001241 | -0.066068 |
| contact_span_prominence_v1 | 4 | -0.055949 | -0.061667 | -0.008197 | -0.099290 |
| contact_span_prominence_v1 | 6 | -0.053103 | -0.057234 | -0.006598 | -0.086792 |
| contact_span_prominence_v1 | 8 | -0.054306 | -0.058472 | -0.004861 | -0.087425 |
| multiswing_balanced_v1 | 4 | -0.055536 | -0.070355 | -0.006360 | -0.115232 |
| multiswing_balanced_v1 | 6 | -0.043060 | -0.057352 | -0.002379 | -0.088764 |
| multiswing_balanced_v1 | 8 | -0.041169 | -0.056575 | -0.002537 | -0.080723 |

Role-count coverage also failed on at least one validation dataset for every
variant. Full per-checkpoint membership, selected counts, span distributions,
current validity, redundancy, future contact/survival and stability rows are
in the six dataset artifact files. All persisted selected records had current
validity `1.0`; observed failures came from coverage, span, stability and/or
utility gates, not hidden invalid-line acceptance.

Validation gate results and rejection reasons are persisted in
`decision.json.validation_gate_results`. The lock binds all four validation
dataset result IDs and all frozen source identities before any holdout path.

## Holdout and temporal boundary

Holdout:

- Status: `NOT_OPENED_BEFORE_VALIDATION_LOCK`.
- `suiusdt_1h` and `suiusdt_4h` files contain explicit not-opened payloads with
  empty selector outputs.
- No holdout provider result was loaded or evaluated.

Temporal:

- Status: `NOT_OPENED_BEFORE_VALIDATION_LOCK`.
- BTCUSDT 4h temporal files contain explicit not-opened payloads.
- No Phase 10C.2 checkpoint was loaded for selection.

## Final artifacts

- Root: `/tmp/trendline_v2_phase11s1_structural_selection/20260522_20260701__20250801_20260401`
- Exact inventory: 21 files, 20 manifest members.
- Decision ID: `44ffc590402b49d25b44a327522411e2f5ffadce13607fe0ed957e5db02e3b9d`
- Manifest ID: `3c0f999220b4397bcfc208475c876fb79af1ec1df0bfc558d245bc56e3850930`
- Output inventory SHA-256: `3731fd6d35472002eae4ae81cc9eb0d87bfcdfbc8552e44209ba1ede46b2c4b3`

The final decision binds execution counts:

```text
provider_execution_count:   0
network_request_count:      0
configuration_variant_count: 0
parallel_execution_count:   0
```

## Validation

Completed:

- Structural-selection hermetic suite: `42 passed, 1 skipped`.
- Structural-selection external pinned verifier: `43 passed`.
- Required focused bundle suite: `97 passed, 8 skipped`.
- Viewer plus Trendline V2: `281 passed`.
- Protected Trendline Family: `400 passed`.
- Provider benchmark harness: `4 passed`.
- Frontend TypeScript/Node suite: `13 passed`.
- Frontend audit: `0 vulnerabilities`.
- Ruff: passed.
- compileall: passed.
- `git diff --check`: passed.
- Generated bundle self-verification: passed.
- Source inventory immutability: passed by bundle verifier and execution audit.
- Codebase-memory reindex: indexed, non-zero split indexes. `flipperAgent-src`
  has `22,773` nodes / `118,557` edges; `flipperAgent-tests` has `5,580`
  nodes / `23,487` edges; `flipperAgent-scripts` has `1,690` nodes / `7,685`
  edges; `flipperAgent-plans` has `5,313` nodes / `5,294` edges.
- GitNexus reindex: completed, `49,916` nodes / `83,015` edges. It reports
  stale branch metadata from another checkout; this is not approval evidence.

## Limitations and interpretation

- Evidence is descriptive research output only; candidate rows share anchors and
  overlapping geometry.
- Phase 11S.1 tests strict body-side validity only on each
  candidate's native/owner timeframe.
- It does not establish lower-timeframe invalidation semantics.
- An HTF trendline projected onto an LTF may cross LTF candle
  bodies without invalidating the owner-timeframe structure.
- No PnL, profitability, trading-policy, runtime, or production claim follows.
- `NO_STRUCTURAL_SELECTION_FINALIST` is valid evidence, not an implementation
  failure and not grounds to weaken gates or add selectors.
- No recommendation, parameter promotion, canonical YAML change, viewer hiding,
  tracking, interaction, MTF, or Regime integration is authorized.

`NO_STRUCTURAL_SELECTION_FINALIST` therefore rejects the tested
strict native-timeframe selector family. It does not prove that
tolerant, close-based, multi-anchor, hierarchical-pivot or MTF-owned
trendlines are impossible.

## Remediation record

- Validation lock is staged, persisted, reloaded and identity-checked before any
  finalist-only holdout loader.
- Existing output roots are rejected before source loading.
- Publication uses one pre-created staging directory and atomic directory
  replacement; pre-publication failures remove staging.
- Offline tests cover causal future-row invariance, loader boundaries, lock
  ordering, atomic publication, cleanup, forged derived members, and source
  inventory immutability.

`PHASE_11S1_REMEDIATION: PENDING_ORCHESTRATOR_REVIEW`
`RUNTIME STRUCTURAL SELECTOR: NOT AUTHORIZED`
`PHASE_11B: BLOCKED`
`PHASE_12: NOT AUTHORIZED`
`MERGE/PUSH: NOT AUTHORIZED`
