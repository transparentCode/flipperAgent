---
goal: Remove proven obsolete Trendline files and eliminate internal compatibility-facade dependencies
stage: architect-to-coder
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-architect
status: Ready
source_agent: quant-architect
target_agent: quant-coder
tags: [handoff, quant, trendline, cleanup]
---

# Trendline Obsolete Cleanup V1

## Objective

Delete only proven-unreferenced Trendline scaffolding and move canonical API and
integration implementations off transitional root facades. Preserve behavior,
public imports, persisted identities, serialization, hashes, and compatibility.

## Repository state

- Base branch: `main`
- Base commit: `6aadfecdb3209e254e4899b0ab956d3410e1a05d`
- Feature branch: `refactor/trendline-obsolete-cleanup-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-obsolete-cleanup-v1`
- Main checkout must remain untouched.
- Baseline combined suite: `416 passed in 25.49s`.

## Verified cleanup classification

### Delete

Delete exactly:

- `src/libs/models/trendline/domain/contracts.py`
- `src/libs/models/trendline/domain/entities.py`

Both are consolidation scaffolding with zero graph, text, dynamic-import, test,
script, documentation, `__all__`, or pickle-path references. Their runtime
objects are owned by `domain/context.py`, `domain/families.py`, and
`domain/__init__.py`.

### Migrate internal imports

- `src/libs/models/trendline/api.py`
  - import validation and snapshot contracts from direct domain owners;
  - provider protocol from `discovery.contracts`;
  - provider registry from `discovery.registry`;
  - repository protocol from `storage.repository`;
  - tracker from `tracking.service`;
  - use MTF owner package or direct MTF owners without a transitional root file.
- `src/libs/models/trendline/config_loader.py`
  - forward directly to `configuration.loader`, not through integration.
- `src/libs/integrations/trendline_regime_v2/ablation.py`
  - import `ContractValidationError` from `domain.validation`.
- `src/libs/integrations/trendline_regime_v2/shadow.py`
  - replace canonical root facade imports with direct domain, discovery, MTF,
    and storage owners.

### Retain

- `src/libs/models/trendline/interaction/zones.py`: reserved target ownership
  seam; later extraction may move zone implementation into it.
- Every canonical root forwarding module.
- Entire `src/libs/models/trendline_family/` compatibility package.
- `src/libs/integrations/trendline_configuration/` forwarding seam.
- Canonical and family optimization ablation compatibility surfaces.
- `repository._phase_g_enabled` compatibility export.
- `domain/serialization.py`, configuration `derived.py`, and `profiles.py`.

### Breaking work explicitly deferred

- Deleting root facades or `trendline_family`.
- Changing provider identity
  `libs.models.trendline_family.provider.NativeDeterministicLineProvider`.
- Changing scorer identity
  `libs.models.trendline_family.optimization.ablation.WeightedFeatureScorer`.
- Removing lightly used public exports without versioned deprecation evidence.

## Implementation requirements

1. Add/extend AST import-boundary tests so canonical API and RegimeV2
   integration implementations cannot regress to canonical transitional root
   facades. Include `config`, `config_loader`, `config_resolver`,
   `event_lifecycle`, and `registry` in facade inventory.
2. Add a guard proving deleted module paths are absent and have zero tracked
   references. Do not create runtime import shims for deleted paths.
3. Add direct object-identity tests for migrated imports where useful.
4. Delete only two approved files.
5. Do not change algorithms, configuration, identities, serialization,
   lifecycle, outputs, protected evidence, or old-model packages.
6. Inspect caller/callee impact through codebase-memory before edits.
7. Commit import isolation and deletions separately. User request authorizes
   implementing cleanup on this feature branch; do not merge or push.

Suggested commits:

```text
refactor(trendline): isolate compatibility facades
refactor(trendline): remove obsolete domain scaffolds
docs(trendline): record obsolete cleanup evidence
```

## Acceptance criteria

- Exactly two production files deleted.
- Canonical API and integration implementations use direct owners.
- Root and `trendline_family` compatibility imports retain identical objects.
- Historical pickle fixture loads.
- Provider/scorer identity strings unchanged.
- Snapshot bytes, IDs, hashes, transitions, events, MTF payloads unchanged.
- Protected artifacts/config unchanged.
- Original checkout remains clean.

## Validation

Run focused boundary, identity, configuration, snapshot, MTF, and integration
tests first. Then:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  -q -ra

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_* -q -ra

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

Stop on identity/hash/serialization drift, compatibility import failure,
protected-artifact change, need for algorithm change, or pressure to delete more
than two files.

## Residual risk

Unknown external consumers could import either deleted module directly. Risk is
low: neither owns a class/function module identity, neither is documented or
exported, and repository-wide reference scans are empty. Revert deletion commit
if external evidence later appears.

READY_FOR_CODER
