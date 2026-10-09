"""TradingView frame codec and message parsing. Pure: no I/O, no clock.

A WebSocket message carries one or more frames ``~m~<len>~m~<payload>``. A
payload is a JSON object (the server hello has no ``m`` key, every other
message has ``m`` and ``p``) or a heartbeat ``~h~<n>`` that must be echoed back.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.bars import RawBar
from apps.scraper_app.domain.errors import ScraperError

SERIES_ID = "sds_1"
SYMBOL_ID = "sds_sym_1"
AUTH_TOKEN = "unauthorized_user_token"

_FRAME_HEAD = re.compile(r"~m~(\d+)~m~")


@dataclass(frozen=True, slots=True)
class Message:
    """One decoded frame payload."""

    payload: str
    heartbeat: bool
    body: Any  # parsed JSON for non-heartbeat payloads, else None

    @property
    def method(self) -> str | None:
        if isinstance(self.body, dict):
            method = self.body.get("m")
            return method if isinstance(method, str) else None
        return None

    @property
    def params(self) -> list[Any]:
        if isinstance(self.body, dict) and isinstance(self.body.get("p"), list):
            return self.body["p"]
        return []


def encode_frame(payload: str) -> str:
    return f"~m~{len(payload)}~m~{payload}"


def encode_message(method: str, params: list[Any]) -> str:
    return encode_frame(json.dumps({"m": method, "p": params}))


def split_frames(raw: str) -> list[str]:
    """Split one WebSocket message into frame payloads; malformed input raises."""
    payloads: list[str] = []
    pos = 0
    while pos < len(raw):
        head = _FRAME_HEAD.match(raw, pos)
        if head is None:
            raise ScraperError(
                errors.PROTOCOL_ERROR, f"malformed frame header at {pos}"
            )
        start = head.end()
        end = start + int(head.group(1))
        if end > len(raw):
            raise ScraperError(errors.PROTOCOL_ERROR, "frame length exceeds message")
        payloads.append(raw[start:end])
        pos = end
    return payloads


def parse_payload(payload: str) -> Message:
    if payload.startswith("~h~"):
        return Message(payload=payload, heartbeat=True, body=None)
    try:
        # Decimal keeps the provider's exact text; NaN/Infinity stay detectable.
        body = json.loads(payload, parse_float=Decimal, parse_constant=Decimal)
    except ValueError as exc:
        raise ScraperError(
            errors.PROTOCOL_ERROR, f"payload is not JSON: {exc}"
        ) from exc
    return Message(payload=payload, heartbeat=False, body=body)


def decode_message(raw: str) -> list[Message]:
    return [parse_payload(payload) for payload in split_frames(raw)]


def heartbeat_reply(message: Message) -> str:
    """Heartbeats are echoed back unchanged."""
    return encode_frame(message.payload)


def resolve_symbol_param(request_symbol: str) -> str:
    return "=" + json.dumps(
        {"symbol": request_symbol, "adjustment": "splits", "session": "extended"},
        separators=(",", ":"),
    )


def build_requests(
    session: str, request_symbol: str, resolution: str, n_bars: int
) -> list[str]:
    """The four requests, in the order the server expects them."""
    return [
        encode_message("set_auth_token", [AUTH_TOKEN]),
        encode_message("chart_create_session", [session, ""]),
        encode_message(
            "resolve_symbol",
            [session, SYMBOL_ID, resolve_symbol_param(request_symbol)],
        ),
        encode_message(
            "create_series",
            [session, SERIES_ID, "s1", SYMBOL_ID, resolution, n_bars, ""],
        ),
    ]


@dataclass(frozen=True, slots=True)
class SeriesResult:
    """A complete exchange: resolved name, provider time, ascending unique bars."""

    pro_name: str
    provider_time: int
    bars: tuple[RawBar, ...]


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ScraperError(errors.PROTOCOL_ERROR, f"non-numeric bar value: {value!r}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ScraperError(errors.PROTOCOL_ERROR, f"bad bar value: {value!r}") from exc


def _raw_bar(values: Any) -> RawBar:
    if not isinstance(values, list) or not values:
        raise ScraperError(errors.PROTOCOL_ERROR, "bar values are not a list")
    numbers = [_to_decimal(v) for v in values]
    time = numbers[0]
    if not time.is_finite() or time != time.to_integral_value():
        raise ScraperError(
            errors.PROTOCOL_ERROR, f"bar time is not whole seconds: {time}"
        )
    return RawBar(time=int(time), fields=tuple(numbers[1:]))


class SeriesAccumulator:
    """Folds server messages into one :class:`SeriesResult`.

    An error frame raises at once. ``result`` returns only a complete exchange.
    """

    def __init__(self) -> None:
        self.provider_time: int | None = None
        self.pro_name: str | None = None
        self.completed = False
        self._bars: dict[int, RawBar] = {}

    def feed(self, message: Message) -> None:
        if message.heartbeat:
            return
        method = message.method
        if method is None:
            self._feed_hello(message.body)
        elif method == "symbol_error":
            raise ScraperError(errors.SYMBOL_ERROR, _detail(message.params))
        elif method == "series_error":
            raise ScraperError(errors.SERIES_ERROR, _detail(message.params))
        elif method in ("critical_error", "protocol_error"):
            raise ScraperError(
                errors.PROTOCOL_ERROR, f"{method}: {_detail(message.params)}"
            )
        elif method == "symbol_resolved":
            self._feed_resolved(message.params)
        elif method == "timescale_update":
            self._feed_bars(message.params)
        elif method == "series_completed":
            params = message.params
            if len(params) > 1 and params[1] == SERIES_ID:
                self.completed = True

    def _feed_hello(self, body: Any) -> None:
        if self.provider_time is not None or not isinstance(body, dict):
            return
        stamp = body.get("timestamp")
        if isinstance(stamp, int) and not isinstance(stamp, bool):
            self.provider_time = stamp

    def _feed_resolved(self, params: list[Any]) -> None:
        if len(params) < 3 or params[1] != SYMBOL_ID or not isinstance(params[2], dict):
            return
        name = params[2].get("pro_name")
        if not isinstance(name, str) or not name:
            raise ScraperError(
                errors.PROTOCOL_ERROR, "symbol_resolved without pro_name"
            )
        self.pro_name = name

    def _feed_bars(self, params: list[Any]) -> None:
        if len(params) < 2 or not isinstance(params[1], dict):
            return
        series = params[1].get(SERIES_ID)
        if not isinstance(series, dict):
            return
        points = series.get("s")
        if not isinstance(points, list):
            raise ScraperError(errors.PROTOCOL_ERROR, "timescale_update without bars")
        for point in points:
            if not isinstance(point, dict):
                raise ScraperError(errors.PROTOCOL_ERROR, "bar entry is not an object")
            bar = _raw_bar(point.get("v"))
            self._bars[bar.time] = bar  # same time again: the last one wins

    def result(self) -> SeriesResult:
        if self.pro_name is None or not self.completed:
            raise ScraperError(
                errors.INCOMPLETE,
                f"resolved={self.pro_name is not None} completed={self.completed} "
                f"bars={len(self._bars)}",
            )
        if not self._bars:
            raise ScraperError(errors.EMPTY, "series completed without bars")
        if self.provider_time is None:
            raise ScraperError(
                errors.PROTOCOL_ERROR, "server hello carried no timestamp"
            )
        return SeriesResult(
            pro_name=self.pro_name,
            provider_time=self.provider_time,
            bars=tuple(self._bars[t] for t in sorted(self._bars)),
        )


def _detail(params: list[Any]) -> str:
    return " ".join(str(p) for p in params[1:])[:200]


__all__ = [
    "AUTH_TOKEN",
    "SERIES_ID",
    "SYMBOL_ID",
    "Message",
    "SeriesAccumulator",
    "SeriesResult",
    "build_requests",
    "decode_message",
    "encode_frame",
    "encode_message",
    "heartbeat_reply",
    "parse_payload",
    "resolve_symbol_param",
    "split_frames",
]
