# Trendlines

`app/trendlines` is the canonical home for reusable trendline logic, data-pipeline contracts,
and trendline-native signal extraction. It was extracted from the legacy `app/geometry/` module
(now removed) and is the authoritative ownership location for all trendline capabilities.

## Quick Reference

| Intent | Entry Point |
|-|-|
| Extract pivots + fit lines only | `fit_trendlines(df, ...)` |
| Fit + boundary adaptation | `fit_trendlines_to_boundary(df, asset, timeframe, ...)` |
| Full pipeline with signals | `fit_and_signal(df, asset, timeframe, ...)` |
| Low-level pipeline | `run_trendline_pipeline(df, extractor, fitter)` |
| Build a registry component | `build_extractor(name)`, `build_fitter(name)` |
| List available components | `list_extractors()`, `list_fitters()` |

## Module Map

```
app/trendlines/
├── __init__.py          # Public API surface — all stable exports
├── api.py               # Facade: fit_trendlines, fit_and_signal, TrendlineOutput
├── cli.py               # CLI: drift-monitor, pipeline-opt subcommands
│
├── contracts/           # Core DTOs: PivotSet, Trendline, TrendlineFitResult
├── config/              # TrendlinesConfig hierarchy + trendlines.yaml
├── registry/            # build_extractor, build_fitter, search grid surfaces
├── pipeline/            # Orchestration: extract → fit chain
│
├── pivots/              # Pivot extractors: fractal, rdp_zigzag
├── fitting/             # Trendline fitters: pathfinding, least_squares, ransac
├── boundary/            # Ray, BoundaryResult, adapter, interaction detection
├── signals/             # AlphaSignal, 4 extractors, TrendlineSignalOrchestrator
│
├── data/                # Dataset contracts, walk-forward splits, artifact I/O
├── workflows/           # Optimization engine, promotion, drift monitor
└── docs/                # This documentation
```

## Registered Components

| Kind | Registry Name | File |
|-|-|-|
| Extractor | `fractal` | `pivots/fractal.py` |
| Extractor | `rdp_zigzag` | `pivots/rdp_zigzag.py` |
| Fitter | `pathfinding` | `fitting/pathfinding.py` |
| Fitter | `least_squares` | `fitting/least_squares.py` |
| Fitter | `ransac` | `fitting/ransac.py` |
| Fitter | `ensemble` | `fitting/ensemble.py` |

The **ensemble** fitter is a meta-fitter that runs pathfinding + least_squares + RANSAC
on the same pivot set, deduplicates near-identical lines by slope/intercept similarity,
and yields up to 3 support + 3 resistance = 6 lines per call. It is the default fitter
for the Bayesian optimizer.

Deprecated aliases handled by the registry: `fractals→fractal`, `rdp-zigzag→rdp_zigzag`,
`ols→least_squares`, `least-squares→least_squares`.

## Pipeline Stages

```
OHLC DataFrame
    │
    ▼  Stage 1 — EXTRACT
PivotSet          ← FractalPivotExtractor | RDPZigZagPivotExtractor
    │
    ▼  Stage 2 — FIT
TrendlineFitResult  ← EnsembleFitter (default) | PathfindingFitter | LeastSquaresFitter | RansacFitter
    │
    ▼  Stage 3 — ADAPT
BoundaryResult      ← build_boundary_result_from_trendline_result()
    │
    ▼  Stage 4 — SIGNAL
{signals[], composite_direction, composite_confidence}
                    ← TrendlineSignalOrchestrator (4 extractors)
    │
    ▼  Stage 5 — CONFLUENCE  (app/alpha/ — not owned here)
Final alpha signal
```

## Scope

**In scope:**
- Canonical pivot extractor and trendline fitter implementations and registry
- Typed hierarchical config (`TrendlinesConfig`) with YAML source and Python fallback
- Boundary adaptation: `Trendline → Ray → BoundaryResult`, interaction detection
- Trendline-native signal extraction (structural, temporal, pattern, fakeout + orchestrator)
- Data contracts: dataset manifest, walk-forward temporal splits, artifact persistence
- Optimization workflow: 3-step greedy sweep, fitness scoring, promotion
- Drift monitoring workflow

**Out of scope:**
- Cross-domain confluence (regime + oscillator + trendline) → lives in `app/alpha/`
- Portfolio or strategy scoring
- Geometry compatibility shims (geometry module is gone)

## Reference Docs

| Doc | Contents |
|-|-|
| [architecture.md](architecture.md) | Layer model, dependency rules, Mermaid diagrams |
| [agent-map.md](agent-map.md) | Coding guide: how to add, change, and debug |
| [pipeline.md](pipeline.md) | End-to-end pipeline execution and API examples |
| [config.md](config.md) | TrendlinesConfig hierarchy, YAML loading |
| [signals.md](signals.md) | 4 signal extractors, orchestrator, quality scoring |
| [boundary.md](boundary.md) | Boundary adaptation, Ray contract, interaction detection |
| [pivots.md](pivots.md) | Fractal and RDP-zigzag pivot extraction algorithms |
| [fitting.md](fitting.md) | Pathfinding, least-squares, and RANSAC fitting algorithms |
| [data.md](data.md) | Dataset contracts, walk-forward splits, artifact persistence |
| [workflows.md](workflows.md) | Optimization workflow, fitness function, promotion, drift monitor |
