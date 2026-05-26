"""Tests for libs/portfolio/equity_curve.py — mock DB."""

import pytest

from libs.contracts.schemas import EquityPoint
from libs.portfolio.equity_curve import EquityCurveBuilder


# ---------------------------------------------------------------------------
# Fake async connection / pool (same pattern as test_trade_journal)
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeConnection:
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
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _make_eq_row(ts: float = 1000, equity: float = 10000) -> FakeRecord:
    return FakeRecord(
        timestamp=ts,
        equity=equity,
        balance=equity,
        unrealized_pnl=0.0,
        drawdown_pct=0.0,
        open_position_count=0,
    )


# ---------------------------------------------------------------------------
# get_equity_curve
# ---------------------------------------------------------------------------

class TestGetEquityCurve:
    @pytest.mark.asyncio
    async def test_empty_table(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 0})]
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        result = await builder.get_equity_curve()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_equity_points(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 2})]
        conn.fetch_results = [
            _make_eq_row(1000, 10000),
            _make_eq_row(2000, 10500),
        ]
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        result = await builder.get_equity_curve()
        assert len(result) == 2
        assert isinstance(result[0], EquityPoint)
        assert result[0].equity == 10000
        assert result[1].equity == 10500

    @pytest.mark.asyncio
    async def test_filters_generate_where_clause(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 0})]
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        await builder.get_equity_curve(start_timestamp=1000, end_timestamp=5000)
        _, count_query, count_args = conn.executed[0]
        assert "timestamp >= $1" in count_query
        assert "timestamp <= $2" in count_query
        assert count_args[0] == 1000
        assert count_args[1] == 5000

    @pytest.mark.asyncio
    async def test_striding_when_over_max_points(self):
        conn = FakeConnection()
        conn.fetchrow_results = [FakeRecord({"count": 20000})]
        conn.fetch_results = [_make_eq_row(i * 100, 10000 + i) for i in range(5)]
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        result = await builder.get_equity_curve(max_points=100)
        # Should have used ROW_NUMBER striding
        _, data_query, data_args = conn.executed[1]
        assert "ROW_NUMBER" in data_query
        # stride = 20000 // 100 = 200
        assert 200 in data_args


# ---------------------------------------------------------------------------
# save_equity_point
# ---------------------------------------------------------------------------

class TestSaveEquityPoint:
    @pytest.mark.asyncio
    async def test_upsert(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        point = EquityPoint(
            timestamp=1000,
            equity=10000,
            balance=10000,
            unrealized_pnl=0,
            drawdown_pct=0,
            open_position_count=0,
        )
        await builder.save_equity_point(point)

        assert len(conn.executed) == 1
        op, query, args = conn.executed[0]
        assert op == "execute"
        assert "ON CONFLICT (timestamp) DO UPDATE" in query
        assert args[0] == 1000
        # Default exposure values
        assert args[6] == 0.0
        assert args[7] == 0.0

    @pytest.mark.asyncio
    async def test_upsert_with_exposure(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        point = EquityPoint(
            timestamp=2000,
            equity=10500,
            balance=10500,
            unrealized_pnl=0,
            drawdown_pct=0,
            open_position_count=1,
        )
        await builder.save_equity_point(point, net_exposure_pct=50.0, gross_exposure_pct=50.0)

        _, _, args = conn.executed[0]
        assert args[6] == 50.0
        assert args[7] == 50.0


# ---------------------------------------------------------------------------
# build_from_account_snapshots
# ---------------------------------------------------------------------------

class TestBuildFromAccountSnapshots:
    @pytest.mark.asyncio
    async def test_empty_table(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        result = await builder.build_from_account_snapshots()
        assert result == []

    @pytest.mark.asyncio
    async def test_maps_snapshot_rows(self):
        conn = FakeConnection()
        conn.fetch_results = [
            _make_eq_row(1000, 10000),
            _make_eq_row(2000, 10500),
        ]
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        result = await builder.build_from_account_snapshots()
        assert len(result) == 2
        assert result[0].timestamp == 1000
        assert result[1].equity == 10500

    @pytest.mark.asyncio
    async def test_reads_from_risk_account_snapshots_table(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        await builder.build_from_account_snapshots()
        _, query, _ = conn.executed[0]
        assert "risk_account_snapshots" in query

    @pytest.mark.asyncio
    async def test_filters_by_timestamp(self):
        conn = FakeConnection()
        conn.fetch_results = []
        pool = FakePool(conn)
        builder = EquityCurveBuilder(pool)

        await builder.build_from_account_snapshots(
            start_timestamp=500, end_timestamp=2000
        )
        _, query, args = conn.executed[0]
        assert "timestamp >= $1" in query
        assert "timestamp <= $2" in query
        assert args[0] == 500
        assert args[1] == 2000
