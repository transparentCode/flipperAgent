# V1 Regression Removal Readiness Assessment

## Summary

**Can v1 be safely removed after full v2 migration? Yes — with a defined sequence.**

Once all consumers import from v2 (either `api.py` or `compat.py`), v1 can be removed in a single coordinated step. The main blocker is `compat.py` itself, which imports v1 types to re-export them for consumer convenience. Once consumers are migrated to use v2-native types, `compat.py`'s v1 imports become unnecessary, and v1 can be deleted.

## Current Consumer Status

### Already Migrated to v2 compat (no direct v1 imports)

| Consumer | Import Path | Status |
|-|-|-|
| `app/strategy/regime_regression.py` | `from app.regression.compat import ...` | Migrated |
| `app/cross_sectional/orchestrator.py` | `from app.regression.compat import ...` | Migrated |
| `app/backtest/features/regime_regression.py` | `from app.regression.compat import ...` | Migrated |

### Indirect Consumers (import from migrated modules, not v1 directly)

| Consumer | Imports From | Status |
|-|-|-|
| `app/backtest/runner.py` | `app.backtest.features.regime_regression` (RegimeBridge) | OK — uses migrated module |
| `app/backtest/bridge/regime_regression.py` | `app.backtest.features.regime_regression` (shim) | OK — compat shim |
| `app/backtest/bridge/__init__.py` | `app.backtest.features.regime_regression` | OK — re-export |
| `app/backtest/strategies/regime_regression_strategy.py` | `app.strategy.regime_regression` | OK — uses migrated module |
| `app/backtest/scripts/run_hybrid_30m.py` | `app.backtest.features.regime_regression` | OK — uses migrated module |

### V2 Internal Dependencies on V1

| File | What It Imports | Why |
|-|-|-|
| `app/regression/compat.py` | V1 `PipelineConfig`, `OrchestratorConfig`, `PluginConfig`, `RegressionContext`, `RegimeSnapshot`, `CascadeContext` | Re-exports for consumer convenience + config conversion |
| `app/regression/tests/test_phase6_integration.py` | V1 `PipelineConfig`, `OrchestratorConfig`, `PluginConfig`, `RegressionContext`, `RegimeSnapshot` | Integration tests validating compat layer |

### V1-Only Code (stays in v1, no v2 equivalent)

| File | Description |
|-|-|
| `app/regression/adaptive_regression.py` | Bridges regime detection ↔ regression. Coordinates regime context at top level. |
| `app/regression/tvlc_formatter.py` | TradingView Lightweight Charts payload builder. |
| `app/regression/analysis/structural_channel.py` | RANSAC FractalChannel wrapper. |
| `app/regression/scripts/` | CLI scripts (run_optimization.py, monitor_optimization.py) |

## Removal Sequence

### Phase 1: Decouple `compat.py` from v1 types

Replace v1 type imports in `compat.py` with v2-native equivalents or thin local stubs:

```python
# Instead of:
from app.regression.config import PipelineConfig as V1PipelineConfig

# Provide a minimal local dataclass or use v2 types directly
```

This is the **critical step** — once compat.py no longer imports from `app.regression`, no v2 code depends on v1.

### Phase 2: Update integration tests

`test_phase6_integration.py` imports v1 types to test the compat layer. After Phase 1, either:
- Update tests to use the new stubs/v2 types
- Move compat tests to a separate file that can be deleted with v1

### Phase 3: Assess v1-only code

Decide disposition of v1-only modules:

| Module | Recommendation |
|-|-|
| `adaptive_regression.py` | Port to v2 if regime bridge is needed, or keep regime integration in consumer layer |
| `tvlc_formatter.py` | Move to `app/export/` or `app/utils/` if still needed — it has zero regression dependencies |
| `structural_channel.py` | Port to v2 `analysis/` if RANSAC channels are desired |
| `scripts/` | Rewrite against v2 API or archive |

### Phase 4: Delete `app/regression/`

Once Phases 1-3 are complete:

1. `rm -rf app/regression/`
2. Update `AGENTS.md` to remove v1 references
3. Clean up any stale imports:
   ```bash
   grep -rn "from app\.regression\b" app/ --include="*.py"
   ```
4. Run full test suite

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|-|-|-|-|
| Consumer still imports v1 directly | Low (all 3 migrated) | High | Grep audit before deletion |
| `compat.py` breaks without v1 types | Medium | High | Phase 1 decouples first |
| `adaptive_regression.py` needed | Low | Medium | Port before deleting |
| Notebooks reference v1 | Unknown | Low | Search notebooks for imports |

## Conclusion

V1 removal is safe and straightforward once `compat.py` is decoupled from v1 type imports. No external consumer currently imports v1 directly — they all go through v2 compat. The removal is a 4-phase sequence that can be done incrementally.
