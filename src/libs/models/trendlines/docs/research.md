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
