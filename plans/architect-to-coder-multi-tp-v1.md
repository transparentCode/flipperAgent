---
goal: Implement multi-TP (multiple take-profit levels with partial exits) in production pipeline and scoring
stage: architect-to-coder
date_created: 2026-05-29
last_updated: 2026-05-29
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, multi-tp, risk, position-tracker, scoring, partial-exit]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Multi-TP Partial Exit System

## Objective

Implement config-driven multi-level take-profit with partial exits in the production pipeline, plus a matching `backtest_multi_tp()` scoring function so that optimization and production use identical exit logic. This closes the parity gap identified in v7 analysis: 3 of 5 assets (SOL, BNB, DOGE) lose most alpha under single-exit vs multi-TP scoring.

## Context Retrieved

### Prior Decisions
- v7 ad-hoc script (`/tmp/squeeze_optimization_v7.py`) validated multi-TP with TP1=1.5%/TP2=3%/TP3=5%, portions 40/30/30, SL=2%, trail-to-breakeven after TP1. All 5 assets profitable (BTC +0.19, XRP +1.49, SOL +1.26, BNB +3.01, DOGE +2.39 Sharpe).
- Production currently uses single `take_profit_price` with full exit. Both scoring optimizers in repo (`compute_returns`, `compute_signal_weighted_returns`) use single-exit logic.
- Per-asset optimized params in project-context.md were tuned against v7 multi-TP — deploying them with single-exit production creates a parity gap.
- Risk Manager architecture (2026-05-25): RiskEngine runs rule pipeline → PositionSizer → SL/TP → assessment. Stream topology: strategy → signals → risk_app → orders → execution_app → fills → portfolio_app.
- FillListener in risk_app handles FIFO partial fill matching for position lifecycle.
- PortfolioWorker uses PositionMatcher for independent FIFO matching and ClosedTrade records.

### Current Architecture (verified from source)
| Component | File | Current Behavior |
|-----------|------|-----------------|
| PositionState | `src/libs/contracts/risk.py` | Single `take_profit_price: Optional[float]` |
| PositionTracker | `src/libs/risk/position_tracker.py` | `check_sl_tp_hlc()` returns full positions; `close_position()` pops entire position |
| TakeProfitCalculator | `src/libs/risk/take_profit.py` | Computes single TP via `risk_reward`, `fixed_pct`, or `trailing` |
| RiskEngine | `src/libs/risk/engine.py` | Calls `tp_calc.calculate()` → single `take_profit_price` in `RiskAssessment` |
| RiskWorker | `src/apps/risk_app/risk_worker.py` | `_process_price_update()` emits full-size close order on SL/TP hit |
| FillListener | `src/apps/risk_app/fill_listener.py` | FIFO matching, creates new PositionState with single `take_profit_price` |
| ExecutionWorker | `src/apps/execution_app/execution_worker.py` | Passes orders to OrderManager, publishes fills |
| PaperExecutor | `src/libs/execution/paper_executor.py` | Always fills full `order.size` |
| PortfolioWorker | `src/apps/portfolio_app/portfolio_worker.py` | PositionMatcher FIFO, ClosedTrade records, equity snapshots |
| OrderExecutionRequest | `src/libs/contracts/execution.py` | Single `take_profit_price` field |
| ExecutionReport | `src/libs/contracts/execution.py` | Single `take_profit_price` field |
| scoring.py | `src/libs/optim_utils/scoring.py` | `compute_returns()` (direction-based), `compute_signal_weighted_returns()` (continuous) — both single-exit |
| risk.yaml | `configs/risk.yaml` | `take_profit:` with single method/params |
| DB schema | `sql/002_pipeline.sql` | `risk_positions` table has single `take_profit_price` column |

## Scope Boundaries

### In Scope
1. Multi-level TP fields on `PositionState` (schema change)
2. `TakeProfitCalculator` — new `multi_level` method computing N TP prices
3. `PositionTracker` — partial exit logic with trail-to-breakeven
4. `RiskEngine` — pass multi-TP levels through assessment
5. `RiskWorker` — emit partial close orders on individual TP hits
6. `FillListener` — apply partial fills to partially-closed positions
7. `OrderExecutionRequest` / `ExecutionReport` — metadata for partial close context
8. `PaperExecutor` — handle partial close orders
9. `PortfolioWorker` — partial fill accounting in PositionMatcher
10. `scoring.py` — new `backtest_multi_tp()` function
11. `risk.yaml` — multi-TP config structure
12. `sql/002_pipeline.sql` — schema migration for new columns
13. Unit + E2E tests

