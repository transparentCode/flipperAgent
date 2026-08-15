"""Exact-ID Valkey signal publication for the bounded D9B primitive."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from apps.decision_app.transport.live_input import (
    compare_stream_ids,
    normalize_stream_id,
)
from apps.decision_app.transport.publication import (
    SignalPublicationAck,
    SignalPublicationEnvelope,
    signal_payload_fingerprint,
)
from libs.contracts.serialization import valkey_decode, valkey_encode
from libs.contracts.signal import TradeSignal


class SignalTransportError(ValueError):
    """Raised when the D9B signal transport contract cannot be trusted."""


def _entry_id(value: object) -> str:
    try:
        return normalize_stream_id(value)
    except (TypeError, ValueError) as exc:
        raise SignalTransportError(f"invalid Valkey stream entry ID: {exc}") from exc


def _entry_parts(entry: object) -> tuple[str, Mapping[object, object]]:
    if not isinstance(entry, Sequence) or len(entry) != 2:
        raise SignalTransportError("Valkey stream entry must be an ID/fields pair")
    stream_id = _entry_id(entry[0])
    fields = entry[1]
    if not isinstance(fields, Mapping):
        raise SignalTransportError("Valkey stream entry fields must be a mapping")
    return stream_id, fields


class ValkeySignalPublisher:
    """Publish one D8 envelope using an explicit market-time stream ID."""

    def __init__(
        self,
        client: Any,
        *,
        stream_maxlen: int = 1000,
        stream_approximate: bool = True,
    ) -> None:
        if client is None:
            raise TypeError("client is required")
        for name in ("xrange", "xrevrange", "xadd"):
            if not callable(getattr(client, name, None)):
                raise TypeError(f"client must provide {name}()")
        if isinstance(stream_maxlen, bool) or not isinstance(stream_maxlen, int):
            raise TypeError("stream_maxlen must be an integer")
        if stream_maxlen <= 0:
            raise ValueError("stream_maxlen must be positive")
        if not isinstance(stream_approximate, bool):
            raise TypeError("stream_approximate must be bool")
        self._client = client
        self._stream_maxlen = stream_maxlen
        self._stream_approximate = stream_approximate

    async def publish(
        self,
        envelope: SignalPublicationEnvelope,
    ) -> SignalPublicationAck:
        if not isinstance(envelope, SignalPublicationEnvelope):
            raise TypeError("envelope must be SignalPublicationEnvelope")
        required_id = _entry_id(envelope.stream_entry_id)
        existing = await self._exact_entry(envelope.stream_key, required_id)
        if existing is not None:
            return self._ack_for_existing(envelope, existing)
        head = await self._stream_head(envelope.stream_key)
        if head is not None and compare_stream_ids(head, required_id) > 0:
            return self._ack(
                envelope,
                "CONFLICT",
                "stream head advanced past required explicit ID",
            )

        fields = valkey_encode(envelope.signal)
        try:
            returned_id = await self._client.xadd(
                envelope.stream_key,
                fields,
                id=required_id,
                maxlen=self._stream_maxlen,
                approximate=self._stream_approximate,
            )
            if _entry_id(returned_id) != required_id:
                return self._ack(
                    envelope,
                    "CONFLICT",
                    "Valkey returned a different explicit stream ID",
                )
            return self._ack(envelope, "PUBLISHED", None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # XADD is ambiguous: the server may have committed before the
            # client observed the exception.  Reconcile by exact ID first.
            existing = await self._exact_entry(envelope.stream_key, required_id)
            if existing is not None:
                return self._ack_for_existing(envelope, existing)
            head = await self._stream_head(envelope.stream_key)
            if head is not None and compare_stream_ids(head, required_id) > 0:
                return self._ack(
                    envelope,
                    "CONFLICT",
                    "stream head advanced past required explicit ID",
                )
            return self._ack(envelope, "FAILED", f"ambiguous XADD failure: {exc}")

    async def _exact_entry(
        self,
        stream_key: str,
        required_id: str,
    ) -> tuple[str, Mapping[object, object]] | None:
        raw = await self._client.xrange(stream_key, required_id, required_id)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise SignalTransportError("XRANGE result must be a sequence")
        for entry in raw:
            entry_id, fields = _entry_parts(entry)
            if entry_id == required_id:
                return entry_id, fields
        return None

    async def _stream_head(self, stream_key: str) -> str | None:
        raw = await self._client.xrevrange(stream_key, "+", "-", count=1)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise SignalTransportError("XREVRANGE result must be a sequence")
        return _entry_parts(raw[0])[0]

    def _ack_for_existing(
        self,
        envelope: SignalPublicationEnvelope,
        entry: tuple[str, Mapping[object, object]],
    ) -> SignalPublicationAck:
        entry_id, fields = entry
        try:
            signal = valkey_decode(dict(fields), TradeSignal)
            identical = (
                signal_payload_fingerprint(signal) == envelope.payload_fingerprint
                and signal.idempotency_key == envelope.signal.idempotency_key
            )
        except Exception:  # noqa: BLE001
            identical = False
        if identical:
            return self._ack(envelope, "ALREADY_IDENTICAL", None)
        return self._ack(
            envelope,
            "CONFLICT",
            f"existing entry {entry_id} has different or undecodable signal",
        )

    @staticmethod
    def _ack(
        envelope: SignalPublicationEnvelope,
        outcome: str,
        reason: str | None,
    ) -> SignalPublicationAck:
        return SignalPublicationAck(
            decision_id=envelope.decision_id,
            stream_key=envelope.stream_key,
            stream_entry_id=envelope.stream_entry_id,
            payload_fingerprint=envelope.payload_fingerprint,
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
        )


__all__ = ["SignalTransportError", "ValkeySignalPublisher"]
