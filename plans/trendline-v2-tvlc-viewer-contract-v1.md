# Trendline V2 TVLC Viewer Contract V1

Status: `ARCHITECTURE_ONLY`

Authorization: `PHASE_6V_TVLC_VIEWER_NOT_AUTHORIZED`

## Engine mandate

All Trendline V2 interactive charting must use TradingView Lightweight Charts:

```text
npm package: lightweight-charts
```

No Plotly, Matplotlib, Bokeh, Altair, ECharts, ApexCharts, Highcharts,
Chart.js, TradingView Advanced Charts, custom SVG renderer, or floating CDN is
allowed.

At viewer phase start, verify official TradingView sources and record checked
date, prior expected version `5.2.0`, current stable version, breaking changes,
migration, and selected exact version. Pin exact version in `package.json` and
commit lockfile. Never use `latest`, caret, tilde, preview, master, or CDN
versions.

## Ownership boundary

Runtime dependency is forbidden:

```text
trendline_v2 runtime -> browser/UI/JavaScript/TVLC
```

Allowed direction:

```text
serialized Trendline V2 output -> viewer adapter -> Lightweight Charts
```

Preferred future ownership is `src/apps/trendline_v2_viewer/`, outside
`src/libs/models/trendline_v2/`. Host framework remains unresolved; do not add
React, Vue, Svelte, or another framework during Phase 6A.

## Rendering design

Future viewer uses TypeScript and:

```text
CandlestickSeries
+
one batched custom ISeriesPrimitive per displayed discovery snapshot
```

Primitive owns finite segments, approved extensions, role styling, anchors,
confirmation state, selected/hovered emphasis, optional provider evidence, and
labels. It is read-only. Manual drawing, editing, dragging, and chart-to-model
feedback are forbidden.

## Timestamp adapter

Model timestamps are epoch nanoseconds. Lightweight Charts intraday values are
UNIX seconds. Conversion happens only at viewer boundary and must:

- reject unsafe or lossy conversion;
- never silently round sub-second values;
- preserve UTC;
- test pre-epoch and boundary values where supported;
- bind chart payload identity to source snapshot identity.

Conversion policy remains a Phase 6V decision, not a runtime model change.

## Backend payload contract

Future chart-neutral payload includes:

```text
schema_version
asset
timeframe
observed_at
confirmed_through
input_identity
config_identity
provider_identity
candles
candidate_id
role
geometry endpoints
anchors
anchor confirmation times
provider evidence
status/reason
```

Model runtime remains free of TVLC types.

## Attribution and tests

Future viewer must enable supported TradingView attribution or prominent
official link. Required tests cover exact package/lockfile version, no other
chart dependency, payload validation, nanosecond conversion, primitive
coordinates, resize, visibility toggles, role styling, browser smoke, stable
payload identity, model-state immutability, and attribution.

No viewer source, package, lockfile, browser test, or chart dependency is added
in Phase 6A.