### Explicit Non-Goals
- Live exchange execution (only paper executor changes)
- Changing signal generation or strategy logic
- Changing position sizing or risk rules
- Adding new risk rules for multi-TP
- Per-asset TP level customization (future follow-up; this phase uses global levels)
- Async/concurrent partial exit orchestration across multiple assets

## Affected Symbols, Modules, and Execution Flows

### Directly Modified (d=1 — WILL BREAK if not updated together)
| Symbol | File | Change |
|--------|------|--------|
| `PositionState` | `src/libs/contracts/risk.py` | Add multi-TP fields |
| `RiskAssessment` | `src/libs/contracts/risk.py` | Add multi-TP levels list |
| `OrderExecutionRequest` | `src/libs/contracts/execution.py` | Add `close_reason` field |
| `PositionTracker` | `src/libs/risk/position_tracker.py` | New partial exit methods |
| `TakeProfitCalculator` | `src/libs/risk/take_profit.py` | New `multi_level` method |
| `RiskEngine.assess()` | `src/libs/risk/engine.py` | Multi-TP dispatch |
| `RiskWorker._process_price_update()` | `src/apps/risk_app/risk_worker.py` | Partial order emission |
| `FillListener._apply_fill()` | `src/apps/risk_app/fill_listener.py` | Partial fill handling |
| `PaperExecutor.execute_order()` | `src/libs/execution/paper_executor.py` | Partial close support |
| `PortfolioWorker._process_fill()` | `src/apps/portfolio_app/portfolio_worker.py` | Partial close accounting |
| `scoring.py` | `src/libs/optim_utils/scoring.py` | New `backtest_multi_tp()` |
| `risk.yaml` | `configs/risk.yaml` | Multi-TP config section |
| `002_pipeline.sql` | `sql/002_pipeline.sql` | New columns on risk_positions |

### Affected Execution Flows
- **Signal → Risk → Order → Execution → Fill → Portfolio**: The core trading pipeline. Every stage is touched.
- **Price update → SL/TP check → Partial close order**: The hot path for exit logic.
- **Position persistence (save/load)**: DB schema change for new fields.
- **Optimization pipeline** (`scoring.py` consumers): Any optimizer using `compute_returns()` or `compute_signal_weighted_returns()` gains access to `backtest_multi_tp()` as an alternative.

### Unchanged (no blast radius)
- Signal generation, strategy models, feature pipeline
- Ingestion, candle storage
- Position sizing, risk rules
- MTF aggregation
- Config validation

---

## Data Contracts and Interfaces

### 1. PositionState (schema change)

```python
class PositionState(BaseModel):
    """Tracks a single open position."""
    asset: str
    direction: int
    entry_price: float
    current_price: float
    size: float                                   # REMAINING size (decreases on partial exits)
    original_size: float = 0.0                     # NEW — initial size at entry (immutable)
    unrealized_pnl: float
    entry_timestamp: float
    source_model: str
    source_timeframe: str
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None      # KEPT — backward compat for single-TP mode
    trailing_stop_distance: Optional[float] = None

    # --- Multi-TP fields (new) ---
    tp_levels: list[float] = Field(default_factory=list)
    """Ascending (long) or descending (short) TP price levels, e.g. [tp1, tp2, tp3]."""
    tp_portions: list[float] = Field(default_factory=list)
    """Fraction of ORIGINAL position to close at each level, e.g. [0.4, 0.3, 0.3]. Must sum ≤ 1.0."""
    tp_levels_hit: list[bool] = Field(default_factory=list)
    """Tracks which TP levels have been hit, e.g. [True, False, False]."""
    original_stop_loss: Optional[float] = None
    """NEW — original SL before trail-to-breakeven. Used for logging/audit."""
    trail_to_breakeven: bool = False
    """NEW — when True, SL moves to entry_price after TP1 hit."""
```

**Design rationale**: Three parallel lists (`tp_levels`, `tp_portions`, `tp_levels_hit`) keep the schema flat and JSON-serializable. The `take_profit_price` field is retained for backward compatibility — when `tp_levels` is empty, existing single-TP code path activates unchanged.

