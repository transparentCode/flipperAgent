---
goal: Correct SR-V2.0 so the detector obeys its causal contract and the adequacy study compares displacement-origin bands with independently evaluated matched naive bands.
stage: architect-to-coder
date_created: 2026-07-18
last_updated: 2026-07-18
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, v2, displacement-origin, remediation, adequacy, kiss]
source_agent: Quant Orchestrator
target_agent: Codex quant-coder
source_base: 88ea5931b87a6a9bb0d302a64c3cb0924b164a52
supersedes: plans/architect-to-coder-sr-v2.0-displacement-origin-adequacy-v2.md
---

# SR-V2.0 — Displacement-Origin Adequacy Remediation

## Objective

Correct the existing V2.0 implementation in one bounded pass and regenerate
trustworthy frozen-development evidence for this exact claim:

> A full-range band taken from the nearest opposing candle before a directional
> displacement close produces better first-revisit reaction quality than a
> same-width band centered on the immediately preceding close.

The naive control rule is intentionally parameter-free. This remediation
corrects the approved plan's contradiction between its stated "naive zone"
objective and its reuse of V1.9 non-zone outcome controls.

The current bundle
`2623894d6cc782a967c6f2c83305c42d598eba34effa45ae34407734fb3cd5c4`
and study
`9856c44834cd1355431c8b4b2adf92fbefadbbcc203f85b31b6628236db5fd58`
are superseded review evidence. They must not be promoted or reused as the
corrected V2.0 result.

## Scope Boundaries

Continue on branch `feature/sr-v2.0-displacement-origin-adequacy` from
`88ea5931b87a6a9bb0d302a64c3cb0924b164a52`.

Remain inside the active package `src/libs/models/sr`, its tests, the strict
V2.0 trial YAML, generated ignored V2 evidence, and the existing V2.0
coder-to-review handoff.

Use only the frozen TAOUSDT Binance USD-M 1d development source already bound
by the V2.0 YAML:

- cohort source bundle:
  `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`;
- underlying source capsule bundle:
  `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`;
- source ID:
  `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`;
- 629 frozen rows through 2025-12-31;
- Wilder ATR(14), SMA seed, common start 28;
- six existing quarterly development folds;
- no provider calls, refresh, holdout access, or new data.

Do not lower readiness or utility thresholds because the original result missed
the completed-outcome threshold by one. Do not add rescue parameters or a
second detector.

## Affected Symbols, Modules, and Execution Flows

Expected implementation surface:

- `src/libs/models/sr/detection/displacement_origin.py`;
- `src/libs/models/sr/research/studies/displacement_origin_adequacy/`;
- `configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml`;
- focused tests under:
  - `tests/models/sr/detection/test_displacement_origin.py`;
  - `tests/models/sr/research/studies/displacement_origin_adequacy/`;
- `plans/coder-to-review-sr-v2.0-displacement-origin-adequacy-v1.md`.

The existing shared
`research/evidence/baseline_adequacy/controls.py::compute_control_outcome`
may remain the pure post-anchor excursion scorer. It must not substitute for
constructing control geometry or finding an independent control touch.

The corrected execution flow is:

1. Load the exact frozen V1.7 cohort source and canonical TAOUSDT source
   capsule.
2. Compute point-in-time Wilder ATR(14).
3. Detect real displacement-origin candidates.
4. Build two naive control interpretations for each in-fold real candidate at
   confirmation time.
5. Evaluate real and control bands independently through first touch, expiry,
   fold censoring, and reaction horizon.
6. Form exact same-side completed pairs.
7. Compute paired excess metrics and gate disposition.
8. Publish and semantically recompute an immutable deterministic bundle.

Before editing existing symbols, use the available codebase-memory impact tools
required by repository instructions. If the index is unavailable, record that
fact and perform explicit caller/import/diff inspection instead.

## Data Contracts or Interfaces

### 1. Corrected real detector contract

For confirmation bar `t`:

