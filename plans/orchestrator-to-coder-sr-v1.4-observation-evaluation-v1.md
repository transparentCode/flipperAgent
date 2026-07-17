---
goal: Implement SR-V1.4 causal observation traces and descriptive diagnostics without changing model behavior.
stage: orchestrator-to-coder
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Quant Orchestrator
status: Approved for implementation
tags: [handoff, quant, sr, observation, evaluation, diagnostics, causality]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: d85a02ea5fa2aa5debba64234efc607220ccabba
source_branch: feature/sr-v1.3-checkpoint-replay
target_branch: feature/sr-v1.4-observation-evaluation
---

# Orchestrator To Coder: SR-V1.4 Observation And Evaluation v1

## Decision

SR-V1.0 foundation/configuration, SR-V1.1 lifecycle, SR-V1.2 causal
detection/association, and SR-V1.3 checkpoint/replay are approved.

Implement SR-V1.4 causal observation traces and descriptive diagnostics only.
Stop after implementation and return a coder-to-review handoff. Do not merge.

This phase must make the current eight-parameter model observable without
changing what the model detects, associates, transitions, emits, or stores in
SRState.

## Branch And Working-Tree Safety

1. Verify HEAD is exactly:

   d85a02ea5fa2aa5debba64234efc607220ccabba

2. Create:

   feature/sr-v1.4-observation-evaluation

   directly from that commit.

3. Do not merge V1.3 or V1.4.
4. Do not stage, edit, delete, regenerate, or commit the pre-existing
   .codebase-memory artifacts or unrelated untracked plan drafts.
5. Keep implementation and coder handoff in separate commits.
6. If the exact base is unavailable or the dirty working tree overlaps an
   in-scope file, stop and report the blocker.

## Why This Phase Comes Next

The model is now deterministic, causal, stateful, and checkpoint-safe. Before
adding features, tuning parameters, integrating storage, or connecting trading
policy, we need an evidence surface that answers:

- what zones existed at each closed bar;
- when each zone first became knowable;
- whether it should render as a horizontal line or rectangular band;
- how its lifecycle changed through touch, breach, fakeout, break, or expiry;
- which resolved asset/timeframe configuration produced it;
- whether uninterrupted and checkpoint-resumed observation paths agree;
- what descriptive facts can be reported without inventing a quality score.

This phase creates that read-only surface. It does not claim that any zone is
good, predictive, profitable, or ready for trading.

## Locked Scope

Add only:

~~~text
src/libs/models/sr/evaluation/
├── __init__.py
├── contracts.py
├── identity.py
├── trace_builder.py
└── diagnostics.py

tests/models/sr/evaluation/
├── __init__.py
├── test_contracts.py
├── test_trace_builder.py
├── test_diagnostics.py
├── test_causality.py
└── test_checkpoint_parity.py
~~~

Modify existing import/boundary tests only where required to approve this new
package. Do not modify lifecycle, detection, association, replay,
serialization, configuration, YAML, or domain behavior unless an existing
blocking defect is discovered. If one is discovered, stop and report it rather
than expanding V1.4.

Public APIs are exported only from libs.models.sr.evaluation. Do not add these
APIs to the package root libs.models.sr.

## Dependency Direction

Allowed production dependencies:

~~~text
evaluation.identity
  -> domain deterministic_hash and canonical UTC primitive conventions only

evaluation.contracts
  -> domain contracts
  -> evaluation identity helpers

evaluation.trace_builder
  -> evaluation contracts
  -> domain SRSnapshot/SREvent/ZoneRecord contracts
  -> ResolvedSRConfig

evaluation.diagnostics
  -> evaluation contracts
~~~

The implementation may arrange identity helper calls to avoid circular imports,
but must preserve these architectural rules:

- no production core package imports evaluation;
- evaluation never calls SREngine;
- evaluation never changes SRState, SRSnapshot, SREvent, or ZoneRecord;
- evaluation consumes snapshots produced by replay_bars or SREngine.step;
- evaluation does not import adapters, YAML, serialization, lifecycle rules,
  detection, association, legacy SR, trendline, regime, strategy, execution,
  risk, portfolio, or optimization modules;
