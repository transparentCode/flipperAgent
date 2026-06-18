from __future__ import annotations

from apps.signal_app.models import SignalPair


class StaticSignalPairCatalog:
    def __init__(self, pairs: list[SignalPair]) -> None:
        self._pairs = list(pairs)

    def list_pairs(self) -> list[SignalPair]:
        return list(self._pairs)

    def get_pair(self, asset: str, timeframe: str) -> SignalPair | None:
        normalized = SignalPair(asset=asset, timeframe=timeframe)
        for pair in self._pairs:
            if pair.key == normalized.key or (
                pair.asset == normalized.asset and pair.timeframe == normalized.timeframe
            ):
                return pair
        return None