1. Use `ATR[t-1]` only as the displacement threshold scale.
2. Require a non-zero range.
3. Require `abs(close-open) >= 1.0 * ATR[t-1]`.
4. Require `abs(close-open)/(high-low) >= 0.60`.
5. SUPPORT requires both:
   - `close[t] > open[t]`;
   - `close[t]` strictly above every high in the prior five completed bars.
6. RESISTANCE requires both:
   - `close[t] < open[t]`;
   - `close[t]` strictly below every low in the prior five completed bars.
7. Search the prior three bars nearest-first for an opposing non-doji candle.
8. Use that base candle's full high-low range.
9. `formed_at = base.closed_at`.
10. `available_at = confirmation.closed_at`.
11. `atr_at_creation = ATR[t]`, the point-in-time ATR at confirmation close.
12. `source = displacement_origin_v2`.
13. Emit at most one candidate per confirmation bar.

The prior ATR remains causal and correct for threshold qualification. It must
not be stored as candidate creation ATR.

### 2. Naive control-band contract

For every real candidate whose confirmation is inside one of the six folds,
construct a deterministic naive geometry using only information available at
confirmation:

- `center = close[t-1]`;
- `half_width = real_candidate.geometry.half_width`;
- lower and upper bounds derive from that center and half-width;
- `formed_at = bars[t-1].closed_at`;
- `available_at = real_candidate.available_at`;
- `atr_at_creation = ATR[t]`;
- fixed control source: `prior_close_naive_v2`;
- preserve the real candidate's state key, fold, confirmation identity, ATR,
  and width;
- create SUPPORT and RESISTANCE interpretations in the configured stable side
  order.

These are controls for an eligible real candidate, not controls created after
learning the real touch outcome. Build both even when the real band later has
no touch or is censored.

Use a small study-local immutable control-band/result contract. Reusing
`CandidateLevel` for its geometry and identity fields is acceptable if the
control source and control/real distinction remain explicit in serialized
evidence. Do not add a registry or new core abstraction.

### 3. Independent touch and outcome evaluation

Real and naive bands must each run through the same causal evaluator:

- touch search starts at confirmation index plus one;
- inclusive OHLC/band intersection;
- exactly 50 search bars at most;
- search expires at the earlier of 50 bars or fold end;
- a touched band receives a 10-bar reaction horizon;
- every horizon bar must close strictly before fold end;
- incomplete same-fold horizons are right-censored;
- no-touch, right-censored, completed, outside-fold, and any applicable invalid
  accounting remain explicit;
- quality remains favorable excursion ATR minus adverse excursion ATR,
  normalized by ATR at that band's own touch.

A control must find its own touch. It must never inherit the real case's
`touch_bar_id`, `first_touch_at`, anchor close, or reference ATR.

### 4. Pairing and metrics

A primary comparison pair exists only when:

- the real outcome is completed;
- the same-side naive control outcome is completed;
- fold, state key, confirmation/availability time, side, creation ATR, and
  zone width match exactly;
- real and control geometry identities remain distinct.

For each completed pair:

`paired_excess_quality_atr = real_quality_reference_atr - naive_quality_reference_atr`

The opposite-side control remains diagnostic. It must not enter the primary
paired excess.

Compute:

- completed pair count;
- completed real count and all real status counts;
- control counts/statuses by fold and side;
- unpaired reason counts;
- fold median paired excess;
- pooled median paired excess across comparable pairs;
- fraction of comparable folds with median paired excess strictly above zero;
- worst comparable-fold median paired excess.

Do not compare a real outcome with a fold median containing an identical copy
of that outcome. The previous same-touch fold-pool calculation must be removed.

### 5. Corrected immutable gates

Keep the approved numeric thresholds, applying them to the paired design:

Readiness:

- completed real/naive same-side pairs >= 24;
- comparable folds >= 4;
- completed pairs per comparable fold >= 4;
- completed naive controls per side per comparable fold >= 4.

