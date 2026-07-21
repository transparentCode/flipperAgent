---
goal: Independently review safe removal of obsolete Trendline scaffolding
stage: orchestrator-decision
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, trendline, cleanup, decision]
---

# Trendline Obsolete Cleanup V1 Decision

## Decision

**APPROVED**

Cleanup removes only proven-obsolete scaffolding and reduces internal reliance
on compatibility facades. No model behavior, public compatibility surface,
persisted identity, configuration, serialization, or protected evidence changed.

## Reviewed state

- Base branch: `main`
- Base commit: `6aadfecdb3209e254e4899b0ab956d3410e1a05d`
- Feature branch: `refactor/trendline-obsolete-cleanup-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-obsolete-cleanup-v1`
- Reviewed HEAD before this decision: `cec99f7c3206c71d8921b74e1f0b9c5a3d31488f`
- Original checkout: clean on `main` at base commit
- Merge/push/rebase/cherry-pick: none

## Approved changes

Deleted exactly:

- `src/libs/models/trendline/domain/contracts.py`
- `src/libs/models/trendline/domain/entities.py`

Both were thin duplicate aliases with zero source, test, script, dynamic-import,
package-export, or pickle identity consumers. Canonical ownership remains in
`domain/context.py`, `domain/families.py`, and `domain/__init__.py`.

Migrated imports only in:

- `src/libs/models/trendline/api.py`
- `src/libs/models/trendline/config_loader.py`
- `src/libs/integrations/trendline_regime_v2/ablation.py`
- `src/libs/integrations/trendline_regime_v2/shadow.py`

These now import direct canonical owners. Runtime object-identity tests pass.

## Retained compatibility

- All canonical root forwarding modules.
- Entire `libs.models.trendline_family` package.
- Trendline configuration integration seam.
- Historical optimization ablation facades.
- Historical provider and scorer identity strings.
- `interaction/zones.py` target architecture seam.
- `_phase_g_enabled` historical repository export.

Historical plan documents still mention deleted module paths as prior architecture
evidence. They remain untouched intentionally and are not runtime consumers.

## Independent evidence

- Fresh codebase-memory index: zero nodes for deleted module paths.
- Exact deletion set: two approved files only.
- Protected-scope diff across configs, artifacts, research, old trendline, SR,
  `trendline_family`, and configuration integration: empty.
- Import-boundary and obsolete-reference guards: passed.
- Historical pickle, provider/scorer identity, snapshot identity, MTF,
  configuration, replay, and compatibility tests: passed in combined suites.

Independent validation:

```text
core and consumer suite: 420 passed in 29.08s
trendline script suite:   157 passed in 69.86s
Ruff:                     passed
compileall:               passed
git diff --check:         passed
```

## Residual risk

Unknown external code could import either deleted submodule directly. Risk is
low: modules owned no class/function identity, were undocumented package
exports, and had no tracked runtime consumers. Deletion commit can be reverted
independently if external evidence appears.

Removing root facades or `trendline_family` remains a breaking-change decision,
not part of this cleanup.

## Integration state

No merge or push performed. Feature branch is ready for user review or explicit
integration request.

APPROVED
