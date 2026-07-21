---
goal: Complete Trendline Model Makeover V1 architecture and runtime optimization without output drift
stage: architect-to-coder
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, trendline, remediation]
---

# Trendline Model Makeover V1 Remediation Contract

## Routing

Architect pass skipped. User review provides complete defects, boundaries, acceptance criteria, and validation. This document converts that review into one bounded coder contract. Coder can act without guessing.

## Verified starting state

- Worktree: `/Users/aloobhujia/flipperAgent-trendline-makeover-v1`
- Branch: `refactor/trendline-model-makeover-v1`
- Starting HEAD: `999096449230292c903d21c498dec9ceea36e6af`
- Feature worktree tracked state: clean
- Original checkout: clean on `main` at `c85a2b366133e7d7be4bc18b51bedfd793742189`
- Existing nine phase commits must remain intact.
- Prior independent validation: 406 passed; Ruff, compileall, diff check passed.
- Code graph refreshed at starting HEAD.
- `TrendlineFamilyTracker.update`: 325 lines, 44 outgoing calls, CRITICAL impact.
- `compose_mtf_snapshot`: 110 lines; `mtf/composition.py`: 2,154 lines, CRITICAL identity/serialization surface.
- Interaction and matching ATR functions retain separate Python list loops.

## Objective

Resolve all blocking orchestrator findings while preserving exact trendline behavior, deterministic identity, serialization, public imports, configuration values/hashes, causality, and prior commits.

## Scope

### 1. Enforce direct owner imports

Replace canonical owner-package imports through transitional root facades. Required direction:

- `configuration` imports only direct domain validation/identity owners.
- `discovery` imports direct domain/configuration owners and discovery contracts.
- `tracking` imports direct domain, discovery, interaction, configuration, and storage owners.
- `interaction` imports direct domain/configuration/kernel owners.
- `mtf` imports direct domain/configuration owners.
- `storage` imports direct domain owners.

Root `contracts.py`, `events.py`, `repository.py`, `provider.py`, `tracker.py`, and similar modules remain external compatibility surfaces only.

Move `CandidateGenerationStatus`, `CandidateGenerationResult`, and `LineCandidateProvider` into `discovery/contracts.py`. `discovery/provider.py` must import contracts, never reverse.

Add AST tests covering owner packages and forbidden transitional-facade dependencies.

### 2. Extract tracker phases

Reduce `TrendlineFamilyTracker.update()` to explicit orchestration. Extract immutable phase-result records and pure/small phase functions for:

1. confirmed-frame preparation;
2. prior-state load and compatibility;
3. candidate generation/validation;
4. rail grouping and family association;
5. family lifecycle advancement;
6. interaction/event advancement;
7. immutable snapshot construction;
8. persistence;
9. output construction.

Keep behavior-heavy state decisions in existing tracking/interaction helpers. Do not create unnecessary classes. Phase records must have explicit inputs/outputs and frozen dataclasses where state is carried.

Acceptance: `update()` materially smaller and readable; phase-level replay tests prove exact serialized snapshot bytes, IDs, transitions, events, features, ordering, and repository writes.

### 3. Complete MTF ownership decomposition

Move implementation from `mtf/composition.py` into real owners:

- `contracts.py`: immutable MTF enums/dataclasses and primitive validation local to contracts;
- `projection.py`: source-family/member projection;
- `freshness.py`: timeframe age and source freshness;
- `relations.py`: pair relations and intersections;
- `clustering.py`: deterministic clustering and cluster construction;
- `serialization.py`: MTF identity payload, ID, serialize/deserialize;
- `features.py`: shadow feature payload;
- `store.py`: latest snapshot store;
- `composition.py`: validation/orchestration only.

No forwarding-only responsibility modules. Avoid cycles through lower-level contracts/helpers. Preserve source validation, ordering, provenance, identity, serialization, and disabled behavior exactly.

### 4. Wire deterministic Numba ATR into semantic runtime

Use one validated NumPy/scalar ATR adapter and `kernels.atr.true_range_mean` for both:

