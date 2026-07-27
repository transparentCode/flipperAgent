# Research Preparation

L2-A1 provides deterministic preparation contracts for the future research notebook. Preparation
is not replay or model execution.

## Scope and purpose

`TrendlineResearchSpec` binds purpose (`SMOKE` or `RESEARCH`), asset, ordered timeframes, primary
timeframe, and a mode-specific data specification. Model parameter dictionaries are not accepted
by this spec; component choices and parameters come from canonical trendlines YAML.

Supported modes:

- `SYNTHETIC`: explicit integer seed, UTC start, and positive bar count per timeframe. No network.
- `INJECTED`: caller supplies a mapping or async loader. This is the local CSV/parquet/cache seam;
  path handling is intentionally outside L2-A1.
- `BINANCE`: explicit timezone-aware event start and knowledge cutoff. Only `RESEARCH` purpose
  may use it. The application bridge uses `BinanceNativeAdapter`, requests `close_time`, keeps
  open-time event indexes, and records `exchange_close_time` provenance.

## Validation and identity

Every prepared frame has a timezone-aware, ordered, unique event index, numeric OHLCV, valid OHLC
shape, `bar_available_at`, explicit timestamp semantics, and explicit provenance. `OPEN_TIME`
requires availability strictly after event time; `CLOSE_TIME` requires equality. Bars unavailable by
the requested cutoff are rejected. Provider normalization may sort before this boundary; canonical
validation never silently sorts, deduplicates, or drops conflicting rows.

Each timeframe receives one `TrendlineSourceRef`. `TrendlineResearchDatasetIdentity` binds the
explicit data specification, dataset manifest, source references, timestamp semantics, availability
provenance, and one `availability_id` for the complete UTC availability schedule. `source_id`
identifies event index and model-visible OHLCV; `availability_id` identifies the exact knowledge
schedule; `dataset_id` binds both. Identical OHLCV with different availability schedules therefore
produces different dataset identities. Dataset identity serialisation contains no full frame values
or full timestamp sequence.

Data specifications are mode-strict. Synthetic accepts only seed/start/count fields, Binance accepts
only explicit event and knowledge bounds, and injected accepts none of those source-selection fields.
Incompatible fields fail closed and do not enter mode identity payloads.

`resolve_research_config()` overlays global pipeline parameters with asset/timeframe values, then
validates named components in explicit research mode. `PreparedTrendlineResearchRun` contains only
validated spec, dataset, configuration, and preparation identity. It does not run pivots, fitters,
signals, replay, optimization, or promotion, and it never writes YAML.

## Boundaries

The canonical package imports no application connector, Binance SDK, Jupyter, IPython, Plotly,
TVLC, RegimeV2, or Trendline V2 code. Concrete provider integration belongs under
`apps.ingestion_app.adapters`. L2-A2 adds causal replay and evidence APIs; L2-B adds notebook and
viewer presentation.

## Causal Replay and Evidence (L2-A2)

`run_causal_replay()` consumes only a `PreparedTrendlineResearchRun`. It executes every prefix
from each explicit `TrendlineReplayWindow.warmup_start_position` through `end_position`, including
positions omitted by `record_every`. Warm-up and intermediate executions update revision-aware
history; only positions satisfying the recording rule become evidence points.

Each prefix uses its own source reference, final event timestamp, and final bar-availability time.
Research execution passes the prepared YAML-resolved pipeline configuration through canonical
facades. Signal replay selects only prior boundary revisions known by the current prefix
availability time. Invalid model outputs remain recorded observations; unexpected execution
errors fail with timeframe, position, event, availability, and underlying error type.

Replay IDs bind preparation, dataset, resolved research configuration, and replay specification.
Replay-point IDs bind exact prefix source, checkpoint, stage identities, timestamps, finality, and
compact output content. They do not bind the full parent dataset ID. Full and independently
truncated preparations can therefore be compared at shared causal positions with
`verify_replay_future_invariance()`; parent preparation, dataset, replay, and frame-length
identities may differ. Comparison still requires matching asset, timeframe, resolved pipeline
configuration, timestamp/availability semantics, research mode, signal mode, and compatible
warm-up scope.

