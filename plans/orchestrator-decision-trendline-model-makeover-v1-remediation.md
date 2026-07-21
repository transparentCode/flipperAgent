---
goal: Independently review Trendline Model Makeover V1 remediation
stage: orchestrator-decision
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [decision, quant, trendline, remediation]
---

# Trendline Model Makeover V1 Remediation Decision

## Decision

**APPROVED**

The bounded remediation satisfies the makeover contract and is suitable for
user review. This decision does not merge, push, declare production readiness,
or authorize the deferred Hough/research work.

## Repository state reviewed

- Base branch: `origin/main`
- Base commit: `c85a2b366133e7d7be4bc18b51bedfd793742189`
- Feature branch: `refactor/trendline-model-makeover-v1`
- Feature worktree: `/Users/aloobhujia/flipperAgent-trendline-makeover-v1`
- Remediated code/test HEAD: `1718a29afabed9a4a8cce3615d8cb44903bdf577`
- Original checkout: clean on `main` at the base commit
- Feature worktree: clean before this decision record
- Merge, push, rebase, force-push, cherry-pick: none

## Independent review findings

1. Owner packages import direct domain, configuration, interaction, discovery,
   tracking, MTF, and storage owners. They do not import transitional root
   facades. Discovery contracts own the provider protocol and result contracts.
2. `TrendlineFamilyTracker.update()` is 54 lines and delegates nine explicit
   phases backed by frozen phase-result records. Replay tests compare serialized
   snapshot bytes, identities, transitions, events, features, ordering, and
   repository writes.
3. `mtf/composition.py` is orchestration-focused at 194 lines. Projection,
   freshness, relations, clustering, serialization, features, store, and
   immutable contracts contain their actual implementations and retain public
   object identity.
4. Both semantic ATR paths call the shared validated adapter and deterministic
   Numba kernel. Short frames use `min(configured_window, row_count)`, and
   compiled versus Python tracker outputs remain byte-identical.
5. The five historical RegimeV2 ablation symbols resolve to integration-owned
   identical objects through canonical package/submodule and
   `trendline_family` package/submodule compatibility surfaces.
6. Configuration hashes, representative snapshot identity, serialization,
   causality, and public compatibility tests remain exact.
7. The malformed literal `\\x60` Markdown text was corrected.

## Review remediation

The first independent pass found that the AST helper supplied a module name,
rather than its containing package, to `importlib.util.resolve_name`. A relative
`from ..contracts import ...` could therefore evade the owner/facade guard even
though no such live violation existed.

Commit `1718a29` fixes package resolution and adds a synthetic relative-import
regression. Independent rerun: `8 passed` for the import-boundary module.

## Independent validation

Exact combined command:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  -q -ra
```

Result: `416 passed in 25.19s`.

Additional independent evidence:

- Ruff over all required canonical, compatibility, integration, and test paths:
  passed.
- `compileall` over canonical, compatibility, and integration packages: passed.
- `git diff --check`: passed.
- Ablation identity probe: 5 symbols across 4 historical surfaces passed.
- Owner/facade scan using corrected relative-import resolution: zero violations.
- Forbidden old trendline, SR, RegimeV2, and integration imports in canonical
  runtime: zero violations, apart from the explicitly deprecated optimization
  compatibility facades allowed by the contract.
- Original checkout remained clean on `main`.

## Independent benchmark rerun

Fixed `(4096, 3)` public DataFrame fixture, window 4096:

| Public ATR path | Python p50 | Compiled warm p50 | First compiled call | Parity |
| --- | ---: | ---: | ---: | --- |
| interaction | 1,791.938 us | 39.708 us | 140.892 ms | exact |
| normalization | 1,803.292 us | 35.250 us | 0.055 ms after shared warm-up | exact |

This supports ATR-path acceleration only, not an end-to-end tracker performance
claim.

## Residual risks and deferrals

- `tracking/service.py` remains large because lifecycle policy was not rewritten;
  its public orchestration is now phase-explicit and parity locked.
- `mtf/contracts.py` remains large because it owns the immutable MTF contract
  set; behavior-preserving subdivision can be considered separately.
- Deprecated ablation facades intentionally import integration ownership only
  when historical optimization APIs are requested.
- Hough, candidate-quality research, new providers, parameter optimization,
  SQLite, and TradingView Lightweight Charts remain deferred.

## Integration state

No merge or push was performed. The feature branch remains available for user
review and an explicitly authorized later integration action.

APPROVED