**Feature flag**: `len(tp_levels) > 0` determines multi-TP mode. When empty, all existing single-TP logic is unchanged.

### 2. RiskAssessment (schema change)

```python
class RiskAssessment(BaseModel):
    allowed: bool
    signal: TradeSignal
    proposed_size: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None      # KEPT for single-TP compat
    rejection_reason: str = ""
    rules_applied: list[str] = Field(default_factory=list)
    verdicts: list[RiskVerdict] = Field(default_factory=list)

    # --- Multi-TP (new) ---
    tp_levels: list[float] = Field(default_factory=list)
    tp_portions: list[float] = Field(default_factory=list)
    trail_to_breakeven: bool = False
```

### 3. OrderExecutionRequest (minimal change)

```python
class OrderExecutionRequest(BaseModel):
    # ... all existing fields unchanged ...
    close_reason: str = Field(default="", description="Why this close was triggered: 'tp1', 'tp2', 'tp3', 'sl', 'signal', or ''")
```

**Rationale**: The `close_reason` field is additive (default empty string). Partial close orders are standard market orders with a reduced `size` — no structural change to order flow. The execution layer doesn't need to know about TP levels; it just fills the order.

### 4. TakeProfitCalculator — new method

```python
class TakeProfitCalculator:
    _METHODS = {"risk_reward", "fixed_pct", "trailing", "multi_level"}

    def calculate_multi(
        self,
        signal: TradeSignal,
        stop_loss_price: float | None,
        config: dict[str, Any],
    ) -> tuple[list[float], list[float], bool]:
        """Compute multi-level TP prices and portions.

        Returns
        -------
        tp_levels : list[float]
            TP prices in ascending order (long) or descending order (short).
        tp_portions : list[float]
            Fraction of original position to close at each level.
        trail_to_breakeven : bool
            Whether to move SL to entry after first TP hit.
        """
```

Config-driven from `risk.yaml`:
```yaml
take_profit:
  default_method: multi_level      # NEW — feature flag
  # ... existing single-TP methods preserved ...
  multi_level:
    levels:
      - pct: 1.5
        portion: 0.40
      - pct: 3.0
        portion: 0.30
      - pct: 5.0
        portion: 0.30
    trail_to_breakeven: true        # move SL to entry after first TP hit
```

### 5. PositionTracker — new methods

```python
class PositionTracker:
    def check_sl_tp_hlc_multi(
        self, asset: str, high: float, low: float, close: float,
    ) -> list[tuple[PositionState, str, float]]:
        """Check multi-TP positions for partial exits.

        Returns
        -------
        list of (position, close_reason, close_size) tuples:
            close_reason: 'tp1', 'tp2', 'tp3', 'sl'
            close_size: fractional size to close (NOT full position)
        """

    def apply_partial_exit(
        self, asset: str, pos_index: int, close_size: float, tp_level_index: int,
    ) -> None:
        """Reduce position size after a partial TP hit.

        - Decrements pos.size by close_size
        - Marks tp_levels_hit[tp_level_index] = True
        - If tp_level_index == 0 and trail_to_breakeven:
            pos.stop_loss_price = pos.entry_price
        """
```

**Check order within a single bar**: If both SL and a TP could be hit on the same bar (using H/L extremes), TP takes priority (consistent with existing `check_sl_tp_hlc` behavior).

**Trail-to-breakeven**: After TP1 is hit, if `trail_to_breakeven=True`, the SL moves to entry_price. This means the remaining position can only lose the TP1 profit at worst — no further capital at risk.

### 6. RiskWorker._process_price_update() — partial order emission

```python
async def _process_price_update(self, payload: dict) -> None:
    # ... existing price update, trailing stop logic ...

    # Multi-TP: check for partial exits
    partial_exits = self.positions.check_sl_tp_hlc_multi(self.asset, high, low, close)
    for pos, close_reason, close_size in partial_exits:
        close_side = "sell" if pos.direction == 1 else "buy"
        order = OrderExecutionRequest(
            asset=self.asset,
            side=close_side,
            size=close_size,           # PARTIAL size, not full
            order_type="market",
            timestamp=price_update.timestamp,
            requested_price=close,
            idempotency_key=f"{close_reason}_{self.asset}_{int(pos.entry_timestamp)}",
            close_reason=close_reason,
            model_name=pos.source_model,
            source_timeframe=pos.source_timeframe,
        )
        # Publish partial close order
        await self.redis_client.xadd(...)

    # Legacy single-TP path (positions where tp_levels is empty)
    hit_positions = self.positions.check_sl_tp_hlc(self.asset, high, low, close)
    # ... existing full-exit logic unchanged ...
```

