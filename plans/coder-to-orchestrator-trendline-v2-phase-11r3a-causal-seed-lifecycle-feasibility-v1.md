# Coder to Orchestrator: Phase 11R.3A Causal Seed Lifecycle

## Status

`CANONICAL_STUDY_COMPLETE`

Implementation approved. One canonical 88-checkpoint publication completed.

## Scope

Created exactly:

- `scripts/analyze_trendline_v2_causal_seed_lifecycle_feasibility.py`
- `tests/scripts/test_trendline_v2_causal_seed_lifecycle_feasibility.py`
- this handoff

No `src/`, config, runtime, viewer, provider, canonical evidence bundle or
prior Phase 11R.1/11R.2 file changed. Worktree contains only three scoped
untracked files.

## Contract

Namespace:

`trendline_v2_phase11r3a_causal_seed_lifecycle_feasibility_contract`

Contract identity is derived from canonical JSON and pinned by the script's
identity-drift guard. Values are reported by:

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/analyze_trendline_v2_causal_seed_lifecycle_feasibility.py \
  --verify
```

Derived freeze triplet:

- Contract ID: `df65b38a0bbdf675e97336bcb3a750ba64483cfee32428ec08c4b40da63d85b1`
- Canonical JSON byte length: `22226`
- Canonical JSON SHA-256: `154fe9a3168b5c16c17156fd278acc8d63433ba645aca14727bad50b429423e8`

The contract binds exact Phase 11R.1 and Phase 11R.2 commits, Git blobs,
file SHA-256 values, contract IDs, decision IDs, manifest IDs and inventories.

## Frozen Semantics

- Four validation datasets, 88 checkpoints, two reconstruction repeats.
- 52 provider-role gaps and 26 unique gap identities.
- A lineage becomes eligible only when its anchor pair appears in the exact
  Phase 11R.1 strict seed pool at a scheduled checkpoint.
- Geometry is immutable: original anchors, role and exact timestamp-space line
  persist across seed eviction; refit, reanchor, pivot replacement and slope
  adjustment are prohibited.
- States distinguish `STRICT_ACTIVE_NEAR`, `PERSISTED_ACTIVE_NEAR`, and
  `PERSISTED_DISTANT`; `RETIRED` is terminal and carries typed reasons.
- Strict-seed entry occurs at scheduled checkpoints. Breach, contact, reversal
  and retirement replay on every owner-timeframe bar using `available_at`.
- State retention is allowed for every nonterminal state and is not a
  transition event.
- Exact 96-hour, three-touch, 0.35 ATR contact and 0.5 ATR two-close breach rules.
- Reversal requires post-breach contact, permits one role flip, and activates
  reversed near/distant state only after contact.
- Descriptive union excludes unavailable `NOT_YET_STRICT_ACTIVE`,
  `REVERSAL_PENDING` and `RETIRED` states.
- Original support breaches require two consecutive closes below line minus
  `0.5 * ATR_at_bar`; original resistance breaches require two consecutive
  closes above line plus `0.5 * ATR_at_bar`. Counters reset on clean closes.
- Checkpoint processing replays bar events first, then applies strict-seed
  membership, then classifies near/distant state from the last completed bar.
- Semantic roles are original before reversal, opposite after reversal, and
  absent for not-yet, pending and retired states; last active role persists
  separately for pending and retired evidence.
- Structural distant states remain non-actionable.
- Recovery uses orthogonal status, ordered mechanisms and typed unrecovered
  reasons, classified once per unique `(dataset_id, checkpoint_index, role)`.
- Coverage denominator is 176 checkpoint-role cells. Zero strict denominator
  blocks inflation calculation.
- Candidate-level and unique-gap-level outcome rates are both persisted;
  headline decision rates use unique-gap `any candidate succeeds` aggregation.
- `RETIRED` persists at later checkpoints without repeated transition events.
- Candidate outcomes use `(dataset_id, checkpoint_index, role, lineage_id)`;
  future windows are 24/48/96 hours with strict post-checkpoint timing and
  exact role-aware reaction formulas.
- Transition evidence includes fixed geometry, effective availability time,
  breach/contact chronology, projection, distance, retirement and input identity.
- No provider ranking, selector, parameter search, holdout or temporal access.
- Proposed output is 23 files, 22 manifest members, excluding SUI and temporal paths.

## Implementation

- `LifecycleLineage` freezes anchor identity and exact timestamp-space geometry.
- `LifecycleBar` binds OHLC, ATR and `available_at` with strict numeric checks.
- `LifecycleCheckpoint` freezes scheduled strict-seed membership and source
  identity.
- `build_lifecycle_inputs()` reuses only Phase 11R.1 persisted-input,
  hierarchical-pivot and strict-seed paths; it does not execute a provider.
- `derive_lifecycle_evidence()` replays owner bars before checkpoint
  classification and emits strict entry, persistence, breach, post-breach
  contact, reversal, and terminal retirement evidence.
- `derive_future_outcomes()` applies exact post-checkpoint owner-timeframe
  bars and role-aware 24/48/96-hour contact, survival and reaction rules.
- `verify_retained_sources()` checks frozen Phase 11R.1/11R.2 evidence and only
  four approved BTC/ETH raw inputs. SUI raw and temporal paths remain blocked.
- `run_lifecycle_study()` creates staging before source access, checks source
  immutability before and after manifest construction, writes canonical 23-file
  evidence, verifies it, then performs one atomic directory replacement.
- `_derive_lifecycle_study_evidence()` is the single source-backed derivation
  path used by publication and real-bundle verification; verification compares
  every non-manifest byte against fresh retained-source output.
- `_verify_lifecycle_bundle()` also enforces exact transition-trigger edges,
  retirement reasons, strict-seed reconciliation, gap/candidate bindings and
  actionable-versus-structural outcome schemas.
- Checkpoint projection and distance use line-at-checkpoint; original,
  reversed and pending bar precedence is explicit.
- Gap recovery retains pending and retired lineages for reason attribution;
  outcomes are emitted only for recovered candidate keys.
- Policy metrics persist 176-cell coverage, candidate inflation, candidate and
  unique-gap rates, zero-denominator support and decision headline evidence.
- Synthetic tests cover immutable geometry, strict entry, available-at event
  timing, breach reset, distant persistence, reversal retirement, source
  mutation refusal, atomic publication, future timing and semantic tampering.

## Guard Boundary

`--execute-lifecycle-study` requires
`TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY=1` and refuses an existing output
root before source access. Publication is staged and atomic. `--verify` remains
source-free when canonical output is absent; when output exists it performs
full canonical bundle verification. Synthetic bundles are accepted only by the
explicit `_verify_synthetic_lifecycle_bundle_for_tests()` helper; CLI verify,
canonical staging verification and published-bundle verification reject
artifact-controlled synthetic markers.

## Phase 11R.3A Remediation

Implementation review remediation is complete without changing the frozen
contract or opening the canonical study boundary:

- pre-activation lineages are omitted from checkpoint state evidence until
  their first strict checkpoint;
- gap-level recovery status remains aggregate while candidate-level recovery
  status and mechanisms are persisted and validated independently;
- event projection/distance and checkpoint projection/distance use their own
  timestamps and bars, with no generic `distance_atr` field;
- strict seed IDs are independently derived from retained Phase 11R.2 seed
  pairs and reconciled against actual and expected checkpoint membership;
- retired counts use unique lineage IDs;
- candidate rates are persisted separately for 24h, 48h and 96h horizons;
- direct study calls enforce the execution environment guard;
- zero pooled strict observations raise a blocking lifecycle-study error.
- canonical verification rejects synthetic trust markers and unknown source
  audit/source snapshot fields; synthetic fixtures use an explicit test-only
  verifier path.

No Phase 11R.1/11R.2 source bundle, provider, network, holdout, temporal path,
canonical output or runtime configuration was changed or accessed for study
execution.

## Validation

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_v2_causal_seed_lifecycle_feasibility.py \
  tests/scripts/test_trendline_v2_sparse_geometry_failure_attribution.py \
  tests/scripts/test_trendline_v2_independent_sparse_geometry.py \
  -q -ra

ruff check \
  scripts/analyze_trendline_v2_causal_seed_lifecycle_feasibility.py \
  tests/scripts/test_trendline_v2_causal_seed_lifecycle_feasibility.py

PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/analyze_trendline_v2_causal_seed_lifecycle_feasibility.py

git diff --check
```

