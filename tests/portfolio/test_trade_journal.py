"""Tests for libs/portfolio/trade_journal.py — mock DB."""

import pytest

from libs.contracts.schemas import ClosedTrade, TradeJournalEntry
from libs.portfolio.trade_journal import TradeJournal


# ---------------------------------------------------------------------------
# Fake async connection / pool for testing
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Dict-like object that supports both key-access and index-access."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeConnection:
    """In-memory async connection mock with basic query tracking."""

    def __init__(self):
        self.executed: list[tuple] = []
        self.fetch_results: list = []
        self.fetchrow_results: list = []

    async def fetch(self, query, *args):
        self.executed.append(("fetch", query, args))
        return self.fetch_results

    async def fetchrow(self, query, *args):
        self.executed.append(("fetchrow", query, args))
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))


class FakePool:
    """Fake asyncpg pool that returns a FakeConnection."""

    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireContext(self._conn)


class _FakeAcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _make_trade_row(**overrides) -> FakeRecord:
    defaults = dict(
        trade_id="t1",
        asset="BTCUSDT",
        direction=1,
        entry_price=100.0,
        exit_price=110.0,
        size=1.0,
        realized_pnl=10.0,
        realized_pnl_pct=10.0,
        commission_total=0.1,
        slippage_bps=1.5,
        entry_timestamp=1000.0,
        exit_timestamp=2000.0,
        duration_seconds=1000.0,
        source_model="TestModel",
        source_timeframe="1h",
        entry_order_id="o1",
        exit_order_id="o2",
        mae_pct=2.5,
        mfe_pct=12.0,
    )
    defaults.update(overrides)
    return FakeRecord(defaults)


# ---------------------------------------------------------------------------
# get_closed_trades
# ---------------------------------------------------------------------------

class TestGetClosedTrades:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        result = await journal.get_closed_trades()
        assert result == []

    @pytest.mark.asyncio
    async def test_maps_rows_to_closed_trades(self):
        conn = FakeConnection()
        conn.fetch_results = [_make_trade_row()]
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        result = await journal.get_closed_trades()
        assert len(result) == 1
        assert isinstance(result[0], ClosedTrade)
        assert result[0].trade_id == "t1"
        assert result[0].realized_pnl == 10.0
        assert result[0].mae_pct == 2.5

    @pytest.mark.asyncio
    async def test_filters_generate_parameterized_query(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        await journal.get_closed_trades(asset="BTCUSDT", model="TestModel")
        # Should have executed a fetch with params
        assert len(conn.executed) == 1
        op, query, args = conn.executed[0]
        assert op == "fetch"
        assert "asset = $1" in query
        assert "source_model = $2" in query
        assert args[0] == "BTCUSDT"
        assert args[1] == "TestModel"

    @pytest.mark.asyncio
    async def test_limit_and_offset(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        await journal.get_closed_trades(limit=50, offset=10)
        _, query, args = conn.executed[0]
        assert "LIMIT" in query
        assert "OFFSET" in query
        # limit=50, offset=10 should be at the end of args
        assert 50 in args
        assert 10 in args


# ---------------------------------------------------------------------------
# get_trade_count
# ---------------------------------------------------------------------------

class TestGetTradeCount:
    @pytest.mark.asyncio
    async def test_returns_count(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 42})]
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        count = await journal.get_trade_count()
        assert count == 42

    @pytest.mark.asyncio
    async def test_filters_applied(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 5})]
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        count = await journal.get_trade_count(asset="ETHUSDT")
        _, query, args = conn.executed[0]
        assert "asset = $1" in query
        assert args[0] == "ETHUSDT"
        assert count == 5


# ---------------------------------------------------------------------------
# save_closed_trade
# ---------------------------------------------------------------------------

class TestSaveClosedTrade:
    @pytest.mark.asyncio
    async def test_executes_insert(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        trade = ClosedTrade(
            trade_id="t1",
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            exit_price=110.0,
            size=1.0,
            realized_pnl=10.0,
            realized_pnl_pct=10.0,
            entry_timestamp=1000.0,
            exit_timestamp=2000.0,
            duration_seconds=1000.0,
        )
        await journal.save_closed_trade(trade)

        assert len(conn.executed) == 1
        op, query, args = conn.executed[0]
        assert op == "execute"
        assert "ON CONFLICT (trade_id) DO NOTHING" in query
        assert args[0] == "t1"


# ---------------------------------------------------------------------------
# get_journal_entries
# ---------------------------------------------------------------------------

class TestGetJournalEntries:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_trades(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        result = await journal.get_journal_entries()
        assert result == []

    @pytest.mark.asyncio
    async def test_enriches_with_equity(self):
        conn = FakeConnection()
        conn.fetch_results = [_make_trade_row()]
        # Equity lookups: entry equity, exit equity, entry drawdown
        conn.fetchrow_results = [
            FakeRecord({"equity": 10000.0}),
            FakeRecord({"equity": 10500.0}),
            FakeRecord({"drawdown_pct": 3.5}),
        ]
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        result = await journal.get_journal_entries()
        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, TradeJournalEntry)
        assert entry.equity_at_entry == 10000.0
        assert entry.equity_at_exit == 10500.0
        assert entry.drawdown_at_entry_pct == 3.5
        assert entry.risk_reward_achieved > 0

    @pytest.mark.asyncio
    async def test_missing_snapshots_default_to_zero(self):
        conn = FakeConnection()
        conn.fetch_results = [_make_trade_row()]
        conn.fetchrow_results = []  # No snapshots
        pool = FakePool(conn)
        journal = TradeJournal(pool)

        result = await journal.get_journal_entries()
        assert result[0].equity_at_entry == 0.0
        assert result[0].equity_at_exit == 0.0
        assert result[0].drawdown_at_entry_pct == 0.0


# ---------------------------------------------------------------------------
# _compute_risk_reward
# ---------------------------------------------------------------------------

class TestComputeRiskReward:
    def test_positive_pnl(self):
        trade = ClosedTrade(
            trade_id="t1", asset="BTC", direction=1,
            entry_price=100.0, exit_price=110.0, size=1.0,
            realized_pnl=10.0, realized_pnl_pct=10.0,
            entry_timestamp=0, exit_timestamp=100, duration_seconds=100,
        )
        rr = TradeJournal._compute_risk_reward(trade)
        # risk_taken = 100*1*0.02 = 2.0, rr = 10/2 = 5.0
        assert rr == pytest.approx(5.0)

    def test_zero_entry_price(self):
        trade = ClosedTrade(
            trade_id="t1", asset="BTC", direction=1,
            entry_price=0.0, exit_price=0.0, size=1.0,
            realized_pnl=0.0, realized_pnl_pct=0.0,
            entry_timestamp=0, exit_timestamp=100, duration_seconds=100,
        )
        assert TradeJournal._compute_risk_reward(trade) == 0.0