**Idempotency**: Each partial close gets a unique key like `tp1_BTCUSDT_1716000000`. Since each TP level can only be hit once per position, the key is naturally unique.

### 7. FillListener._apply_fill() — partial fill handling

The existing FIFO partial fill logic already handles partial closes correctly — a sell of size 0.4 against a long of size 1.0 will reduce the position to 0.6. **No structural change needed** to the matching logic. The existing code already handles:
- `match_qty = min(remaining, pos.size)` 
- Partial close: `pos.size -= match_qty`

One small addition: after a partial fill from a TP hit, the TP tracking state should be preserved on the reduced position. The existing code already preserves `stop_loss_price` and `take_profit_price` on partial closes, so the new `tp_levels`, `tp_portions`, `tp_levels_hit` fields will be naturally preserved since they're on the same `PositionState` object.

### 8. scoring.py — `backtest_multi_tp()`

Port the v7 `backtest_multi_tp()` function as a pure-math scoring function:

```python
def backtest_multi_tp(
    directions: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    commission_bps: float = 4.0,
    trail_to_breakeven: bool = True,
) -> tuple[np.ndarray, list[dict]]:
    """Multi-TP backtest matching production exit logic.

    Parameters
    ----------
    directions : np.ndarray
        Signal directions (-1, 0, 1).
    high, low, close : np.ndarray
        OHLC price arrays.
    tp_pcts : tuple[float, ...]
        TP levels as fractions above/below entry (e.g. 0.015 = 1.5%).
    tp_portions : tuple[float, ...]
        Fraction of original position to close at each level.
    sl_pct : float
        Stop-loss as fraction below/above entry (e.g. 0.02 = 2%).
    commission_bps : float
        Round-trip commission in basis points.
    trail_to_breakeven : bool
        Move SL to entry after first TP hit.

    Returns
    -------
    equity_returns : np.ndarray
        Per-bar strategy returns (same length as input).
    trades : list[dict]
        Trade-level results with entry/exit info and TP/SL hit flags.
    """
```

This function is a direct port of the v7 script's `backtest_multi_tp()` logic, adapted to:
- Accept configurable TP levels/portions/SL (not hardcoded)
- Use basis-point commission (matching production PaperExecutor)
- Return both equity returns (for Sharpe computation) and trade-level detail (for win rate, TP hit rates)

### 9. Config Changes (risk.yaml)

```yaml
risk:
  take_profit:
    default_method: multi_level      # CHANGED from fixed_pct
    # --- Existing single-TP methods preserved for backward compat ---
    risk_reward:
      ratio: 2.0
    fixed_pct:
      pct: 1.5
    trailing:
      atr_multiplier: 3.0
    # --- New multi-level config ---
    multi_level:
      levels:
        - pct: 1.5
          portion: 0.40
        - pct: 3.0
          portion: 0.30
        - pct: 5.0
          portion: 0.30
      trail_to_breakeven: true

  stop_loss:
    default_method: fixed_pct        # CHANGED from atr_based for v7 alignment
    fixed_pct:
      pct: 2.0                       # matches v7 SL_PCT
    atr_based:
      multiplier: 2.0
    trailing:
      atr_multiplier: 2.0
```

### 10. DB Schema Migration

Add new columns to `risk_positions`:

```sql
-- Migration: add multi-TP columns to risk_positions
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS original_size DOUBLE PRECISION;
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS tp_levels JSONB DEFAULT '[]';
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS tp_portions JSONB DEFAULT '[]';
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS tp_levels_hit JSONB DEFAULT '[]';
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS original_stop_loss DOUBLE PRECISION;
ALTER TABLE risk_positions ADD COLUMN IF NOT EXISTS trail_to_breakeven BOOLEAN DEFAULT false;
```

Also update `002_pipeline.sql` CREATE TABLE to include these columns for fresh deployments.

---

## Implementation Order

### Phase 1: Schema + Config + Scoring (no production behavior change)

