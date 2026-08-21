# Ingestion → Decision pipeline observability

This dashboard uses the existing OpenTelemetry Collector, Prometheus, Tempo,
Loki, and Grafana stack. It adds no service, storage, or event contract.

## Data path

```text
Timescale canonical candles
        ↓
ingestion.outbox
        ↓
Valkey ingestion streams
        ↓
Decision DirectCursorInput
        ↓
Decision lanes
        ↓
watermarks and finalization
```

Ingestion metrics describe canonical commits, websocket state, durable outbox
publication, and recovery. Decision metrics describe the bounded input reader,
lane evaluation, publication, rebuilds, and current service state.

## Decision lag

Decision lag is measured in closed intervals, not wall-clock age. For each
timeframe, the runtime uses `TimeframeGrid.expected_closed_cutoff()` at the
observation time and compares it with the latest accepted canonical market
cutoff or lane watermark. The value is the number of complete timeframe
intervals behind, never a raw timestamp difference. A 4-hour lane therefore
does not appear four times later than a 1-hour lane merely because its wall
clock is different.

The gauges are replaced when a new Decision generation is installed. Retired
lanes and input series therefore disappear from the dashboard instead of
remaining as stale time series.

## Input outcomes and latency

`decision.input.records_total` records every bounded reader disposition:
`INSERTED`, `DUPLICATE`, `ALREADY_REPRESENTED`,
`RECONSTRUCTION_REQUIRED`, `CONFLICT`, and `MALFORMED`.

Input latency is measured at the Decision acceptance boundary. Market latency
is the elapsed time from the bar market cutoff to acceptance. Canonical-event
latency is the elapsed time from the outbox event's `occurred_at` timestamp to
acceptance. The dashboard's steady-state percentile panels filter to
`outcome="INSERTED"`.

## Why there is no consumer lag or PEL metric

Decision uses bounded direct `XREAD` cursors, not a consumer group. It has no
Decision-side PEL, ACK, or pending-message backlog to expose. The relevant
operational signals are closed-interval input lag, lane watermark lag, blocked
inputs, input dispositions, and finalization/publication outcomes.

The existing ingestion outbox pending gauge remains an ingestion durability
signal; it is not reused as a Decision consumer-lag metric.

## Health and interpretation

The alert health configuration probes Decision `/health/ready`. A `ready`
response is healthy. Recovery and rebuild states are valid operational states;
the alert does not require every lane to be LIVE at every instant. A degraded
Decision service remains observable and alert-worthy through the same health
system.

Metric labels are intentionally bounded to `lane`, `asset`, `timeframe`,
`outcome`, and `state`. Event IDs, stream IDs, timestamps, trace IDs, candle
IDs, generation UUIDs, and model-specific values are never metric labels.
