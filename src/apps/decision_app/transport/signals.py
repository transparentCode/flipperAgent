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
from libs.common.signal_authority import (
    SignalAuthorityStore,
    SignalRouteAuthority,
    signal_route_from_stream,
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
        authority_store: SignalAuthorityStore | None = None,
        authority_records: Mapping[str, SignalRouteAuthority] | None = None,
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
        if authority_store is not None and not isinstance(
            authority_store, SignalAuthorityStore
        ):
            raise TypeError("authority_store must be SignalAuthorityStore or None")
        self._authority_store = authority_store
        if authority_records is not None:
            if any(
                not isinstance(record, SignalRouteAuthority)
                for record in authority_records.values()
            ):
                raise TypeError("authority_records must contain authority records")
            self._authority_records = dict(authority_records)
        else:
            self._authority_records = {}

    async def publish(
        self,
        envelope: SignalPublicationEnvelope,
    ) -> SignalPublicationAck:
        if not isinstance(envelope, SignalPublicationEnvelope):
            raise TypeError("envelope must be SignalPublicationEnvelope")
        required_id = _entry_id(envelope.stream_entry_id)
        route = None
        if self._authority_store is not None:
            route = signal_route_from_stream(envelope.stream_key)
        fields = valkey_encode(envelope.signal)
        authority_record = None
        if route is not None and self._authority_store.manages(route):
            authority_record = self._authority_records.get(route)
            if authority_record is None:
                return self._ack(
                    envelope,
                    "FAILED",
                    "managed Decision route has no captured authority record",
                )
            try:
                effect_cutoff_ms = int(required_id.split("-", 1)[0])
            except (TypeError, ValueError) as exc:
                raise SignalTransportError(
                    "managed Decision stream ID must be epoch-millisecond-0"
                ) from exc
            if effect_cutoff_ms <= authority_record.boundary_ms:
                return self._ack(
                    envelope,
                    "FAILED",
                    "Decision effect cutoff is not after captured authority boundary",
                )
            try:
                guarded = await self._authority_store.guarded_exact_xadd(
                    route=route,
                    expected_owner="decision",
                    expected_epoch=authority_record.epoch,
                    expected_boundary_ms=authority_record.boundary_ms,
                    effect_cutoff_ms=effect_cutoff_ms,
                    stream_key=envelope.stream_key,
                    fields=fields,
                    stream_id=required_id,
                    maxlen=self._stream_maxlen,
                    approximate=self._stream_approximate,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return await self._reconcile_managed_failure(
                    envelope,
                    route=route,
                    authority_record=authority_record,
                    effect_cutoff_ms=effect_cutoff_ms,
                    required_id=required_id,
                    reason=f"authority-guarded XADD failure: {exc}",
                )
            if not guarded.allowed:
                return self._ack(
                    envelope,
                    "FAILED",
                    guarded.reason or "Decision authority denied",
                )
            if guarded.outcome == "EXISTING":
                if guarded.existing_fields is None or guarded.stream_id is None:
                    raise SignalTransportError("existing guarded signal is incomplete")
                return self._ack_for_existing(
                    envelope, (guarded.stream_id, guarded.existing_fields)
                )
            if guarded.outcome == "CONFLICT":
                return self._ack(
                    envelope,
                    "CONFLICT",
                    guarded.reason or "stream head advanced past required explicit ID",
                )
            if guarded.stream_id != required_id:
                return self._ack(
                    envelope,
                    "CONFLICT",
                    "Valkey returned a different explicit stream ID",
                )
            return self._ack(envelope, "PUBLISHED", None)

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

        try:
            returned_id = await self._client.xadd(
                envelope.stream_key,
                fields,
                id=required_id,
                maxlen=self._stream_maxlen,
                approximate=self._stream_approximate,
            )
            if returned_id is None:
                raise SignalTransportError("authority-guarded XADD returned no ID")
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

    async def _reconcile_managed_failure(
        self,
        envelope: SignalPublicationEnvelope,
        *,
        route: str,
        authority_record: SignalRouteAuthority,
        effect_cutoff_ms: int,
        required_id: str,
        reason: str,
    ) -> SignalPublicationAck:
        try:
            guarded = await self._authority_store.guarded_exact_lookup(  # type: ignore[union-attr]
                route=route,
                expected_owner="decision",
                expected_epoch=authority_record.epoch,
                expected_boundary_ms=authority_record.boundary_ms,
                effect_cutoff_ms=effect_cutoff_ms,
                stream_key=envelope.stream_key,
                stream_id=required_id,
            )
        except Exception as exc:  # noqa: BLE001
            return self._ack(
                envelope, "FAILED", f"{reason}; reconciliation failed: {exc}"
            )
        if not guarded.allowed:
            return self._ack(
                envelope,
                "FAILED",
                guarded.reason or "Decision authority denied during reconciliation",
            )
        if guarded.outcome == "EXISTING":
            if guarded.existing_fields is None or guarded.stream_id is None:
                return self._ack(
                    envelope, "FAILED", "existing guarded signal is incomplete"
                )
            return self._ack_for_existing(
                envelope, (guarded.stream_id, guarded.existing_fields)
            )
        if guarded.outcome == "CONFLICT":
            return self._ack(
                envelope,
                "CONFLICT",
                guarded.reason or "stream head advanced past required explicit ID",
            )
        return self._ack(envelope, "FAILED", reason)

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
