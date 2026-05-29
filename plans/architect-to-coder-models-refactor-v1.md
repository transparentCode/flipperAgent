---
goal: Refactor src/libs/models/ to unified BaseModel hierarchy, single auto-discovery registry, per-model features.py, and consistent directory layout
stage: architect-to-coder
date_created: 2026-05-29
last_updated: 2026-05-29
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, models, refactor, registry, architecture]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect → Coder: Models Folder Refactor v1

## Objective

Refactor `src/libs/models/` from the current dual-ABC / dual-registry / manual-import structure to a clean, extensible layout with:
1. A unified `BaseModel` ABC with `model_type` discriminator
2. A single auto-discovery `ModelRegistry`
3. Per-model `features.py` declaring required indicators
4. Consistent per-model directory layout
5. A `_template/` cookiecutter for new models
6. Backward-compatible wrappers during transition

## Scope Boundaries

**In scope:**
- Merging `ScoringModel` into `BaseModel` subclass hierarchy
- Unifying `ModelRegistry` + `ScoringModelRegistry` into one registry
- Replacing manual `__init__.py` imports with auto-discovery
- Adding `model_type` field to `ModelMeta`
- Adding per-model `features.py` stubs
- Renaming `scoring_model.py` → `scorer.py` in squeeze_breakout
- Cleaning duplicate optimization files in squeeze_breakout
- Creating `_template/` directory
- Updating all consumers (apps, tests, scripts)

**Explicit non-goals:**
- Changing any model evaluation logic (signals, edge scores, directions)
- Modifying optimization algorithms or objective functions
- Adding model serialization/versioning (future phase)
- Adding standardized validation contracts beyond current level (future phase)
- Changing config YAML structure or runtime behavior
- Refactoring `scoring_feature_pipeline.py` internals

---

## Current State — File Inventory

### Top-level files
| File | Role | Disposition |
|------|------|-------------|
| `base.py` | `BaseModel` ABC + `ModelMeta` dataclass | **MODIFY** — extend `ModelMeta`, keep `BaseModel` |
| `scoring_base.py` | `ScoringModel` ABC (duplicates 80% of `BaseModel`) | **REPLACE** — make `ScoringModel` a thin subclass of `BaseModel` |
| `registry.py` | `ModelRegistry` (decorator, manual) | **REPLACE** — auto-discovery registry |
| `scoring_registry.py` | `ScoringModelRegistry` (decorator, manual) | **DEPRECATE** — thin wrapper over unified registry |
| `feature_extractors.py` | Shared helpers | **KEEP** unchanged |
| `legacy_adapter.py` | `LegacyScoringAdapter` wraps `BaseModel` → `ScoringOutput` | **MODIFY** — update imports |
| `__init__.py` | Manual import list for registration | **REPLACE** — auto-discovery |

### Per-model directories (current layout)
| Model Dir | model.py | scoring_model.py | optimization/ | monitor.py | __init__.py |
|-----------|----------|-------------------|---------------|------------|-------------|
| `squeeze_breakout/` | ✅ direction | ✅ scorer | `optimizer.py`, `scoring_optimize.py`, `scoring_optimizer.py` | ❌ | ✅ re-exports both |
| `mean_reversion/` | ✅ direction | ❌ | `optimizer.py`, `optimize.py`, `monitor.py` | ✅ | ✅ re-exports model |
| `momentum/` | ✅ direction | ❌ | `optimizer.py`, `optimize.py`, `monitor.py` | ✅ | ✅ re-exports model |
| `trend_following/` | ✅ direction | ❌ | `optimizer.py`, `optimize.py`, `monitor.py` | ✅ | ✅ re-exports model |
| `divergence_edge/` | ✅ scorer | ❌ | `optimizer.py`, `optimize.py` | ❌ | ✅ re-exports model |
| `regime_pullback/` | ✅ scorer | ❌ | `optimizer.py`, `optimize.py` | ❌ | ✅ re-exports model |
| `regime_relative_value/` | ✅ scorer | ❌ | `optimizer.py`, `optimize.py` | ❌ | ✅ re-exports model |

---

## Consumer Map — All Import Sites

