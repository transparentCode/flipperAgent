# Analysis capabilities

The capability catalog is the stable metadata surface. It describes the twenty-one
approved model and technical-analysis capabilities without importing or
executing them. The optional `execution` namespace exposes the existing native
request/result adapters; the optional `invocation` namespace adds checked,
host-attested source and point-in-time context around one native execution.

R2's bound executor is deliberately explicit. It validates the catalog entry,
the static invocation specification, source/context time ordering, and each
native capability's cutoff/identity facts, then calls the existing dispatcher
exactly once and retains its native result unchanged. The unbound dispatcher
remains available for callers that already own those boundaries.

`AnalysisSourceAttestation` records what the host asserts about a source. It is
not source authentication: the digest is host-attested, not a canonical hash of
an external record. Pure TA and Trendlines requests do not carry market identity
in their native inputs, so their identity remains source-attested rather than
being mislabeled as native verification. R3 supplies the bounded offline seam
that maps an already-validated canonical provider slice into those attestations;
it does not acquire or inspect a real source in this phase.

The bound executor also requires the attested source availability to cover the
latest native datum used by the request. The minimum is the final closed bar,
reference, or anchor for the nine directly inspectable paths; Regression checks
the native observed-through cutoff after execution. Later availability is valid
when request/evaluation times reflect processing latency, and no universal
source-availability-versus-market rule is imposed.

Caller-threaded SR results carry a deterministic fingerprint of the exact
previous native state. Regression identity retains the native opaque source and
channel hashes and additionally records the effective `window_size`, so a stale
native config hash cannot collapse two different effective computations.

Invocation method versions and parameter fingerprints identify the semantic
contract and native configuration used for a call. They are not model-quality,
promotion, or alpha claims. No network, database, persistence, dynamic plugin,
Decision, or runtime activation is owned by this package.

## R3 canonical source to TVLC vertical slice

R3 accepts only an immutable, contiguous, native Binance 4-hour canonical slice
for the frozen BTCUSDT/BTC-USDT-PERP identity. Its digest covers the exact
Decimal OHLCV and provenance values before any native request converts values to
finite floats. Source availability is supplied by the caller and must cover the
final closed bar; no derivation, resampling, CCXT fallback, network call, or
mixed-source slice is permitted.

The named R3 adapters map the same source slice to the existing R2-bound
Trendlines, swing-anchor, explicit-range VWAP, Traditional pivot, and explicit
Fibonacci requests. They call the bound executor only, preserve each native
result, and require one source attestation and one market cutoff across the
vertical slice. Fibonacci anchors are resolved from the preceding causal swing
snapshot; no automatic anchor selection is introduced.

R3's viewer projection builds the candle frame only after source hashing and
delegates the base chart to the existing TVLC 5.2.1 renderer. It appends only
factual VWAP, seven Traditional levels, explicit Fibonacci levels beginning at
anchor availability, and swing-anchor metadata. The JSON-safe provenance list
contains capability, method, parameter/state, source-digest, and cutoff facts;
it contains no score, confidence, direction, alpha, or strategy signal.

The architecture diagram in `overview.d2` is the canonical R2/R3 boundary view;
the SVG is its rendered companion.

## R4A deterministic toolbox kernels

R4A adds three stateless, explicit-request capabilities without changing the
existing seven contracts:

- `ta.parallel_channel_geometry` computes a three-anchor channel using bar
  ordinals, not elapsed-time or screen geometry.
- `ta.fibonacci_trend_extension_geometry` computes caller-selected levels from
  an explicit A/B impulse and C retracement with `C + (B - A) * ratio`.
- `ta.anchored_vwap_path` emits the cumulative HLC3 VWAP path from an explicit
  first bar and preserves leading/later zero-volume semantics.

The callable catalog is therefore exactly ten capabilities at the R4A stage. The machine-readable
tool taxonomy is a separate vocabulary for current kernels, future analytical
families, and viewer-only shapes. The recommender boundary is also separate:
future suggestions cannot override deterministic kernel authority, and R4A does
not train or activate a recommender.

The R4A ten-capability baseline identifiers were:

```text
model.regression
model.sr
model.trendlines
ta.anchored_vwap_path
ta.fibonacci_geometry
ta.fibonacci_trend_extension_geometry
ta.parallel_channel_geometry
ta.swing_anchors
ta.traditional_pivot_geometry
ta.vwap_geometry
```

## R4B deterministic Gann and volume-profile kernels

R4B adds three explicit, stateless analytical kernels, bringing the callable
catalog to exactly thirteen capabilities from the R4A baseline:

- `ta.gann_fan_geometry` emits caller-selected price/time rays from one causal
  anchor and an explicit price-per-bar scale. It uses bar ordinals only; it has
  no pixel, screen-angle, or automatic-scale semantics.
- `ta.gann_box_geometry` emits caller-selected price fractions and fractional
  bar-coordinate time levels between two explicit coordinates. It does not
  interpolate timestamps or implement Gann arcs or squares.
- `ta.volume_profile_geometry` is one shared histogram kernel for fixed-range
  and anchored-volume-profile callers. The caller supplies the exact bars and
  range; R4B never selects a lower timeframe or performs resampling.