A fold is comparable only when its pair and per-side completed-control
thresholds pass.

Utility, evaluated only after all readiness gates pass:

- pooled median paired excess >= 0.10 ATR;
- positive comparable-fold fraction >= 0.60;
- worst comparable-fold median paired excess >= -0.10 ATR.

Disposition remains exactly one of:

- `DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL`;
- `DISPLACEMENT_ORIGIN_NOT_BETTER_THAN_NAIVE_NULL`;
- `INSUFFICIENT_EVIDENCE`.

If any readiness gate fails, utility values may be serialized as diagnostics
but cannot change `INSUFFICIENT_EVIDENCE`.

Update the strict YAML and exact approved config payload to use paired-gate
names. No call-time override or hidden Python numeric fallback is allowed.

### 6. Source provenance

Use the existing canonical
`libs.models.sr.research.cohort.contracts.source_capsule` adapter for the
loaded TAOUSDT `AssetSource`.

Required distinction:

- `FrozenInputs.capsule.source_bundle_id` is the underlying immutable capsule
  ID `d2104949...`;
- the study and manifest continue binding the outer frozen cohort source bundle
  `6b5a0a81...`;
- both IDs and the source ID remain validated separately.

Remove redundant manual capsule construction and resulting unused imports.

### 7. Artifact contract

The corrected evidence bundle may retain the three members:

- `manifest.json`;
- `study.json`;
- `cases.json`.

The casebook must include enough real candidate, naive control geometry,
independent status/touch/outcome, pairing, and accounting information for full
semantic recomputation.

The validator must recompute detector output, both control bands, independent
touches, pairs, metrics, gates, identities, and disposition from the frozen
source and exact YAML. Rehashed tampering must fail.

Old V2.0 artifacts remain ignored and superseded. Do not mutate them in place
or claim their IDs as corrected evidence.

## Implementation Order

1. Run codebase-memory/caller/import impact inspection for the detector,
   V2 outcomes/metrics/contracts, shared control scorer, and source capsule
   adapter.
2. Mark the existing coder handoff `Needs Revision` while remediation is in
   progress.
3. Fix detector direction and confirmation-ATR identity.
4. Replace same-touch pseudo-controls with typed prior-close naive bands.
5. Extract or reuse one causal band evaluator for both real and controls so
   touch, expiry, horizon, and censoring rules cannot drift.
6. Replace fold-pool null metrics with exact same-side paired excess.
7. Update strict config contracts and YAML gate names without changing numeric
   thresholds.
8. Correct source-capsule provenance through the canonical adapter.
9. Harden semantic contracts and artifact validation for geometry, independent
   touch, pairing, metrics, gates, and disposition.
10. Run focused tests and adversarial probes before generating evidence.
11. Commit implementation and tests.
12. Generate the corrected evidence twice from that exact implementation
    commit; require identical bundle ID and member bytes.
13. Validate the published bundle from the implementation commit.
14. Run full validation and protected V1.12 checks from final code HEAD.
15. Update the existing coder-to-review handoff with superseded and new
    evidence IDs, exact counts, disposition, commands, and commits.
16. Commit the docs-only handoff update. Do not merge.

## Acceptance Criteria

### Detector

- A controlled test with unequal `ATR[t-1]` and `ATR[t]` proves threshold
  qualification uses the former and `candidate.atr_at_creation` uses the
  latter.
- Bearish gap-up/strong-body bars closing above structure do not create
  SUPPORT.
- Bullish gap-down/strong-body bars closing below structure do not create
  RESISTANCE.
- Existing strict ties, nearest opposing base, full geometry, causality,
  prefix/full parity, ordering, and contract checks remain passing.

### Controls and outcomes

- A controlled fixture proves the naive band center is exactly
  `close[t-1]`, while width equals the real band width.
- Changing the real width changes naive bounds and can change a controlled
  naive touch result. Width cannot be metadata-only.
- Controls are constructed for in-fold candidates before real outcome status
  is known.