### Application code (`src/apps/`)
| File | Imports | Impact |
|------|---------|--------|
| `apps/strategy_app/model_manager.py` | `BaseModel`, `ModelRegistry`, `LegacyScoringAdapter`, `import libs.models` | Phase 1+2+3 |
| `apps/strategy_app/scoring_model_manager.py` | `ScoringModel`, `ScoringModelRegistry`, `import libs.models` | Phase 2+3 |
| `apps/strategy_app/strategy_worker.py` | `ScoringModelManager` (via scoring_model_manager) | Phase 2 (transitive) |

### Library code (`src/libs/`)
| File | Imports | Impact |
|------|---------|--------|
| `libs/optim_utils/objective.py` | `BaseModel`, `ModelRegistry`, `import libs.models` | Phase 1+3 |
| `libs/optim_utils/scoring_feature_pipeline.py` | No model imports (builds features only) | None |
| `libs/models/legacy_adapter.py` | `BaseModel`, `ModelMeta`, `ScoringModel` | Phase 2 |
| `libs/models/*/optimization/optimizer.py` (×7) | Model-specific imports + `import libs.models.*` | Phase 3 |
| `libs/models/*/optimization/optimize.py` (×6) | `import libs.models`, `scoring_feature_pipeline` | Phase 3 |
| `libs/models/squeeze_breakout/optimization/scoring_optimize.py` | `import scoring_optimizer` | Phase 4 (cleanup) |
| `libs/models/squeeze_breakout/optimization/scoring_optimizer.py` | Model-specific imports | Phase 4 (cleanup) |

### Scripts (`scripts/`)
| File | Imports | Impact |
|------|---------|--------|
| `scripts/batch_optimize.py` | `import libs.models`, `scoring_feature_pipeline` | Phase 3 |
| `scripts/mr_optimization_v7.py` | `import libs.models`, `scoring_feature_pipeline` | Phase 3 |
| `scripts/sb_2yr_validation.py` | `import libs.models`, `scoring_feature_pipeline` | Phase 3 |

### Tests (`tests/`)
| File | Imports | Impact |
|------|---------|--------|
| `tests/test_legacy_adapter.py` | `BaseModel`, `ModelMeta`, `ScoringModel`, `LegacyScoringAdapter`, `ModelRegistry`, `SqueezeBreakoutModel`, `MeanReversionModel` | Phase 2+3 |
| `tests/test_migration_workflow.py` | `BaseModel`, `ModelMeta`, `LegacyScoringAdapter`, `ModelRegistry` | Phase 1+3 |
| `tests/test_mean_reversion_model.py` | `ModelRegistry`, `MeanReversionModel` | Phase 1 |
| `tests/test_squeeze_breakout_model.py` | `SqueezeBreakoutModel` | Phase 1 (transitive) |
| `tests/test_scoring_model.py` | `ScoringModel`, `ModelMeta` | Phase 2 |
| `tests/test_scoring_model_manager.py` | `ScoringModelRegistry` | Phase 2 |
| `tests/test_regime_pullback_scorer.py` | `RegimePullbackScorer` | None (direct model import) |
| `tests/test_regime_relative_value_scorer.py` | `RegimeRelativeValueScorer`, `RegimePullbackScorer`, `DivergenceEdgeScorer`, `ScoringModelRegistry` | Phase 2 |
| `tests/test_divergence_edge_optimizer.py` | `divergence_edge.optimization.optimizer` | None (direct) |
| `tests/test_regime_pullback_optimizer.py` | `regime_pullback.optimization.optimizer` | None (direct) |
| `tests/models/test_models.py` | `MeanReversionModel`, `TrendFollowingModel`, `MomentumModel` | Phase 1 (transitive) |
| `tests/models/test_optimization.py` | `MeanReversionModel` | Phase 1 (transitive) |
| `tests/models/test_optimization_scoring.py` | `mean_reversion.optimization.optimizer`, `trend_following.optimization.optimizer` | None (direct) |

---

## Data Contracts / Interfaces

### Extended ModelMeta (target)
```python
@dataclass(frozen=True)
class ModelMeta:
    """Declarative metadata each model exposes."""
    name: str
    model_type: str  # "direction" | "scoring" | "ensemble" | "ml"
    required_indicators: list[str]
    required_fields: list[str]
    hyperparameter_schema: dict[str, ParamDef] = field(default_factory=dict)
    min_history_bars: int = 0
    external_data_sources: list[str] = field(default_factory=list)
    sub_models: list[str] = field(default_factory=list)
    artifacts_path: str | None = None
    trainable: bool = False
```