- standard-library-only runtime dependencies.

Tests may call replay_bars and the state codec to produce authoritative
fixtures.

## Observation Schema

Define one software protocol constant:

~~~text
SR_EVALUATION_SCHEMA_VERSION = "1.0"
~~~

This is not YAML configuration and not a hyperparameter.

### ZoneRenderKind

Use a string enum with exactly:

~~~text
LINE
BAND
~~~

Derivation is fixed:

- LINE when geometry.half_width == 0.0;
- BAND when geometry.half_width > 0.0.

Do not introduce a configurable rendering threshold.

### SnapshotReference

Create an immutable exact-type contract containing:

~~~text
snapshot_id: str
as_of: datetime
~~~

It must validate:

- snapshot_id is a lowercase SHA-256 identifier;
- as_of is timezone-aware UTC.

Snapshot references remain in caller snapshot order and must have strictly
increasing as_of timestamps.

### ObservedEvent

Create an immutable, plot-ready event record containing:

~~~text
snapshot_id: str
snapshot_as_of: datetime
event_id: str
zone_id: str
event_type: SREventType
timestamp: datetime
price: float
bar_id: str
~~~

The builder copies these values from the authoritative snapshot and event. It
must not reinterpret an event.

Validate:

- hash identifiers and exact enum/type contracts;
- positive finite price;
- event timestamp <= snapshot_as_of;
- event identity remains the existing domain event_id;
- one event_id may appear only once in a trace.

Ordering is snapshot order, then the event order already present in each
snapshot. Do not re-sort by event type, price, side, or zone.

### ZoneObservation

Create an immutable, self-contained plot record with at least:

~~~text
schema_version: str
state_key: SRStateKey
config_hash: str
snapshot_id: str
as_of: datetime

zone_id: str
side: ZoneSide
source: str
render_kind: ZoneRenderKind

lower_bound: float
center: float
upper_bound: float

created_at: datetime
available_at: datetime
visible_from: datetime
visible_until: datetime | None

status: ZoneStatus
touch_count: int
fakeout_count: int
pending_breach_count: int
age_bars: int
last_interaction_at: datetime | None
runtime_updated_at: datetime

observation_id: str  # derived, init=False
~~~

Required semantics:

- Copy all definition/runtime values from the ZoneRecord in that snapshot.
- lower_bound, center, and upper_bound come from the immutable zone geometry.
- lower_bound <= center <= upper_bound and all prices are positive and finite.
- render_kind follows the exact half-width rule above.
- visible_from is exactly available_at, never created_at.
- created_at may precede available_at for a confirmed pivot, but no consumer may
  backdate zone visibility to created_at.
- For ACTIVE and BREACH_PENDING, visible_until is None.
- For BROKEN and EXPIRED, visible_until is exactly runtime.updated_at.
- A terminal zone is therefore drawn through its terminal transition close,
  inclusively, and never extended afterward.
- runtime_updated_at <= observation.as_of.
- visible_from <= observation.as_of.
- Counters and age are non-negative exact integers.
- observation_id is a deterministic hash of every semantic field above except
  itself.

A zone can appear in multiple snapshot observations. Its definition, geometry,
side, source, created_at, available_at, and zone_id must remain identical in all
observations. Fakeout changes runtime state and counters only; it must not
replace or resize the zone.

### SREvaluationTrace

Create an immutable aggregate containing:

~~~text
schema_version: str
state_key: SRStateKey
config_hash: str
field_provenance: tuple[tuple[str, str], ...]
snapshots: tuple[SnapshotReference, ...]
zone_observations: tuple[ZoneObservation, ...]
events: tuple[ObservedEvent, ...]
trace_id: str  # derived, init=False
~~~

Validate:

- exact contract types, not subclasses or arbitrary iterables;
- at least one SnapshotReference is required;
- all snapshots are strictly ordered by as_of with unique snapshot IDs;
- every observation/event refers to a trace snapshot;
- all observations share trace schema, state key, and config hash;
- all events refer to zone IDs present in the same snapshot observations;
- no duplicate observation IDs or event IDs;
- field_provenance is a unique, canonically ordered tuple of non-empty
  path/source pairs;
- trace_id hashes the schema, state key, config hash, canonical provenance,
  ordered snapshot IDs, ordered observation IDs, and ordered event IDs.

The builder must copy field_provenance exactly from the validated
ResolvedSRConfig. That existing config contract remains the sole authority for
the exact eight paths and permitted provenance sources. Evaluation must not
duplicate or hardcode a second parameter-path registry. No config values are
copied into a second configuration model; config hash and field-level
provenance are the ownership/audit surface.

## Trace Builder API

Implement:

~~~python
build_evaluation_trace(
    snapshots: tuple[SRSnapshot, ...],
    resolved_config: ResolvedSRConfig,
) -> SREvaluationTrace
~~~

Input policy:

- snapshots must be exactly tuple[SRSnapshot, ...];
- resolved_config must be exactly ResolvedSRConfig;
- empty snapshot input is a structural evaluation failure and raises
  ContractValidationError;
- snapshots must be strictly increasing in caller order;
- all snapshot IDs must be unique;
- every snapshot must have the same schema, state key, and config hash;
- snapshot symbol/timeframe must match resolved_config.asset/timeframe;
- snapshot config_hash must equal resolved_config.resolved_config_hash;
- validate the entire snapshot tuple before returning a trace;
- on any contract error raise ContractValidationError and return no trace;
- do not sort, skip, fill, deduplicate, mutate, or repair caller input.

Output ordering:

1. SnapshotReference records preserve snapshot order.
2. For each snapshot, ZoneObservation records preserve the canonical zone order
   already supplied by SRSnapshot.zones.
3. ObservedEvent records preserve snapshot order and existing per-snapshot event
   order.

The builder emits one ZoneObservation for every zone in every supplied snapshot,
including retained terminal zones. Keeping terminal observations is required so
a checkpoint-resumed suffix trace equals the corresponding uninterrupted suffix.
visible_until prevents downstream renderers from extending terminal geometry.

The builder must be pure:

- no replay execution;
- no engine calls;
- no YAML/config resolution;
- no file/database/cache/network operations;
- no global mutable state;
- no clock access;
- no input mutation.

## Diagnostic Contracts And API

Implement:

~~~python
compute_diagnostics(trace: SREvaluationTrace) -> SRDiagnostics
~~~

Diagnostics must be derived only from the trace. They must not inspect future
bars, raw OHLCV outside the trace, or external data.

### ZoneDiagnostics

Create an immutable per-zone contract containing at least:

~~~text
zone_id: str
side: ZoneSide
render_kind: ZoneRenderKind
available_at: datetime
terminal_at: datetime | None
final_status: ZoneStatus
lifetime_bars: int
touch_count: int
fakeout_count: int
first_touch_at: datetime | None
time_to_first_touch_bars: int | None
status_bar_counts: tuple[tuple[ZoneStatus, int], ...]
left_censored: bool
right_censored: bool
diagnostic_id: str  # derived
~~~

Exact semantics:

- left_censored is true when available_at < trace.snapshots[0].as_of.
- right_censored is true when the final observed status is ACTIVE or
  BREACH_PENDING.
- terminal_at is the first non-null visible_until; all later terminal
  observations must carry the same value.
- lifetime_bars, touch_count, and fakeout_count come from the final observation.
- first_touch_at is the first TOUCHED event only when the trace contains the
  zone from availability. If left_censored, report None rather than pretending
  an in-window touch was the lifetime first touch.
- time_to_first_touch_bars is the difference between the creation/availability
  snapshot index and first-touch snapshot index. It is None for left-censored
  zones and for zones with no observed touch.
