# L2-A1 — Canonical Research Data and Configuration Foundation

## 1. Disposition

L2-A1 implementation complete. No commit created. Preparation is deterministic, bounded,
availability-aware, and does not execute trendline models.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
starting commit: 0abb0b56b34816bd42e6aa705abc3189bbbda11f
subject: feat: enforce causal trendline signal inputs
```

## 3. Worktree/environment proof

L1-B3/R1 was committed before L2-A1. Python environment:

```text
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
RUFF=/Users/aloobhujia/.local/bin/ruff
PYTHONPATH=src:$PWD
```

No dependency installation or real provider call was used. The L2-A1 worktree contains only the
authorized implementation, tests, documentation, and this handoff.

## 4. Baseline research-data gap

Approved L1-B3 baseline was 367 canonical tests, 71 consumer/ingestion tests, and 20 offline
workflow tests. Existing `src/libs/models/trendlines/workflows/pipeline/data_fetch.py` still
references the retired `app.connectors.BinanceConnector` seam and has implicit wall-clock bounds.
The new research path does not use that helper.

## 5. Explicit YAML pipeline parameters

Added parity values to `config/trendlines.yaml` and the Python fallback:

```text
extractor: fractal
fitter: pathfinding
extractor_params: window_left=3, window_right=3
fitter_params: pivot_window=3, line_fit_mode=endpoint
```

No optimized value, search-grid value, asset override, or promotion output changed.

## 6. Global/asset-timeframe resolution

`resolve_pipeline_config()` now merges global component names/parameters with partial
asset/timeframe overrides, canonicalizes aliases, validates construction and execution policy,
and returns fully explicit component parameters. Component-name changes start a fresh compatible
parameter map; missing explicit parameters fail closed. Runtime rejects RDP; research mode accepts
explicit RDP.

Tested override: BTCUSDT/1h changes Fractal `window_right` from 3 to 5 while retaining global
`window_left=3`. RDP component override uses explicit `epsilon_atr=0.5` and
`min_segment_bars=1`.

## 7. Research-purpose contracts

Added frozen `TrendlineResearchPurpose` (`SMOKE`, `RESEARCH`), `TrendlineResearchDataMode`
(`SYNTHETIC`, `INJECTED`, `BINANCE`), `TrendlineResearchDataSpec`, and `TrendlineResearchSpec`.
Asset and ordered unique timeframe scope are validated. `SMOKE + BINANCE` fails. Synthetic data
requires seed/start/bar counts. Binance data requires timezone-aware event start and knowledge
cutoff. Research specs accept no model hyperparameter dictionaries.

## 8. Synthetic data

`generate_synthetic_frames()` uses fixed seeded NumPy generation, explicit timeframe duration,
open-time event indexes, and `fixed_interval_derived` availability. It writes no files and makes
no network calls. Generator semantics version:

```text
trendlines.synthetic-generator.v1
```

Same spec produced byte-equivalent frames and stable identity. Different seed changed source and
dataset IDs.

## 9. Injected data

`prepare_research_dataset()` accepts a mapping or async/sync injected loader. It validates every
requested timeframe, rejects missing or unexpected timeframes, copies/normalizes each frame once,
computes one source reference per timeframe, and builds one manifest and dataset identity. No CSV
or Parquet path handling was added.

## 10. Binance adapter bridge

Added `apps.ingestion_app.adapters.trendlines_research.BinanceTrendlineResearchLoader`. It uses
the current `BinanceNativeAdapter` injection seam and never imports the retired connector.
Validation used only a fake adapter; real provider calls: 0.

## 11. Pagination and availability

Named protocol page limit:

```text
BINANCE_KLINE_PAGE_LIMIT = 1500
```

The bridge requests `include_close_time=True`, preserves open-time event indexes, maps exchange
`close_time` to `bar_available_at`, marks `exchange_close_time`, advances from last close time +
1 ms, rejects non-advancing pagination, removes bars unavailable by knowledge cutoff, and rejects
conflicting duplicate event rows. Mocked bounded run: 2 pages, 2 provider calls, 1 retained
complete bar.

## 12. Dataset/source identities

Semantics version:

```text
trendlines.research-data.v1
```

For deterministic synthetic/injected BTCUSDT 1h+4h, 24 bars per timeframe:

```text
research configuration id:
b26b507df800e3d45261544dd50d68298eef55d2a6776b81cb86c525542bdb07

