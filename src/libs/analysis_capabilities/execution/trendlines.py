"""Thin execution adapter for the canonical Trendlines model."""

from dataclasses import dataclass

from libs.models.trendlines import (
    TrendlineBar,
    TrendlineSnapshot,
    analyze_trendlines,
)


@dataclass(frozen=True, slots=True)
class TrendlinesExecutionRequest:
    """The native ordered closed-bar input for one Trendlines analysis."""

    history: tuple[TrendlineBar, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.history, tuple):
            raise TypeError("history must be a tuple of TrendlineBar values")
        if any(not isinstance(bar, TrendlineBar) for bar in self.history):
            raise TypeError("history must contain only TrendlineBar values")


def execute_trendlines(request: TrendlinesExecutionRequest) -> TrendlineSnapshot:
    """Run the canonical Trendlines facade without changing its input."""

    if not isinstance(request, TrendlinesExecutionRequest):
        raise TypeError("request must be TrendlinesExecutionRequest")
    return analyze_trendlines(request.history)


__all__ = ("TrendlinesExecutionRequest", "execute_trendlines")
