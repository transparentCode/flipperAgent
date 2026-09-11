"""Provider contracts for ingestion."""

from .base import HistoricalCandleProvider, LiveCandleProvider

__all__ = ["HistoricalCandleProvider", "LiveCandleProvider"]
