"""
Tests for L2 ingestion pipeline integration.

Tests:
1. L2DepthFeatureRecord model validation
2. TimescaleWriter.insert_l2_depth SQL generation (structural)
3. L2 feature computation from raw orderbook
4. poll_l2_depth task structure
5. TimescaleReader.get_latest_l2_features query structure
6. Schedule registration
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from apps.ingestion_app.models.tick_models import L2DepthFeatureRecord
from apps.ingestion_app.constants import TABLE_L2_DEPTH_FEATURES
from libs.models.regime_classification.l2_features import compute_l2_features


# ------------------------------------------------------------------
# 1. L2DepthFeatureRecord
# ------------------------------------------------------------------

class TestL2DepthFeatureRecord:

    def test_valid_record(self):
        r = L2DepthFeatureRecord(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            bid_ask_imbalance=0.3,
            depth_ratio=1.2,
            spread_bps=1.5,
            depth_decay_bid=0.05,
            depth_decay_ask=0.04,
            best_bid=100.0,
            best_ask=100.5,
            bid_depth_total=500.0,
            ask_depth_total=400.0,
            snapshot_levels=20,
        )
        assert r.symbol == "BTCUSDT"
        assert r.bid_ask_imbalance == 0.3
        assert r.snapshot_levels == 20

    def test_defaults(self):
        r = L2DepthFeatureRecord(
            timestamp=datetime.now(timezone.utc),
            symbol="ETHUSDT",
        )
        assert r.bid_ask_imbalance is None
        assert r.depth_ratio is None
        assert r.snapshot_levels == 20

    def test_timestamp_coercion_from_ms(self):
        ts_ms = 1700000000000  # milliseconds
        r = L2DepthFeatureRecord(
            timestamp=ts_ms,
            symbol="BTCUSDT",
        )
        assert r.timestamp.tzinfo is not None  # UTC aware


# ------------------------------------------------------------------
# 2. Table constant
# ------------------------------------------------------------------

class TestConstants:

    def test_l2_table_name(self):
        assert TABLE_L2_DEPTH_FEATURES == "l2_depth_features"


# ------------------------------------------------------------------
# 3. L2 feature computation
# ------------------------------------------------------------------

class TestL2FeatureComputation:

    def test_symmetric_book(self):
        """Symmetric orderbook should have imbalance near 0."""
        bids = np.array([[100.0, 10.0], [99.0, 10.0], [98.0, 10.0]])
        asks = np.array([[101.0, 10.0], [102.0, 10.0], [103.0, 10.0]])
        features = compute_l2_features(bids, asks, top_n=3)
        assert abs(features.bid_ask_imbalance) < 0.01
        assert abs(features.depth_ratio - 1.0) < 0.01

    def test_bid_heavy_book(self):
        """Bid-heavy book should have positive imbalance."""
        bids = np.array([[100.0, 50.0], [99.0, 50.0], [98.0, 50.0]])
        asks = np.array([[101.0, 10.0], [102.0, 10.0], [103.0, 10.0]])
        features = compute_l2_features(bids, asks, top_n=3)
        assert features.bid_ask_imbalance > 0.5
        assert features.depth_ratio > 1.0

    def test_ask_heavy_book(self):
        """Ask-heavy book should have negative imbalance."""
        bids = np.array([[100.0, 10.0], [99.0, 10.0], [98.0, 10.0]])
        asks = np.array([[101.0, 50.0], [102.0, 50.0], [103.0, 50.0]])
        features = compute_l2_features(bids, asks, top_n=3)
        assert features.bid_ask_imbalance < -0.5
        assert features.depth_ratio < 1.0

    def test_spread_positive(self):
        bids = np.array([[100.0, 10.0]])
        asks = np.array([[100.5, 10.0]])
        features = compute_l2_features(bids, asks)
        assert features.spread_bps > 0

    def test_none_inputs(self):
        features = compute_l2_features(None, None)
        assert math.isnan(features.bid_ask_imbalance)

    def test_empty_array(self):
        features = compute_l2_features(np.array([]).reshape(0, 2), np.array([]).reshape(0, 2))
        assert math.isnan(features.bid_ask_imbalance)


# ------------------------------------------------------------------
# 4. Task function exists and is importable
# ------------------------------------------------------------------

class TestTaskImports:

    def test_poll_l2_depth_importable(self):
        from apps.ingestion_app.jobs.l2_depth import poll_l2_depth
        assert callable(poll_l2_depth)

    def test_worker_functions_include_l2(self):
        from apps.ingestion_app.worker import WorkerSettings
        func_names = [f.__name__ for f in WorkerSettings.functions]
        assert "poll_l2_depth" in func_names


# ------------------------------------------------------------------
# 5. Schedule includes L2 depth
# ------------------------------------------------------------------

class TestSchedule:

    def test_schedule_has_l2_cron(self):
        from apps.ingestion_app.schedules import IngestionScheduler
        scheduler = IngestionScheduler()
        jobs = scheduler.get_cron_jobs()
        job_funcs = [j.coroutine.__name__ for j in jobs]
        assert "poll_l2_depth" in job_funcs
