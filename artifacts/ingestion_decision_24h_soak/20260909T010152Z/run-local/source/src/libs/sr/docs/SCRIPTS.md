# S/R Scripts — CLI Tools & Utilities Reference

## Overview

`app/sr/scripts/` provides CLI tools for running, monitoring, diagnosing, and smoke-testing the S/R optimization pipeline. All scripts use `BinanceConnector` for real OHLCV data and share common utilities for data fetching and UTC normalization.

## Module Map

```
app/sr/scripts/
├── __init__.py                 # (empty)
├── _utils.py                   # Shared: UTC normalization, paginated fetching, multi-asset data maps
├── run_optimization.py         # CLI: Two-stage S/R optimization (main entry point)
├── monitor_optimization.py     # CLI: Inspect, watch, list, compare optimization results
├── zone_quality_audit.py       # CLI: Real-data zone quality diagnostic
├── smoke_test.py               # CLI: Quick pipeline + universe validation with synthetic data
└── status_writer.py            # Atomic JSON status file for cross-process monitoring
```

---

## run_optimization.py

Main CLI entry point for two-stage S/R optimization on real market data.

### Usage

```bash
# Single asset, default settings
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h --n-trials 50

# Multi-asset with date range
python app/sr/scripts/run_optimization.py \
    -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h,4h \
    --start-date 2023-01-01 --end-date 2026-03-01 \
    --n-trials 100 --timeout 7200

# Preview YAML changes without writing
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \
    --n-trials 50 --apply --dry-run

# Apply best params to sr.yaml
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \
    --n-trials 50 --apply

# Quick test run with custom seed
python app/sr/scripts/run_optimization.py --n-trials 5 --timeout 60 --seed 123 --quiet
```

### CLI Flags

| Flag | Default | Description |
|-|-|-|
| `-a/--assets` | `BTCUSDT` | Comma-separated trading pairs |
| `-t/--timeframes` | `1h` | Comma-separated timeframes |
| `--n-trials` | 50 | Stage 1 Optuna trials |
| `--timeout` | 3600 | Stage 1 timeout (seconds) |
| `--stage2-n-trials` | 30 | Stage 2 per-asset trials |
| `--stage2-timeout` | 600 | Stage 2 per-asset timeout |
| `--config` | `app/sr/config/sr.yaml` | Path to sr.yaml config |
| `--start-date` | — | Start date (YYYY-MM-DD), overrides `--lookback` |
| `--end-date` | — | End date (YYYY-MM-DD), defaults to now |
| `-l/--lookback` | 90 | Lookback days from today |
| `--sampler` | `tpe` | Optuna sampler: `tpe`, `cma-es`, `random` |
| `--fold-stride` | 3 | Stage 2: evaluate every Nth fold (higher = faster) |
| `--seed` | from YAML or 42 | Optuna sampler seed (overrides YAML) |
| `--output` | auto-generated | Explicit output path (under `results/`) |
| `--apply` | off | Write best params back to YAML config |
| `--dry-run` | off | With `--apply`, preview YAML diff without writing |
| `--quiet` | off | Suppress progress output |
| `--log-interval` | 10 | Print progress every N trials |
| `--no-trial-history` | off | Omit per-trial history from saved JSON |

### Execution Flow

```
main(argv)
  │
  ├── 1. Parse arguments
  ├── 2. Fetch OHLCV data (fetch_multi_asset_data)
  │       └── Paginated via BinanceConnector, UTC-normalized
  ├── 3. Build configs (build_configs)
  │       ├── Load sr.yaml → SRConfigResolver → OptimizationConfig
  │       ├── Stage 1: UniverseOptimizationConfig (CLI overrides YAML)
  │       ├── Stage 2: AssetOptimizationConfig (YAML defaults + CLI overrides)
  │       │     └── quality_*, constraint_penalty_floor, seed wired from YAML
  │       └── Universe: UniverseSRConfig (reuses same raw YAML load)
  ├── 4. Validate minimum bars (stage2_config.min_bars per asset/tf)
  ├── 5. Initialize SRStatusFileWriter
  ├── 6. Run TwoStageOptimizer.optimize()
  │       ├── Stage 1 callbacks → status writer + progress printer
  │       └── Stage 2 callbacks → status writer + per-asset progress
  ├── 7. Print results table
  ├── 8. Save results JSON (auto-timestamped path)
  ├── 9. Apply to YAML if --apply (with .bak backup)
  └── 10. Exit code: 0 if accept_rate > 10%, else 1
```