| Step | File | Change | Risk |
|------|------|--------|------|
| 1.1 | `src/libs/contracts/risk.py` | Add multi-TP fields to `PositionState` and `RiskAssessment` | LOW — additive defaults |
| 1.2 | `src/libs/contracts/execution.py` | Add `close_reason` to `OrderExecutionRequest` | LOW — default empty |
| 1.3 | `configs/risk.yaml` | Add `multi_level` section under `take_profit` | LOW — not activated yet |
| 1.4 | `src/libs/optim_utils/scoring.py` | Add `backtest_multi_tp()` function | LOW — additive, no callers yet |
| 1.5 | `sql/002_pipeline.sql` | Add new columns to CREATE TABLE | LOW — additive |
| 1.6 | Tests: unit tests for `backtest_multi_tp()` against v7 reference output | — |

**Gate**: All existing 806+ unit tests pass. New scoring function produces identical results to v7 script on same input data.

### Phase 2: TakeProfitCalculator + PositionTracker (library layer)

| Step | File | Change | Risk |
|------|------|--------|------|
| 2.1 | `src/libs/risk/take_profit.py` | Add `calculate_multi()` method | LOW — additive |
| 2.2 | `src/libs/risk/position_tracker.py` | Add `check_sl_tp_hlc_multi()` and `apply_partial_exit()` | MEDIUM — new code path |
| 2.3 | `src/libs/risk/position_tracker.py` | Update `save_positions()` / `load_positions()` for new fields | MEDIUM — DB schema |
| 2.4 | Tests: unit tests for multi-TP calculation, partial exit, trail-to-breakeven | — |

**Gate**: PositionTracker tests cover all partial exit scenarios: TP1-only, TP1+TP2, all three, SL before any TP, SL after TP1 (breakeven), bar where both SL+TP could hit.

### Phase 3: RiskEngine + RiskWorker (production hot path)

| Step | File | Change | Risk |
|------|------|--------|------|
| 3.1 | `src/libs/risk/engine.py` | Branch on `default_method == "multi_level"` → call `calculate_multi()` | MEDIUM — conditional |
| 3.2 | `src/apps/risk_app/risk_worker.py` | `_process_price_update()`: add multi-TP partial order emission | HIGH — production hot path |
| 3.3 | `src/apps/risk_app/risk_worker.py` | `_process_signal_batch()`: pass `tp_levels`/`tp_portions` to order | MEDIUM |
| 3.4 | `src/apps/risk_app/fill_listener.py` | Ensure TP state preserved on partial fills; update `open_position` call | MEDIUM |
| 3.5 | Tests: RiskWorker integration tests for partial order emission | — |

**Gate**: Integration test: signal → risk assessment with multi-TP → partial close orders emitted in correct sequence → position size decreases correctly → SL moves to breakeven after TP1.

### Phase 4: Execution + Portfolio (downstream)

| Step | File | Change | Risk |
|------|------|--------|------|
| 4.1 | `src/libs/execution/paper_executor.py` | Handle partial close orders (already works — verify with tests) | LOW |
| 4.2 | `src/apps/portfolio_app/portfolio_worker.py` | Verify partial fills work with PositionMatcher (already works — add tests) | LOW |
| 4.3 | Tests: E2E test for full multi-TP lifecycle | — |

**Gate**: E2E test: signal → multi-TP assessment → TP1 hit → partial close order → partial fill → position reduced → TP2 hit → partial close → TP3 hit → full close → ClosedTrade records correct.

### Phase 5: Optimizer Integration

| Step | File | Change | Risk |
|------|------|--------|------|
| 5.1 | Update optimizer scripts to use `backtest_multi_tp()` instead of `compute_returns()` | LOW |
| 5.2 | Validate v7 params reproduce expected Sharpe ratios with new scoring function | — |

---

## Acceptance Criteria

### Functional
1. **Multi-TP config**: Setting `take_profit.default_method: multi_level` activates multi-TP with config-driven levels/portions.
2. **Backward compat**: Setting `take_profit.default_method: fixed_pct` (or any single-TP method) works exactly as before — zero behavior change.
3. **Partial exits**: Each TP level triggers a partial close order for the correct portion of the original position.
4. **Trail-to-breakeven**: After TP1 hit, SL moves to entry_price when `trail_to_breakeven: true`.
5. **Position lifecycle**: A position's `size` field decreases on each partial close. `tp_levels_hit` tracks which levels were hit.
6. **Idempotency**: Each partial close has a unique idempotency key. Re-processing the same price bar does not emit duplicate orders.
7. **Scoring parity**: `backtest_multi_tp()` in scoring.py produces the same trade results as the v7 script on identical input data (within floating-point tolerance).
8. **DB persistence**: Positions can be saved and loaded with multi-TP state intact.