Volume Profile uses the explicitly named
`volume_profile.explicit_range_uniform_overlap.v1` method. It allocates each
bar's volume across rows by continuous high-low overlap, classifies the whole
bar as up when `close >= open`, and computes deterministic POC and contiguous
value-area rows. This is a reproducible R4B contract, not a claim of parity
with TradingView's undisclosed lower-timeframe allocation.

The two volume-profile taxonomy tools intentionally map to that one capability;
their range selection remains caller-owned. HVN/LVN detection, smoothing,
automatic ranges, and developing profiles are not implemented. The recommender
boundary remains documentation/research-only and is not changed by R4B.

## R4C explicit pattern geometry kernels

R4C adds four explicit-anchor, stateless pattern-geometry kernels, bringing the
callable catalog to exactly seventeen capabilities:

- `ta.abcd_pattern_geometry` exposes four-point ABCD leg magnitudes, ordinal
  spans, and factual ratios without naming or classifying a pattern.
- `ta.xabcd_pattern_geometry` exposes five-point XABCD magnitudes, ordinal
  spans, and harmonic-relevant ratios without Gartley, Butterfly, Bat, Crab, or
  Cypher classification.
- `ta.head_shoulders_pattern_geometry` exposes regular or inverse five-extrema
  topology, a bar-ordinal neckline, and exact prominence values. It does not
  encode trend, volume, breakout, target, or trading semantics.
- `ta.triangle_pattern_geometry` exposes two explicit same-side boundary lines,
  their gap, and their exact mathematical apex. It does not classify ascending,
  descending, or symmetrical subtypes.

All R4C anchors are caller-supplied confirmed `SwingAnchor` values. No kernel
discovers pivots, runs a zigzag, searches for candidates, applies tolerance
bands, emits scores, predicts breakouts, or produces direction, confidence,
PnL, or strategy output. Bar ordinals are the time coordinate even when the
wall-clock spacing is irregular. Future recommender logic may suggest tools or
anchors, but deterministic geometry remains authoritative.

The thirteen callable identifiers are:

```text
model.regression
model.sr
model.trendlines
ta.anchored_vwap_path
ta.fibonacci_geometry
ta.fibonacci_trend_extension_geometry
ta.gann_box_geometry
ta.gann_fan_geometry
ta.parallel_channel_geometry
ta.swing_anchors
ta.traditional_pivot_geometry
ta.volume_profile_geometry
ta.vwap_geometry
```

The seventeen callable identifiers after R4C are:

```text
model.regression
model.sr
model.trendlines
ta.abcd_pattern_geometry
ta.anchored_vwap_path
ta.fibonacci_geometry
ta.fibonacci_trend_extension_geometry
ta.gann_box_geometry
ta.gann_fan_geometry
ta.head_shoulders_pattern_geometry
ta.parallel_channel_geometry
ta.swing_anchors
ta.traditional_pivot_geometry
ta.triangle_pattern_geometry
ta.volume_profile_geometry
ta.vwap_geometry
ta.xabcd_pattern_geometry
```

## R4D advanced pattern geometry kernels

R4D adds four explicit-anchor, stateless pattern-geometry kernels, bringing the
callable catalog to exactly twenty-one capabilities:

- `ta.cypher_pattern_geometry` measures explicit five-anchor Cypher geometry
  and factual ratios without validating a named Cypher setup or PRZ.
- `ta.three_drives_pattern_geometry` measures six explicit coordinates,
  drive/retracement magnitudes, ordinal spans, and factual price/time ratios
  without symmetry tolerances or reversal semantics.
- `ta.elliott_impulse_wave_geometry` measures explicit start-through-wave-five
  geometry without enforcing Elliott theory rules.
- `ta.elliott_correction_wave_geometry` measures explicit start/A/B/C geometry
  without classifying Zigzag, Flat, or another correction subtype.

All four requests require confirmed caller-supplied `SwingAnchor` values in
causal order. They report only magnitudes, ordinal spans, and deterministic
ratios. They do not discover anchors, scan candles, classify named patterns,
rank candidates, emit confidence or targets, predict breakouts, or produce
trading/strategy output. The taxonomy replaces the broad planned
`elliott_wave_pattern` placeholder with concrete impulse, correction, triangle,
double-combo, and triple-combo entries; only the first two are callable in R4D.

The twenty-one callable identifiers after R4D are:

```text
model.regression
model.sr
model.trendlines
ta.abcd_pattern_geometry
ta.anchored_vwap_path
ta.cypher_pattern_geometry
ta.elliott_correction_wave_geometry
ta.elliott_impulse_wave_geometry
ta.fibonacci_geometry
ta.fibonacci_trend_extension_geometry
ta.gann_box_geometry
ta.gann_fan_geometry
ta.head_shoulders_pattern_geometry
ta.parallel_channel_geometry
ta.swing_anchors
ta.three_drives_pattern_geometry
ta.traditional_pivot_geometry
ta.triangle_pattern_geometry
ta.volume_profile_geometry
ta.vwap_geometry
ta.xabcd_pattern_geometry
```