### Unified BaseModel ABC (target)
```python
class BaseModel(ABC):
    """Abstract base for all quantitative models."""
    meta: ModelMeta  # must declare model_type

    def __init__(self, params: dict[str, Any]) -> None: ...
    def _defaults(self) -> dict[str, Any]: ...
    def validate_features(self, available: set[str]) -> list[str]: ...
    def validate_required_fields(self, available: set[str]) -> list[str]: ...

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ModelOutput | ScoringOutput: ...

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series: ...  # template method

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series: ...
```

### ScoringModel (target — thin subclass)
```python
class ScoringModel(BaseModel):
    """Marker subclass for models that emit ScoringOutput."""
    # Inherits everything from BaseModel — no duplication
    # Subclasses override evaluate() to return ScoringOutput
    pass
```

### Auto-discovery Registry (target)
```python
class ModelRegistry:
    _registry: dict[str, Type[BaseModel]] = {}

    @classmethod
    def register(cls, name: str): ...  # decorator (kept)

    @classmethod
    def get(cls, name: str) -> Type[BaseModel]: ...

    @classmethod
    def list_all(cls) -> list[str]: ...

    @classmethod
    def list_by_type(cls, model_type: str) -> list[str]: ...

    @classmethod
    def auto_discover(cls) -> None:
        """Scan models/*/ for BaseModel subclasses and register them."""
        ...
```

### ScoringModelRegistry (backward-compat wrapper)
```python
class ScoringModelRegistry:
    """Thin wrapper — delegates to ModelRegistry, filters by model_type='scoring'."""

    @classmethod
    def get(cls, name: str) -> Type[BaseModel]:
        import warnings
        warnings.warn("ScoringModelRegistry is deprecated. Use ModelRegistry.", DeprecationWarning, stacklevel=2)
        return ModelRegistry.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return ModelRegistry.list_by_type("scoring")

    @classmethod
    def register(cls, name: str):
        """Delegate to ModelRegistry.register."""
        return ModelRegistry.register(name)
```

---

## Implementation Order — 5 Phases

### Phase 1: Extend ModelMeta + Add model_type to Existing Models
**Risk: LOW — additive only, no interface breaks**

#### Changes
1. **`src/libs/models/base.py`** — Add `model_type` field to `ModelMeta` dataclass:
   ```python
   model_type: str = "direction"  # default preserves backward compat
   ```
   Also add new optional fields: `external_data_sources`, `sub_models`, `artifacts_path`, `trainable`.

2. **Direction models** — Add `model_type="direction"` to each `ModelMeta(...)` call:
   - `squeeze_breakout/model.py`
   - `mean_reversion/model.py`
   - `momentum/model.py`
   - `trend_following/model.py`

3. **Scoring models** — Add `model_type="scoring"` to each `ModelMeta(...)` call:
   - `squeeze_breakout/scoring_model.py`
   - `divergence_edge/model.py`
   - `regime_pullback/model.py`
   - `regime_relative_value/model.py`

#### Green Gate
- [ ] `pytest tests/models/test_models.py` — all direction models pass
- [ ] `pytest tests/test_mean_reversion_model.py` — registry lookup works
- [ ] `pytest tests/test_squeeze_breakout_model.py` — squeeze model passes
- [ ] `pytest tests/test_scoring_model.py` — scoring model base passes
- [ ] `pytest tests/test_regime_pullback_scorer.py tests/test_regime_relative_value_scorer.py` — scoring models pass
- [ ] `python -c "from libs.models.base import ModelMeta; m = ModelMeta(name='t', model_type='direction', required_indicators=[], required_fields=[]); assert m.model_type == 'direction'"` — new field works
- [ ] All existing tests pass (full `pytest`)

#### Rollback
Revert the single commit. Only the `model_type` field was added with a default value — no downstream breaks.

---

### Phase 2: Unify ScoringModel → BaseModel Subclass
**Risk: MEDIUM — changes class hierarchy, but ScoringModel interface is preserved**

