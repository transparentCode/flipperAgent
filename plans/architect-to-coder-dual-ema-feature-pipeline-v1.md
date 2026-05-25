---
goal: Add multi-instance indicator support to FeatureManager so features.yaml can declare multiple instances of the same indicator type with different parameters and distinct output keys
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, feature-pipeline, indicator, multi-instance, ema, trend-following]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Multi-Instance Indicator Support v1

## 1. Objective

Enable `features.yaml` to declare multiple instances of the same indicator type (e.g., two EMAs with different periods) with distinct output keys, so that `FeatureManager.process_tick()` publishes all instances under their configured aliases and downstream models (e.g., `TrendFollowingModel` expecting `EMA_fast` and `EMA_slow`) receive the correct keys in the `FeatureVector`.

**Root cause:** Currently, YAML dict keys must be unique, and `FeatureManager` uses `ind.__class__.__name__` as the output key — so only one instance of each indicator type can exist, and the output key is always the class name. `TrendFollowingModel` expects `EMA_fast` and `EMA_slow` but only receives `EMA`.

## 2. Scope Boundaries

### In Scope

- Edit `src/apps/signal_app/feature_manager.py` — support aliased indicator entries and use the alias as the output key.
- Edit `configs/features.yaml` — add `EMA_fast` and `EMA_slow` entries using the new alias syntax.
- New tests in `tests/integration/signals/test_feature_manager.py` — cover multi-instance behavior.

### Explicit Non-Goals

- Modifying `IndicatorRegistry`, `Indicator` base class, or any individual indicator implementation.
- Modifying `FeatureVector`, `ModelOutput`, or any contract in `schemas.py`.
- Modifying `TrendFollowingModel` or any model code (they already expect the correct keys).
- Modifying `SignalWorker` (it delegates to `FeatureManager` and publishes whatever dict it returns).
- Modifying `StrategyWorker`, `ModelManager`, or any `strategy_app` code.
- Adding new indicators.
- Optimization or backtesting harness changes.

---

## 3. Affected Symbols, Modules, and Execution Flows

| Symbol / Module | Change Type | Blast Radius |
|---|---|---|
| `src/apps/signal_app/feature_manager.py` → `FeatureManager.__init__` | Edit — change internal storage from `List[Indicator]` to `List[Tuple[str, Indicator]]` | Internal only. External access via `self.indicators` preserved as property. |
| `src/apps/signal_app/feature_manager.py` → `FeatureManager._initialize_indicators` | Edit — parse `type` key from params, derive output alias | Internal only. |
| `src/apps/signal_app/feature_manager.py` → `FeatureManager.prime` | Edit — iterate over tuples instead of bare indicators | Internal only. Same behavior. |
| `src/apps/signal_app/feature_manager.py` → `FeatureManager.process_tick` | Edit — use alias as output key instead of `__class__.__name__` | **Key change.** Output dict keys change from class names to config-defined aliases. For non-aliased entries, the key remains the class name (backward compatible). |
| `configs/features.yaml` | Edit — add `EMA_fast` and `EMA_slow` entries | Additive. Existing entries unchanged. |
| `src/apps/signal_app/signal_worker.py` | **No change** | Reads `self.feature_manager.indicators` for lookback — preserved via property. Publishes whatever dict `process_tick()` returns. |

**Execution flows affected:**
- **Live inference flow:** `SignalWorker.process_message()` → `FeatureManager.process_tick()` → publishes `FeatureVector` to `features:{asset}:{timeframe}` → `StrategyWorker` → `TrendFollowingModel.evaluate()`. After this change, the `FeatureVector.features` dict will contain `EMA_fast` and `EMA_slow` keys, making `TrendFollowingModel` functional in production.
- **Priming flow:** `SignalWorker.start()` → `FeatureManager.prime()` — unchanged behavior, just iterates tuples.
- **Optimization flow:** Not affected. Optimization harness uses `model.batch_evaluate()` with a pre-built DataFrame, not `FeatureManager`.

---

## 4. Design: Config-Level Aliasing via `type` Key

### 4.1 Config Format

When a `features.yaml` entry contains a `type` key, it is treated as an **aliased instance**:
- The YAML dict key becomes the **output alias** (used as the key in the results dict).
- The `type` value specifies which **indicator class** to look up in `IndicatorRegistry`.
- All other keys are passed as constructor parameters.

When there is no `type` key, the YAML dict key is both the indicator type name and the output key (current behavior — fully backward compatible).

**Example:**

```yaml
features:
  assets:
    default:
      timeframes:
        default:
          # Single-instance (existing format, unchanged):
          RSI:
            period: 14
          ATR:
            period: 14
          MACD:
            fast_period: 12
            signal_period: 9
            slow_period: 26
          BollingerBands:
            period: 20
            num_std: 2.0

          # Multi-instance (new aliased format):
          EMA_fast:
            type: EMA
            period: 12
          EMA_slow:
            type: EMA
            period: 26
```

