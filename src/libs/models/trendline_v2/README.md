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

Use generic asset/timeframe runner with:

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/run_trendline_v2_viewer.py \
  --asset <ASSET> \
  --timeframe <TIMEFRAME> \
  --input-csv <CSV_PATH> \
  --serve
```