Phase 11R.1 and Phase 11R.2 retained bundles must be verified read-only before
any future study authorization. The implementation pass performed retained
source preflight only: 21 Phase 11R.1 members, 24 Phase 11R.2 members and four
approved raw BTC/ETH inputs. Raw SUI and temporal reads remained zero.

Focused remediation tests: `105 passed`.
Cross-phase regression: `286 passed, 17 skipped`.
V2/viewer regression: `281 passed`.
Protected Trendline Family regression: `400 passed`.
Provider benchmark regression: `4 passed`.
Ruff, compileall, `git diff --check` and contract verification: passed.

## Canonical Run Evidence

Published root:

`/tmp/trendline_v2_phase11r3a_causal_seed_lifecycle/20260522_20260701`

- study status: `CAUSAL_SEED_LIFECYCLE_FEASIBILITY_COMPLETE`
- decision ID: `d1e97bbccb64dba0a12a88d324af19c40e1563ffce87e77707e5ce9f21b42d1b`
- manifest ID: `74a5e78b119cc18a8c982a4e75a953a545780b10dbe7798464a8a9abdd1a146d`
- output inventory SHA-256: `6335ec5dd2e67bc94f51ae5a1e0c0e265db743ad1aeccb0094ce4507466d2ff0`
- files: `23`; manifest members: `22`
- unresolved evidence: `0`
- lineage count: `651`; checkpoint states: `4435`; transitions: `1567`
- unique retired lineage count: `144`; future outcome rows: `147`

