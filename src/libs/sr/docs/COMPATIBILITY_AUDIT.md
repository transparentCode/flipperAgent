# SR Compatibility Audit

Audit date: 2026-04-29

This document records the remaining compatibility surface for `app/sr` after the v2 migration and post-hardening cleanup pass.

## Summary

- The legacy module paths listed in the cleanup plan are already removed from the current `app/sr` tree except for `app/sr/state/state_manager.py`.
- No in-repo imports of the removed module paths were found.
- The only live deprecated class alias that remains intentionally supported is `SRStateManager` in `app/sr/state/state_manager.py`.
- `ZoneStateStore` keeps a small set of method-level compatibility delegates (`snapshot`, `restore`, `snapshot_levels`, `restore_levels`) that forward to the canonical v2 persistence methods.

## Wrapper Status Matrix

| Legacy Surface | Current File Status | Canonical Replacement | Current Support Decision | Removal Target |
|-|-|-|-|-|
| `app.sr.orchestrator` | File absent | `app.sr.pipeline.SRv2Pipeline` and `app.sr.universe.router.UniverseSRRouter` | Not supported. No remaining in-repo imports found. | Already removed. |
| `app.sr.aggregation.mtf_aggregator` | File absent | `app.sr.pipeline.SRv2Pipeline` coordinated pipeline flow | Not supported. No remaining in-repo imports found. | Already removed. |
| `app.sr.detectors.base` | File absent | `app.sr.kernels.base.BaseSRKernel` | Not supported. No remaining in-repo imports found. | Already removed. |
| `app.sr.enhancement.base` | File absent | No direct module alias. Behavior is owned by the v2 pipeline and lifecycle surfaces. | Not supported. No remaining in-repo imports found. | Already removed. |
| `app.sr.optimization.optimizer` | File absent | `app.sr.optimization.universe_optimizer.UniverseSROptimizer` | Not supported. No remaining in-repo imports found. | Already removed. |
| `app.sr.state.state_manager.SRStateManager` | File present | `app.sr.state.state_manager.ZoneStateStore` | Intentionally supported as a deprecated class alias. Emits `DeprecationWarning` on construction. | Remove in the next focused SR deprecation-removal pass after external callers migrate. |
| `ZoneStateStore.snapshot`, `restore`, `snapshot_levels`, `restore_levels` | File present | `snapshot_zones`, `restore_zones`, `snapshot_scored_levels`, `restore_scored_levels` | Intentionally supported as thin delegation helpers for compatibility. | Review in the same future deprecation-removal pass as `SRStateManager`. |

## Search Notes

- No current `app/sr/**` matches for `datetime.utcnow`.
- No current in-repo imports were found for `app.sr.orchestrator`, `app.sr.aggregation.mtf_aggregator`, `app.sr.detectors.base`, `app.sr.enhancement.base`, or `app.sr.optimization.optimizer`.
- In-repo imports of `app.sr.state.state_manager` are limited to canonical `ZoneStateStore` usage plus the explicit `SRStateManager` deprecation regression in `app/sr/tests/test_phase5.py`.