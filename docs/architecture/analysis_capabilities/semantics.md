# Analysis capability semantics

This document records the causal numerical contracts for the currently exposed
analysis capabilities. R2 adds an opt-in host-attested invocation envelope
around these native contracts: source identity, source/request/market/evaluation
times, native cutoff reconciliation, and deterministic method/parameter identity.
The envelope is deliberately not an authenticity claim. R3 constructs and
authenticates these attested inputs from an immutable canonical source slice and
wires the existing viewer consumer.

The bound path rejects a source availability time earlier than the latest native
source fact used by its request. Regression obtains that fact from the native
`observed_through` result; the other paths use their final bar, reference, or
anchor availability. Later source availability is permitted when the request
and evaluation clocks include that processing latency. SR caller-threaded state
is identified separately by a deterministic fingerprint of the exact previous
state, and Regression also records its effective `window_size` alongside the
native opaque configuration hashes.

## Traditional pivot geometry

`ta.traditional_pivot_geometry` consumes one completed high/low/close range.
For `R = H - L` and `P = L + R/3 + (C-L)/3`, it emits the fixed ordered levels:

```text
S3 = L - 2(H-P)    S2 = P-R        S1 = 2P-H
P  = P              R1 = 2P-L       R2 = P+R
R3 = H + 2(P-L)
```

Flat ranges emit the exact common source float for all seven levels.

## Two-point Fibonacci geometry

`ta.fibonacci_geometry` uses explicit causal start and end anchors only. Every
retracement and extension is a linear two-point calculation. Prices are finite
signed real values, so valid down-leg extensions may be negative. No automatic
anchor selection, logarithmic geometry, or three-point mode is implied.

## Causal swing anchors

`ta.swing_anchors` emits strict confirmed extrema. Equal highs/lows do not win a
tie; a wide candle may independently receive both roles. `formed_at` is the
extremum timestamp and `available_at` is the confirmation timestamp.

## Explicit-range VWAP geometry

`ta.vwap_geometry` computes one explicit-range HLC3 bar-VWAP. Each positive-volume
bar contributes its stable bounded-range HLC3 value and volume weight; zero-volume
bars remain part of the ordered range but contribute no arithmetic. The range
has no hidden session reset.

## Time terminology

`market_as_of` is the closed-data cutoff. `formed_at` describes when a factual
anchor occurred, `available_at` when that anchor became causally usable, and
`first_bar_closed_at` identifies the first closed bar in an explicit VWAP range.

## R3 canonical source and viewer boundary

The R3 source contract is a non-empty tuple of closed, ordered, non-overlapping
native Binance 4-hour `CanonicalMarketRecord` values for the exact
`BTCUSDT`/`binance`/`BTC-USDT-PERP`/`4h` identity. Records must be aligned to the
fixed UTC 4-hour grid, contiguous, and homogeneous in provider provenance:
`provider` / `binance_native` / no source timeframe. The source availability
timestamp is caller-supplied complete-slice knowledge and must be at or after
the final close. The canonical digest includes the exact Decimal OHLCV and
provenance fields but excludes source availability, which is separately bound
in the R2 attestation.

The R3 request layer has no implicit range or anchor selection. Trendlines
requires exactly 300 records; VWAP requires an explicit contiguous suffix or
record tuple; Traditional pivots require one exact reference record; Swing
anchors require an explicit positive span; Fibonacci requires two identities
resolved from the same causal Swing snapshot and an explicit ratio set. Native
results are obtained only through `execute_bound_analysis_capability`, and the
five-result bundle rejects mixed source attestations, cutoffs, or capability
identities.

The viewer uses the same hashed source to construct a close-time candle frame,
then delegates base candles and existing Trendlines geometry to the TVLC 5.2.1
renderer. Extra overlays are descriptive only: one explicit-range VWAP, seven
Traditional levels, explicit Fibonacci levels beginning at the later anchor
availability, and Swing anchors as metadata. Projection never extends beyond
the authenticated market cutoff, and the emitted provenance has no quality,
confidence, directional, alpha, or strategy meaning.

## R4A deterministic toolbox kernels

`ta.parallel_channel_geometry` requires three explicit confirmed anchors and an
ordered closed-bar timeline. If `iA`, `iB`, `iC`, and `iT` are the bar ordinals,
the baseline slope is `(B.price - A.price) / (iB - iA)`, the offset is
`C.price - (A.price + slope * (iC - iA))`, and the two reported cutoff values
are the baseline and that baseline plus offset at `iT`. Low baselines require a
strictly positive offset; high baselines require a strictly negative offset.
No automatic anchor selection, wall-clock slope, or chart-pixel geometry exists.

`ta.fibonacci_trend_extension_geometry` requires an explicit ordered A/B/C
low-high-low or high-low-high topology and an explicit finite, positive,
strictly ordered ratio tuple. Each level is exactly `C.price + (B.price -
A.price) * ratio`; the signed impulse is shared by both directions.

`ta.anchored_vwap_path` treats the first supplied closed bar as the explicit
anchor and makes one forward pass using the stable HLC3 expression
`low + (high-low)/3 + (close-low)/3`. Leading zero-volume bars emit no point,
later zero-volume bars carry the unchanged VWAP forward, and an all-zero range
is rejected. Its final point is the same arithmetic result as the existing
explicit-range VWAP kernel.