### Exit Codes

| Code | Meaning |
|-|-|
| 0 | Success (>10% of Stage 2 assets accepted, or Stage 1 score > 0 when no Stage 2) |
| 1 | Failure: data fetch error, insufficient bars, optimization error, or low accept rate |

### Run Quality Criteria (Accepted vs Rejected)

CLI exit code only reflects process success. Use these criteria to decide if the optimization result should be accepted for deployment.

| Run state | Criteria | Decision |
|-|-|-|
| Accepted | Stage 1 completed and audit composite >= 0.68, with false breakout <= 0.30 | Apply to config |
| Conditionally accepted | Stage 2 shows `n_folds == 0`, but Stage 1 is strong and extended-window audit drop <= 0.03 | Apply as Stage 1-only baseline |
| Borderline | Audit composite 0.62 to 0.67, or two audit metrics borderline | Keep in candidate set, do not promote yet |
| Rejected | Audit composite < 0.62, or at least two reject-level audit metrics | Do not apply |

Recommended quick checks after each run:
1. Review Stage 2 table for `accepted`, `fallback_to_global`, and `n_folds`.
2. Run optimization-window audit.
3. Run regime-transfer audit on a wider or shifted date range.
4. Accept only if both audits remain within acceptance bands.

### Config Resolution

`build_configs()` loads YAML once and wires fields into both stages:

- **Stage 1**: `n_trials`, `timeout_s`, `parameter_space` from YAML; CLI `--n-trials`/`--timeout` override
- **Stage 2**: All `per_asset_*` fields, `quality_*` fields, `seed` sourced from YAML via `OptimizationConfig`; CLI `--stage2-n-trials`, `--stage2-timeout`, `--sampler`, `--fold-stride`, `--seed` override
- **Universe**: Full raw YAML passed as `global_config` to `UniverseSRConfig`

---

## monitor_optimization.py

Subparser CLI for inspecting and watching optimization results.

### Usage

```bash
# Show detailed results from a file
python app/sr/scripts/monitor_optimization.py show results/BTCUSDT_1h_20260429.json

# List all result files
python app/sr/scripts/monitor_optimization.py list
python app/sr/scripts/monitor_optimization.py list --sort score

# Watch live optimization progress
python app/sr/scripts/monitor_optimization.py watch
python app/sr/scripts/monitor_optimization.py watch --interval 3

# Compare two optimization runs
python app/sr/scripts/monitor_optimization.py compare run1.json run2.json
```

### Commands

#### `show <path>`

Displays detailed results from a single result JSON file.

```
================================================================
  S/R OPTIMIZATION RESULT
================================================================
  File:      results/BTCUSDT_1h_20260429.json
  Timestamp: 2026-04-29T14:32:00
  Total Time: 45.2 min (2712s)

  STAGE 1: GLOBAL
    Score:  0.7340
    Trials: 50

    Parameters:
      ensemble.structural_vs_micro_ratio: 0.520000
      kernels.order_block.displacement_atr: 1.800000
      ...

  STAGE 2: PER-ASSET
    Optimized: 3
    Accepted:  2

    Asset        TF    Train     Val Status     Folds Gates Const
    ------------ ----- ------- ------- ---------- ----- ----- -----
    BTCUSDT      1h    0.6800  0.6200 accepted       4     0     0
    ETHUSDT      1h    0.7100  0.5800 fallback       4     1     2
    SOLUSDT      1h    0.6500  0.6100 accepted       4     0     1
================================================================
```

#### `list [--sort time|score|asset]`