`content_id` covers serialized output, boundary snapshot, timestamps, and prefix source reference.
`validate_replay_point_integrity()` recomputes both `content_id` and `replay_point_id`; mutation of
nested output or boundary objects after identity creation fails closed rather than regenerating IDs.

`replay_snapshot_rows()`, `replay_pivot_count_rows()`, `replay_line_rows()`,
`replay_ray_rows()`, and `replay_signal_rows()` return deterministic typed rows without model
execution. `inspect_replay_pivots()` is an explicit selected-position diagnostic re-extraction and
checks counts against authoritative fit metadata.

`TrendlineResearchEvidenceBundle` contains replay-wide diagnostic rows plus one
`TrendlineEvidenceSelection` derived from a recorded `(timeframe, position)`. It excludes full
frames, notebook state, credentials, and wall-clock creation time. Summary bounds are global
temporal extrema across all independently replayed timeframes, regardless of timeframe iteration
order. Persistence is explicit through `write_research_evidence_bundle()`; reads first verify the
content-addressed `bundle_id`, then validate selection/binding, selected rows and pivots, row
counts, distributions, totals, and global bounds. A matching hash does not make contradictory
evidence semantically valid.

Snapshot rows are the bundle's coordinate-to-point map. Every diagnostic row carries its
`timeframe`, replay `position`, `replay_point_id`, `content_id`, source/checkpoint identity, and
stage-specific IDs. Pivot-count, line, ray, and signal rows also carry recomputed evidence IDs;
readers rebuild these IDs from row content and reject stale or duplicate values. Per-coordinate
line/ray/signal counts and ordinals must match the snapshot row. Replay-spec windows determine
the exact expected recorded coordinates, while summary timeframe and executed-position counts
derive from those windows.

RDP remains research-only and every RDP replay point retains `retrospective_revising` finality.
Multi-timeframe replay is independent per timeframe; no confluence, interpolation, resampling, or
cross-timeframe signal composition occurs.

## Package-local notebook and viewer (L2-B)

`libs.models.trendlines.research_viewer` is a presentation-only leaf. It consumes
validated prepared runs, replay points, and evidence bundles; it does not execute
models, fetch data, resolve YAML, construct history, or rebuild diagnostics. Core
trendlines and `workflows.research` do not import it.

`research/trendlines_research_lab.ipynb` defaults to bounded `SMOKE` + `SYNTHETIC`
data for BTCUSDT on 1h and 4h. It prepares, replays, validates evidence, builds one
selected payload, and serves a temporary read-only loopback bundle. Binance mode is
guarded by explicit `RESEARCH` purpose, provider authorization, and an injected
loader; no real provider call is part of L2-B validation.

The viewer payload binds selected replay point, content, checkpoint, source,
fit/boundary/signal revisions, and a separate display-window identity. The display
window is a bounded chart view and is not the model prefix source. Bundle writes are
explicit and canonical; no permanent export or YAML mutation occurs by default.

Finality is textual: Fractal is `CONFIRMED / APPEND-ONLY`; RDP is
`RETROSPECTIVE / RESEARCH ONLY`. The viewer presents selected lines, rays, pivots,
signals, summary, timeline, and identity audit without extrapolating geometry.

## Full Research Lab (L2-B3)

`libs.models.trendlines.research_lab` is the notebook workbench layer. It composes
the tested preparation, replay, evidence, and viewer APIs; it does not contain
extractors, fitters, signal loops, data fetching, YAML resolution, or chart
JavaScript. It is explicitly imported by the notebook and is not exported from
the root trendlines package.

Lab controls are immutable and bind purpose, data mode, asset, ordered timeframes,
explicit data specification, replay windows, signal inclusion, viewer policy, and
provider authorization. Synthetic smoke controls perform no provider call.
Injected frames require an explicit mapping or loader. Binance controls require
research purpose, explicit bounds, an explicit loader, and authorization before
the loader can run.