root configuration id:
d51c84382cd0d23815bcc6ad76a645297b9fdbd0b8ad05b1f30eb7ea7e2e7252

search-grid identity:
b8b88ff3af02485986b1d736e4b2c2625220cebc1cb1c359f169cec486af95ad

synthetic dataset id:
13d8e0699d9ff23fbdae9b78e68dda0f6998be497263a3c4e4b22475d5a04096

injected dataset id:
8b10a9ee7ccd2cd8b274126d6cc71ae4198f44e704318f357e6c6658fd8f4e06
```

Synthetic and injected source IDs matched because frames matched; dataset IDs differ because data
mode is part of the explicit data specification.

Per-timeframe source evidence:

| mode | timeframe | bars | source ID | event start | event end | availability end | source |
|---|---:|---:|---|---|---|---|---|
| synthetic/injected | 1h | 24 | `9afb8509a765094fceb39bdd39817c6063eacadb61269449f57a5c7e77119723` | 2025-01-01T00:00:00Z | 2025-01-01T23:00:00Z | 2025-01-02T00:00:00Z | fixed_interval_derived |
| synthetic/injected | 4h | 24 | `c77c3c2aa29a9bb36d1f035b44d885dd2a47718c6181073f8dd2d85f63824108` | 2025-01-01T00:00:00Z | 2025-01-04T20:00:00Z | 2025-01-05T00:00:00Z | fixed_interval_derived |

Mocked Binance dataset identity:

```text
13e53b91df9ec5d838677aa71bfc223e07f3d924391230fc58dc018b5ab59fb6
```

## 13. Research configuration identity

`PreparedTrendlineResearchConfig` carries ordered timeframe pipeline configs, root config ID,
search-grid identity, and research config ID. Config identity changes when resolved component
names, parameters, or search grids change. No wall-clock value participates.

## 14. Prepared-run contract

`prepare_trendline_research()` returns validated spec, prepared dataset, resolved configuration,
and preparation ID only. It does not run pivot extraction, fitting, signals, replay, optimization,
holdout access, or promotion. `asyncio.run()` is not hidden in canonical APIs.

## 15. Dependency-boundary evidence

`workflows/research/` imports only canonical config/data/identity/signal contracts. It contains no
`apps.*`, `app.*`, Binance SDK, Jupyter, IPython, Plotly, TVLC, RegimeV2, Trendline V2,
`BinanceConnector`, or `app.connectors` import/reference. Concrete Binance integration is isolated
under `apps.ingestion_app.adapters`.

## 16. No-YAML-mutation evidence

The only YAML change adds explicit parity pipeline parameters required by L2-A1. Research code
loads/resolves/hashes YAML but contains no `config_apply`, `apply_to_config`, or YAML write path.
No optimization output was promoted.

## 17. Canonical tests

Added exactly 20 non-parametrized tests across `test_research_config.py` and
`test_research_data.py`.

```text
387 collected
387 passed
```

Coverage includes explicit parameters, precedence, runtime/research RDP policy, deterministic
configuration IDs, mode constraints, synthetic determinism, injected timeframe contracts,
duplicate rejection, one source resolution per timeframe, dataset multi-timeframe identity, no
model execution, and dependency boundaries.

## 18. Binance bridge tests

Added exactly 8 mocked tests:

```text
8 passed
```

Coverage includes native adapter seam, close-time request, named page limit, pagination advance,
open-time index, exchange-close provenance, cutoff filtering, and conflicting duplicates.

## 19. Performance evidence

Seven repetitions; medians in milliseconds; fixed seed 42 and UTC synthetic frames.

| total bars | synthetic preparation | injected preparation |
|---:|---:|---:|
| 1,000 | 4.719 ms | 4.327 ms |
| 10,000 | 24.227 ms | 23.354 ms |
| 100,000 | 278.554 ms | 227.216 ms |

Configuration resolution median: `0.447 ms`. Preparation stayed linear and below the 1-second
100,000-bar budget. Source resolution count was exactly one per timeframe: 2 calls for a 2-TF
run. Canonical validation performs one frame copy per timeframe; no repeated source fingerprint,
OHLCV scan, row-dictionary conversion, or model pass exists.

L2-A1 has no pre-existing research-preparation implementation, so a numeric before/after baseline
does not exist; current timings are the first implementation baseline.

## 20. Canonical regression

```text
387 passed
```

## 21. Consumer regression

```text
71 passed
```

Command covered RegimeV2 trendline producer, shadow collector, RegimeV2, and ingestion adapters.

## 22. Offline regression

```text
20 passed
```

Optimizer, optimization integration, and trendlines pipeline workflow tests remain green.

## 23. Static validation

```text
targeted Ruff: passed
compileall: passed
git diff --check: passed
repository-local Python caches removed
```

## 24. Files changed

```text
src/apps/ingestion_app/adapters/trendlines_research.py
src/apps/ingestion_app/constants.py
src/libs/models/trendlines/__init__.py
src/libs/models/trendlines/config/__init__.py
src/libs/models/trendlines/config/base_config.py
src/libs/models/trendlines/config/defaults.py
src/libs/models/trendlines/config/loader.py
src/libs/models/trendlines/config/resolve.py
src/libs/models/trendlines/config/trendlines.yaml
src/libs/models/trendlines/docs/architecture.md
src/libs/models/trendlines/docs/config.md
src/libs/models/trendlines/docs/data.md
src/libs/models/trendlines/docs/research.md
src/libs/models/trendlines/docs/workflows.md
src/libs/models/trendlines/workflows/__init__.py
src/libs/models/trendlines/workflows/research/__init__.py
src/libs/models/trendlines/workflows/research/config.py
src/libs/models/trendlines/workflows/research/contracts.py
src/libs/models/trendlines/workflows/research/data.py
src/libs/models/trendlines/workflows/research/synthetic.py
src/libs/models/trendlines/tests/test_research_config.py
src/libs/models/trendlines/tests/test_research_data.py
tests/ingestion/test_trendlines_research_adapter.py
plans/coder-to-orchestrator-trendlines-l2a1-research-foundation-v1.md
```

## 25. Git status

Expected final status is the authorized L2-A1 implementation/tests/docs plus this untracked
handoff. No prior committed files were modified outside scope; no commit was created for L2-A1.

## 26. Commands executed

```text
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
git status --short --untracked-files=all
codebase-memory index attempt (contained worker crash; live-source fallback used)
pytest canonical collection and execution
pytest research config/data tests
pytest mocked Binance bridge tests
pytest consumer/ingestion matrix
pytest offline workflow group
ephemeral synthetic/injected preparation benchmarks
ephemeral mocked Binance preparation smoke
compileall canonical package and bridge/tests
targeted Ruff over every changed Python file
git diff --check
cache removal under src/tests
```

## 27. Residual risks

- Binance bridge remains a mocked-only validation path; no real provider call was authorized.
- Existing legacy optimization helper retains retired connector and implicit-bound behavior; new
  research preparation intentionally does not migrate it.
- Dataset source IDs represent model-visible OHLCV; availability provenance is bound separately in
  dataset identity. Persistent dataset storage and replay evidence remain out of scope.
- L2-A1 resolves research-mode configuration but does not execute or score any model.

## 28. Recommended next phase

```text
L2-A2 — Causal replay, diagnostics and evidence APIs
```

Do not build notebook or TVLC presentation before L2-A2 approval.
