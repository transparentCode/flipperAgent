# Coder to Orchestrator: Trendline V2 Phase 11R.3B Implementation

## Status

`READY_FOR_TEMPORAL_V2_CLOSURE`

The original R3B engine executed once and produced a complete negative result,
but its timestamp-only future window was one bar late. Its evidence remains
preserved byte-for-byte as superseded history. Reviewed temporal-v2 evidence
now closes temporal remediation without another replay.

## Scope

Changed only:

- `scripts/analyze_trendline_v2_joint_structural_compression.py`
- `tests/scripts/test_trendline_v2_joint_structural_compression.py`
- `plans/coder-to-orchestrator-trendline-v2-phase-11r3b-joint-structural-compression-v1.md`

No `src/`, config, YAML, runtime, viewer, provider, lifecycle, holdout,
temporal, network, or generated evidence changes.

Implemented in the approved three-file boundary:

- strict retained R3A/raw-source verifier with exact four-file raw allowlist;
- causal candidate table and deterministic policy ranking;
- joint Cartesian core-pair selection, coherent fill, role-transfer retention,
  shortfall/rejection evidence;
- shared structural-context lane capped at one line per role;
- exact 24/48/96-hour outcome and stability calculations;
- contender, matched-control and independent-diagnostic derivations;
- gate, decision and validation-lock identity construction;
- canonical CSV/JSON serialization, atomic staging and strict bundle verifier.
- source-derived byte rederivation for publication and strict verification;
- explicit synthetic verifier seam requiring caller-supplied expected evidence;
- eligible-incumbent retention denominator and stable lineage-pair continuity;
- budget-bound matched populations with persisted exact outcome-key evidence;
- Jaccard-based adjacent-continuity gate and frozen finalist precedence;
- published gate/comparison/diagnostic records and dataset-specific metrics;
- required coverage, missing-role, churn, replacement and structural-context metrics;
- execution guard at direct runner boundary.
- complete 88-cell matched-control reconciliation with duplicate/missing/extra
  cell evidence;
- role-transfer-aware role membership churn without changing global lineage
  additions/removals;
- role-scoped inversion shortfall attribution;
- structural distance and contraction summaries with explicit null denominators.
- versioned temporal-v2 contract using
  `checkpoint < available_at <= checkpoint + horizon`;
- exact open-time boundary `checkpoint <= bar_open < checkpoint + horizon`;
- strict temporal-v2 source-backed verifier and atomic versioned publication;
- explicit 1h/4h boundary tests for 24h, 48h and 96h availability windows.

## Frozen boundary

- Base commit: `b7cd736e08bda2eb82fa7f0dad62c842428c602a`
- Branch: `research/trendline-v2-phase-11r3b-joint-structural-compression-v1`
- Validation datasets: BTCUSDT 1h, BTCUSDT 4h, ETHUSDT 1h, ETHUSDT 4h
- Actionable states: `STRICT_ACTIVE_NEAR`, `PERSISTED_ACTIVE_NEAR`,
  `REVERSED_ACTIVE_NEAR`
- Structural-only states: `PERSISTED_DISTANT`, `REVERSED_PERSISTED_DISTANT`
- Excluded states: `NOT_YET_STRICT_ACTIVE`, `REVERSAL_PENDING`, `RETIRED`
- Budgets: `1`, `2`, `3` lines per role
- Policies: two matched comparison controls, one diagnostic-only control, and
  three contenders
- Horizons: `24h`, `48h`, `96h`
- Finalist failure status: `NO_JOINT_STRUCTURAL_COMPRESSION_FINALIST`

Comparator and evidence boundaries are explicit:

- matched controls: `joint_hash_order_control_v1` and
  `joint_nearest_projection_control_v1`;
- diagnostic-only control: `independent_incumbent_control_v1`;
- contender-first matching uses exact per-role selected counts and namespaced
  contender/budget/control keys;
- validation lock stores generated deterministic evidence IDs, not logical
  record names;
- finalist is null or valid contender-budget ID, never contract-predetermined;
- complete study may end with no finalist;
- incumbency is rank priority only, with retention derived after selection;
- outcome role stays fixed through each horizon;
- structural context uses separate exact distance/contact formulas;
- R3A dataset IDs are explicitly named
  `lineage_lifecycle_evidence_ids`.

Source identities bind the protected Phase 11R.3A output and Phase 11R.1,
Phase 11R.2, and allowed BTC/ETH raw inventories. Raw SUI, holdout, temporal,
network, provider, and legacy access are prohibited.

## Contract identity

Computed by `contract_triplet()` from canonical JSON. No source access occurs
while deriving or validating identity.

