# Trendline Family Model — Phase B Re-review

## Current Mode

Review / approval gate for remediated Phase B native candidate generation.

## Decision

**REVISION REQUIRED — Phase C remains blocked.**

The prior Phase-B findings are substantially resolved:

- timestamp-space segment validation now matches emitted geometry,
- irregular/missing-bar regression coverage exists,
- resolved config is bound to request asset/timeframe,
- minimum source-pivot semantics are corrected,
- exact-line diagnostics no longer borrow unverified full-path evidence,
- result contracts and registry boundaries are immutable/status-safe,
- OHLC coherence checks exist,
- future-row invariance and parameter-effect coverage exist,
- fixture provenance/config/fingerprint/geometry are recorded.

Two residual correctness issues remain at the candidate input boundary.

---

## Finding B-R1 — Confirmed plateau pivots repaint after confirmation

**Severity:** High / blocking before stateful tracking

`CausalFractalPivotExtractor` currently:

1. treats every equal maximum/minimum in a plateau as an extremum,
2. groups the currently confirmed equal contiguous candidates,
3. selects the current group midpoint.

As the plateau extends, the midpoint changes. A pivot already published with a concrete `confirmation_time` can disappear and be replaced by a later pivot.

Reproduced with `left_bars=1`, `right_bars=1` and highs `[1, 2, 2, 2, 1]`:

```text
prefix ending at index 2:
  confirmed high pivot = index 1, confirmation_index 2

prefix ending at index 3:
  confirmed high pivot = index 2, confirmation_index 3
```

The earlier confirmed pivot is rewritten even though data after its declared confirmation caused the change.

This does not violate same-timestamp future-row filtering, but it violates the stronger streaming invariant required by the family tracker:

> Once a pivot is published as confirmed, later bars must not alter its identity, timestamp, price or confirmation time while it remains inside the lookback window.

Otherwise Phase C receives avoidable anchor churn and loses anchor-overlap evidence for a structure whose price geometry may not have changed.

### Required correction

Adopt and document one causal plateau policy. Acceptable examples:

- a deterministic non-repainting asymmetric tie rule; or
- delay plateau publication until its complete plateau extent and right-side confirmation are known, then publish one stable representative.

Do not retain a rolling midpoint over the currently visible plateau.

### Required tests

- rolling-prefix plateau test proving an emitted pivot never moves after confirmation;
- both high and low plateau cases;
- pivot ID, timestamp, price and confirmation time remain stable;
- future rows beyond `observed_at` still have no effect on the result at that same `observed_at`.

---

## Finding B-R2 — Numeric-string OHLCV is accepted but path validation can become lexicographic

**Severity:** High / blocking correctness

`confirmed_ohlcv_window` calls `pd.to_numeric(...)` for validation but does not assign the converted values back to the returned frame.

Consequently object/string columns pass validation. Later, `_segment_is_valid` computes:

```python
body_top = ohlcv[["open", "close"]].max(axis=1)
body_bottom = ohlcv[["open", "close"]].min(axis=1)
```

For strings, these operations are lexicographic before conversion to float.

Example:

```text
open="9", close="10"
lexicographic minimum = "10"
numeric minimum       = 9.0
```

Reproduced on the same OHLC values:

```text
numeric frame -> NO_VALID_FITTED_PATHS
string frame  -> VALID
```

The string frame admitted a support line that crosses the true numeric candle body.

### Required correction

Choose one strict policy:

1. reject non-numeric dtypes, restoring a hard numeric-input contract; or
2. normalize all required OHLC columns to finite float values in the copied returned window before any downstream computation.

The second option is acceptable only if the normalized float frame is what both pivot extraction and fitting consume.

### Required tests

- numeric-like string input is either explicitly rejected or produces exactly the same result as the corresponding float frame;
- include values crossing digit widths such as `"9"` and `"10"`;
- verify support and resistance body checks;
- ensure malformed non-numeric strings return explicit `invalid_provider_input` semantics.

---

## Verified Evidence

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
67 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
status: ready
nodes: 39,542
edges: 124,597
```

Verified corrected behavior:

- asset mismatch returns `config_asset_mismatch`,
- timeframe mismatch returns `config_timeframe_mismatch`,
- invalid result statuses are rejected,
- irregular timestamp-space body crossing is rejected,
- three source pivots with `min_pivots_per_side=3` produce a valid two-anchor line,
- exact-line diagnostics use anchor-span coverage and two verified touches,
- nested result metadata is recursively frozen,
- registry mappings are private/immutable.

---

## Blast Radius

Required corrections are limited to:

```text
src/libs/models/trendline_family/pivots.py
possibly src/libs/models/trendline_family/fitting.py only if numeric normalization is placed there
tests/models/trendline_family/
```

No Phase-C matching, family state, lifecycle, interaction, RegimeV2 or MTF work is needed.

## Approval Gate

Phase B can be approved after both residual issues are fixed and the full Phase-A/Phase-B test suite remains green.
