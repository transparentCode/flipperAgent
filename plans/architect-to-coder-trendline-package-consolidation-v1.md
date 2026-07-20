---
goal: Finish and validate the existing trendline package consolidation without changing model behavior or protected prior evidence
stage: architect-to-coder
date_created: 2026-07-21
last_updated: 2026-07-21
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, trendline, package-migration, invariants]
source_agent: Quant Orchestrator
target_agent: quant-coder
---

# Objective

Finish the current dirty-tree migration that makes `libs.models.trendline` the canonical stateful Trendline Family implementation and `libs.models.trendline_family` a compatibility-only surface. Validate the full candidate, fix only concrete implementation defects, document actual additive scope accurately, and create one reviewable commit.

# Scope Boundaries

- Candidate implementation: `src/libs/models/trendline/`.
- Compatibility surface: `src/libs/models/trendline_family/`.
- Neutral integrations: `src/libs/integrations/trendline_configuration/` and `src/libs/integrations/trendline_regime_v2/`.
- Direct canonical consumers: six modified research scripts and RegimeV2 family adapter.
- Migration and invariant tests under `tests/models/trendline_family/`, plus direct script and RegimeV2 adapter tests.
- Existing dirty source/test changes are implementation candidate input. Preserve prior plan, artifact, log, dataset, and fixture bytes. Do not rewrite protected evidence to make validation pass.

# Affected Symbols, Modules, and Execution Flows

- `libs.models.trendline.api.update_trendline_families` through config resolution, tracker update, provider generation, repository reads/writes, snapshots, and features.
- `libs.models.trendline.tracker.TrendlineFamilyTracker.update` and all callers/callees.
- `libs.models.trendline.provider.NativeDeterministicLineProvider` including persisted provider identity.
- `libs.models.trendline.optimization.ablation.WeightedFeatureScorer` including persisted scorer identity.
- Compatibility forwarding through `libs.models.trendline_family._compat.reexport_module`.
- Historical storage through `libs.models.trendline.storage` and `TrendlineContext` reconstruction.
- Typed configuration resolution and provenance through `libs.integrations.trendline_configuration`.
- RegimeV2 shadow/ablation consumers through `libs.integrations.trendline_regime_v2`.
- Separate systems remain independent: `libs.trendlines`, `app.trendlines`, and `libs.models.trendlines_old`.

Before editing any existing symbol, use codebase-memory `search_graph`, `trace_path`, and `get_code_snippet` on the exact symbol. Warn the orchestrator before proceeding if impact is HIGH or CRITICAL beyond the scope above.

# Data Contracts or Interfaces

- Exact line geometry and `value_at` behavior must remain unchanged.
- Completed-bar causality and no-future-evidence rules must remain unchanged.
- Deterministic family, snapshot, event, MTF, relation, cluster, config, and artifact identities must remain unchanged.
- Family geometry identity remains distinct from support/resistance role.
- Frozen snapshots/events/domain contexts keep field order, defaults, ordering, UTC, and `as_of` validation.
- Snapshot serialization and old/new object identity parity must hold.
- Historical module paths must import canonical objects. Historical built-in provider and scorer identity strings remain `libs.models.trendline_family.*`.
- Explicit abstention remains typed and reason-coded.
- MTF source ordering, freshness, allowlist, completeness, and evidence hashes remain deterministic.
- External `current_price` remains an assertion input, not feature calculation source.

# Implementation Order

1. Capture git status and protected-evidence inventory. Do not alter existing plans, artifacts, logs, trial inputs, or fixtures.
2. Use codebase-memory to inspect callers/callees for each symbol that needs modification.
3. Audit atomic package ownership and import direction. Canonical code must not import compatibility or legacy trendline packages.
4. Audit compatibility object identity, serialization, and persisted semantic identities.
5. Audit additive Phase 1C-1E domain/storage/config/integration work separately from package-move parity. Fix only proven defects.
6. Run narrow migration/invariant tests first, then full trendline-family, integration, script, lint, compile, and diff checks.
7. Run change-scope detection before commit. Review every staged path. Create one intentional commit only after checks pass.
8. Return exact changed files, validation output, residual risks, and commit hash.

# Acceptance Criteria

- `libs.models.trendline` owns one canonical implementation.
- `libs.models.trendline_family` contains forwarding compatibility only, with old/new object identity parity.
- `libs.trendlines`, `app.trendlines`, and `libs.models.trendlines_old` remain byte-unchanged and semantically independent.
- Partial staging cannot omit canonical or neutral integration modules required by compatibility consumers.
- Exact geometry, causal updates, deterministic IDs/hashes, family/role separation, immutable contracts, replay, abstention, MTF evidence, and RegimeV2 feature contracts pass tests.
- Phase 1D historical storage and Phase 1E configuration semantics are acknowledged as additive behavior, not mislabeled as pure no-behavior-change movement.
- No fresh-window provider request occurs. Persisted normalized-input identity drift remains separate work.
- No protected prior evidence bytes change.
- Complete candidate is committed once and ready for independent review.

# Validation Checklist

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
PYTHONPATH=src .venv/bin/python -m pytest tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py tests/signals/test_trendline_family_shadow_projected_runtime.py -q -ra
PYTHONPATH=src .venv/bin/python -m pytest tests/scripts/test_trendline_family_candidate_geometry_trial.py tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py tests/scripts/test_trendline_family_candidate_evidence_report.py tests/scripts/test_trendline_family_candidate_rejection.py tests/scripts/test_trendline_family_candidate_density.py tests/scripts/test_trendline_family_candidate_quality_normalization.py -q -ra
PYTHONPATH=src .venv/bin/python -m pytest tests/test_regime_v2_trendline_feature_producer.py tests/models/sr/research/studies/swing_reversal_adequacy/test_import_boundaries.py -q -ra
.venv/bin/ruff check src/libs/models/trendline src/libs/models/trendline_family src/libs/integrations tests/models/trendline_family
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline src/libs/models/trendline_family src/libs/integrations
git diff --check
```

Also run focused migration, domain, storage, configuration, compatibility-pickle, and historical-identity tests before broad suites.

# Explicit Non-Goals

- No algorithm, threshold, YAML, TVLC, feature-formula, lifecycle-policy, MTF-policy, or trading-policy changes.
- No deletion or modification of `libs.trendlines`, `app.trendlines`, or `libs.models.trendlines_old`.
- No fresh-window provider call and no normalized-input persistence remediation.
- No rewrite of prior plans, artifacts, trial bundles, datasets, logs, or fixtures.
- No merge, push, rebase, history rewrite, or destructive git action.

Package is complete enough for `quant-coder` to act without guessing. Any scope contradiction routes back to Quant Orchestrator before editing.