- status_bar_counts count one bar per observation only through terminal_at,
  inclusive. Repeated retained terminal observations after terminal_at do not
  inflate duration.
- status entries use fixed enum order:
  ACTIVE, BREACH_PENDING, BROKEN, EXPIRED.
- No averages, ratios, ranking, weighting, quality labels, or thresholds.

### SnapshotDiagnostics

Create an immutable per-snapshot record containing:

~~~text
snapshot_id: str
as_of: datetime
active_zone_count: int
pending_zone_count: int
live_zone_count: int
new_terminal_zone_count: int
event_count: int
~~~

Definitions:

- live = ACTIVE or BREACH_PENDING;
- new terminal means a BREAK_CONFIRMED or EXPIRED event in that snapshot;
- terminal zones retained from earlier snapshots are not live and are not newly
  terminal.

### SRDiagnostics

Create an immutable run-level contract containing at least:

~~~text
trace_id: str
snapshot_count: int
zone_count: int
support_zone_count: int
resistance_zone_count: int

created_event_count: int
touched_event_count: int
breach_started_event_count: int
false_breakout_event_count: int
break_confirmed_event_count: int
expired_event_count: int

max_live_zone_count: int
final_live_zone_count: int
left_censored_zone_count: int
right_censored_zone_count: int

snapshots: tuple[SnapshotDiagnostics, ...]
zones: tuple[ZoneDiagnostics, ...]
diagnostics_id: str  # derived
~~~

Required rules:

- Event counts are exact counts within this trace, not lifetime estimates.
- Zone counts use unique zone_id values.
- Zone diagnostics are ordered by first observation time, then zone_id.
- Snapshot diagnostics preserve trace snapshot order.
- All totals must reconcile exactly with the nested records.
- diagnostics_id deterministically hashes all semantic scalar values and ordered
  nested diagnostic IDs.
- Empty, NaN, infinity, division, percentage, score, and threshold semantics are
  not needed because no ratios are computed.

## Identity Rules

Use explicit primitive payload construction and the approved deterministic hash
helper. Do not use repr, pickle, object __dict__, reflection-based generic
serialization, memory addresses, unordered sets, local timezone strings, or
floating-point rounding.

All datetime values entering an identity payload use the existing canonical UTC
format. Enum values use their string values. Tuple ordering is semantic and must
be preserved.

Repeated builds from equal inputs must return equal contracts and identical IDs.

## Causality And Parity Invariants

The following are release gates.

### Availability

A zone may be observed in the snapshot where it becomes available, but:

~~~text
visible_from == ZoneDefinition.available_at
visible_from <= observation.as_of
visible_from != created_at when pivot confirmation delayed availability
~~~

No observation contract may authorize drawing the zone before available_at.

### Prefix Causality

For snapshots S and any non-empty prefix P:

- P trace snapshots equal the corresponding prefix of S trace snapshots;
- P zone observations equal all S trace observations belonging to P snapshots;
- P events equal all S trace events belonging to P snapshots;
- observation and event identities are unchanged;
- only aggregate trace_id and diagnostics that legitimately depend on run length
  may differ.

No later snapshot may revise an earlier observation.

### Checkpoint-Resume Parity

Using the approved V1.3 lifecycle parity sequence:

1. replay the full bar sequence;
2. build the full trace;
3. replay a prefix;
4. canonical checkpoint round-trip its state;
5. replay the suffix;
6. build a suffix trace;
7. compare it to the full trace restricted to suffix snapshot IDs.

Require exact equality for:

- SnapshotReference records;
- ZoneObservation records and observation IDs;
- ObservedEvent records and event IDs;
- zone geometry and visible windows;
- per-snapshot diagnostics for the suffix.

Run-level and per-zone diagnostics may differ only where the suffix is correctly
marked left-censored or lacks earlier events. Do not fabricate pre-checkpoint
event history.

### Fakeout Geometry

