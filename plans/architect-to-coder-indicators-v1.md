# Architect to Coder Handoff: Indicator Framework & Registry

## 1. Intent & Scope
**Objective:** Implement the `libs/features` module using a rigorous, domain-driven structure (`trend`, `momentum`, `volatility`, etc.).
**Scale/Depth:** Focus initially on establishing the architectural core: the abstract `Indicator` class, the `ParameterRegistry`, and 2 "tracer bullet" indicators (EMA and RSI) to prove the Dual-Mode Parity execution model works.

## 2. Directory Structure Target
This phase targets the implementation of the following hierarchy inside the monorepo:
```text
/libs
  /features
    /indicators
      /trend
        ema.py
      /momentum
        rsi.py
      registry.py
      base.py
```

## 3. High-Level Requirements

### A. The Abstract Base (`base.py`)
Create the gatekeeper class `Indicator(ABC)`. It must enforce the **"Trinity of Modes"**:
1. `batch(data)`: `@abstractmethod` that accepts vectorized inputs (e.g., Polars Series or list of bars) for offline backtesting and Optuna sweeps.
2. `prime(historical_data)`: `@abstractmethod` that pre-warms the live internal state using the last $N$ periods (where $N = $ `lookback_required`).
3. `update(new_tick_or_bar)`: `@abstractmethod` for event-driven live trading. Executes in $O(1)$ time by advancing the pre-warmed internal state.

*Required Properties:* `is_primed` (boolean) and `lookback_required` (integer).

### B. Dual-Mode Parity Implementation
Indicators like `EMA` and `RSI` are **not** split into separate `LiveRSI` and `BatchRSI` files. They are encapsulated strictly as a single class (e.g., `class RSI(Indicator):` in `rsi.py`).
- The `batch()` method executes lightning-fast array math.
- The `update()` method manages sliding windows, circular buffers, or EWMA constants locally.

### C. The Parameter Registry (`registry.py`)
Build a lightweight registry interface that allows downstream services to request an indicator dynamically via string (e.g., mapping `"RSI"` -> `RSI` class). This enables config-driven scaling.

## 4. Required Implementation Steps

### Phase 1: Core Scaffolding
- [ ] Create `libs/features/indicators/base.py` and define the `Indicator` abstract base class.
- [ ] Create `libs/features/indicators/registry.py` with a simple registration decorator or dictionary map.

### Phase 2: Tracer Indicators
- [ ] Implement `libs/features/indicators/trend/ema.py`.
- [ ] Implement `libs/features/indicators/momentum/rsi.py`.

### Phase 3: Parity Testing
- [ ] Write `tests/integration/features/test_indicator_parity.py`.
- [ ] **Crucial Assertion:** The test MUST prove that running `.batch(1000 bars)` yields the exact same mathematical value at $T=1000$ as calling `.prime(100 bars)` followed by 900 sequential calls to `.update(1 bar)`.

## 5. Exit Criteria & Quant Constraints
The mathematical core must be entirely shielded from message brokers and external databases. All indicators must rigorously adhere to the base contract. A failure in testing mathematical equivalence between `batch` and `update` sequences invalidates the dual-mode architecture.
