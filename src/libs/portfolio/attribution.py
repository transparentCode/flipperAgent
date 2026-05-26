"""PnLAttributor — break down PnL by asset, model, or timeframe."""

from __future__ import annotations

from typing import Literal

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ClosedTrade, PnLAttribution

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)

GroupByDimension = Literal["asset", "model", "timeframe"]

_GROUP_KEY_MAP = {
    "asset": lambda t: t.asset,
    "model": lambda t: t.source_model,
    "timeframe": lambda t: t.source_timeframe,
}


def attribute_pnl(
    trades: list[ClosedTrade],
    group_by: GroupByDimension,
) -> list[PnLAttribution]:
    """Group closed trades by dimension and compute per-group PnL stats.

    Returns a list of PnLAttribution, one per unique group key,
    sorted descending by total_pnl.
    """
    if not trades:
        return []

    key_fn = _GROUP_KEY_MAP[group_by]

    # Group trades
    groups: dict[str, list[ClosedTrade]] = {}
    for t in trades:
        key = key_fn(t) or "(unknown)"
        groups.setdefault(key, []).append(t)

    total_pnl_all = sum(t.realized_pnl for t in trades)

    result: list[PnLAttribution] = []
    for group_key, group_trades in groups.items():
        wins = [t for t in group_trades if t.realized_pnl > 0]
        losses = [t for t in group_trades if t.realized_pnl <= 0]
        group_total_pnl = sum(t.realized_pnl for t in group_trades)

        pnl_pct = (
            (group_total_pnl / total_pnl_all * 100)
            if total_pnl_all != 0
            else 0.0
        )

        result.append(PnLAttribution(
            group_key=group_key,
            group_type=group_by,
            total_pnl=group_total_pnl,
            trade_count=len(group_trades),
            win_count=len(wins),
            loss_count=len(losses),
            avg_pnl=group_total_pnl / len(group_trades),
            max_win=max((t.realized_pnl for t in wins), default=0.0),
            max_loss=min((t.realized_pnl for t in losses), default=0.0),
            pnl_pct_of_total=pnl_pct,
        ))

    result.sort(key=lambda a: a.total_pnl, reverse=True)
    return result