A sequence containing BREACH_STARTED followed by FALSE_BREAKOUT must prove:

- same zone_id before, during, and after the fakeout;
- same lower/center/upper values;
- same created_at, available_at, and visible_from;
- BREACH_PENDING returns to ACTIVE;
- fakeout_count increases;
- visible_until remains None.

### Terminal Geometry

For BROKEN and EXPIRED:

- visible_until equals the terminal runtime.updated_at;
- later retained terminal observations keep the same visible_until and geometry;
- live-zone counts exclude the terminal zone;
- terminal status duration is not inflated by later retained snapshots.

## Configuration And Hyperparameter Policy

The model configuration remains exactly:

~~~text
detection.pivot_span_bars
detection.zone_half_width_atr
association.merge_distance_atr
lifecycle.touch_tolerance_atr
lifecycle.break_buffer_atr
lifecycle.break_confirm_closes
lifecycle.max_age_bars
runtime.max_active_zones
~~~

Rules:

- no new YAML keys;
- no changed defaults;
- no per-asset/timeframe values;
- no runtime overrides;
- no evaluation thresholds;
- no quality-score weights;
- no plotting thresholds;
- no parameter search space.

V1.4 records resolved config hash and provenance so V1.5 can compare asset/timeframe
runs without losing configuration identity. V1.4 does not select or tune those
values.

## Import And Side-Effect Boundaries

Production evaluation code must not import:

- pandas, NumPy, Polars, SciPy, sklearn, TensorFlow, PyTorch;
- matplotlib, Plotly, Bokeh, Altair, seaborn;
- YAML loaders;
- filesystem/pathlib file operations;
- pickle;
- SQL/database clients;
- Redis/Valkey/cache clients;
- requests/httpx/network clients;
- legacy app.sr or libs.sr;
- trendline, regime, strategy, execution, risk, portfolio, or optimization
  packages.

Importing libs.models.sr.evaluation must perform no I/O and must not import
optional plotting/data libraries.

Update the approved SR import allowlist narrowly for this package. Do not weaken
the boundary scan globally.

## Required Tests

### Contracts

- exact-type validation;
- invalid schema/hash/enum/timestamp/numeric rejection;
- LINE for zero half-width and BAND for positive half-width;
- visible_from must equal available_at;
- terminal/nonterminal visible_until rules;
- deterministic observation, trace, and diagnostics IDs;
- unknown/missing ownership and duplicate identity rejection;
- no input mutation.

### Trace Builder

- non-empty exact snapshot tuple required;
- strict snapshot ordering and unique IDs;
- mixed state key/config/schema rejection;
- resolved config ownership and provenance;
- one observation per zone per snapshot;
- terminal zones retained in observations with frozen visible_until;
- event-to-snapshot and event-to-zone ownership;
- existing snapshot zone/event ordering preserved;
- support and resistance;
- line and band geometry;
- repeated build equality.

### Diagnostics

- exact six event counts;
- unique zone/support/resistance counts;
- per-snapshot active/pending/live/new-terminal counts;
- max and final live-zone counts;
- lifetime/final counters;
- first-touch timestamp and bar distance;
- status bar counts stop at terminal;
- left-censored suffix behavior;
- right-censored live-zone behavior;
- fakeout is not counted as break;
- deterministic ordering and identities.

### Causality

- delayed pivot visibility begins at available_at, not created_at;
- non-empty prefix equivalence;
- extending a trace never changes prior observation/event records or IDs;
- no future timestamps enter a prefix;
- no later lifecycle state overwrites an earlier observation.

### Checkpoint Parity

- exact uninterrupted/suffix SnapshotReference equality;
- exact uninterrupted/suffix ZoneObservation equality and IDs;
- exact uninterrupted/suffix ObservedEvent equality and IDs;
- exact suffix snapshot diagnostics;
- left-censoring is explicit for pre-checkpoint zones;
- no fabricated pre-checkpoint events;
- fakeout geometry preservation;
- terminal visible-window preservation.