Lists all result files in `optimization/results/`.

| Option | Default | Description |
|-|-|-|
| `--sort` | `time` | Sort by `time` (newest first), `score` (highest first), or `asset` |

#### `watch [--interval N] [--status-file PATH]`

Live progress dashboard that polls the status JSON written by `SRStatusFileWriter`.

| Option | Default | Description |
|-|-|-|
| `--interval` | 5 | Poll interval in seconds |
| `--status-file` | `.optimization_status.json` | Path to status file |

Display includes:
- Stage 1 progress bar with trial count and best score
- Stage 2 current asset/tf and completion count
- ETA (Stage 1: based on trial rate; Stage 2: based on asset completion rate)
- Elapsed time, PID liveness check
- Terminal states: `COMPLETED` or `FAILED` with error message

**ETA calculation**:
- Uses UTC-aware timestamps from the status file
- Stage 1: `remaining_trials / (completed_trials / elapsed_seconds)` (starts after 3 trials)
- Stage 2: `remaining_assets / (completed_assets / elapsed_seconds)` (starts after 1 asset)

#### `compare <path1> <path2>`

Side-by-side comparison of two result files showing:
- Global scores with delta
- Per-asset validation scores with delta
- Global parameter diff (changed params marked with `*`)

### Helper Functions

| Function | Description |
|-|-|
| `_load_result_json(path)` | Raw JSON dict from result file |
| `_load_result_summary(path)` | Minimal fields for list view |
| `_fmt_param(v)` | Format parameter value for display |
| `_check_process_alive(pid)` | Check if optimizer PID is still running |
| `_format_duration(seconds)` | Human-readable duration string |

---

## zone_quality_audit.py

Real-data zone quality diagnostic. Runs the full S/R pipeline bar-by-bar via `MultiBarRunner` and evaluates with `ZoneQualityEvaluator`.

### Usage

```bash
# Recent 90 days
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h

# Date range
python app/sr/scripts/zone_quality_audit.py -a ETHUSDT -t 4h \
    --start-date 2025-01-01 --end-date 2026-01-01

# Custom config and bar range
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h \
    --config app/sr/config/sr.yaml --bar-range 100:500

# Lower minimum bars threshold
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h --min-bars 50
```

### CLI Flags

| Flag | Default | Description |
|-|-|-|
| `-a/--asset` | `BTCUSDT` | Trading pair (single asset) |
| `-t/--timeframe` | `1h` | Timeframe |
| `--config` | `app/sr/config/sr.yaml` | Path to sr.yaml config |
| `--start-date` | — | Start date (YYYY-MM-DD), overrides `--lookback` |
| `--end-date` | — | End date (YYYY-MM-DD), defaults to now |
| `-l/--lookback` | 90 | Lookback days from today |
| `--bar-range` | full data | Bar range as `start:end` (e.g. `100:500`) |
| `--min-bars` | 100 | Minimum bars required to run audit |
| `--quiet` | off | Suppress progress output |

### Output

```
================================================================
  S/R ZONE QUALITY AUDIT
================================================================
  Asset:     BTCUSDT
  Timeframe: 1h
  Bars:      2160

  QUALITY METRICS
    Survival Rate:       0.7400
    Touch Accuracy:      0.8200
    False Breakout Rate: 0.1800
    Strength Stability:  0.8500
    Coverage:            0.6300

  COMPOSITE SCORE:       0.7100

  ZONE STATISTICS
    Total zones created:  47
    Zones reached active: 35
    Zones broken:         8
    Zones expired:        4

  EVENT HISTOGRAM
    Touches:          128
    Breakouts:        22
    False breakouts:  4
================================================================
```

### Execution Flow

```
main(argv)
  │
  ├── 1. Fetch OHLCV data (fetch_data)
  ├── 2. Validate min_bars (configurable via --min-bars)
  ├── 3. Resolve SR config (SRConfigResolver for asset/tf)
  ├── 4. Parse bar range (optional --bar-range start:end)
  ├── 5. Run audit
  │       ├── Build SRv2Pipeline with resolved config
  │       ├── MultiBarRunner.run(df, start_bar, end_bar)
  │       ├── ZoneQualityEvaluator.evaluate(run_result)
  │       └── composite_score(metrics)
  └── 6. Print report
```