All three capabilities are stateless, explicit-cutoff, source-attested
contracts. They are deterministic analytical kernels, not selectors, scores,
signals, or recommender outputs. The taxonomy and future recommender boundary
are documentation surfaces only.

## R4B deterministic Gann and volume-profile geometry

`ta.gann_fan_geometry` consumes one explicit confirmed anchor, an explicit
positive `price_per_bar` 1x1 scale, an ordered reduced ratio tuple, and an
ordered closed-bar timeline. For anchor ordinal `iA`, cutoff ordinal `iT`, and
ratio `p x t`, its ray slope is
`sign * price_per_bar * p / t`, where a low anchor has positive sign and a high
anchor has negative sign. The reported price is the anchor price plus that
slope times `iT - iA`. Ratios are compared by integer cross multiplication;
screen pixels, elapsed wall-clock time, logarithmic axes, and automatic scaling
are not part of the contract.

`ta.gann_box_geometry` consumes two explicit causally available coordinates and
caller-supplied ordered fractions including exact zero and one endpoints. Price
levels use `start.price + (end.price - start.price) * f`. Time levels use
`start_ordinal + (end_ordinal - start_ordinal) * f` and retain fractional bar
positions without inventing interpolated timestamps. The box is a grid only;
Gann fan rays, arcs, and squares are separate or deferred concepts.

`ta.volume_profile_geometry` is one explicit-range kernel for both fixed-range
and anchored-profile callers. It uses exactly the supplied closed bars and no
hidden timeframe selection, resampling, provider, or session reset. Its method
version is `volume_profile.explicit_range_uniform_overlap.v1`: non-flat bar
volume is allocated to price rows in proportion to continuous high-low overlap,
with the final overlapping row receiving the floating residual so each bar's
volume is conserved. Flat bars go to their containing row, with the global high
in the final row. Whole bars are classified up when `close >= open` and down
otherwise. POC chooses the lowest row index on an exact total tie. Value area
starts at POC and expands contiguously by the larger adjacent volume, then by
closer distance and finally the row above on a tie; it stops before exceeding
the explicit target. This is R4B's reproducible allocation contract and does
not claim TradingView lower-timeframe numerical parity.

R4B introduces no selectors, quality scores, signals, predictive labels,
recommender execution, HVN/LVN detection, smoothing, or production/runtime
activation.

## R4C explicit pattern geometry

R4C adds four caller-owned explicit-anchor pattern kernels. ABCD and XABCD
report finite leg magnitudes, bar-ordinal spans, and factual ratios; they do
not classify named ABCD or harmonic families. Head & Shoulders accepts regular
and inverse alternating five-extrema topology, requires a raw head extremum and
three strictly positive neckline prominences, and reports the neckline in bar
coordinates without trend, volume, breakout, target, or direction semantics.
Triangle geometry assigns the two high anchors to the upper line and the two
low anchors to the lower line, reports exact ordinal slopes and gap, and keeps
future, present/past, or parallel apex facts descriptive rather than classifying
triangle subtypes.

All four kernels require confirmed `SwingAnchor` inputs in the request. They do
not discover pivots, construct zigzags, search historical candidates, use
tolerance bands, rank alternatives, or emit confidence, predictive, trading,
PnL, or strategy output. Their snapshots reconstruct derived values from the
authenticated anchors and stored bar ordinals. Named harmonic classification
and Elliott subtype/theory validation remain deferred. A future recommender may
suggest an explicit tool or anchor set but cannot override these deterministic
kernels.

## R4D advanced pattern geometry

`ta.cypher_pattern_geometry` requires explicit causal X-A-B-C-D anchors with
alternating swing kinds. It reports the leg magnitudes, ordinal spans, and the
factual ratios `AB/XA`, `XC/XA`, and `CD/XC`. It does not assert a Cypher
classification, apply 0.786/1.414 bands, or emit a potential-reversal zone. X
and C must have distinct prices so the required `CD/XC` ratio is finite; this
is denominator validity, not a Cypher ratio band.

`ta.three_drives_pattern_geometry` requires six explicit alternating
coordinates: start, Drive 1, retracement A, Drive 2, retracement C, and Drive
3. It reports each price magnitude and ordinal span together with the
drive/retracement price and time ratios. Price/time symmetry is descriptive;
there is no Fibonacci tolerance, reversal prediction, or direction signal.

`ta.elliott_impulse_wave_geometry` requires explicit start, Waves 1 through 5
and reports the five factual wave magnitudes, ordinal spans, and selected
price/time ratios. `ta.elliott_correction_wave_geometry` requires explicit
start/A/B/C anchors and reports the three factual leg magnitudes, spans, and
ratios. Neither kernel enforces Elliott theory rules or classifies correction
subtypes such as Zigzag or Flat.

R4D uses only caller-supplied confirmed anchors and ordinal bar coordinates.
There is no automatic pattern search, named-family classifier, scoring,
confidence, target, prediction, or trading output. The machine-readable
taxonomy contains exactly 34 sorted unique entries: the broad planned
`elliott_wave_pattern` placeholder is removed, and concrete impulse, correction,
triangle, double-combo, and triple-combo entries are present; only impulse and
correction are callable. The four R4D method versions are explicit immutable
contracts and remain separate from any future recommender or runtime surface.