- A controlled case proves real and naive first touches can occur on different
  bars and produce different outcomes.
- No code path copies the real touch identity into a naive outcome.
- Exactly two ordered control interpretations exist per in-fold real candidate.
- Search offset, exact 50-bar expiry, fold-end truncation, and `>= fold_end`
  censoring have boundary regressions.

### Pairing and decisions

- Each eligible primary pair has exactly one real and one same-side naive
  completed outcome.
- Pair matching fails closed on fold, side, confirmation time, ATR, width,
  control identity, or geometry mismatch.
- Primary excess is recomputed from the paired outcomes.
- Opposite-side diagnostics cannot influence primary metrics or disposition.
- Readiness has precedence over utility.
- Tests cover all three dispositions, unknown gate categories, sparse folds,
  zero/tie semantics, and deterministic ordering.

### Artifacts and provenance

- Rehashed modifications to a real candidate, control bounds, control touch,
  pair mapping, metric, gate, source identity, implementation identity, or
  disposition are rejected.
- Bundle/member symlink and non-regular-file protections remain passing.
- Canonical source capsule exposes `d2104949...`; study provenance exposes
  `6b5a0a81...`.
- Two corrected evaluations from the same implementation commit are
  byte-identical.
- The final handoff reports detection, real status, control status, paired,
  unpaired, fold, side, base-distance, gate, and disposition counts.
- The package is complete enough for independent review without inference.

## Validation Checklist

Run at minimum:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/models/sr/detection/test_displacement_origin.py -q`;
- `PYTHONPATH=src .venv/bin/python -m pytest tests/models/sr/research/studies/displacement_origin_adequacy -q`;
- shared V1 baseline-control regression tests affected by the reused scorer;
- `PYTHONPATH=src .venv/bin/python -m pytest tests/models/sr/architecture -q`;
- `PYTHONPATH=src .venv/bin/python -m pytest tests/models/sr -q`;
- Ruff over `src/libs/models/sr` and `tests/models/sr`;
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/sr`;
- package imports and V2 CLI help;
- `git diff --check 4dd1f74d22dc0296c3d09599ef75906a7d0f147a..HEAD`;
- corrected V2 semantic bundle validation from the implementation commit;
- deterministic double-run member-byte comparison;
- V1.12 semantic validation and exact protected hash checks;
- codebase-memory change detection or an explicitly documented fallback diff
  and import-boundary inspection.

Independent probes must additionally demonstrate:

1. no current or adversarial candidate stores `ATR[t-1]` as creation ATR;
2. candle direction is required independently of structural breakout;
3. naive geometry uses prior close and real width;
4. real and naive touch identities are independently computed;
5. primary paired excess is not a self-copy or fold-pool substitution;
6. source capsule and cohort bundle identities remain distinct;
7. rehashed artifact tampering is rejected.

Report exact commands and counts. If Ruff or codebase-memory is unavailable,
record the limitation; do not silently claim it passed.

## Explicit Non-Goals

Do not:

- change or merge `SREngine`, lifecycle, association, runtime configuration,
  or production behavior;
- touch `configs/sr.yaml`;
- access providers, network data, refreshes, or holdout;
- lower thresholds, widen detector rules, fetch one extra observation, or tune
  after seeing the result;
- add ML, indicators, volume POC, ZigZag, pivots, fractals, FVG, order blocks,
  or a second detector;
- add a detector registry, plugin framework, database, viewer, JavaScript, or
  browser gate;
- add a configurable control-center parameter;
- reuse the legacy `src/libs/sr` package;
- mutate or delete ignored prior evidence;
- stage or modify the pre-existing architect-plan drafts other than this new
  approved handoff;
- begin V2.1 or merge the branch.

A valid outcome may still be `INSUFFICIENT_EVIDENCE`. That is not a defect and
does not authorize rescue tuning.

The handoff is complete and approved enough for the coder to implement without
guessing. Return the remediated branch to independent quant review; do not route
directly to approval.
