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
