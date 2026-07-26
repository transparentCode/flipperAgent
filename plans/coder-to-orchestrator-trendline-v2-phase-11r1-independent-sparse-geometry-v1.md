# Coder-to-Orchestrator Handoff: Phase 11R.1 Contract-Freeze Final Remediation

## Result

READY_FOR_CONTRACT_FREEZE_REVIEW

One authorized study attempt occurred under canonical contract `3bcad03f…` and
published valid no-finalist evidence. The prior superseded-contract attempt
stopped fail-closed at validation checkpoint 23 before provider-quality
evaluation. No retry occurred. No provider, network, holdout, temporal, runtime,
YAML, tracking, interaction, viewer, or legacy-model change occurred. No commit
was created.

## Scope

Branch: research/trendline-v2-phase-11r1-independent-sparse-geometry-v1

Changed files: exactly these three untracked files:

- scripts/analyze_trendline_v2_independent_sparse_geometry.py
- tests/scripts/test_trendline_v2_independent_sparse_geometry.py
- this handoff

## Canonical contract freeze

Contract now has one explicit _contract_payload() implementation.
_legacy_contract_payload() was removed.

- Superseded reproducible candidate: 1772834e47020a6de9afe868a8bbec271702575d329e2cdbe7341a960a250afb
- Earlier superseded candidate: 60955f468158cd2961f9d3977b7d3cdba77ae8b0e5a214974ac6c5f9b348538d
- Canonical JSON byte length: 14905
- Canonical JSON SHA-256: deab0f575d7c9461cadc3d3925558b517ad41443c860133a9817f281ba08ae91
- Namespaced contract ID: 3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3
- Namespace: trendline_v2_phase_11r1_independent_sparse_geometry_feasibility_contract

Top-level payload keys, exact set:

schema_version, base_commit, prior_evidence, independence, scopes,
checkpoint_policy, atr, hierarchical_pivots, owner_timeframe_validity,
seed_pool, methods, scope_method_sets, research_line_contract, stability,
future_evaluation, validation, holdout, temporal_audit, execution_accounting,
matched_control_semantics, decision_statuses, artifacts, study_controls

## Method definitions

methods.primary contains only:

- hierarchical_multitouch_pair_v1: timestamp-space seed-pair geometry;
  initial population is every confirmed same-role pivot from first seed anchor
  through checkpoint; both seed anchors included; touch tolerance 0.35 ATR;
  one output per role. Ranking order:
  negative_scale_48_touch_count, negative_touch_count,
  negative_touch_scale_hours, negative_anchor_span_hours,
  last_touch_age_bars, current_distance_atr, seed_id.
- deterministic_theil_sen_multitouch_v1: unique touch-pair median slope,
  median intercept, one refit, minimum three inliers, initial touch tolerance
  0.35 ATR, inlier tolerance 0.5 ATR, both seed anchors included, one output
  per role. Ranking order:
  negative_scale_48_touch_or_inlier_count,
  negative_touch_or_inlier_count, negative_structural_span_hours,
  median_abs_inlier_residual_atr, last_touch_or_inlier_age_bars,
  current_distance_atr, refit_id.

methods.controls contains only:

- latest_wide_pair_control_v1: second_anchor_time_desc,
  first_anchor_time_desc, seed_id_asc.
- hash_wide_pair_control_v1: seed_id_asc.

Controls use same seed pool and cardinality. Scope method sets:

validation = hierarchical_multitouch_pair_v1,
             deterministic_theil_sen_multitouch_v1,
             latest_wide_pair_control_v1,
             hash_wide_pair_control_v1
holdout    = <locked_validation_winner>, latest_wide_pair_control_v1
temporal   = <locked_validation_winner>

Validation ranking order is exact:
gate_passed_desc, worst_dataset_96_zone_survival_delta_desc,
pooled_96_zone_survival_delta_desc, pooled_96_reaction_delta_desc,
median_continuation_desc, median_touch_desc, median_span_desc,
provider_id_asc.

## Contract semantics fixed

- Prefix rule: timestamp < checkpoint; only confirmed causal pivots.
- `confirmed_through` is an exclusive completion boundary, not a candle
  timestamp. Scheduling uses the final actual source timestamp and excludes a
  checkpoint without a complete 96-hour future window.
- One shared future-window validator requires exact count, ordering and
  timestamp sequence. Interior missing, duplicate or misaligned timestamps
  block; natural source-end insufficiency excludes the checkpoint.
- Cross-asset schedule: 22 checkpoints per dataset; 88 validation checkpoints
  across four datasets and 44 holdout checkpoints across two datasets.
- Projection, close, ATR, validity and distance are checkpoint-owned.
- Equal-price plateau grouping is consecutive-only; midpoint representative.
- Future zone: low <= line + 0.35ATR and high >= line - 0.35ATR.
- Reaction is evaluated only on bars strictly after first contact and before
  first sustained breach, using ATR from first contact bar. Contact candle
  cannot produce reaction; no intrabar order is assumed.
- Utility control samples use exact `(checkpoint_index, role)` keys from each
  primary provider. Latest-wide control must contain exactly one line for every
  primary key; missing keys block. Hash control remains descriptive only.
- Per-primary metrics persist matched sample keys, matched count, matched
  outcomes and latest-wide control identity. Per-dataset and pooled deltas use
  matched outcomes and counts, never unmatched control roles.