### Non-Functional
9. **No new dependencies**: Pure Python, no new packages.
10. **Performance**: Multi-TP check adds O(n_positions × n_tp_levels) work per price bar — negligible for <10 positions.
11. **Observability**: Log messages include `close_reason` (tp1/tp2/tp3/sl) for each partial close.

### Test Coverage
12. **Unit tests**: ≥25 new tests covering:
    - `TakeProfitCalculator.calculate_multi()` — long/short, various configs
    - `PositionTracker.check_sl_tp_hlc_multi()` — all hit scenarios
    - `PositionTracker.apply_partial_exit()` — size reduction, TP tracking, trail-to-breakeven
    - `backtest_multi_tp()` — v7 parity, edge cases (no signals, immediate SL, all TPs hit)
    - `RiskEngine.assess()` — multi-TP assessment output
    - `RiskWorker._process_price_update()` — partial order emission
    - Backward compat: existing single-TP tests still pass
13. **E2E tests**: ≥2 new tests:
    - Full multi-TP lifecycle through all pipeline stages
    - Mixed mode: one asset with multi-TP, another with single-TP

---

## Validation Checklist

- [ ] All existing 806+ unit tests pass (zero regression)
- [ ] All 15 E2E tests pass (zero regression)
- [ ] `backtest_multi_tp()` output matches v7 script output on BTCUSDT 1h data
- [ ] Setting `default_method: fixed_pct` produces identical behavior to pre-change
- [ ] Setting `default_method: multi_level` activates multi-TP
- [ ] Trail-to-breakeven moves SL to entry after TP1 hit
- [ ] Partial close orders have correct `size` (portion of original, not current)
- [ ] Position `size` field decreases correctly after each partial fill
- [ ] DB save/load round-trips all multi-TP fields
- [ ] Idempotency keys prevent duplicate partial close orders on price replay
- [ ] Docker build succeeds with schema changes
- [ ] `mypy` / type checking passes (if configured)

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Race condition**: Two price bars fire in rapid succession, both see TP1 not yet hit | MEDIUM | Idempotency key `tp1_{asset}_{entry_ts}` deduplicates. Also, `tp_levels_hit[0]` is set synchronously in `apply_partial_exit()` before next check runs. |
| **Floating-point portion drift**: After 3 partial exits, remaining size ≠ 0 due to FP precision | LOW | After final TP hit, if `remaining < 1e-9`, treat as fully closed. |
| **Config validation**: Portions that don't sum to 1.0 | LOW | Validate at config load: `sum(portions) ≤ 1.0 + ε`. Log warning if < 1.0 (residual position stays open until opposite signal). |
| **Bar priority**: SL and TP hit on same bar | LOW | TP takes priority (consistent with existing behavior). Document this. |
| **Existing optimizers break**: Callers of `compute_returns()` | NONE | `backtest_multi_tp()` is additive; existing functions unchanged. |
| **Portfolio PositionMatcher confusion**: Sees multiple partial sells for same entry | LOW | PositionMatcher already handles partial fills via FIFO — a sell of 0.4 correctly reduces the open entry of 1.0 to 0.6. |

---

## Key Implementation Notes

### 1. Portion Computation
Portions are fractions of **original_size**, not current remaining size. Example:
- Entry: size=1.0, original_size=1.0
- TP1 hit: close_size = 0.40 × 1.0 = 0.40 → remaining = 0.60
- TP2 hit: close_size = 0.30 × 1.0 = 0.30 → remaining = 0.30
- TP3 hit: close_size = 0.30 × 1.0 = 0.30 → remaining = 0.00

This matches v7 behavior exactly and avoids compounding portion errors.

### 2. Trail-to-Breakeven Logic
```
if tp1_hit and trail_to_breakeven:
    pos.stop_loss_price = pos.entry_price
    pos.original_stop_loss = <previous SL>  # for audit/logging
```
After TP1, the worst-case outcome for the remaining 60% position is exit at entry (zero loss). The TP1 profit (0.4 × 1.5% ≈ 0.6%) is locked in.