- `interaction.observations.calculate_interaction_atr`;
- `tracking.matching.calculate_normalization_atr`.

Preserve existing short-frame behavior exactly:

```python
effective_window = min(configured_window, row_count)
```

Preserve method strings, sample counts, empty/error behavior, numeric operation order, snapshots, and IDs. Runtime backend selection must be non-semantic. Compiled and `.py_func` outputs must match exactly.

Benchmark actual public DataFrame ATR functions before/after, including DataFrame-to-array conversion and warm compiled path. Report fixture shape, warm-up, Python p50, compiled p50, cold cost, memory observation, exact parity. Do not claim end-to-end model speedup beyond evidence.

### 5. Restore ablation compatibility

Keep ownership in `libs.integrations.trendline_regime_v2`, but restore deprecated historical imports:

```python
from libs.models.trendline.optimization import WeightedFeatureScorer
from libs.models.trendline.optimization.ablation import WeightedFeatureScorer
from libs.models.trendline_family.optimization import WeightedFeatureScorer
from libs.models.trendline_family.optimization.ablation import WeightedFeatureScorer
```

Compatibility surfaces must resolve to integration-owned identical objects. Mark deprecated and exclude these explicit compatibility modules/surfaces from core runtime dependency checks. Canonical runtime and owner modules must not import RegimeV2/integration code. Add package- and submodule-level identity tests.

### 6. Documentation/environment closeout

- Replace literal `\x60` strings in `configs/trendline/README.md` with Markdown backticks.
- Update architecture and coder handoff with real final ownership, benchmarks, tests, risks, and commit list.
- Make documented validation command reproducible in feature worktree. A worktree-local `.venv` symlink to original checkout environment is acceptable if kept untracked/ignored and explicitly documented; do not commit environment contents.
- Write `plans/coder-to-orchestrator-trendline-model-makeover-v1-remediation.md` using `quant-write-handoff` requirements.

## Non-goals

- No Hough, new pivots, fitters, candidate formulas, parameters, research, tuning, holdout work, SQLite, TVLC, signals, model blending, RegimeV2 policy change, or protected evidence regeneration.
- No algorithm change outside equivalent ATR backend execution.
- No merge, push, rebase, force-push, branch switch, cherry-pick, or squash.
- No edits to old trendline/SR implementations.

## Stop conditions

Stop and report if branch differs, original checkout changes, algorithm change becomes necessary, IDs/serialization/config hashes drift, compiled/Python ATR diverge, public compatibility cannot be restored without core reverse dependency, protected artifacts change, or unrelated defect blocks validation.

## Commit plan

Preserve prior nine commits. Add focused remediation commits, preferably:

1. `refactor(trendline): enforce direct owner dependencies`
2. `refactor(trendline): extract tracker update phases`
3. `refactor(trendline): complete mtf responsibility ownership`
4. `perf(trendline): wire deterministic atr kernel`
5. `fix(trendline): restore ablation compatibility`
6. `docs(trendline): close makeover remediation`

Do not squash.

## Validation

Run focused tests after each subsystem, then full canonical suite. Final commands:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  -q -ra

ruff check \
  src/libs/models/trendline \
  src/libs/models/trendline_family \
  src/libs/integrations/trendline_configuration \
  src/libs/integrations/trendline_regime_v2 \
  tests/models/trendline_family

PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline \
  src/libs/models/trendline_family \
  src/libs/integrations

git diff --check
```

Also run direct public-import probes, AST owner-boundary checks, exact config-hash checks, deterministic replay/serialization checks, compiled-versus-`.py_func` ATR parity, and actual public ATR benchmark.

## Expected return

Coder returns:

- commit list and final HEAD;
- file/symbol summary;
- exact focused/full test results;
- identity/config/serialization evidence;
- import-boundary evidence;
- public compatibility evidence;
- benchmark methodology/results;
- residual risks;
- confirmation original checkout untouched and no push/merge;
- durable coder-to-orchestrator remediation handoff ending `READY_FOR_ORCHESTRATOR_REVIEW` or `BLOCKED`.