- Persisted future fields:
  survives_tolerant_owner_tf, has_zone_contact,
  zone_contact_and_survives, has_role_consistent_reaction,
  first_contact_offset_bars, first_sustained_breach_offset_bars.
- Exact future bars required: 1h 24/48/96; 4h 6/12/24. Missing,
  duplicated, or misaligned timestamps reject.
- Temporal source is prefix-only; future outcomes are explicitly not evaluated.
- Temporal gates only: five checkpoints; support present at least four;
  resistance at least four; both at least three; zero inversion; current
  validity 1.0; median span at least 168h; adjacent continuation at least
  0.40. Touch and distance gates do not apply temporally.
- Zero remains valid evidence. None is missing and fails required gates cleanly
  without TypeError.
- Validation lock binds source identities, dataset/result IDs, method IDs,
  704 validation derivations, ordered ranking, winner and holdout access. Lock bytes are
  reloaded, canonical-byte checked and identity rehashed.
- Verifier reconstructs every checkpoint from raw OHLCV with expected methods,
  stability, geometry, pivots, seed counts, provider evidence, future fields,
  matched checkpoint-role control samples, derivation identity and metrics.
- Publication requires exact 21-path inventory, shared deterministic CSV row
  builders, fresh-root refusal, staging cleanup and one atomic directory replace.
- CLI requires exactly one of --execute-study and --verify; generation also
  requires TRENDLINE_V2_ALLOW_PHASE11R1_STUDY=1. No parameter changes after
  results.

## Exact artifact inventory

cross_scope_summary.csv
datasets/btcusdt_1h/checkpoint_membership.json
datasets/btcusdt_1h/provider_metrics.json
datasets/btcusdt_4h/checkpoint_membership.json
datasets/btcusdt_4h/provider_metrics.json
datasets/ethusdt_1h/checkpoint_membership.json
datasets/ethusdt_1h/provider_metrics.json
datasets/ethusdt_4h/checkpoint_membership.json
datasets/ethusdt_4h/provider_metrics.json
datasets/suiusdt_1h/checkpoint_membership.json
datasets/suiusdt_1h/provider_metrics.json
datasets/suiusdt_4h/checkpoint_membership.json
datasets/suiusdt_4h/provider_metrics.json
decision.json
manifest.json
source_audit.json
study_contract.json
temporal/btcusdt_4h/checkpoint_membership.json
temporal/btcusdt_4h/provider_metrics.json
temporal_summary.csv
validation_lock.json

21 total files; 20 manifest members plus manifest.

## Protected evidence

- Phase 9C.2 output inventory: ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
- Phase 9C.2 source inventory: 631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be
- Phase 10C.2 output inventory: 64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c
- Phase 10C.1 source inventory: 872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f
- Phase 11S.1 inventory: 3731fd6d35472002eae4ae81cc9eb0d87bfcdfbc8552e44209ba1ede46b2c4b3

Quarantined prior bundle remains forensic-only under:
 /tmp/trendline_v2_phase11r1_independent_sparse_geometry_superseded/contract_mismatch_53c42d249ea51022/
Canonical output root:
 /tmp/trendline_v2_phase11r1_independent_sparse_geometry/20260522_20260701__20250801_20260401/

## Canonical study evidence

- Study status: `NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST`.
- Decision ID: `a06d0ca3a7a08b89db7a065133d5c30eeaa51800172187f4b75e7146e21e29fa`.
- Manifest ID: `6393883d533a6b56eb2abfb7b1402bee6eb75cfb366f59e942b7e44bb128ab32`.
- Output inventory: `17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50`.
- Validation lock: `ef381809b4d0155c625be28e752786099272910d7633a9c0d29101b8a2f81815`.
- Validation winner: none.
- Derivations: validation `704`, holdout `0`, temporal `0`; maximum `890`.
- Holdout and temporal: unopened.
- Validation-root inventory before/after: `ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532`.
- Pinned upstream Phase 9C.2 source inventory: `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be`.

## Failed attempt retained

- Failure checkpoint: validation checkpoint 23.
- Failure reason: exclusive `confirmed_through` boundary was mistaken for a
  row timestamp; final 96-hour timestamp was absent.
- Artifacts published: none.
- Holdout/temporal: unopened.
- Retry: none.

The initial external evidence run reported `76 passed, 1 failed` because its
`provider_rank` mutation assigned persisted rank value `0` back to `0`. The
test-only mutation now increments the original value, and the verifier rejects
the changed copied bundle. Canonical study artifacts were not regenerated.

## Validation

- Focused hermetic suite: 64 passed, 13 skipped.
- Ruff: passed.
- Compileall: passed.
- Direct artifact verifier: passed.
- Corrected external evidence suite: 77 passed.
- Contract: `3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3`,
  14905 bytes, SHA-256
  `deab0f575d7c9461cadc3d3925558b517ad41443c860133a9817f281ba08ae91`.
- Execution accounting: validation 704; holdout maximum 176; temporal maximum
  10; overall maximum 890.
- No new study execution, provider execution, network request, holdout access or
  temporal access occurred during test-only remediation.
- Codebase-memory reindex was previously attempted and contained worker crash
  on untracked Phase 11R.1 files; no source or evidence mutation occurred.

## Boundary

READY_FOR_CONTRACT_FREEZE_REVIEW

Phase 11R.2 attribution research, runtime provider use, parameter tuning,
commit, merge and push remain unauthorized. Holdout and temporal access remain
closed.
