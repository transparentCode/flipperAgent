"""Standard metric instruments for flipperAgent apps."""

from __future__ import annotations

from opentelemetry import metrics


def create_app_metrics(meter: metrics.Meter, app_name: str) -> dict:
    """Create standard RED metrics + stream-specific gauges.

    Returns a dict of instrument references keyed by name.
    """
    return {
        # Rate
        "messages_processed": meter.create_counter(
            f"{app_name}.messages.processed_total",
            description=f"Total messages processed by {app_name}",
        ),
        # Errors
        "messages_errored": meter.create_counter(
            f"{app_name}.messages.error_total",
            description=f"Total processing errors in {app_name}",
        ),
        # Duration
        "message_duration": meter.create_histogram(
            f"{app_name}.message.duration_ms",
            description=f"Message processing duration in {app_name}",
            unit="ms",
        ),
    }


def create_stream_lag_callback(redis_client, stream_key: str, group_name: str):
    """Return an async callback that reads XPENDING to report stream lag."""

    async def _observe(options):
        try:
            info = await redis_client.xpending(stream_key, group_name)
            # info[0] = count of pending messages
            pending_count = info[0] if info else 0
            return [
                metrics.Observation(
                    pending_count,
                    {"stream": stream_key, "group": group_name},
                )
            ]
        except Exception:
            return []

    return _observe
