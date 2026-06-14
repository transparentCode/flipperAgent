# `portfolio_app` Architecture Metadata

This folder documents the current validated portfolio analytics and recommendation shape.

## Files

- `catalog.yaml` — machine-readable portfolio metadata
- `overview.d2` — app/component relationship map
- `io.d2` — focused contracts, queues, and persistence view
- this file — scope and rendering notes

## Scope

This slice reflects the current validated portfolio behavior:

- per-asset fill consumption from execution streams
- mark-to-market updates from signal price streams
- shared portfolio state restore across workers
- transactional closed-trade and equity-curve persistence
- portfolio observability and analytics routes
- recommendation-only rebalance policy surface
- Timescale-backed portfolio performance history

## Key Contract Split

- portfolio consumes runtime market/execution streams:
  - `fills:{symbol}`
  - `price_update:{symbol}:{timeframe}`
- portfolio persists its own analytics state in TimescaleDB:
  - `portfolio_equity_curve`
  - `portfolio_closed_trades`
  - `portfolio_processed_fills`
- portfolio does not own canonical lifecycle or control-plane Valkey state

## Rendering

If `d2` is installed locally:

```bash
d2 docs/architecture/portfolio_app/overview.d2 docs/architecture/portfolio_app/overview.svg
d2 docs/architecture/portfolio_app/io.d2 docs/architecture/portfolio_app/io.svg
```

Or use:

```bash
./scripts/render_d2.sh docs/architecture/portfolio_app/overview.d2
./scripts/render_d2.sh docs/architecture/portfolio_app/io.d2
```
