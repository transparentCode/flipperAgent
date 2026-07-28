# Mature Trendlines Research Viewer

`libs.models.trendlines.research_viewer` is a presentation layer for validated
L2-A2 replay and evidence contracts. Core payload and bundle APIs remain
presentation-only. The generic `runner.py` composition seam is the explicit
research-only entry point for guarded Binance acquisition and final-point replay.

The package creates strict `trendlines_research_viewer_payload_v1` payloads and
explicit two-file `trendlines_research_viewer_bundle_v1` bundles. Its server binds
only to loopback and serves one validated bundle with `Cache-Control: no-store`.

Default notebook mode is deterministic synthetic smoke data. Binance mode requires
an explicit research spec, injected loader, and provider authorization. Permanent
evidence or viewer export is always explicit. The generic runner requires
`TRENDLINES_ALLOW_RESEARCH_VIEWER_FETCH=1`, accepts arbitrary canonical Binance
symbols and fixed timeframes through `1w`, records one final replay point, and
publishes only an atomic `viewer_bundle/` plus `run_report.json`.

Example:

```bash
TRENDLINES_ALLOW_RESEARCH_VIEWER_FETCH=1 \
PYTHONPATH="$PWD/src:$PWD" \
.venv/bin/python scripts/run_trendlines_research_viewer.py \
  --asset TAOUSDT \
  --timeframe 4h \
  --source binance \
  --start 2026-01-01T00:00:00Z \
  --end 2026-03-01T00:00:00Z \
  --output /tmp/trendlines_taousdt_4h \
  --display-bars 250 \
  --serve \
  --port 8766
```

Verify an existing output without fetching or replaying:

```bash
PYTHONPATH="$PWD/src:$PWD" \
.venv/bin/python scripts/run_trendlines_research_viewer.py \
  --verify-output /tmp/trendlines_taousdt_4h
```

```bash
npm ci
npm run build
```