Gap recovery across 26 unique gaps:

- `ACTIONABLE`: `1`
- `STRUCTURAL_ONLY`: `10`
- `NOT_RECOVERED`: `15`
- actionable recovery count: `1`
- structural-only recovery count: `10`
- unrecovered gap count: `15`
- distance-persistence recovery count: `11`
- role-reversal recovery count: `2`
- pending-without-contact count: `0`
- retired-relevant recovery count: `6`

Coverage and density:

- strict actionable coverage: `0.8522727272727273` (`150/176`)
- expanded actionable coverage: `0.8579545454545454` (`151/176`)
- expanded structural coverage: `0.9147727272727273` (`161/176`)
- added actionable observations: `675`
- added structural-only observations: `914`
- candidate inflation ratio: `1.9778461538461538`
- maximum lineages per cell: `96`
- median lineages per cell: `12.0`

Candidate-level outcomes by horizon:

```text
horizon   survival        contact         reaction        evaluable
24h       1.0             0.0             0.0             3
48h       1.0             0.0             0.0             3
96h       1.0             0.0             0.0             3
```

Unique-gap outcomes:

- 48h survival: `1.0` (`1/1`)
- 96h survival: `1.0` (`1/1`)
- 96h contact: `0.0` (`0/1`)

Transition causes:

```text
strict_seed_confirmed:                    671
same_role_sustained_breach_confirmed:     306
reversal_contact_confirmed_after_breach:   201
distance_returned_at_most_8_atr:           143
distance_exceeded_8_atr:                    84
reversed_role_sustained_breach_confirmed:  141
reversed_distance_exceeded_8_atr:           15
reversed_distance_returned_at_most_8_atr:    3
original_projection_invalid:                 3
```

Strict-seed reconciliation: `88/88` checkpoint entries matched independently;
actual IDs `1625`, expected IDs `1625`, identity failures `0`, count failures
`0`.

Source and execution audit:

- source snapshots before/after: equal; source immutability verified
- Phase 11R.1 inventory: `17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50`
- Phase 11R.2 inventory: `382df2e22cb508d3982eb7e6d9566849dc65eb7316a8ce8c64b9c44d2d6713e4`
- allowed raw BTC/ETH inventory: `2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27`
- raw SUI access: `false`
- temporal access: `false`; holdout access: `false`
- network requests: `0`; provider executions: `0`; legacy executions: `0`

Post-publication validation: focused `105 passed`; approved cross-phase
`286 passed, 17 skipped`; Ruff, compileall, diff check and default source-backed
verification passed.

## Known Gaps

No holdout or temporal path was opened. No second run or retry is authorized.

## Next Step

Next step: independent review of canonical evidence. Commit remains
unauthorized.
