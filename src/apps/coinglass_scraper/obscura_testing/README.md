# Obscura CDP Testing

This folder is an isolated prototype for running the CoinGlass scraper against an
external CDP-compatible browser, starting with `Obscura`.

It does **not** replace the main Chromium-based scraper in
`src/apps/coinglass_scraper/interceptor.py`.

## What it uses

- existing CoinGlass scraping logic from `apps.coinglass_scraper.interceptor`
- `patchright` as the client
- `connect_over_cdp(...)` instead of `chromium.launch(...)`

## Files

- `cdp_interceptor.py` — CDP-attached interceptor subclass
- `run_obscura_probe.py` — one-shot CLI probe for local testing

## Expected flow

1. Start Obscura with a CDP endpoint.
2. Attach via `patchright.chromium.connect_over_cdp(...)`.
3. Inject CoinGlass cookies.
4. Run the same runtime-helper extraction used by the working scraper.

## Example

Print a default Obscura launch command:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.obscura_testing.run_obscura_probe \
  --print-default-launch-command
```

If Obscura is already running on port `9222`:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.obscura_testing.run_obscura_probe \
  --endpoint-url http://127.0.0.1:9222 \
  --coin SOL \
  --exchange Binance \
  --symbol SOLUSDT \
  --short-name SOL
```

If you want the probe to launch Obscura itself:

```bash
PYTHONPATH=src .venv/bin/python -m apps.coinglass_scraper.obscura_testing.run_obscura_probe \
  --launch-command "obscura serve --host 127.0.0.1 --port 9222"
```

## Notes

- This path assumes the browser exposes a Chromium-compatible CDP endpoint.
- If `browser.new_context(...)` is not supported by the remote browser, the code
  falls back to the first existing context.
- This is intended for feasibility/perf testing, not production routing yet.
