"""W3C trace context propagation through Valkey stream payloads."""

from __future__ import annotations

from typing import Any

from opentelemetry import context
from opentelemetry.propagate import get_global_textmap
from opentelemetry.propagators.textmap import Getter, Setter

# Keys used in Valkey flat-map payloads to carry the traceparent header.
# Underscore-prefixed to avoid collision with Pydantic model fields.
TRACEPARENT_KEY = "_traceparent"
TRACESTATE_KEY = "_tracestate"


class DictSetter(Setter):
    def set(self, carrier: dict[str, Any], key: str, value: str) -> None:
        carrier[key] = value


class DictGetter(Getter):
    def get(self, carrier: dict[str, Any], key: str) -> list[str] | None:
        val = carrier.get(key)
        if val is None:
            return None
        return [val]

    def keys(self, carrier: dict[str, Any]) -> list[str]:
        return list(carrier.keys())


_setter = DictSetter()
_getter = DictGetter()


def inject_trace_context(payload: dict[str, str]) -> dict[str, str]:
    """Inject current span's trace context into a Valkey payload dict.

    Adds ``_traceparent`` (and optionally ``_tracestate``) keys.
    Safe to call even if no active span — will be a no-op.
    """
    get_global_textmap().inject(
        carrier=payload,
        setter=_setter,
    )
    # The propagator writes "traceparent" / "tracestate" keys.
    # Rename to underscore-prefixed to avoid collisions with model fields.
    if "traceparent" in payload:
        payload[TRACEPARENT_KEY] = payload.pop("traceparent")
    if "tracestate" in payload:
        payload[TRACESTATE_KEY] = payload.pop("tracestate")
    return payload


def extract_trace_context(payload: dict[str, str]) -> context.Context:
    """Extract trace context from a Valkey payload dict.

    Returns an OTel Context that should be used as the parent for new spans.
    """
    # Rename underscore-prefixed keys back to standard names for the propagator
    carrier: dict[str, str] = {}
    if TRACEPARENT_KEY in payload:
        carrier["traceparent"] = payload[TRACEPARENT_KEY]
    if TRACESTATE_KEY in payload:
        carrier["tracestate"] = payload[TRACESTATE_KEY]
    return get_global_textmap().extract(
        carrier=carrier,
        getter=_getter,
    )