### 3. Multi-TP Check Logic (check_sl_tp_hlc_multi)
```
for each position with non-empty tp_levels:
    # Check SL first (uses current stop_loss_price, which may be at breakeven)
    if SL hit:
        yield (pos, "sl", pos.size)  # full remaining size
        continue
    
    # Check TP levels in order (lowest unhit first for longs)
    for i, (level, portion, hit) in enumerate(zip(tp_levels, tp_portions, tp_levels_hit)):
        if hit:
            continue
        if (direction==1 and high >= level) or (direction==-1 and low <= level):
            close_size = portion * pos.original_size
            close_size = min(close_size, pos.size)  # safety clamp
            yield (pos, f"tp{i+1}", close_size)
            # Apply the partial exit immediately so next level check sees updated state
            apply_partial_exit(pos, close_size, i)
            break  # only one TP per bar (conservative — could hit multiple on extreme bars)
```

**One TP per bar**: Conservative approach matching v7 behavior. On a huge bar that blows through all three levels, TP1 fires on bar N, TP2 on bar N+1 (when price is still above), TP3 on bar N+2. This slightly understates performance vs "all TPs on same bar" but is safer and matches production latency reality.

### 4. Feature Flag
The feature flag is purely config-driven:
- `take_profit.default_method: multi_level` → multi-TP active
- `take_profit.default_method: fixed_pct` (or any other) → existing single-TP behavior
- No code-level feature flags, no environment variables

### 5. Scoring Function Parity
The v7 script processes all TP levels within the same bar (lines 439-470). The production implementation is more conservative (one TP per bar). The scoring function `backtest_multi_tp()` should match **production behavior** (one TP per bar) so optimizer results predict production performance accurately. This is a deliberate deviation from v7 — slightly lower backtested Sharpe but more realistic.

**Decision point for the coder**: Implement one-TP-per-bar in both scoring and production. If the user later wants to explore all-TPs-per-bar, it can be a boolean config flag.

---

## Architecture Tradeoffs and Rejected Options

### Option A (Rejected): Separate Position per TP Level
Create 3 separate PositionState objects at entry (sizes 0.4, 0.3, 0.3) each with their own TP.
- **Pro**: Uses existing single-TP code path unchanged.
- **Con**: Triples position count, breaks position_count limits, makes trail-to-breakeven impossible (SL on position 1 can't affect positions 2 and 3), makes total exposure accounting wrong (3× positions shown).
- **Rejected because**: Trail-to-breakeven requires coordinated state across TP levels, which separate positions cannot provide.

### Option B (Chosen): Multi-TP fields on single PositionState
Keep one position, track TP levels and hit status as lists.
- **Pro**: Minimal schema change, trail-to-breakeven is trivial, position count stays accurate, backward compat via empty lists.
- **Con**: Adds complexity to `check_sl_tp_hlc`, requires new methods.
- **Chosen because**: Lowest blast radius, cleanest backward compat, matches v7 mental model.

### Option C (Rejected): TP levels as separate related table
Store TP levels in a `risk_position_tp_levels` join table.
- **Pro**: More normalized.
- **Con**: Over-engineered for 3 levels, adds DB join complexity, harder to serialize for Valkey streams.
- **Rejected because**: JSONB columns on `risk_positions` are simpler and sufficient for ≤5 TP levels.

---

## Pipeline Effectiveness Test Plan

After multi-TP is implemented, run this validation:

1. **Scoring parity**: Run `backtest_multi_tp()` on all 5 assets with v7 params. Verify Sharpe ratios are within 10% of v7 results (accounting for one-TP-per-bar vs all-TPs-per-bar difference).
2. **Config toggle**: Run with `default_method: fixed_pct` (single TP). Verify scores match `compute_returns()` output.
3. **Config toggle**: Switch to `default_method: multi_level`. Verify Sharpe improves for SOL, BNB, DOGE.
4. **E2E Docker test**: Full pipeline startup → inject synthetic signal → verify TP1 partial close → verify SL at breakeven → verify TP2 partial close → verify final close.
5. **Regression**: All existing unit tests and E2E tests pass unchanged.

---

This handoff is complete and actionable. The coder agent can proceed without guessing on any design decision.