### Regressions And Boundaries

- all existing 263 SR tests remain green;
- existing lifecycle suite remains green;
- trendline-family import boundary remains green;
- exact eight config paths and YAML values remain unchanged;
- no production caller is added outside evaluation tests;
- no prohibited dependency or side effect is introduced.

## Explicit Non-Goals

Do not implement:

- real-market data fetching or dataset adapters;
- CSV, Parquet, JSON, YAML, filesystem, database, cache, or cloud artifact
  writers;
- checkpoint repositories or scheduling;
- chart rendering, HTML, SVG, images, TradingView/Pine output, plotting-library
  integration, or UI;
- quality scores, confidence, strength, ranking, reaction quality, zone
  usefulness labels, or promotion gates;
- forward-return, excursion, PnL, win-rate, Sharpe, drawdown, trading-cost, or
  strategy evaluation;
- future-horizon labels;
- parameter tuning, grid search, Optuna, walk-forward, or holdout logic;
- new features or additional model inputs;
- alternate pivot detectors, zone association variants, clustering, regression,
  ML, volume, order-book, regime, or trendline integration;
- multi-timeframe composition;
- storage/runtime/worker/signal-app integration;
- terminal-zone pruning or event-history persistence;
- schema migration;
- factory annotation-introspection follow-up;
- legacy SR integration;
- any V1.5 work.

## Acceptance Commands

Run the current baseline before implementation, then run and report:

~~~bash
.venv/bin/python -m pytest tests/models/sr/evaluation -q
.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/replay tests/models/sr/evaluation -q
.venv/bin/python -m pytest tests/models/sr/lifecycle -q
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q
ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr
PYTHONPATH=src .venv/bin/python -c "from libs.models.sr.evaluation import build_evaluation_trace, compute_diagnostics; print('ok')"
rg -n "pickle|app\.sr|libs\.sr|pandas|numpy|polars|scipy|sklearn|tensorflow|torch|matplotlib|plotly|bokeh|altair|seaborn|sqlalchemy|redis|valkey|requests|httpx" src/libs/models/sr/evaluation tests/models/sr/evaluation
git diff --quiet d85a02e -- configs src/libs/models/sr/config
git diff --check
~~~

The rg command may match the boundary-test denylist itself; report and classify
each match rather than claiming zero text matches blindly.

Run independent probes for:

1. delayed pivot availability versus created_at;
2. zero-width LINE and positive-width BAND observations;
3. fakeout lifecycle with frozen geometry;
4. terminal visible_until freezing across retained snapshots;
5. prefix causality and stable observation/event IDs;
6. uninterrupted versus checkpoint-resumed suffix parity;
7. config provenance and trace ownership;
8. exact diagnostics reconciliation;
9. explicit left/right censoring;
10. input immutability and fail-closed invalid tuples.

## Mandatory Coder Handoff

Return plans/coder-to-review-sr-v1.4-observation-evaluation-v1.md containing:

- exact base, target branch, and implementation/handoff commits;
- exact added/modified files;
- public evaluation contracts and APIs;
- dependency and call graph;
- visibility-window and LINE/BAND semantics;
- ordering and deterministic identity payloads;
- config hash/provenance ownership;
- prefix-causality evidence;
- checkpoint-resume suffix-parity evidence;
- fakeout and terminal-geometry evidence;
- left/right censoring behavior;
- diagnostic reconciliation results;
- baseline and final tests, Ruff, compile, imports, boundaries, config diff, and
  independent probes;
- confirmation that no model logic, YAML/config value, feature, score,
  threshold, tuning, data fetch, artifact writer, plotting, storage, runtime
  integration, or later phase was added;
- known risks and deliberately deferred work.

## Stop Condition

Stop after V1.4 implementation, validation, commits, and coder-to-review handoff.
Do not merge. Do not begin V1.5 market trials, data acquisition, plotting,
features, tuning, storage, or strategy integration without explicit Quant
Review approval.
