"""Loss-safe multiplexed Binance websocket delivery for ingestion."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import LiveStreamInterrupted
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_WAKE_SENTINEL = object()


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _require_positive_duration(value: object, *, field_name: str) -> timedelta:
    if not isinstance(value, timedelta):
        raise TypeError(f"{field_name} must be a timedelta")
    if value <= timedelta(0):
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_queue_maxsize(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("queue_maxsize must be an integer")
    if value <= 0:
        raise ValueError("queue_maxsize must be positive")
    return value


def _utc_from_milliseconds(value: object, *, field_name: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataIngestionError(
            f"Binance websocket {field_name} must be integer milliseconds"
        )
    try:
        milliseconds = int(value)
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance websocket {field_name} is not a valid timestamp"
        ) from exc


def _decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance websocket {field_name} is not a valid Decimal"
        ) from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"Binance websocket {field_name} must be finite")
    return parsed


def _same_live_observation(
    first: CandleObservation,
    second: CandleObservation,
) -> bool:
    return (
        first.lane == second.lane
        and first.provider_id == second.provider_id
        and first.provider_symbol == second.provider_symbol
        and first.transport == second.transport
        and first.open_time == second.open_time
        and first.close_time == second.close_time
        and first.open == second.open
        and first.high == second.high
        and first.low == second.low
        and first.close == second.close
        and first.volume == second.volume
        and first.taker_buy_base == second.taker_buy_base
        and first.provider_close_time == second.provider_close_time
        and first.provider_event_id == second.provider_event_id
    )


def _build_recovery_requests(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    interruption_time: datetime,
    timeframe_duration: timedelta,
    alignment_origin: datetime,
    reason: str,
) -> tuple[RecoveryRequest, ...]:
    recovery_until = aligned_bucket_start(
        interruption_time,
        timeframe_duration,
        alignment_origin,
    )
    requests: list[RecoveryRequest] = []
    ordered_routes = sorted(
        routes.values(),
        key=lambda route: (
            route[0].venue,
            route[0].instrument_id,
            route[0].timeframe,
        ),
    )
    for lane, _provider_symbol in ordered_routes:
        recovery_since = last_consumed_close.get(lane, connection_anchor)
        if recovery_since < recovery_until:
            requests.append(
                RecoveryRequest(
                    lane=lane,
                    since=recovery_since,
                    until=recovery_until,
                    reason=reason,
                )
            )
    return tuple(requests)


class BinanceWebSocketManager:
    """Own one multiplexed Binance websocket and deliver closed candles."""

    provider_id = "binance_native"

    def __init__(
        self,
        *,
        stream_url: str,
        queue_maxsize: int,
        client_factory: Callable[..., Any] = UMFuturesWebsocketClient,
        observability: IngestionObservability | None = None,
    ) -> None:
        stream_url = _require_non_empty_string(stream_url, field_name="stream_url")
        if not stream_url.startswith("wss://"):
            raise ValueError("stream_url must use wss://")
        if not callable(client_factory):
            raise TypeError("client_factory must be callable")
        self.stream_url = stream_url
        self.queue_maxsize = _require_queue_maxsize(queue_maxsize)
        self.client_factory = client_factory
        self.observability = observability or IngestionObservability()
        self._ever_connected = False

    @staticmethod
    def _validate_subscriptions(
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> dict[str, tuple[MarketLane, str]]:
        if not isinstance(subscriptions, Mapping):
            raise TypeError("subscriptions must be a mapping")
        if not subscriptions:
            raise ValueError("subscriptions must not be empty")
        _require_non_empty_string(base_timeframe, field_name="base_timeframe")
        _require_positive_duration(
            timeframe_duration,
            field_name="timeframe_duration",
        )
        _require_utc(alignment_origin, field_name="alignment_origin")
        _require_utc(connection_anchor, field_name="connection_anchor")
        if (
            aligned_bucket_start(
                connection_anchor,
                timeframe_duration,
                alignment_origin,
            )
            != connection_anchor
        ):
            raise ValueError("connection_anchor must align to the base grid")

        routes: dict[str, tuple[MarketLane, str]] = {}
        for lane, provider_symbol in subscriptions.items():
            if not isinstance(lane, MarketLane):
                raise TypeError("subscription keys must be MarketLane instances")
            if lane.timeframe != base_timeframe:
                raise ValueError(
                    f"live lane timeframe '{lane.timeframe}' must equal "
                    f"base_timeframe '{base_timeframe}'"
                )
            _require_non_empty_string(
                provider_symbol,
                field_name="provider_symbol",
            )
            normalized_symbol = provider_symbol.casefold()
            if normalized_symbol in routes:
                raise ValueError(
                    f"duplicate normalized provider symbol '{provider_symbol}'"
                )
            routes[normalized_symbol] = (lane, provider_symbol)
        return routes

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        routes = self._validate_subscriptions(
            subscriptions,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )
        return self._stream_closed_candles(
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )

    def _parse_message(
        self,
        raw_message: object,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
    ) -> CandleObservation | None:
        if isinstance(raw_message, (str, bytes, bytearray)):
            try:
                payload = json.loads(raw_message)
            except (TypeError, ValueError) as exc:
                raise DataIngestionError(
                    "Binance websocket returned invalid JSON"
                ) from exc
        else:
            payload = raw_message

        if not isinstance(payload, Mapping):
            raise DataIngestionError("Binance websocket payload must be a mapping")

        if "data" not in payload:
            if "result" in payload and "id" in payload:
                return None
            raise DataIngestionError("Binance websocket payload is missing data")

        stream_name = payload.get("stream")
        data = payload.get("data")
        if not isinstance(stream_name, str) or not stream_name.strip():
            raise DataIngestionError("Binance websocket stream name is malformed")
        if not isinstance(data, Mapping):
            raise DataIngestionError("Binance websocket data is malformed")
        if data.get("e") != "kline":
            raise DataIngestionError("Binance websocket event is not a kline")

        kline = data.get("k")
        if not isinstance(kline, Mapping):
            raise DataIngestionError("Binance websocket kline is malformed")

        raw_symbol = kline.get("s")
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise DataIngestionError("Binance websocket kline symbol is malformed")
        route = routes.get(raw_symbol.casefold())
        if route is None:
            raise DataIngestionError(
                f"Binance websocket returned unknown symbol '{raw_symbol}'"
            )
        lane, provider_symbol = route
        expected_stream = (
            f"{provider_symbol.lower()}@kline_{base_timeframe}"
        ).casefold()
        if stream_name.casefold() != expected_stream:
            raise DataIngestionError(
                f"Binance websocket stream '{stream_name}' does not match "
                f"configured symbol '{provider_symbol}'"
            )

        if kline.get("i") != base_timeframe:
            raise DataIngestionError(
                "Binance websocket interval does not match base timeframe"
            )
        closed = kline.get("x")
        if not isinstance(closed, bool):
            raise DataIngestionError(
                "Binance websocket kline close flag must be a boolean"
            )
        if not closed:
            return None

        open_time = _utc_from_milliseconds(
            kline.get("t"),
            field_name="open timestamp",
        )
        provider_close_time = _utc_from_milliseconds(
            kline.get("T"),
            field_name="close timestamp",
        ) + timedelta(milliseconds=1)
        close_time = open_time + timeframe_duration
        if provider_close_time != close_time:
            raise DataIngestionError(
                "Binance websocket provider close timestamp disagrees with "
                "timeframe_duration"
            )
        if (
            aligned_bucket_start(open_time, timeframe_duration, alignment_origin)
            != open_time
        ):
            raise DataIngestionError(
                "Binance websocket open timestamp is not base-grid aligned"
            )

        try:
            observation = CandleObservation(
                lane=lane,
                provider_id=self.provider_id,
                provider_symbol=provider_symbol,
                transport="websocket",
                open_time=open_time,
                close_time=close_time,
                open=_decimal_value(kline.get("o"), field_name="open"),
                high=_decimal_value(kline.get("h"), field_name="high"),
                low=_decimal_value(kline.get("l"), field_name="low"),
                close=_decimal_value(kline.get("c"), field_name="close"),
                volume=_decimal_value(kline.get("v"), field_name="volume"),
                taker_buy_base=_decimal_value(
                    kline.get("V"),
                    field_name="taker_buy_base",
                ),
                received_at=datetime.now(UTC),
                provider_close_time=provider_close_time,
                provider_event_id=None,
            )
        except (TypeError, ValueError) as exc:
            raise DataIngestionError(
                "Binance websocket returned invalid candle values"
            ) from exc
        return observation

    async def _stream_closed_candles(
        self,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self.queue_maxsize)
        last_consumed_close: dict[MarketLane, datetime] = {}
        last_consumed_observation: dict[MarketLane, CandleObservation] = {}
        failure: LiveStreamInterrupted | None = None
        intentional_stop = False
        stream_finished = False
        client: Any | None = None

        def recovery_requests(reason: str) -> tuple[RecoveryRequest, ...]:
            return _build_recovery_requests(
                routes=routes,
                last_consumed_close=last_consumed_close,
                connection_anchor=connection_anchor,
                interruption_time=datetime.now(UTC),
                timeframe_duration=timeframe_duration,
                alignment_origin=alignment_origin,
                reason=reason,
            )

        def wake_consumer() -> None:
            try:
                queue.put_nowait(_WAKE_SENTINEL)
                self.observability.set_queue_utilization(
                    queue.qsize(),
                    self.queue_maxsize,
                )
            except asyncio.QueueFull:
                pass

        def interrupt(reason: str, detail: str | None = None) -> None:
            nonlocal failure
            if intentional_stop or stream_finished or failure is not None:
                return
            failure = LiveStreamInterrupted(
                reason=reason,
                recovery_requests=recovery_requests(reason),
            )
            self.observability.record_websocket_interruption()
            self.observability.set_websocket_connected(False)
            if detail:
                _LOGGER.warning(
                    "Binance live websocket interrupted: reason=%s detail=%s",
                    reason,
                    detail,
                )
            else:
                _LOGGER.warning(
                    "Binance live websocket interrupted: reason=%s",
                    reason,
                )
            wake_consumer()

        def schedule(callback: Callable[..., None], *args: object) -> None:
            if stream_finished:
                return
            try:
                loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                pass

        def handle_message(raw_message: object) -> None:
            if failure is not None or stream_finished:
                return
            try:
                observation = self._parse_message(
                    raw_message,
                    routes=routes,
                    base_timeframe=base_timeframe,
                    timeframe_duration=timeframe_duration,
                    alignment_origin=alignment_origin,
                )
            except (
                DataIngestionError,
                KeyError,
                IndexError,
                OverflowError,
                TypeError,
                ValueError,
            ) as exc:
                interrupt("websocket_malformed_payload", str(exc))
                return
            if observation is None:
                return
            try:
                queue.put_nowait(observation)
                self.observability.set_queue_utilization(
                    queue.qsize(),
                    self.queue_maxsize,
                )
            except asyncio.QueueFull:
                interrupt(
                    "websocket_queue_overflow",
                    "finalized candle queue is full",
                )

        def handle_close() -> None:
            interrupt("websocket_disconnected")

        def handle_error(error: object) -> None:
            interrupt("websocket_error", str(error))

        def on_open(_websocket: object, *_args: object) -> None:
            return None

        def on_message(_websocket: object, raw_message: object) -> None:
            schedule(handle_message, raw_message)

        def on_close(_websocket: object, *_args: object) -> None:
            schedule(handle_close)

        def on_error(_websocket: object, error: object, *_args: object) -> None:
            schedule(handle_error, error)

        stream_names = sorted(
            f"{provider_symbol.lower()}@kline_{base_timeframe}"
            for _normalized_symbol, (_lane, provider_symbol) in routes.items()
        )

        try:
            try:
                client = await asyncio.to_thread(
                    self.client_factory,
                    stream_url=self.stream_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_close=on_close,
                    on_error=on_error,
                    is_combined=True,
                )
                await asyncio.to_thread(client.subscribe, stream_names)
                if self._ever_connected:
                    self.observability.record_websocket_reconnect()
                self._ever_connected = True
                self.observability.set_websocket_connected(True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK failures must become typed interruptions
                interrupt("websocket_error", str(exc))

            while True:
                if failure is not None:
                    raise failure
                item = await queue.get()
                self.observability.set_queue_utilization(
                    queue.qsize(),
                    self.queue_maxsize,
                )
                if failure is not None:
                    raise failure
                if item is _WAKE_SENTINEL:
                    continue

                observation = item
                if not isinstance(observation, CandleObservation):
                    interrupt(
                        "websocket_malformed_payload",
                        "internal queue contained an invalid item",
                    )
                    raise failure

                previous = last_consumed_observation.get(observation.lane)
                if previous is None:
                    if observation.close_time <= connection_anchor:
                        continue
                    if observation.open_time < connection_anchor:
                        interrupt(
                            "websocket_malformed_payload",
                            "older out-of-order candle preceded live progress",
                        )
                        raise failure
                    if observation.open_time != connection_anchor:
                        interrupt(
                            "websocket_gap_detected",
                            "first live candle did not begin at the connection anchor",
                        )
                        raise failure
                elif _same_live_observation(observation, previous):
                    continue
                elif observation.open_time < previous.close_time:
                    interrupt(
                        "websocket_malformed_payload",
                        "older out-of-order finalized candle received",
                    )
                    raise failure
                elif observation.open_time > previous.close_time:
                    interrupt(
                        "websocket_gap_detected",
                        "finalized live candle gap detected",
                    )
                    raise failure

                yield observation
                last_consumed_close[observation.lane] = observation.close_time
                last_consumed_observation[observation.lane] = observation
        finally:
            stream_finished = True
            intentional_stop = True
            self.observability.set_websocket_connected(False)
            self.observability.set_queue_utilization(
                queue.qsize(),
                self.queue_maxsize,
            )
            if client is not None:
                try:
                    await asyncio.to_thread(client.stop)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - cleanup must not mask stream outcome
                    _LOGGER.warning(
                        "Binance live websocket cleanup failed: %s",
                        exc,
                    )


__all__ = ["BinanceWebSocketManager"]
