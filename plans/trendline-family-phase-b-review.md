# Trendline Family Model — Phase B Review

Date: 2026-07-11
Mode: Quant review
Decision: **Revision required; Phase C is blocked**

## 1. Scope Reviewed

Reviewed the Phase-B implementation under:

```text
src/libs/models/trendline_family/pivots.py
src/libs/models/trendline_family/fitting.py
src/libs/models/trendline_family/provider.py
src/libs/models/trendline_family/registry.py
src/libs/models/trendline_family/config.py
configs/trendline_family.yaml
tests/models/trendline_family/
```

The review checked:

- causal pivot availability,
- exact timestamp-space line semantics,
- pathfinding behavior,
- resolved-config ownership,
- deterministic candidate identities and ordering,
- diagnostic truthfulness,
- explicit abstention/error contracts,
- legacy import isolation,
- parameter-effect coverage,
- blast radius.

## 2. Validation Reproduced

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
50 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
status: ready
nodes: 39,470
edges: 124,050
```

No runtime imports from:

```text
libs.trendlines
libs.models.trendlines_old
app.trendlines
```

No production consumer outside the new package currently imports the Phase-B provider/fitter/pivot classes. The correction blast radius is therefore still low.

## 3. What Is Correct

The following Phase-B decisions are approved:

- new code is self-owned under `libs.models.trendline_family`,
- causal fractals retain pivot and confirmation timestamps separately,
- future rows after `observed_at` are filtered,
- candidate IDs and output ordering are deterministic for identical complete inputs,
- support comes from low pivots and resistance from high pivots,
- exact line geometry passes through its two declared anchors,
- runtime modules receive a resolved typed config and do not read YAML,
- explicit abstention statuses exist,
- no family matching, lifecycle, interaction, RegimeV2, MTF, or optimization work drifted into Phase B,
- limiting the first provider to at most one line per role is acceptable for the MVP.

## 4. Blocking Findings

## B1 — Path validity is evaluated in bar-index space, but emitted geometry is timestamp-space

Severity: **High**

Current segment validation interpolates with:

```text
(index - previous.index) / (current.index - previous.index)
```

while the emitted `LineGeometry` uses elapsed seconds between pivot timestamps.

These two lines differ whenever bars are missing, irregularly spaced, or otherwise not exactly equidistant in physical time.

A controlled irregular-index case was accepted as a valid support path even though the emitted timestamp-space line was above the intermediate candle body:

```text
index-space validation value: 5
emitted timestamp-space value: 9
intermediate body bottom: 7
result: incorrectly accepted
```

Affected implementation:

```text
fitting.py:151-158
```

Required correction:

- construct/evaluate the same timestamp-space geometry used by the emitted candidate,
- calculate every intermediate line value from the actual bar timestamp,
- verify pivot indices point to their declared timestamps in the supplied frame,
- add an irregular/missing-bar regression test.

The model may allow irregular bar spacing, but it must use one coordinate system consistently.

## B2 — Resolved config identity is not bound to the requested asset/timeframe

Severity: **High**

The provider accepts a config resolved for one market and emits candidates labelled as another.

Verified example:

```text
resolved config: ETHUSDT / 4h
provider call: BTCUSDT / 1h
result: VALID BTCUSDT/1h candidates
```

This defeats the global/timeframe/asset/asset-timeframe config architecture and makes candidate audit metadata unreliable.

Additionally, invalid `asset` or `timeframe` values are not validated before fitting. They raise `ContractValidationError` during candidate construction instead of returning the documented explicit provider-input error result.

Affected implementation:

```text
provider.py:84-97
provider.py:164-175
provider.py:206-215
```

Required correction:

- validate non-empty string `asset` and `timeframe` before computation,
- require `config.asset == asset`,
- require `config.timeframe == timeframe`,
- return explicit `PROVIDER_CONFIG_ERROR`/reason codes for these expected input violations,
- add mismatch and invalid-scalar tests,
- include asset, timeframe, observed timestamp, model/config versions, and resolved config hash in result-level audit metadata for both valid and abstention outputs.

Do not catch unexpected internal programming errors as provider-input errors.

## B3 — `min_pivots_per_side` rejects valid multi-pivot structures because of DP tie behavior

Severity: **High**

The fitter first requires enough available pivots and then also requires the selected DP path length to meet the same threshold:

```text
fitting.py:83-87
```

The DP objective is total index span. All paths sharing the same start/end have the same span, and ties retain the earliest direct predecessor:

```text
fitting.py:123-126
```

As a result, three perfectly collinear, mutually valid pivots with:

```text
min_pivots_per_side = 3
```

produce a two-point selected path and are rejected as `NO_VALID_FITTED_PATHS`.

Verified controlled result:

```text
available low pivots: 3
best path: first pivot -> third pivot
selected path length: 2
fit result: NO_VALID_FITTED_PATHS
```

Required semantic decision and correction:

- define `min_pivots_per_side` as the minimum number of confirmed source pivots required before attempting that role,
- an exact line still requires exactly two declared anchors,
- do not require the chosen path to contain `min_pivots_per_side` unless a separate `min_path_pivots` field is deliberately introduced later,
- if a DP path is retained, make score ties deterministic and explicitly prefer greater path evidence before the final stable tie-break,
- add a three-collinear-pivot test proving the parameter behaves according to its name.

Do not add another hyperparameter merely to preserve the current accidental behavior.

## B4 — Candidate diagnostics overstate evidence belonging to the emitted straight line

Severity: **High**

The emitted line uses only the final two path pivots:

```text
fitting.py:88-96
```

but coverage is measured from the first to last pivot of the entire potentially bent path:

```text
fitting.py:97
```

and provider diagnostics report:

```text
touch_count = full path length
inlier_ratio = 2 / full path length
cut_fraction = 0.0
fitter_consensus = 1.0
anchor_stability = 2 / full path length
```

None of `inlier_ratio`, `fitter_consensus`, or `anchor_stability` is actually measured. `cut_fraction=0` does not evaluate the emitted line over its full relevant horizon. A single fitter is not fitter consensus.

A controlled bent path demonstrated:

```text
path pivots: (0,0), (2,0), (4,10)
emitted anchors: (2,0), (4,10)
earlier path-pivot residual to emitted line: 10
reported touch_count: 3
reported coverage: 0.667
actual exact-anchor span coverage: 0.333
reported fitter_consensus: 1.0
```

This would feed false touch, stability, consensus, and coverage evidence into Phase C ranking and lifecycle decisions.

Required correction:

- coverage/quality must describe the exact emitted line, initially using the declared anchor span only,
- set `touch_count` and `effective_touch_count` to two unless additional pivots are explicitly tested against the emitted line using a documented tolerance,
- preserve the full DP path only as separate provenance metadata,
- set unmeasured optional diagnostics to `None`, especially:
  - `inlier_ratio`,
  - `cut_fraction`,
  - `fitter_consensus`,
  - `anchor_stability`,
- document the initial quality method, for example `anchor_span_coverage_v1`,
- add a bent-path regression test proving historical path points are not mislabeled as touches/inliers of the final line.

Later phases may calculate real residual, cut, stability, and multi-fitter consensus metrics. Phase B must not synthesize them.

## B5 — Phase-B result boundaries are not actually immutable or status-safe

Severity: **Medium, blocking before Phase C**

`CandidateGenerationResult` shallow-copies metadata and does not validate/coerce the status or candidates. Verified behavior:

```text
nested metadata mutation changes an existing frozen result
unknown status string is accepted
mutable candidates list is accepted
non-string reason code is accepted
```

`PivotExtractionResult` and `PathfindingFitResult` similarly accept contradictory states, negative counts, mutable lists, and unknown statuses.

Examples currently accepted:

```text
PivotExtractionResult(status=VALID, pivots=(), input_bars=-1, confirmed_bars=99)
PathfindingFitResult(status="bogus", lines=[])
```

These objects become direct inputs to Phase C and deterministic replay, so they need the same contract discipline established in Phase A.

Required correction:

- validate/coerce enum statuses,
- freeze sequences to tuples,
- recursively freeze metadata,
- require canonical element types,
- reject duplicate IDs,
- enforce status/content coherence,
- enforce non-negative and ordered bar counts,
- validate `FittedPath` role, anchors, path ordering, geometry, coverage, and quality,
- make registry mappings immutable or private and expose deterministic accessor functions.

## 5. Additional Required Hardening

These are small enough to include in the same remediation rather than creating another review cycle.

### OHLC consistency

At the provider input boundary, reject bars where:

```text
high < low
high < open or close
low > open or close
```

Return the explicit invalid-provider-input result. Finite numeric validation alone is insufficient for geometric fitting.

### Causality invariance test

Add a test proving:

```text
full frame containing future rows, observed_at = T
```

produces exactly the same status, candidates, IDs, ordering, geometry, diagnostics, and result metadata as:

```text
frame truncated at T, observed_at = T
```

The current implementation appears to satisfy this; it should be locked as a regression test.

### Parameter-effect coverage

The final Phase-B suite should demonstrate stage ownership for:

- `lookback_bars`,
- `min_bars`,
- `fractal_left_bars`,
- `fractal_right_bars`,
- `min_pivots_per_side`,
- `min_candidate_quality`,
- provider/fitter selector names.

`birth_quality_threshold` remains Phase-C ownership and must not be forced into Phase B.

### Frozen fixture provenance

Enhance the fixture metadata to state:

- fixture version,
- source/reference algorithm,
- resolved candidate config,
- input-data fingerprint or explicit fixture-data version,
- expected exact anchor timestamps and geometry.

The fixture remains offline data only and must not import old runtime code.

## 6. Phase-B Remediation Exit Gate

All must pass before Phase C:

1. timestamp-space line validation is consistent on irregular indexes,
2. asset/timeframe config mismatch fails explicitly,
3. invalid asset/timeframe input does not escape as an unhandled contract error,
4. three valid collinear pivots are not rejected by accidental DP tie collapse,
5. exact-line coverage and touch diagnostics do not borrow unsupported evidence from a bent path,
6. unmeasured diagnostic fields are `None`,
7. Phase-B result contracts reject contradictory/mutable states,
8. OHLC-invalid bars fail explicitly,
9. appended future rows cannot affect an `observed_at=T` result,
10. all parameter-effect tests pass,
11. all 39 approved Phase-A tests continue to pass,
12. no old trendline runtime imports exist.

## 7. Approval Decision

Phase B is **not approved** in its current form.

The implementation has a good modular boundary and correct causal pivot foundation, but Phase C must not consume candidates until the exact emitted line, path evidence, resolved config identity, and diagnostics all describe the same truthful object.