**Output of `process_tick()`** for this config:
```python
{
    "RSI": 55.3,
    "ATR": 120.5,
    "MACD": {"line": 0.5, "signal": 0.3, "histogram": 0.2},
    "BollingerBands": {"upper": 105.0, "middle": 100.0, "lower": 95.0},
    "EMA_fast": 99.5,
    "EMA_slow": 98.2,
}
```

### 4.2 Why This Design

| Option | Description | Verdict |
|---|---|---|
| **A: `type` key in params (chosen)** | Config key = output alias, `type` = indicator class. No `type` key means key = class name. | Minimal change. Fully backward compatible. General-purpose. |
| B: List-based config | Change YAML structure to a list of `{name, type, ...}` entries. | Breaks all existing configs. Over-engineered. |
| C: Nested instances under indicator key | `EMA: {fast: {period: 12}, slow: {period: 26}}` | Ambiguous parsing — hard to distinguish nested instances from parameters. Breaks backward compat. |

### 4.3 Reserved Key

`type` becomes a reserved parameter name in `features.yaml` indicator entries. No existing indicator constructor accepts a `type` parameter, so there is no conflict.

---

## 5. Data Contracts and Interfaces

No changes to any contract or schema.

- `FeatureVector.features` is `dict[str, Any]` — new keys are just new dict entries.
- `TrendFollowingModel` already expects `EMA_fast` and `EMA_slow` — no changes needed.
- `IndicatorRegistry.get(name)` API is unchanged — it still looks up by indicator class name.
- `Indicator` ABC is unchanged.

---

## 6. Implementation Order

### Step 1: Edit `src/apps/signal_app/feature_manager.py`

**6.1.1 Change internal storage**

Replace:
```python
self.indicators: List[Indicator] = []
```

With:
```python
self._indicator_entries: list[tuple[str, Indicator]] = []
```

Add a backward-compatible property so `signal_worker.py` (and tests) that access `self.feature_manager.indicators` for lookback iteration continue to work:

```python
@property
def indicators(self) -> list[Indicator]:
    return [ind for _, ind in self._indicator_entries]
```

**6.1.2 Update `_initialize_indicators()`**

Replace the loop body to detect the `type` key:

```python
for config_key, params in timeframe_node.items():
    try:
        if isinstance(params, dict) and "type" in params:
            indicator_type = params["type"]
            output_key = config_key
            constructor_params = {k: v for k, v in params.items() if k != "type"}
        else:
            indicator_type = config_key
            output_key = config_key
            constructor_params = params if isinstance(params, dict) else {}

        indicator_class = IndicatorRegistry.get(indicator_type)
        indicator = indicator_class(**constructor_params)
        self._indicator_entries.append((output_key, indicator))
        logger.info(f"Initialized indicator {indicator_type} as '{output_key}' for {self.asset} {self.timeframe}")
    except KeyError:
        logger.warning(f"Indicator type for '{config_key}' not found in registry. Skipping.")
    except Exception as e:
        logger.error(f"Error instantiating '{config_key}': {e}", exc_info=True)
```

**6.1.3 Update `prime()`**

Change iteration from `self.indicators` to `self._indicator_entries`:

```python
def prime(self, historical_data):
    for output_key, ind in self._indicator_entries:
        try:
            mapped_data = self._get_mapped_historical_inputs(ind, historical_data)
            ind.prime(mapped_data)
            logger.info(f"Primed indicator '{output_key}'")
        except Exception as e:
            logger.error(f"Error priming '{output_key}': {e}")
            ind._is_primed = False
```

**6.1.4 Update `process_tick()`**

Change iteration and use `output_key` for the results dict:

```python
def process_tick(self, data):
    results = {}
    for output_key, ind in self._indicator_entries:
        if not ind.is_primed:
            logger.warning(f"Indicator '{output_key}' is not primed. Skipping update.")
            continue
        try:
            mapped_input = self._get_mapped_input(ind, data)
            res = ind.update(mapped_input)
            results[output_key] = res
        except Exception as e:
            logger.error(f"Indicator '{output_key}' failed during update: {e}. Un-priming.", exc_info=True)
            ind._is_primed = False
    return results
```

### Step 2: Edit `configs/features.yaml`

In the `default/default` block, **replace** the bare `EMA` entry with two aliased entries:

```yaml
          # Remove:
          # EMA:
          #   period: 20

          # Add:
          EMA_fast:
            type: EMA
            period: 12
          EMA_slow:
            type: EMA
            period: 26
```

Keep all other entries unchanged.

**Note:** If any asset/timeframe-specific block also defines `EMA`, add corresponding `EMA_fast`/`EMA_slow` overrides there as needed (check per-asset configs). Currently, no asset-specific block defines `EMA`.

### Step 3: Add tests

Add tests to `tests/integration/signals/test_feature_manager.py`:

