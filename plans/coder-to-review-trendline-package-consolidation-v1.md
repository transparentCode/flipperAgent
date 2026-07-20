---
goal: Review completed Trendline Family canonical package consolidation and additive domain storage configuration integrations
stage: coder-to-review
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-coder
status: Ready
tags: [handoff, quant, trendline, package-migration, invariants]
source_agent: quant-coder
target_agent: quant-review
---

# Scope Executed

- Audited and completed existing dirty-tree candidate that makes `libs.models.trendline` canonical and `libs.models.trendline_family` forwarding-only.
- Confirmed direct canonical imports for six research scripts and RegimeV2 family adapter.
- Confirmed neutral integration ownership under `libs.integrations.trendline_configuration` and `libs.integrations.trendline_regime_v2`.
- Confirmed Phase 1C domain, Phase 1D historical storage, and Phase 1E typed configuration are additive scope, not pure package-move parity.
- Found one non-behavioral trailing-whitespace defect during staged diff validation and removed it from `trendline/event_lifecycle.py`.
- Preserved prior plan, artifact, log, dataset, and fixture bytes. Added this new stage-correct review handoff only.

# Changes Made

- Canonical implementation now resides under `src/libs/models/trendline/`, including runtime, optimization, research-lab, domain, storage, and configuration modules.
- Historical `src/libs/models/trendline_family/` modules forward through `_compat.reexport_module`; old and new imports resolve identical public objects.
- Historical built-in provider and scorer semantic identities remain `libs.models.trendline_family.*` even though implementation ownership moved.
- RegimeV2 shadow and ablation composition moved to neutral integration modules; historical adapter and optimization paths remain compatibility surfaces.
- Six research scripts import canonical modules. Fresh-window stream/spec identity uses `provider_identity(provider)` so persisted historical identity remains stable.
- Migration, domain, storage, configuration, compatibility-pickle, historical-identity, and cross-artifact integrity tests accompany candidate.
- Removed trailing whitespace from `_event_from_previous` signature; no runtime or interface semantics changed.

# Blast Radius Considered

- Codebase graph traced `update_trendline_families`, `TrendlineFamilyTracker.update`, `NativeDeterministicLineProvider.generate`, `WeightedFeatureScorer.score`, compatibility forwarding, and fresh-window stream/evaluation functions.
- Graph marks API, tracker, provider, storage, configuration, optimizer, and research-trial paths HIGH/CRITICAL because they are direct state and persisted-identity flows. All identified paths remain inside approved handoff scope.
- Change detection reports high overall risk around `build_candidate_stream` and `execute_research_evaluation`; change is limited to canonical imports and historical provider identity preservation, covered by 157 script tests.
- Canonical import audit found no dependency on compatibility or independent legacy packages except required historical provider identity string.
- `libs.trendlines`, `app.trendlines`, and `libs.models.trendlines_old` remain independent and byte-unchanged.

# Validation Performed

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family/test_phase_1b_migration.py tests/models/trendline_family/test_phase_1c_domain_contracts.py tests/models/trendline_family/test_phase_1d_storage.py tests/models/trendline_family/test_phase_1e_configuration.py tests/models/trendline_family/optimization/test_phase_i_remediation.py -q -ra
47 passed in 1.64s

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
377 passed in 23.13s

PYTHONPATH=src .venv/bin/python -m pytest tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py tests/signals/test_trendline_family_shadow_projected_runtime.py -q -ra
15 passed in 2.52s

PYTHONPATH=src .venv/bin/python -m pytest tests/scripts/test_trendline_family_candidate_geometry_trial.py tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py tests/scripts/test_trendline_family_candidate_evidence_report.py tests/scripts/test_trendline_family_candidate_rejection.py tests/scripts/test_trendline_family_candidate_density.py tests/scripts/test_trendline_family_candidate_quality_normalization.py -q -ra
157 passed in 69.46s

PYTHONPATH=src .venv/bin/python -m pytest tests/test_regime_v2_trendline_feature_producer.py tests/models/sr/research/studies/swing_reversal_adequacy/test_import_boundaries.py -q -ra
7 passed in 2.21s

ruff check src/libs/models/trendline src/libs/models/trendline_family src/libs/integrations tests/models/trendline_family
All checks passed!

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline src/libs/models/trendline_family src/libs/integrations
Passed

git diff --check
Passed

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family/test_event_lifecycle.py tests/models/trendline_family/test_phase_1b_migration.py -q -ra
30 passed in 8.46s after whitespace-only remediation
```

- Broad scoped result: 556 tests passed. Focused 47-test preflight is a subset of 377 package tests.
- `.venv/bin/ruff` and `.venv/bin/python -m ruff` were unavailable; repository-global `ruff` executable performed the successful lint check.
- No provider/network research trial was run.

# Not Changed

- No algorithm, threshold, YAML, TVLC, feature formula, lifecycle, MTF, execution, or trading-policy change.
- No normalized-input persistence remediation and no fresh-window provider request.
- No merge, push, rebase, history rewrite, or protected evidence rewrite.
- No change to independent legacy trendline packages.

# Risks or Follow-Up Items

- Blocking issues: none.
- Non-blocking: reviewer should independently inspect compatibility object identity, historical provider/scorer identity, additive storage/configuration semantics, and fresh-window persisted-stream identity.
- Non-blocking: lint relied on global `ruff` because project virtual environment lacks Ruff.
- Package is complete enough for `quant-review` to act without guessing.