Every timeframe is prepared and replayed independently in requested order. The
default selection chooses the latest valid point with both support/resistance
lines and rays, then any valid geometry, then the final recorded point. Explicit
recorded-position navigation rebuilds selected evidence and viewer payload only;
it never reruns replay.

Notebook tables retain full source, availability, checkpoint, snapshot, revision,
content, and replay-point identities. Signal-history tables expose selected
history snapshot/revision pairs, query knowledge time, signal availability time,
and signal input identity. Viewer servers and temporary bundles belong to the
session and are closed by `session.close()`.

Permanent evidence, viewer, and lab-manifest export is explicit opt-in. The lab
does not mutate YAML. Longevity, churn, null comparisons, sensitivity,
robustness, cross-asset adequacy, and predictive outcomes remain L2-D studies;
RSI/MACD and price/oscillator confluence remain separate work.

Research-lab provider accounting is resolved after preparation. Binance loaders
must expose a non-negative integer `provider_calls`; explicit compatibility
wrappers may expose `calls`. Synthetic and injected runs report zero. Malformed
or unavailable Binance accounting fails closed.

Session close is terminal for selection and viewer creation. Inline notebook
viewers are emitted with one explicit `display(IFrame(...))` call per timeframe;
navigator selection calls `open_viewer()` so old temporary bundles and servers
are replaced without replay execution. Table construction timing is accumulated
outside research identities. Explicit exports expose deterministic per-file
byte lengths and SHA-256 inventory rows for evidence, viewer, and lab-manifest
artifacts. Cleanup reports actual server and temporary-root state.

## Adequacy foundation (L2-D1)

`libs.models.trendlines.workflows.research.adequacy` defines measurement scope
on top of prepared runs and completed causal replays. It does not execute model
code, fetch data, tune parameters, compare outcomes, or select an adequacy
decision.

`TrendlineAdequacyStudyConfig` freezes ordered per-timeframe evaluation windows,
recorded-position eligibility, minimum warm-up and prior-executed-prefix
requirements, line and
ray observation units, invalid-point treatment, the causal-prefix-only
availability policy, selected metric names, explicit finite decision rules, and
named naive/null baseline definitions. Its identity contains no frames, provider
state, wall-clock time, or model-parameter mapping.

Adequacy windows must start at or after replay recording scope and contain at
least one position selected by replay `record_every`. Warm-up is validated at
study scope. `prior_executed_prefix_count` means executed causal prefixes before
the current point from replay warm-up; it is not retained snapshot history or
signal-history depth. Decision rules are an ordered subset of selected metrics;
descriptive counts need no invented thresholds. Metric directions are assigned
only where higher/lower utility is unambiguous; ambiguous density and event
counts remain descriptive.

Each `TrendlineAdequacyCohort` binds study, preparation, dataset, resolved
configuration, replay, source, availability, timestamp-semantics, and
availability-provenance identities. Its replay scope is stored as immutable
ordered tuples and its cohort ID is recomputed from those contents.
`collect_adequacy_observations()` first reuses canonical replay-point integrity
validation, then validates event time, bar availability, checkpoint source
horizon, boundary knowledge time, and signal knowledge metadata before emitting
compact observations.
Only recorded replay points inside frozen windows can be eligible. Invalid model
outputs remain retained and reported, but do not contribute geometry counts.

L2-D1 summaries are descriptive coverage/accounting outputs only. No outcome
such as `ADEQUATE_FOR_FURTHER_RESEARCH` is selected. Structural stability,
interaction utility, null execution, and robustness remain separate L2-D2
through L2-D5 studies. All adequacy fixtures are synthetic/offline; no provider
call is part of this foundation.

## Structural stability measurements (L2-D2)

`TrendlineStructuralStabilitySpec` requires an explicit ordered tuple of
positive survival horizons. Its `stability_spec_id` participates in every
structural state and in the content-addressed stability bundle. The bounded
offline study uses horizons `(1, 3, 6, 12)`; package code supplies no hidden
horizon default.