```python
def test_feature_manager_multi_instance_indicator():
    """Multi-instance indicators produce distinct output keys."""
    ConfigManager.reset_singleton()
    # Patch config to include aliased EMA entries
    config_mgr = ConfigManager()
    config_mgr._state = {
        "features": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "EMA_fast": {"type": "EMA", "period": 9},
                            "EMA_slow": {"type": "EMA", "period": 21},
                            "RSI": {"period": 14},
                        }
                    }
                }
            }
        }
    }

    fm = FeatureManager("ANYASSET", "1h")

    # Should have 3 indicators
    assert len(fm.indicators) == 3

    # Verify EMA instances have different periods
    ema_entries = [(k, ind) for k, ind in fm._indicator_entries if ind.__class__.__name__ == "EMA"]
    assert len(ema_entries) == 2
    periods = {k: ind.period for k, ind in ema_entries}
    assert periods == {"EMA_fast": 9, "EMA_slow": 21}

    # Prime and tick
    history = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i, 10.0, 1600000000 + i * 3600) for i in range(30)]
    fm.prime(history)

    tick = (131.0, 129.0, 130.0, 10.0, 1600000000 + 30 * 3600)
    res = fm.process_tick(tick)

    # Output keys must be the aliases, not "EMA"
    assert "EMA_fast" in res
    assert "EMA_slow" in res
    assert "RSI" in res
    assert "EMA" not in res  # No bare "EMA" key
    assert res["EMA_fast"] != res["EMA_slow"]  # Different periods → different values


def test_feature_manager_backward_compat_no_type_key():
    """Entries without 'type' key still work with class name as output key."""
    ConfigManager.reset_singleton()
    config_mgr = ConfigManager()
    config_mgr._state = {
        "features": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "EMA": {"period": 20},
                            "RSI": {"period": 14},
                        }
                    }
                }
            }
        }
    }

    fm = FeatureManager("ANYASSET", "1h")
    assert len(fm.indicators) == 2

    history = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i, 10.0, 1600000000 + i * 3600) for i in range(30)]
    fm.prime(history)

    tick = (131.0, 129.0, 130.0, 10.0, 1600000000 + 30 * 3600)
    res = fm.process_tick(tick)

    assert "EMA" in res
    assert "RSI" in res
```

---

## 7. Acceptance Criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | `features.yaml` entries **without** a `type` key continue to work identically — output key equals the config key (which is the indicator class name). | Existing tests pass unchanged. New backward-compat test passes. |
| 2 | `features.yaml` entries **with** a `type` key instantiate the correct indicator class and use the config key as the output alias. | New multi-instance test passes. |
| 3 | `FeatureManager.process_tick()` returns a dict with aliased keys for multi-instance entries and class-name keys for single-instance entries. | Assertion on output dict keys. |
| 4 | `SignalWorker` code is **unchanged** and continues to work. | `signal_worker.py` has zero diffs. Existing tests pass. |
| 5 | Two EMA instances with different periods produce different output values. | Assertion `res["EMA_fast"] != res["EMA_slow"]`. |
| 6 | `TrendFollowingModel.evaluate()` receives `EMA_fast` and `EMA_slow` in the features dict (end-to-end integration). | Manual or integration test: construct a `FeatureVector` from `process_tick()` output and pass to `TrendFollowingModel.evaluate()` → `direction != 0` when EMA values diverge. |
| 7 | No cross-app imports introduced. | Grep verification. |
| 8 | No `os.getenv` or `logging.getLogger` introduced. | Grep verification. |
| 9 | All existing tests pass with zero regressions. | `pytest tests/ -v` |

---

## 8. Validation Checklist

- [ ] Existing `test_feature_manager` and `test_feature_manager_multiple_indicators` pass unchanged.
- [ ] Existing `test_feature_config.py` tests pass unchanged.
- [ ] New `test_feature_manager_multi_instance_indicator` passes.
- [ ] New `test_feature_manager_backward_compat_no_type_key` passes.
- [ ] `signal_worker.py` has zero code changes.
- [ ] No new files created (only edits to existing files + new test functions).
- [ ] `type` is not used as a constructor parameter by any existing indicator (verify: grep for `def __init__.*type` in `src/libs/features/indicators/`).
- [ ] `process_tick()` output keys match what `TrendFollowingModel` expects.
- [ ] Full test suite: `PYTHONPATH=. ./.venv/bin/pytest tests/ -v --tb=short`.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| An indicator class uses `type` as a constructor parameter name | Very low — no existing indicator does. Python's `type` is a builtin, unlikely to be used. | Grep check in validation. If found, rename the reserved key to `_type` or `indicator_type`. |
| Config migration — users with custom `features.yaml` don't know about `type` key | Low — purely additive. Existing configs are unaffected. | Document the new format in `docs/best_practices.md` or config comments. |
| Fallback chain resolution — an aliased entry in an asset-specific block doesn't fall back correctly | Low — fallback resolves the entire timeframe block, not individual entries. | Existing fallback logic is unchanged. Test with asset-specific aliased entries if needed. |

---

## 10. Summary

This is a minimal, backward-compatible change to **one source file** (`feature_manager.py`) and **one config file** (`features.yaml`). The design uses a `type` key convention in the YAML config to distinguish aliased multi-instance entries from standard single-instance entries. No changes to the indicator registry, indicator base class, individual indicators, contracts, models, or worker processes.

Total estimated diff: ~30 lines changed in `feature_manager.py`, ~6 lines changed in `features.yaml`, ~60 lines of new tests.