- Contract ID: `c1cc02909b8b5a7ed6a3ed0f45aebcb4ce054685b0dd60364d0158360f1ad3b6`
- Canonical JSON byte length: `25446`
- Canonical JSON SHA-256: `9583f52973b1345bb0cd2fd636acc1a061c64d1b4863003938866907b558b4d7`

The original contract/output is superseded, not rewritten:

- Original output status: `SUPERSEDED_PENDING_TEMPORAL_WINDOW_REMEDIATION`
- Original decision: `cc0fe7b74684726c12d510b4711654afbef84781c760a9710ab811d9b0121ca4`
- Original manifest: `50114d67995492cc3e3ec0f0c2cf88c63a50b0bc8689f90d9fdc99a014188c3b`
- Original inventory: `94c2cbd43c685ddb471c186c9440f3c2cf7febd04d588fc1b23f836903ddef03`

Corrected temporal-v2 contract/output:

- Contract: `e99ae58325df06923c83e0732d3a07c77446a32a5aa913d65411518ea4742a52`
- Canonical JSON: 26223 bytes, SHA-256 `e900f47774045f96d1d14658fa3972cda70a42ded2ea95b34aaaf79839da2ed4`
- Output root: `/tmp/trendline_v2_phase11r3b_joint_structural_compression_temporal_v2/20260522_20260701`
- Decision: `66240c90f6d7b4c8575caebd1b248dbaa8084819c99504e19c210a0ec0b331ec`
- Validation lock: `27febb38504b51609b3bf70f7f879ce056f16ec2612bf727d33e236ee80ed276`
- Manifest: `69ec5869678d136dc366039424ca2912b2940d907524f55ed43b1958e0bccc3e`
- Output inventory: `658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c`
- Status: `JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE`
- Finalist: `None`
- Unresolved evidence/reconciliation: `0 / 0`

## Validation run

Implementation and corrected replay validation:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_v2_joint_structural_compression.py \
  tests/scripts/test_trendline_v2_causal_seed_lifecycle_feasibility.py \
  tests/scripts/test_trendline_v2_sparse_geometry_failure_attribution.py \
  tests/scripts/test_trendline_v2_independent_sparse_geometry.py \
  -q -ra

ruff check \
  scripts/analyze_trendline_v2_joint_structural_compression.py \
  tests/scripts/test_trendline_v2_joint_structural_compression.py

PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/analyze_trendline_v2_joint_structural_compression.py

git diff --check
```

Corrected implementation result:

```text
Phase 11R.3B tests: 116 passed
Old R3B strict verifier: passed
Temporal-v2 strict verifier: passed
Ruff: passed
Compileall: passed
Diff check: passed
```

Codebase-memory reindex failed because of a stale or missing legacy-worktree
index target, `flipperAgent-wt-legacy-trendlines`. Existing indexes remained
intact. GitNexus remains stale on an older branch; neither index state affects
artifact verification.

Synthetic coverage includes deterministic IDs, timestamp-space projection,
Cartesian coherent-pair behavior, inversion rejection, role shortfalls,
incumbency and role transfer, matched counts, structural cap, causal horizons,
contact/breach/reaction semantics, stability null denominators, atomic staging,
frozen artifact boundaries, eligible-incumbent retention, stable pair
continuity, matched-control shortfall semantics, required metric fields and
direct-runner guard behavior.

Implementation acceptance:

- exact base remains `b7cd736e...`;
- protected original R3B output remains byte-identical;
- Phase 11R.3A output unchanged;
- temporal-v2 output is separate and atomically published;
- no SUI, temporal, holdout, provider, network, or legacy access;
- no commit, merge, or push.

## Execution boundary

The original R3B output is retained as superseded evidence. Corrected
temporal-v2 execution remains separately guarded by:

```text
TRENDLINE_V2_ALLOW_PHASE11R3B_TEMPORAL_V2_STUDY=1
```

The corrected temporal-v2 runner executed once only and published after strict
staging and source-backed bundle verification. Provider, network, SUI,
holdout, temporal and legacy execution counts were zero.

## Temporal audit boundary

R3A lifecycle code uses availability-aware checkpoint replay, but its retained
future-outcome helper and independent sparse-geometry study use the superseded
timestamp-only future-window convention. Protected outputs were not
regenerated or modified here. Any future use of those outcome fields requires
separate versioned temporal remediation.

## Next boundary

Temporal-v2 review is closed. Phase 11R.4 contract review may proceed, while
R4 execution remains paused and unauthorized.

No runtime selector, YAML parameter, viewer integration, provider change,
promotion, holdout access, further replay, commit, merge, or push is authorized.
