# Lightpanda CDP testing for CoinGlass

This folder is an isolated prototype for benchmarking CoinGlass heatmap extraction
against a `Lightpanda` CDP server.

It intentionally does **not** change the production scraper in
`src/apps/coinglass_scraper/interceptor.py`.

## What it does

- reuses the working `CoinGlassHeatmapInterceptor` extraction logic
- swaps browser bootstrap to `connect_over_cdp(...)`
- attaches Patchright to a running Lightpanda browser
- supports one-shot probing and Chromium-vs-Lightpanda benchmarking

## Files

- `cdp_interceptor.py` — `LightpandaCDPHeatmapInterceptor`
- `run_lightpanda_probe.py` — one-shot attachment/probe script
- `run_browser_benchmarks.py` — Chromium vs Lightpanda benchmark runner

## Example usage

Print the default launch command:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.lightpanda_testing.run_lightpanda_probe \
  --print-default-launch-command
```

Probe a running Lightpanda endpoint:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.lightpanda_testing.run_lightpanda_probe \
  --endpoint-url ws://127.0.0.1:9222
```

Launch Lightpanda and probe CoinGlass:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.lightpanda_testing.run_lightpanda_probe \
  --launch-command "lightpanda serve --host 127.0.0.1 --port 9222"
```

Run Chromium vs Lightpanda benchmarks:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.lightpanda_testing.run_browser_benchmarks \
  --lightpanda-launch-command "lightpanda serve --host 127.0.0.1 --port 9222"
```
