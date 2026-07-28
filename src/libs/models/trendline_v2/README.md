# Trendline V2

Trendline V2 provides causal trendline geometry discovery and point-in-time
inspection. It exposes exact interaction evidence and support/resistance
context for audit tooling.

## Non-goals

Trendline V2 is not a standalone alpha signal, automatic best-line selector,
quality score, trade-entry recommendation or validated actionability ranking.

## Viewer modes

- **Nearest now**: simple display-only proximity compression. It shows one
  representative per exact second anchor, independently capped by role.
- **Focus**: configurable diagnostic density filter using existing causal
  evidence.
- **All raw**: complete provider output in original order for audit.

All modes change display only. Provider output and persisted evidence remain
unchanged.

## Research boundary

Phases 11S, 11R, 12Q, 13H and 14A found no validated production shortlist.
Current proximity is useful for chart relevance, but it is not validated as a
predictive or quality signal.

## Usage

Serve any verified viewer bundle with:

```bash
PYTHONPATH=src .venv/bin/python \
  -m libs.models.trendline_v2.tools.viewer.server \
  --bundle <viewer_bundle>
```

Use the generic runner with any canonical uppercase Binance USD-M symbol and
any supported fixed-duration Binance interval:

```text
1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w
```

CSV example:

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/run_trendline_v2_viewer.py \
  --asset <ASSET> \
  --timeframe <TIMEFRAME> \
  --source csv \
  --input-csv <CSV_PATH> \
  --start <START_ISO_UTC> \
  --end <END_EXCLUSIVE_ISO_UTC> \
  --output <OUTPUT_DIRECTORY> \
  --serve
```

Binance example:

```bash
TRENDLINE_V2_ALLOW_VIEWER_FETCH=1 \
PYTHONPATH=src .venv/bin/python \
  scripts/run_trendline_v2_viewer.py \
  --asset <ASSET> \
  --timeframe <TIMEFRAME> \
  --source binance \
  --start <START_ISO_UTC> \
  --end <END_EXCLUSIVE_ISO_UTC> \
  --output <OUTPUT_DIRECTORY> \
  --serve
```

The exchange validates that the requested symbol exists and is listed. Monthly
`1M` candles remain excluded because the viewer's causal source contract requires
a fixed interval duration.