L2-D2 consumes eligible L2-D1 observations and authoritative replay line and
ray diagnostic rows. It first validates every replay point through
`validate_replay_point_integrity()` and performs no model execution or provider
call while measuring. Invalid and excluded observations contribute no geometry
state. Fitted lines and boundary rays remain separate observation units.

Structural identity uses exact, roleless anchors. A fitted-line key is
`(timeframe, method, start_position, end_position)`; a boundary-ray key is
`(timeframe, start_time, end_time)`. Ordinals, evidence IDs, revisions, fuzzy
matching, rounded geometry, and tolerances are not used. Duplicate roleless
anchors at one coordinate fail closed. Role is attached state, so a role change
is measured separately from birth or disappearance.

Transitions compare adjacent eligible recorded positions in replay order and
preserve their bar gap. Birth, disappearance, persistence, exact shape
revision, role switch, and denominator-aware rates are reported separately for
lines and rays. A zero denominator is represented by `None`, not a fabricated
zero. Shape tuples contain line `(start_value, end_value, slope, intercept)` or
ray `(start_price, end_price, slope, intercept)`; touch count, score, quality,
and R-squared changes are descriptive drift rows and do not define shape
revisions.

Episodes require consecutive eligible observations. Disappearance followed by
reappearance creates a new episode. Survival evaluates only observed births at
exact recorded target positions; recording gaps are unavailable, targets beyond
the scoped end are right-censored, and no interpolation is performed. Rates
use eligible target denominators and are `None` when no target is eligible.

The stability bundle binds cohort, study, stability-spec, eligible observation
identities, state IDs, transition content, drift content, episode content, and
survival content. Timing, paths, and wall-clock values are excluded. The
offline L2-D2 script reloads only the committed L2-C frame artifact, requires
exact source/availability/dataset/preparation/replay identity equality, makes
zero provider calls, and writes canonical bundle, manifest, review, and
checksum artifacts. Measurements are descriptive only: L2-D2 selects no
adequacy outcome and does not run interaction utility, null baselines,
parameter tuning, or robustness studies.

## Causal interaction utility (L2-D3)

L2-D3 evaluates only `BOUNDARY_RAY` geometry. Its event unit is each
non-left-censored boundary-ray episode birth from the validated L2-D2 bundle.
The birth role, slope, intercept, replay point, availability time, and
selection-time ATR are frozen; later replay prefixes cannot alter event
geometry.

Future evaluation starts strictly after the birth position and requires every
used bar availability time to be later than selection availability. Touches
use inclusive exact OHLC range crossing. Defended touches and wick rejection
use independent support/resistance close rules. Breaks classify only the first
adverse-close attempt as confirmed, false, or unresolved using the explicitly
resolved `signals.hold_bars` confirmation count. Horizon results beyond the
available frame are right-censored and excluded from eligible rate
denominators.

Penetration and favourable/adverse excursion are normalised by the
selection-time ATR. No future ATR, later geometry, model interaction label,
signal label, return, P&L, retest lifecycle, role reversal, null baseline, or
parameter tuning enters D3. Support and resistance summaries remain separate.
The interaction bundle binds source, replay, cohort, study, D2 bundle, spec,
events, outcomes, and summaries with deterministic identities. Its outcome is
descriptive evidence only; no adequacy disposition is selected.

Canonical bundle validation receives both the typed D2 structural bundle and
the typed prepared replay. It recomputes the qualifying ray-birth event set,
requires exact event-by-horizon coverage, enforces event-relative coordinates,
and recomputes every stored outcome from the frozen event and replay OHLC
frame. Rehashed payloads with arbitrary dataset/replay IDs, missing or extra
events, duplicate coordinates, or altered touch/break/excursion values fail
closed.

## Paired deterministic naive baselines (L2-D4A)

L2-D4A compares `BOUNDARY_RAY` geometry against the two frozen baseline kinds
in the adequacy study configuration: `RECENT_EXTREMA` and
`HORIZONTAL_SUPPORT_RESISTANCE`. Baseline attempts use exactly the committed
L2-D3 event positions, roles, selection-time ATR, horizons, and break
confirmation policy. This is conditional geometry comparison; it does not
compare event-timing decisions.

