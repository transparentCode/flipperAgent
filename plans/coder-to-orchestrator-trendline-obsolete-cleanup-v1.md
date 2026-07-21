---
goal: Remove proven obsolete Trendline scaffolds while preserving all compatibility and behavior
stage: coder-to-orchestrator
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendline, cleanup]
---

# Trendline Obsolete Cleanup V1

## Outcome

Completed bounded cleanup contract. Canonical API and RegimeV2 integration
implementations now import direct owners. Exactly two approved obsolete domain
scaffolds were deleted. Compatibility objects, public behavior, deterministic
outputs, configuration, and protected evidence remain unchanged in validation.

## Branch and worktree

- Base branch: `main`
- Base commit: `6aadfecdb3209e254e4899b0ab956d3410e1a05d`
- Contract commit: `9120d3262fbe172538ebb0e8148d9b33411ec98c`
- Feature branch: `refactor/trendline-obsolete-cleanup-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-obsolete-cleanup-v1`
- Implementation HEAD before this handoff commit: `dcd538163c6e3aaaed1ed92d62553aecdce580c1`
- Original checkout: clean on `main` at
  `6aadfecdb3209e254e4899b0ab956d3410e1a05d`

No merge, push, rebase, force-push, branch switch, or original-checkout edit
occurred.

## Commits

1. `ed9d603` — `refactor(trendline): isolate compatibility facades`
   - Migrated canonical API, config loader, RegimeV2 ablation, and RegimeV2
     shadow imports to direct owners.
   - Expanded transitional-facade inventory.
   - Added AST import guards and direct/public object-identity tests.
2. `dcd5381` — `refactor(trendline): remove obsolete domain scaffolds`
   - Deleted only `domain/contracts.py` and `domain/entities.py`.
   - Added absence, static-import, relative-import, and dynamic-reference guard.

## Changed implementation ownership

### Direct-owner migrations

- `src/libs/models/trendline/api.py`
  - domain snapshots and validation;
  - discovery contracts and registry;
  - MTF composition and contracts;
  - storage repository;
  - tracking service.
- `src/libs/models/trendline/config_loader.py`
  - canonical `configuration.loader` directly.
- `src/libs/integrations/trendline_regime_v2/ablation.py`
  - `domain.validation.ContractValidationError` directly.
- `src/libs/integrations/trendline_regime_v2/shadow.py`
  - direct domain, discovery, MTF, and storage owners.

### Deleted

- `src/libs/models/trendline/domain/contracts.py`
- `src/libs/models/trendline/domain/entities.py`

Graph refresh before deletion showed both modules had zero external inbound
dependencies. Final codebase-memory refresh returned zero nodes for both paths.

### Tests

- Updated `tests/models/trendline_family/test_import_boundaries.py`.
- Added `tests/models/trendline_family/test_obsolete_cleanup.py`.

## Compatibility and identity evidence

New tests prove identical runtime objects across:

- API-imported domain, provider, repository, tracker, and MTF contracts;
- RegimeV2 shadow and ablation imports;
- canonical root forwarding modules;
- `libs.models.trendline_family` forwarding package;
- canonical, family, and integration configuration loaders.

Existing broad tests continued to prove:

- historical pickle fixture loading;
- serialized snapshot parity and snapshot identity;
- provider identity
  `libs.models.trendline_family.provider.NativeDeterministicLineProvider`;
- scorer identity
  `libs.models.trendline_family.optimization.ablation.WeightedFeatureScorer`;
- resolved configuration values and hashes;
- family/event transitions, events, MTF payloads, replay, and public outputs.

No algorithm, configuration, identity, serialization, lifecycle, or model-output
code changed. Implementation diff contains import-path substitutions only.

## Import and deletion guards

AST guard inventory now includes:

- `config`;
- `config_loader`;
- `config_resolver`;
- `event_lifecycle`;
- `registry`;
- all previously tracked root facades.

Guard scope covers canonical owner packages plus canonical API, canonical config
loader, RegimeV2 ablation, and RegimeV2 shadow. Deleted-module guard checks file
absence and scans all `src/**/*.py` and `tests/**/*.py` for absolute, relative,
and dynamic module references.

Final graph/text checks found:

- zero nodes for both deleted module paths;
- zero old facade imports in RegimeV2 shadow/ablation;
- zero integration-loader imports from canonical `config_loader.py`.

GitNexus compare-scope impact from contract commit reported:

- risk: LOW;
- affected processes: zero;
- affected symbols: test guard symbols only.

## Validation evidence

### Focused baseline

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/test_import_boundaries.py \
  tests/models/trendline_family/test_phase_1c_domain_contracts.py \
  tests/models/trendline_family/test_ablation_compatibility.py \
  tests/models/trendline_family/test_api.py \
  tests/models/trendline_family/test_config_loader.py \
  tests/models/trendline_family/test_mtf.py \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py -q -ra
```

Result: `56 passed in 1.51s`.

### Focused post-migration

Result: `59 passed in 1.39s`.

### Focused post-deletion

Result: `65 passed in 4.20s`.

### Exact broad suite

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  -q -ra
```

Result: `420 passed in 27.03s`.

### Exact script suite

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_* -q -ra
```

Result: `157 passed in 69.46s`.

### Static checks

```bash
ruff check \
  src/libs/models/trendline \
  src/libs/models/trendline_family \
  src/libs/integrations/trendline_configuration \
  src/libs/integrations/trendline_regime_v2 \
  tests/models/trendline_family
```

Result: `All checks passed!`.

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline \
  src/libs/models/trendline_family \
  src/libs/integrations
```

Result: exit `0`.

```bash
git diff --check 9120d3262fbe172538ebb0e8148d9b33411ec98c..HEAD
```

Result: exit `0`.

## Scope and protected evidence

Implementation diff from contract commit contains eight paths:

- four modified implementation files;
- exactly two deleted production files;
- one modified test file;
- one added test file.

No config, fixture, research, artifact, old-model, SR, or
`trendline_family` compatibility file changed. `npx gitnexus analyze` generated
unrelated `AGENTS.md`, `CLAUDE.md`, and `.claude/` edits during graph refresh;
all generated changes were reverted before validation and are absent from diff.

## Non-goals preserved

- No extra obsolete-file deletion.
- No root-facade or `trendline_family` deletion.
- No provider/scorer identity change.
- No algorithm, parameter, lifecycle, serialization, or config change.
- No old-model or SR package use.

## Blockers and residual risk

No blockers.

Residual risk: unknown external consumers outside repository could import either
deleted module path directly. Contract classified risk low because neither module
owned a class/function identity, neither was exported/documented, and repository
graph plus reference scans were empty. Revert deletion commit if external evidence
appears.

Verified facts above come from live feature worktree. No assumptions remain for
orchestrator review.

READY_FOR_ORCHESTRATOR_REVIEW
