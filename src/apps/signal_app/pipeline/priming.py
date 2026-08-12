from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

HistoricalBars = Sequence[tuple[float, ...]]
HistoricalFetcher = Callable[[str, str, int], Awaitable[HistoricalBars]]


class StartupPrimer:
    def __init__(self, fetcher: HistoricalFetcher) -> None:
        self.fetcher = fetcher

    async def fetch_history(
        self,
        asset: str,
        timeframe: str,
        lookback: int,
    ) -> list[tuple[float, ...]]:
        history = await self.fetcher(asset, timeframe, lookback)
        return list(history)