At each model event, confirmed append-only pivots are inspected through
`inspect_replay_pivots()` at the exact selection prefix. Support uses low
pivots and resistance uses high pivots. Recent-extrema uses the latest two
same-role pivots; horizontal support/resistance uses the latest one. Missing
pivots produce explicit abstentions and no baseline outcomes. Frozen baseline
geometry is evaluated with the same causal touch, break, penetration, and
excursion functions as D3.

The comparison bundle retains model and baseline counts, denominators,
abstentions, support/resistance and horizon coordinates, and model-minus-
baseline deltas without selecting a winner or composite score. Its validator
binds the supplied prepared replay, D2 bundle, D3 bundle, exact event-by-
baseline selection coverage, pivot provenance, future OHLC outcomes, summaries,
and bundle identity. Random, shuffled, density-matched, and Monte Carlo nulls
remain deferred to D4B; no D4A adequacy outcome is selected.

## Seeded stochastic nulls (L2-D4B)

L2-D4B keeps the exact L2-D3 model event opportunities, roles, selection
availability, selection-time ATR, horizons, and break-confirmation semantics.
It executes only two explicit phase-local baselines: seeded
`RANDOM_VALID_PIVOT_PAIR` and causal `DENSITY_MATCHED_NULL`. The original D2
study configuration is not mutated, so D2 and D3 identities remain unchanged.

Each draw derives its seed from the baseline identity, explicit seed,
repetition, model event identity, and draw semantics version. Random pairs use
only confirmed append-only same-role pivots in the event prefix. Density-matched
geometry draws only strictly earlier same-timeframe, same-role model events and
transports donor slope and role-signed distance through donor and current ATR.
Abstentions are explicit; no fallback geometry is created.

Available null selections freeze geometry and reuse the D3 future-OHLC outcome
and summary functions. Model and null summaries use the same matched event
subset, with support/resistance and horizons kept separate. Per-repetition
model-minus-null deltas are summarized with deterministic mean, median, extrema,
and 0.05/0.95 interpolated quantiles. No p-values, significance threshold,
composite winner, or adequacy outcome is produced. Time-shifted and
role-shuffled nulls remain out of scope.

The D4B bundle validator receives prepared replay plus typed D2, D3, and D4A
evidence. It recomputes draw identities, candidate/donor pools, transported
geometry, exact selection-by-horizon outcomes, paired summaries, distribution
statistics, and bundle identity. The bounded study reloads only committed
artifacts, makes zero provider calls, and records attempts, availability,
abstentions, repetitions, distributions, identities, and checksums.

## Frozen robustness source matrix (L2-D5A)

L2-D5A acquires source evidence only for later robustness replication. Its
ordered matrix binds one existing BTCUSDT 1h reference artifact plus fresh
BTCUSDT 1h temporal, ETHUSDT 1h, SOLUSDT 1h, and BTCUSDT 4h members. Every
member has an explicit 312-bar event/knowledge window, open-time timestamps,
exchange-close availability, canonical YAML coverage, and content-addressed
specification/evidence identities. The 4h member preserves bar count rather
than calendar duration.

Fresh acquisition uses one page of at most 1,000 rows per member, a fresh
native Binance loader, fixed order, exactly one provider call per member, and
zero application retries. Any failure stops acquisition before publication;
the official output root is never overwritten. The existing reference is
bound by path, checksum, source/availability/dataset/preparation identities,
and the completed D2-D4B chain without refetching it.

Each fresh frame is validated for exact cadence, complete bars, temporal
bounds, finite OHLCV, and availability semantics. It is written as the
strict research frame artifact, reloaded, and injected into a second
preparation. Frame values/dtypes/attributes plus source, availability,
dataset, configuration, and preparation identities must match exactly.
L2-D5A executes no model or replay code and selects no robustness outcome;
D5B remains responsible for applying the frozen D2-D4B protocol offline.
