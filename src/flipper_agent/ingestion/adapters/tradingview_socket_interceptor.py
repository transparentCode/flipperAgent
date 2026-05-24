from flipper_agent.commons.config import ConfigManager
config_manager = ConfigManager()

import json
import asyncio
import pandas as pd
from typing import Optional

from scrapling import StealthyFetcher
from flipper_agent.ingestion.adapters.base import BaseExchangeAdapter
from flipper_agent.commons.logging.logger_utils import bind_logger
from flipper_agent.commons.enums import SystemComponent
from flipper_agent.commons.exceptions import DataIngestionError
from flipper_agent.ingestion.constants import (
    OHLCV_COLUMNS,
    TV_CHART_URL_TEMPLATE,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

class TradingViewInterceptor(BaseExchangeAdapter):
    def __init__(self, cookies_path: str = config_manager.get("ingestion.tradingview.cookies_path", "secrets/tv_cookies.json")):
        self.cookies_path = cookies_path

    async def _load_cookies(self, fetcher: StealthyFetcher):
        try:
            with open(self.cookies_path, 'r') as f:
                cookies = json.load(f)
                fetcher.browser.contexts[0].add_cookies(cookies)
        except FileNotFoundError:
            pass

    async def get_historical_ohlcv(self, symbol: str, timeframe: str, since: int = None, limit: int = None) -> pd.DataFrame:
        target_columns = OHLCV_COLUMNS
        empty_df = pd.DataFrame(columns=target_columns)

        StealthyFetcher.configure(headless=True)
        fetcher = StealthyFetcher()
        page = fetcher.page
        await self._load_cookies(fetcher)
        
        intercepted_data = []
        background_tasks = set()
        
        async def handle_ws_frame(frame):
            try:
                payload = frame.text
                if not payload:
                    return
                if "~m~" in payload:
                    parts = payload.split("~m~")
                    if len(parts) > 2:
                        data = json.loads(parts[2])
                        if isinstance(data, dict) and data.get("m") in ["timescale_update", "du"]:
                            p = data.get("p", [])
                            if len(p) > 1 and isinstance(p[1], dict):
                                series = p[1].get("s", [])
                                for t in series:
                                    if "v" in t:
                                        v = t["v"]
                                        if len(v) >= 6:
                                            intercepted_data.append({
                                                'timestamp': v[0],
                                                'open': v[1],
                                                'high': v[2],
                                                'low': v[3],
                                                'close': v[4],
                                                'volume': v[5]
                                            })
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Error parsing websocket frame: {e}")

        def on_frame_received(frame):
            task = asyncio.create_task(handle_ws_frame(frame))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

        def on_websocket(ws):
            ws.on("framereceived", on_frame_received)

        page.on("websocket", on_websocket)
        
        url = TV_CHART_URL_TEMPLATE.format(symbol=symbol)
        await page.goto(url)
        await asyncio.sleep(config_manager.get("ingestion.tradingview.load_sleep_seconds", 5))
        
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        
        if not intercepted_data:
            return empty_df
        
        df = pd.DataFrame(intercepted_data)
        return df[target_columns]
