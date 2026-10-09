"""Shared helpers for the v2 collector tests: fixtures, fake transport, fake clock."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from apps.scraper_app.adapters.tradingview import protocol
from apps.scraper_app.adapters.tradingview.client import TransportClosed
from apps.scraper_app.domain.bars import RawBar
from apps.scraper_app.domain.datasets import DatasetSpec, Shape
from apps.scraper_app.settings import (
    ScheduleSettings,
    TradingViewSettings,
    parse_settings,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tradingview"
REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION = "cs_fixture000001"


async def require_test_database(connection) -> None:
    """Database-gated tests truncate tables and reset a role password: refuse real stores."""
    name = await connection.fetchval("SELECT current_database()")
    if not str(name).endswith("_test"):
        import pytest

        pytest.fail(
            f"refusing to run against database {name!r}: its name must end with '_test'",
            pytrace=False,
        )


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def make_spec(**overrides: object) -> DatasetSpec:
    base: dict[str, object] = {
        "id": "t.index.1h",
        "request_symbol": "CRYPTOCAP:TOTAL3",
        "canonical_symbol": "CRYPTOCAP:TOTAL3",
        "interval": "1h",
        "shape": Shape.OHLCV,
        "contiguous": True,
        "non_negative": True,
        "finality_horizon_seconds": 86400,
        "revision_watch_seconds": 172800,
    }
    base.update(overrides)
    return DatasetSpec(**base)  # type: ignore[arg-type]


def tv_settings(**overrides: object) -> TradingViewSettings:
    base: dict[str, object] = {
        "ws_url": "wss://example.invalid/socket",
        "origin": "https://example.invalid",
        "connect_timeout_seconds": 1,
        "read_deadline_seconds": 5,
        "max_response_bytes": 20_000_000,
        "request_spacing_seconds": 1.0,
        "max_attempts_per_slot": 3,
        "retry_backoff_seconds": (5, 20),
        "min_bars_per_request": 10,
        "max_bars_per_request": 5000,
    }
    base.update(overrides)
    return TradingViewSettings(**base)  # type: ignore[arg-type]


def schedule_settings(**overrides: object) -> ScheduleSettings:
    base: dict[str, object] = {
        "slot_minutes": (0,),
        "slot_second": 30,
        "late_bar_retries": 3,
        "late_bar_retry_seconds": 20,
        "wake_check_seconds": 30,
    }
    base.update(overrides)
    return ScheduleSettings(**base)  # type: ignore[arg-type]


def production_settings():
    import yaml

    raw = yaml.safe_load((REPO_ROOT / "configs" / "scraper.yaml").read_text())
    return parse_settings(raw["scraper"])


def dec(text: str | float) -> Decimal:
    return Decimal(str(text))


def ohlcv_fields(seed: int, *, volume: bool = True) -> tuple[Decimal, ...]:
    base = 100 + seed
    values = [dec(base), dec(base + 5), dec(base - 5), dec(base + 1)]
    if volume:
        values.append(dec(1000 + seed))
    return tuple(values)


def raw_bars(
    first_open: datetime,
    count: int,
    step_seconds: int = 3600,
    *,
    volume: bool = True,
) -> list[RawBar]:
    start = epoch(first_open)
    return [
        RawBar(time=start + i * step_seconds, fields=ohlcv_fields(i, volume=volume))
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Wire-format builders
# ---------------------------------------------------------------------------


def _num(value: Decimal) -> str:
    return format(value, "f")


def hello_message(provider_time: int) -> str:
    body = json.dumps(
        {"session_id": "x", "timestamp": provider_time, "protocol": "json"}
    )
    return protocol.encode_frame(body)


def synth_exchange(
    *,
    pro_name: str,
    provider_time: int,
    bars: list[RawBar],
    completed: bool = True,
    resolved: bool = True,
    session: str = SESSION,
) -> list[str]:
    """WebSocket messages shaped like a recorded exchange."""
    messages = [hello_message(provider_time)]
    frames = [
        protocol.encode_frame(
            json.dumps(
                {"m": "series_loading", "p": [session, protocol.SERIES_ID, "s1"]}
            )
        )
    ]
    if resolved:
        frames.append(
            protocol.encode_frame(
                json.dumps(
                    {
                        "m": "symbol_resolved",
                        "p": [session, protocol.SYMBOL_ID, {"pro_name": pro_name}],
                    }
                )
            )
        )
    points = ",".join(
        f'{{"i":{i},"v":[{bar.time}.0,{",".join(_num(f) for f in bar.fields)}]}}'
        for i, bar in enumerate(bars)
    )
    frames.append(
        protocol.encode_frame(
            f'{{"m":"timescale_update","p":["{session}",{{"sds_1":{{"s":[{points}],"t":"s1"}}}}]}}'
        )
    )
    if completed:
        frames.append(
            protocol.encode_frame(
                json.dumps(
                    {
                        "m": "series_completed",
                        "p": [session, protocol.SERIES_ID, "streaming", "s1"],
                    }
                )
            )
        )
    messages.append("".join(frames))
    return messages


# ---------------------------------------------------------------------------
# Fake transports
# ---------------------------------------------------------------------------


class ReplayTransport:
    """Replays recorded WebSocket messages; records what the client sent."""

    def __init__(
        self,
        received: list[str],
        *,
        hang_after: bool = False,
        close_after_oversize: bool = False,
    ) -> None:
        self._queue = list(received)
        self._hang_after = hang_after
        self._oversize = close_after_oversize
        self.sent: list[str] = []
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        if self._queue:
            return self._queue.pop(0)
        if self._hang_after:
            import asyncio

            await asyncio.Event().wait()
        raise TransportClosed("replay exhausted", oversize=self._oversize)

    async def close(self) -> None:
        self.closed = True


def connector_for(transport: ReplayTransport):
    async def connect() -> ReplayTransport:
        return transport

    return connect


class ProviderTransport:
    """Answers one exchange from the request it receives.

    ``answer(request_symbol, resolution, n_bars)`` returns the messages to play
    back (or raises). Every created transport is appended to ``provider.opened``.
    """

    def __init__(self, answer: Callable[[str, str, int], list[str]]) -> None:
        self._answer = answer
        self._queue: list[str] = []
        self._symbol = ""
        self.sent: list[str] = []
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(text)
        for message in protocol.decode_message(text):
            if message.method == "resolve_symbol":
                spec = message.params[2]
                self._symbol = json.loads(spec[1:])["symbol"]
            elif message.method == "create_series":
                params = message.params
                self._queue = list(
                    self._answer(self._symbol, params[4], int(params[5]))
                )

    async def recv(self) -> str:
        if not self._queue:
            raise TransportClosed("provider has nothing more to say")
        return self._queue.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeProvider:
    """A deterministic synthetic TradingView for whole-pass tests."""

    def __init__(self, specs: list[DatasetSpec], now: Callable[[], datetime]) -> None:
        self._by_request = {(s.request_symbol, s.resolution): s for s in specs}
        self._now = now
        self.opened: list[ProviderTransport] = []
        self.requests: list[tuple[str, str, int]] = []
        self.revisions: dict[tuple[str, int], tuple[Decimal, ...]] = {}
        self.pro_name_overrides: dict[str, str] = {}
        self.fail_symbols: set[str] = set()
        self.omit_after: dict[str, int] = {}  # symbol -> newest bar time it may serve
        self.skip_newest_closed: set[str] = set()
        self.history_limit: int | None = None
        self.skip_times: set[int] = set()

    def connector(self):
        async def connect() -> ProviderTransport:
            transport = ProviderTransport(self._answer)
            self.opened.append(transport)
            return transport

        return connect

    def _answer(self, symbol: str, resolution: str, n_bars: int) -> list[str]:
        self.requests.append((symbol, resolution, n_bars))
        spec = self._by_request[(symbol, resolution)]
        if symbol in self.fail_symbols:
            return [
                hello_message(epoch(self._now())),
                protocol.encode_frame(
                    json.dumps(
                        {
                            "m": "symbol_error",
                            "p": [SESSION, "sds_sym_1", "invalid symbol"],
                        }
                    )
                ),
            ]
        step = spec.interval_seconds
        now = epoch(self._now())
        forming = now - now % step
        newest = forming
        if symbol in self.omit_after:
            newest = min(newest, self.omit_after[symbol])
        if self.history_limit is not None:
            n_bars = min(n_bars, self.history_limit)
        times = [newest - i * step for i in range(n_bars)][::-1]
        times = [t for t in times if t not in self.skip_times]
        if symbol in self.skip_newest_closed:
            times = [t for t in times if t != forming - step]
        bars = []
        for t in times:
            fields = self.revisions.get((symbol, t)) or self.fields_at(spec, t)
            bars.append(RawBar(time=t, fields=fields))
        pro_name = self.pro_name_overrides.get(symbol, spec.canonical_symbol)
        return synth_exchange(pro_name=pro_name, provider_time=now, bars=bars)

    @staticmethod
    def fields_at(spec: DatasetSpec, time: int) -> tuple[Decimal, ...]:
        seed = (time // spec.interval_seconds) % 997
        return ohlcv_fields(seed, volume=spec.shape is Shape.OHLCV)


class FakeClock:
    """Mutable UTC clock; ``sleep`` advances it instead of waiting."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def make_bar(bar_open: datetime, seed: int = 0, *, interval_seconds: int = 3600):
    from apps.scraper_app.domain.bars import Bar, content_hash

    o, h, low, c, v = ohlcv_fields(seed)
    return Bar(
        bar_open=bar_open,
        bar_close=bar_open + timedelta(seconds=interval_seconds),
        open=o,
        high=h,
        low=low,
        close=c,
        volume=v,
        content_hash=content_hash(o, h, low, c, v),
    )