#### Changes
1. **`src/libs/models/scoring_base.py`** — Replace standalone ABC with thin `BaseModel` subclass:
   ```python
   from libs.models.base import BaseModel

   class ScoringModel(BaseModel):
       """Marker subclass for models that emit ScoringOutput.
       
       Inherits __init__, _defaults, validate_features, validate_required_fields,
       batch_evaluate (template method) from BaseModel.
       """
       pass
   ```
   This removes ~40 lines of duplicated code.

2. **All scoring model files** — Update `batch_evaluate` → `_batch_evaluate_impl`:
   - `divergence_edge/model.py`: Rename `batch_evaluate()` → `_batch_evaluate_impl()` (BaseModel's template method now handles temporal validation + alignment checks)
   - `regime_pullback/model.py`: Same rename
   - `regime_relative_value/model.py`: Same rename
   - `squeeze_breakout/scoring_model.py`: Same rename

3. **`src/libs/models/legacy_adapter.py`** — Update: `LegacyScoringAdapter` inherits from `ScoringModel` which now inherits from `BaseModel`. The adapter's `batch_evaluate()` override must become `_batch_evaluate_impl()` to match the template method pattern. Remove explicit delegation of `_defaults`, `validate_features`, `validate_required_fields` (now inherited).

4. **`src/apps/strategy_app/scoring_model_manager.py`** — No change needed yet (still imports `ScoringModel` and `ScoringModelRegistry` which still work).

5. **`tests/test_scoring_model.py`** — Update to verify `ScoringModel` is a `BaseModel` subclass.

6. **`tests/test_legacy_adapter.py`** — Update batch_evaluate expectations.

#### Green Gate
- [ ] `pytest tests/test_scoring_model.py` — ScoringModel inherits from BaseModel
- [ ] `pytest tests/test_legacy_adapter.py` — adapter wraps correctly
- [ ] `pytest tests/test_regime_pullback_scorer.py` — scoring evaluation unchanged
- [ ] `pytest tests/test_regime_relative_value_scorer.py` — scoring evaluation unchanged
- [ ] `pytest tests/test_scoring_model_manager.py` — manager loads models
- [ ] `python -c "from libs.models.scoring_base import ScoringModel; from libs.models.base import BaseModel; assert issubclass(ScoringModel, BaseModel)"` — hierarchy correct
- [ ] Full `pytest` passes

#### Rollback
Revert Phase 2 commit. The old standalone `ScoringModel` ABC is restored. Phase 1 changes are independent and remain valid.

---

### Phase 3: Unified Registry with Auto-Discovery
**Risk: MEDIUM — changes registration mechanism, but decorator API stays the same**

#### Changes
1. **`src/libs/models/registry.py`** — Rewrite to support:
   - `list_by_type(model_type)` method
   - `auto_discover()` class method that scans `models/*/` for `BaseModel` subclasses
   - Keep `@ModelRegistry.register(name)` decorator working (backward compat)

   ```python
   import importlib
   import pkgutil
   from pathlib import Path

   class ModelRegistry:
       _registry: dict[str, Type[BaseModel]] = {}

       @classmethod
       def register(cls, name: str):
           def wrapper(model_class: Type[BaseModel]):
               cls._registry[name] = model_class
               return model_class
           return wrapper

       @classmethod
       def get(cls, name: str) -> Type[BaseModel]:
           if name not in cls._registry:
               raise KeyError(f"Model '{name}' not found in registry.")
           return cls._registry[name]

       @classmethod
       def list_all(cls) -> list[str]:
           return list(cls._registry.keys())

       @classmethod
       def list_by_type(cls, model_type: str) -> list[str]:
           return [
               name for name, mcls in cls._registry.items()
               if hasattr(mcls, 'meta') and mcls.meta.model_type == model_type
           ]

       @classmethod
       def auto_discover(cls) -> None:
           """Import all model subpackages to trigger @register decorators."""
           package_dir = Path(__file__).parent
           for item in sorted(package_dir.iterdir()):
               if item.is_dir() and not item.name.startswith('_') and (item / '__init__.py').exists():
                   importlib.import_module(f"libs.models.{item.name}")
   ```

2. **`src/libs/models/__init__.py`** — Replace manual imports with auto-discover call:
   ```python
   from libs.models.registry import ModelRegistry
   ModelRegistry.auto_discover()
   ```

3. **`src/libs/models/scoring_registry.py`** — Convert to deprecation wrapper:
   ```python
   import warnings
   from libs.models.registry import ModelRegistry

   class ScoringModelRegistry:
       @classmethod
       def register(cls, name: str):
           return ModelRegistry.register(name)

       @classmethod
       def get(cls, name: str):
           warnings.warn(
               "ScoringModelRegistry is deprecated. Use ModelRegistry.get().",
               DeprecationWarning, stacklevel=2,
           )
           return ModelRegistry.get(name)

       @classmethod
       def list_all(cls) -> list[str]:
           return ModelRegistry.list_by_type("scoring")
   ```

4. **Update all `@ScoringModelRegistry.register(...)` decorators** to `@ModelRegistry.register(...)`:
   - `divergence_edge/model.py`
   - `regime_pullback/model.py`
   - `regime_relative_value/model.py`
   - `squeeze_breakout/scoring_model.py`

   Update their imports from `from libs.models.scoring_registry import ScoringModelRegistry` → `from libs.models.registry import ModelRegistry`.

5. **Update consumers that use `ScoringModelRegistry.get()`**:
   - `apps/strategy_app/scoring_model_manager.py` — change to `ModelRegistry.get()` or leave as-is (wrapper handles it with deprecation warning). **Recommended**: update to `ModelRegistry.get()` now.

6. **Update `import libs.models` trigger sites** — These already work because `__init__.py` calls `auto_discover()`. No changes needed in:
   - `apps/strategy_app/model_manager.py`
   - `apps/strategy_app/scoring_model_manager.py`
   - `libs/optim_utils/objective.py`
   - `scripts/batch_optimize.py`, `scripts/mr_optimization_v7.py`, `scripts/sb_2yr_validation.py`

7. **Update tests**:
   - `tests/test_scoring_model_manager.py` — update `ScoringModelRegistry` import to `ModelRegistry` or verify deprecation wrapper
   - `tests/test_regime_relative_value_scorer.py` — update registry assertion
   - `tests/test_migration_workflow.py` — uses `ModelRegistry._registry` directly, keep working
   - `tests/test_mean_reversion_model.py` — uses `ModelRegistry`, no change

#### Green Gate
- [ ] `pytest tests/test_mean_reversion_model.py` — ModelRegistry auto-discovers and finds MeanReversion
- [ ] `pytest tests/test_scoring_model_manager.py` — ScoringModelManager loads via unified registry
- [ ] `pytest tests/test_regime_relative_value_scorer.py` — scoring models registered
- [ ] `pytest tests/test_migration_workflow.py` — migration workflow passes
- [ ] `python -c "from libs.models.registry import ModelRegistry; ModelRegistry.auto_discover(); assert len(ModelRegistry.list_all()) >= 7; print(ModelRegistry.list_by_type('scoring'))"` — all models discovered, type filtering works
- [ ] `python -c "from libs.models.scoring_registry import ScoringModelRegistry; ScoringModelRegistry.list_all()"` — backward compat wrapper works
- [ ] Full `pytest` passes

#### Rollback
Revert Phase 3 commit. Restore manual `__init__.py` imports and original registry files.

---

### Phase 4: Per-Model Cleanup and Structural Consistency
**Risk: LOW — file renames, stubs, and dead code removal**

#### Changes
1. **`squeeze_breakout/scoring_model.py` → `squeeze_breakout/scorer.py`**:
   - Rename file
   - Update `squeeze_breakout/__init__.py` import
   - Search and update any direct imports of `squeeze_breakout.scoring_model`

2. **Clean duplicate optimization in squeeze_breakout**:
   - `scoring_optimize.py` is a CLI runner that calls `scoring_optimizer.py`
   - `scoring_optimizer.py` is the actual optimizer
   - Consolidate: keep `scoring_optimizer.py` as `optimization/scoring_optimizer.py`, update `scoring_optimize.py` imports

3. **Add `features.py` stubs** to every model directory:
   ```python
   """Feature requirements for <ModelName>.

   Declares required indicators and provides a build_features() helper
   for batch feature construction during optimization.
   """
   from libs.models.base import ModelMeta

   # Re-export from model.py for discoverability
   from libs.models.<model_dir>.model import <ModelClass>

   REQUIRED_INDICATORS = <ModelClass>.meta.required_indicators
   REQUIRED_FIELDS = <ModelClass>.meta.required_fields
   ```
   Add to: `squeeze_breakout/`, `mean_reversion/`, `momentum/`, `trend_following/`, `divergence_edge/`, `regime_pullback/`, `regime_relative_value/`

4. **Create `_template/` directory**:
   ```
   _template/
   ├── __init__.py          (empty, with comment)
   ├── model.py             (skeleton BaseModel subclass)
   ├── features.py          (skeleton feature declarations)
   ├── optimization/
   │   ├── __init__.py
   │   └── optimizer.py     (skeleton optimizer)
   └── README.md            (instructions for using template)
   ```

5. **Update per-model `__init__.py` files** — ensure each re-exports the model class(es) for backward compat:
   ```python
   # squeeze_breakout/__init__.py
   from libs.models.squeeze_breakout.model import SqueezeBreakoutModel  # noqa: F401
   from libs.models.squeeze_breakout.scorer import SqueezeBreakoutScorer  # noqa: F401
   ```

#### Green Gate
- [ ] `pytest tests/test_squeeze_breakout_model.py` — model still importable
- [ ] `python -c "from libs.models.squeeze_breakout import SqueezeBreakoutModel, SqueezeBreakoutScorer"` — re-exports work
- [ ] `python -c "from libs.models.squeeze_breakout.scorer import SqueezeBreakoutScorer"` — new path works
- [ ] `python -c "from libs.models.squeeze_breakout.features import REQUIRED_INDICATORS; print(REQUIRED_INDICATORS)"` — features.py works
- [ ] All per-model `features.py` importable without error
- [ ] `_template/model.py` is valid syntax
- [ ] Full `pytest` passes

#### Rollback
Revert Phase 4 commit. File renames are reversible. Features.py stubs are additive-only.

---

### Phase 5: Final Cleanup and Deprecation Notices
**Risk: LOW — documentation and deprecation only**

#### Changes
1. **Add deprecation warning to `scoring_base.py`**:
   ```python
   import warnings
   warnings.warn(
       "libs.models.scoring_base is deprecated. "
       "Import ScoringModel from libs.models.base instead.",
       DeprecationWarning, stacklevel=2,
   )
   ```

2. **Re-export `ScoringModel` from `base.py`** for the canonical import path:
   ```python
   # At bottom of base.py
   from libs.models.scoring_base import ScoringModel  # noqa: F401 — canonical re-export
   ```
   Alternative (if circular import risk): keep `ScoringModel` in `scoring_base.py` but document that `base.py` is the intended single import point.

3. **Update docstrings** in `base.py`, `registry.py` to reflect new architecture.

4. **Add `models/README.md`** documenting:
   - How to create a new model (copy `_template/`)
   - Directory conventions
   - Registration mechanism
   - Feature declaration pattern

5. **Update `scoring_model_manager.py`** to import from unified registry (if not done in Phase 3).

#### Green Gate
- [ ] Full `pytest` passes
- [ ] `python -c "from libs.models.base import BaseModel, ScoringModel, ModelMeta"` — single import point works
- [ ] `python -c "from libs.models.scoring_base import ScoringModel"` — still works but emits DeprecationWarning
- [ ] No `FutureWarning` or `DeprecationWarning` in normal test output (only when using deprecated paths)

#### Rollback
Revert Phase 5 commit. Pure documentation and deprecation — zero runtime risk.

---

## Validation Checklist (cumulative)

### After all phases
- [ ] `pytest` — full suite green
- [ ] `python -c "from libs.models.registry import ModelRegistry; ModelRegistry.auto_discover(); models = ModelRegistry.list_all(); assert len(models) >= 7, models"` — all models discovered
- [ ] `python -c "from libs.models.registry import ModelRegistry; ModelRegistry.auto_discover(); assert set(ModelRegistry.list_by_type('direction')) == {'SqueezeBreakout', 'MeanReversion', 'Momentum', 'TrendFollowing'}"` — direction models typed
- [ ] `python -c "from libs.models.registry import ModelRegistry; ModelRegistry.auto_discover(); scoring = ModelRegistry.list_by_type('scoring'); assert 'DivergenceEdgeScorer' in scoring and 'RegimePullbackScorer' in scoring and 'SqueezeBreakoutScorer' in scoring"` — scoring models typed
- [ ] `python -c "from libs.models.scoring_registry import ScoringModelRegistry"` — backward compat works (with deprecation warning)
- [ ] `python -c "from libs.models.base import ModelMeta; m = ModelMeta(name='x', model_type='scoring', required_indicators=[], required_fields=[]); assert m.trainable == False"` — extended ModelMeta works
- [ ] All per-model `features.py` importable
- [ ] `_template/` exists with valid model skeleton
- [ ] No circular imports
- [ ] `apps/strategy_app/` boots without error (ModelManager + ScoringModelManager)

### Quant correctness checks
- [ ] Direction model `evaluate()` return type unchanged (`ModelOutput`)
- [ ] Scoring model `evaluate()` return type unchanged (`ScoringOutput`)
- [ ] `LegacyScoringAdapter` wrapping still produces correct `edge_score = direction * conviction`
- [ ] `batch_evaluate()` temporal validation and result alignment checks preserved (from `BaseModel` template method)
- [ ] No model evaluation logic changed — only structural/import changes

---

## Blast Radius and Affected Flows

### Execution flows affected
1. **Strategy evaluation flow** (`StrategyWorker` → `ModelManager` → `BaseModel.evaluate()`) — registry import changes only, no logic change
2. **Scoring evaluation flow** (`StrategyWorker` → `ScoringModelManager` → `ScoringModel.evaluate()`) — ScoringModel now subclasses BaseModel, registry unified
3. **Selection layer flow** (`SelectionLayer` receives outputs) — no change, output contracts unchanged
4. **Optimization flows** (`optimize.py` / `optimizer.py` per model) — `import libs.models` trigger changes from manual to auto-discover, functionally equivalent
5. **Batch optimization scripts** (`scripts/batch_optimize.py`, etc.) — same `import libs.models` change

### Risk assessment
- **Phase 1**: LOW — additive field with default value
- **Phase 2**: MEDIUM — class hierarchy change. Key risk: `batch_evaluate` → `_batch_evaluate_impl` rename in scoring models. Mitigation: template method pattern already proven in BaseModel
- **Phase 3**: MEDIUM — registry mechanism change. Key risk: auto-discover ordering or import timing. Mitigation: decorator registration unchanged, auto-discover just triggers imports
- **Phase 4**: LOW — file renames with backward-compat re-exports
- **Phase 5**: LOW — documentation and deprecation warnings only

---

## Risks and Follow-Up Items

### Blocking risks
1. **Circular imports**: `base.py` ↔ `scoring_base.py` — mitigate by keeping `ScoringModel` in `scoring_base.py` and re-exporting from `base.py` only at module level
2. **Auto-discover import order**: Models must be importable without side effects beyond registration — verify no model `__init__.py` triggers heavy computation

### Non-blocking follow-ups (out of scope)
1. Model serialization/versioning (`artifacts_path`, `trainable` fields are stubs for now)
2. Standardized validation contract (beyond current `validate_features` / `validate_required_fields`)
3. Migrate `scoring_feature_pipeline.py` to use per-model `features.py` declarations
4. Remove `ScoringModelRegistry` wrapper after all consumers migrated (next quarter)
5. Add `model_type="ensemble"` and `model_type="ml"` when those model types are implemented
6. Remove `LegacyScoringAdapter` when direction models are fully migrated to scoring pipeline

---

## Not Changed

- Model evaluation logic (all `evaluate()` and `_batch_evaluate_impl()` method bodies)
- Config YAML structure (`configs/models.yaml`)
- Contract schemas (`FeatureVector`, `ModelOutput`, `ScoringOutput`, `ParamDef`)
- `feature_extractors.py` helper functions
- `scoring_feature_pipeline.py` internals
- Optimization algorithms, objective functions, Optuna integration
- Runtime behavior of `ModelManager`, `ScoringModelManager`, `StrategyWorker`
- Selection layer logic

---

*This handoff package is complete. The coder agent can act on each phase independently without guessing. Each phase has explicit file changes, a green gate, and a rollback strategy.*
