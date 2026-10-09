"""Helpers for the CoinGlass lane tests: fixtures, settings, a fake CDP engine."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

from apps.scraper_app.domain.payloads import HeatmapExpect, PayloadSpec
from apps.scraper_app.settings import CoinGlassSettings

_quiet = logging.getLogger("fake.cdp.engine")
_quiet.setLevel(logging.INFO)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "coinglass"
HEATMAP_IDS = ("1429", "1432", "1436")
COLUMNS = 12
HEATMAP_ENDPOINT = "/api/index/v5/liqHeatMap"
MAXPAIN_ENDPOINT = "/api/liqHeatMap/list"
LIQMAP_ENDPOINT = "/api/index/5/liqMap"


def heatmap_text(name: str = "1429") -> str:
    return (FIXTURE_DIR / f"heatmap_btc_{name}_compact.json").read_text()


def full_heatmap_text() -> str:
    return gzip.decompress(
        (FIXTURE_DIR / "heatmap_btc_1429_full.json.gz").read_bytes()
    ).decode()


def liqmap_text(coin: str = "btc") -> str:
    return (FIXTURE_DIR / f"liqmap_{coin}.json").read_text()


def liqmap_spec(**overrides: Any) -> PayloadSpec:
    base: dict[str, Any] = {
        "id": "cg.btc.liqmap",
        "kind": "liq_map",
        "endpoint": LIQMAP_ENDPOINT,
        "args": {
            "merge": True,
            "symbol": "Binance_BTCUSDT",
            "interval": 1,
            "limit": 1500,
        },
        "requires_login": True,
        "expect": HeatmapExpect("Binance", "BTCUSDT"),
    }
    base.update(overrides)
    return PayloadSpec(**base)


def maxpain_text() -> str:
    return (FIXTURE_DIR / "maxpain_24h_4coins.json").read_text()


def update_time(name: str) -> datetime:
    data = json.loads(heatmap_text(name))["data"]
    return datetime.fromtimestamp(data["updateTime"] / 1000, tz=UTC)


def heatmap_spec(**overrides: Any) -> PayloadSpec:
    base: dict[str, Any] = {
        "id": "cg.btc.heatmap",
        "kind": "liq_heatmap",
        "endpoint": HEATMAP_ENDPOINT,
        "args": {"symbol": "Binance_BTCUSDT", "interval": 5, "limit": 288},
        "expect": HeatmapExpect("Binance", "BTCUSDT", 300, COLUMNS),
    }
    base.update(overrides)
    return PayloadSpec(**base)


def maxpain_spec(**overrides: Any) -> PayloadSpec:
    base: dict[str, Any] = {
        "id": "cg.maxpain",
        "kind": "max_pain",
        "endpoint": MAXPAIN_ENDPOINT,
        "args": {"range": "24h"},
        "coins": ("BTC", "ETH", "SOL", "BNB"),
    }
    base.update(overrides)
    return PayloadSpec(**base)


def coinglass_raw(engine_url: str = "http://127.0.0.1:9", **overrides: Any) -> dict:
    raw: dict[str, Any] = {
        "engine_url": engine_url,
        "host_page_url": "https://www.coinglass.com/pro/futures/LiquidationHeatMapNew",
        "slot_minutes": [5, 20, 35, 50],
        "slot_second": 10,
        "wake_check_seconds": 30,
        "connect_timeout_seconds": 1,
        "command_timeout_seconds": 0.5,
        "navigation_timeout_seconds": 2,
        "helper_timeout_seconds": 0.5,
        "cycle_deadline_seconds": 6,
        "call_spacing_seconds": 0,
        "max_payload_bytes": 5_000_000,
        "max_provider_age_seconds": 900,
        "readiness": {"max_read_age_seconds": 2400},
        "datasets": [
            {
                "id": "cg.btc.heatmap",
                "kind": "liq_heatmap",
                "endpoint": HEATMAP_ENDPOINT,
                "args": {"symbol": "Binance_BTCUSDT", "interval": 5, "limit": 288},
                "expect": {
                    "exchange": "Binance",
                    "instrument": "BTCUSDT",
                    "interval_seconds": 300,
                    "columns": COLUMNS,
                },
            },
            {
                "id": "cg.maxpain",
                "kind": "max_pain",
                "endpoint": MAXPAIN_ENDPOINT,
                "args": {"range": "24h"},
                "coins": ["BTC", "ETH", "SOL", "BNB"],
            },
        ],
    }
    raw.update(overrides)
    return raw


def coinglass_settings(
    engine_url: str = "http://127.0.0.1:9", **overrides: Any
) -> CoinGlassSettings:
    return CoinGlassSettings.model_validate(coinglass_raw(engine_url, **overrides))


def default_helper(params: dict[str, Any]) -> dict[str, Any]:
    if params["endpoint"] == HEATMAP_ENDPOINT:
        text = heatmap_text()
    elif params["endpoint"] == LIQMAP_ENDPOINT:
        text = liqmap_text()
    else:
        text = maxpain_text()
    return {"text": text, "module": "89390", "export": "EJf", "sourceLength": 90}


class FakeEngine:
    """An in-process CDP engine on a real local socket."""

    def __init__(
        self, helper: Callable[[dict[str, Any]], Any] = default_helper
    ) -> None:
        self.helper = helper
        self.targets: list[str] = []
        self.closed: list[str] = []
        self.received: list[dict[str, Any]] = []
        self.cookie_batches: list[list[dict[str, Any]]] = []
        self.hang: set[str] = set()  # methods that never get an answer
        self.die_on: set[str] = set()  # methods that close the socket instead
        self.errors: dict[str, str] = {}  # method -> error message
        self.huge_reply: str | None = None
        self.port = 0
        self._server = None
        self._counter = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self, port: int = 0) -> FakeEngine:
        from websockets.asyncio.server import serve

        def process_request(connection, request):
            if request.path == "/json/version":
                body = json.dumps(
                    {
                        "webSocketDebuggerUrl": f"ws://0.0.0.0:{self.port}/devtools/browser/x"
                    }
                ).encode()
                return connection.respond(HTTPStatus.OK, body.decode())
            return None

        self._server = await serve(
            self._handle,
            "127.0.0.1",
            port,
            process_request=process_request,
            max_size=None,
            logger=_quiet,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, ws) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            method = msg["method"]
            self.received.append(msg)
            key = method
            if (
                method == "Runtime.evaluate"
                and "endpoint" in msg["params"]["expression"]
            ):
                key = "helper"  # only the helper call, not the readiness poll
            if key in self.die_on:
                await ws.close()
                return
            if key in self.hang:
                continue
            reply: dict[str, Any] = {"id": msg["id"]}
            if method in self.errors:
                reply["error"] = {"code": -32000, "message": self.errors[method]}
            else:
                reply["result"] = self._result(method, msg.get("params", {}))
            await ws.send(
                self.huge_reply
                if self.huge_reply and key == "helper"
                else json.dumps(reply)
            )

    def _result(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "Target.getTargets":
            return {
                "targetInfos": [{"targetId": t, "type": "page"} for t in self.targets]
            }
        if method == "Target.closeTarget":
            self.closed.append(params["targetId"])
            if params["targetId"] in self.targets:
                self.targets.remove(params["targetId"])
            return {"success": True}
        if method == "Target.createTarget":
            self._counter += 1
            target = f"new-{self._counter}"
            self.targets.append(target)
            return {"targetId": target}
        if method == "Target.attachToTarget":
            return {"sessionId": "session-1"}
        if method == "Network.setCookies":
            self.cookie_batches.append(params["cookies"])
            return {}
        if method == "Runtime.evaluate":
            expression = params["expression"].strip()
            if "document.readyState" in expression and "endpoint" not in expression:
                return {"result": {"type": "boolean", "value": True}}
            helper_params = json.loads(expression[expression.rindex("})(") + 3 : -1])
            value = self.helper(helper_params)
            return {"result": {"type": "object", "value": value}}
        return {}


def stringify(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


async def eventually(predicate: Callable[[], bool], seconds: float = 10.0) -> None:
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)