### Exit Codes

| Code | Meaning |
|-|-|
| 0 | Audit completed successfully |
| 1 | Data fetch error or insufficient bars |
| 2 | Config resolution error or invalid `--bar-range` format |

---

## smoke_test.py

Quick validation that the full v2 pipeline and universe router work end-to-end with synthetic data (no network calls).

### Usage

```bash
# Single-asset pipeline only
python -m app.sr.scripts.smoke_test

# Include universe router test
python -m app.sr.scripts.smoke_test --universe

# With debug output and timing breakdown
python -m app.sr.scripts.smoke_test --debug --timing
```

### CLI Flags

| Flag | Default | Description |
|-|-|-|
| `--universe` | off | Also run universe router smoke test |
| `--debug` | off | Enable debug mode (prints debug info keys) |
| `--timing` | off | Enable timing breakdown per pipeline stage |

### Tests Run

**Single-asset** (`run_single_asset`):
- Generates 200-bar synthetic OHLCV (GBM walk, seed=42)
- Builds `SRResolvedConfig` with `pivot_hl` + `round_number` kernels
- Runs `SRv2Pipeline` at bar_index=0
- Reports: candidates, scored levels, active zones, events, wall time
- Warns (non-fatal) if zero candidates or scored levels

**Universe** (`run_universe`, requires `--universe`):
- 3 synthetic assets (BTCUSDT, ETHUSDT, SOLUSDT) × 1h
- Builds `UniverseSRConfig` with `max_workers=1`
- Runs `UniverseSRRouter.process()` at bar_index=0
- Reports per-asset results and wall time

### Exit Codes

| Code | Meaning |
|-|-|
| 0 | All tests passed |
| 1 | One or more tests failed |

---

## _utils.py — Shared Data Utilities

Shared functions used by `run_optimization.py`, `zone_quality_audit.py`, and test files.

### Functions

#### `_ensure_utc(df)`

Normalizes DataFrame index to UTC. Localizes naive indices; converts tz-aware indices.

Called automatically by `fetch_data()` on non-empty results.

#### `_parse_date(date_str)`

Parses `YYYY-MM-DD` string to `datetime` object.

#### `_fetch_paginated(connector, symbol, interval, start_ms, end_ms, rate_limit_sleep=0.3)`

Fetches klines with auto-pagination (Binance returns max 1000 per request).

- Deduplicates by index (keeps last)
- Sorts by timestamp
- Sleeps `rate_limit_sleep` seconds between pages (configurable, default 0.3s)
- Returns empty DataFrame if no data

#### `fetch_data(asset, timeframe, lookback_days=90, start_date=None, end_date=None, quiet=False)`

High-level single-asset fetch. Two modes:
- **Date range**: `start_date` → `end_date` (or now if omitted)
- **Lookback**: Last `lookback_days` from now

Returns UTC-normalized OHLCV DataFrame via `_ensure_utc()`.

#### `fetch_multi_asset_data(assets, timeframes, ...)`

Builds `{asset: {tf: DataFrame}}` data map by calling `fetch_data()` per pair. Used by `run_optimization.py` for `TwoStageOptimizer`.

### Data Flow

```
CLI args (--start-date / --lookback)
  │
  ▼
fetch_data() or fetch_multi_asset_data()
  │
  ├── BinanceConnector.get_futures_klines()
  │     └── Paginated: max 1000 bars/request, 0.3s sleep between
  │
  ├── Deduplicate + sort
  │
  └── _ensure_utc() → UTC-normalized DataFrame
```

---

## status_writer.py — Atomic Status File

Writes an atomic JSON status file that `monitor_optimization.py watch` polls to track progress.

### Architecture

```
SRStatusFileWriter
  │
  ├── __init__()     → creates initial status file (removes stale)
  │
  ├── update_stage1(trial, best_score, best_params)
  │                  → called per Stage 1 trial
  │
  ├── start_stage2(asset, tf)
  │                  → called when Stage 2 begins for an asset/tf
  │
  ├── update_stage2(asset, tf, trial, best_score)
  │                  → called per Stage 2 trial
  │
  ├── complete_stage2(asset, tf)
  │                  → increments completed count (single-writer assumption)
  │
  ├── complete(result)
  │                  → terminal: status="completed"
  │
  └── fail(error_msg)
                     → terminal: status="failed"
```

### Write Safety

- **Atomic writes**: `tempfile.mkstemp()` + `os.replace()` — crash-safe on POSIX
- **Single-writer assumption**: `complete_stage2()` does read-modify-write (increment counter) which is not concurrency-safe. Only one optimizer process should write at a time.
- **Stale detection**: `monitor_optimization.py watch` checks PID liveness to detect stale files from crashed runs

### Status File Schema

```json
{
  "pid": 12345,
  "assets": ["BTCUSDT", "ETHUSDT"],
  "timeframes": ["1h"],
  "start_time": "2026-05-01T10:00:00+00:00",
  "last_update": "2026-05-01T10:15:00+00:00",
  "status": "running",
  "stage": "stage2",
  "stage1_trial_current": 50,
  "stage1_n_trials_target": 50,
  "stage1_best_score": 0.734,
  "stage1_best_params": {"ensemble.structural_vs_micro_ratio": 0.52},
  "stage2_asset_current": "ETHUSDT",
  "stage2_tf_current": "1h",
  "stage2_assets_completed": 1,
  "stage2_assets_total": 2,
  "error": null
}
```

Status values: `starting` → `running` → `completed` | `failed`

### File Location

`app/sr/optimization/results/.optimization_status.json`

---

## Typical Workflow

### 1. Smoke Test (validate setup)

```bash
python -m app.sr.scripts.smoke_test --universe --timing
```

### 2. Quality Audit (diagnose current config)

```bash
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h --lookback 180
```

### 3. Run Optimization

```bash
# Terminal 1: Run optimizer
python app/sr/scripts/run_optimization.py \
    -a BTCUSDT,ETHUSDT -t 1h \
    --n-trials 50 --timeout 3600

# Terminal 2: Watch progress
python app/sr/scripts/monitor_optimization.py watch --interval 3
```

### 4. Inspect Results

```bash
python app/sr/scripts/monitor_optimization.py show results/BTCUSDT_ETHUSDT_1h_20260501_100000.json
```

### 5. Compare Runs

```bash
python app/sr/scripts/monitor_optimization.py compare run1.json run2.json
```

### 6. Apply Best Params

```bash
# Preview
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \
    --n-trials 50 --apply --dry-run

# Apply (creates .bak backup)
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \
    --n-trials 50 --apply
```

### 7. Re-Audit (validate improvement)

```bash
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h --lookback 180
```

---

## Tests

| Test File | Tests | Covers |
|-|-|-|
| `test_scripts_utils.py` | 11 | `_ensure_utc`, `_parse_date`, `SRStatusFileWriter` lifecycle/atomic/fail |
| `test_run_optimization_cli.py` | 10 | `parse_args`, `build_configs`, `auto_output_path`, `main` integration (insufficient data, exit codes) |
| `test_monitor_cli.py` | 17 | `parse_args`, `cmd_show`, `cmd_list`, `cmd_compare`, `cmd_watch`, `_format_duration`, `_check_process_alive` |
| `test_zone_quality_audit_cli.py` | 5 | `parse_args`, `main` integration (insufficient data, synthetic audit with full report) |

Test patterns:
- **CLI parsing**: Verify defaults and overrides for all flags
- **Integration**: Mock `fetch_data` / `fetch_multi_asset_data`, feed synthetic OHLCV, verify exit codes and report content
- **Status writer**: Lifecycle (init → update → complete), atomic write safety, fail state
- **Monitor helpers**: Duration formatting, PID liveness, result loading
