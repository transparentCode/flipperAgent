from datetime import timedelta
from pathlib import Path

import pytest

from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.studies.adaptive_context_calibration.config import (
    load_adaptive_context_calibration_config,
)
from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    IntervalBar,
    V23SourceBundle,
    V23SourceMember,
    interval_bars_sha256,
    interval_grid_sha256,
)
from libs.models.sr.research.studies.adaptive_context_calibration.source import _frozen_members


BASE_COMMIT = "60331170abbbb5e538a4a67fa3a970a137160758"
CONFIG_PATH = Path("configs/sr_trials/sr_v2_3_adaptive_context_calibration.yaml")


@pytest.fixture(scope="session")
def config():
    return load_adaptive_context_calibration_config(str(CONFIG_PATH))


def synthetic_provider_rows(config, asset: str):
    protocol = config.provider_12h
    rows = []
    for index in range(protocol.expected_rows):
        timestamp = protocol.start + index * timedelta(hours=12)
        center = 100.0 + (index % 16) * 1.7 + index * 0.03
        close = center + (0.8 if index % 4 in (0, 1) else -0.8)
        open_value = center - (0.5 if index % 3 else -0.5)
        high = max(open_value, close) + 1.5
        low = min(open_value, close) - 1.5
        rows.append((int(timestamp.timestamp() * 1000), open_value, high, low, close, 10.0 + index))
    return tuple(rows)


class FakeFrame:
    columns = ("timestamp", "open", "high", "low", "close", "volume")

    def __init__(self, rows):
        self._rows = tuple(rows)

    def itertuples(self, *, index, name):
        assert index is False
        assert name is None
        return iter(self._rows)


def synthetic_member(config, asset: str) -> V23SourceMember:
    protocol = config.provider_12h
    rows = synthetic_provider_rows(config, asset)
    bars = tuple(
        IntervalBar(
            open_time=protocol.start + index * timedelta(hours=12),
            closed_at=protocol.start + (index + 1) * timedelta(hours=12),
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            bar_id=f"{protocol.venue}:{asset}:{protocol.timeframe}:{row[0]}",
        )
        for index, row in enumerate(rows)
    )
    request_identity = {
        "adapter": protocol.adapter,
        "asset": asset,
        "venue": protocol.venue,
        "timeframe": protocol.timeframe,
        "since_ms": int(protocol.start.timestamp() * 1000),
        "until_ms": int(protocol.end.timestamp() * 1000) - 1,
        "limit": protocol.adapter_limit,
        "bars_sha256": interval_bars_sha256(bars),
        "grid_sha256": interval_grid_sha256(bars),
    }
    return V23SourceMember(
        asset=asset,
        venue=protocol.venue,
        timeframe=protocol.timeframe,
        source_id=deterministic_hash({"source": request_identity}),
        source_bundle_id=deterministic_hash({"member": request_identity}),
        bars_sha256=interval_bars_sha256(bars),
        grid_sha256=interval_grid_sha256(bars),
        row_count=len(bars),
        first_open_time=protocol.start,
        last_closed_at=protocol.end,
        requested_since=protocol.start,
        requested_until=protocol.end,
        provider_calls=0,
        provider_request_since_ms=None,
        provider_request_until_ms=None,
        adapter_limit=protocol.adapter_limit,
        source_kind="synthetic",
        implementation_commit=BASE_COMMIT,
        bars=bars,
    )


@pytest.fixture
def synthetic_source_bundle(config):
    daily = _frozen_members(config, repo_root=Path("."))
    intervals = tuple(synthetic_member(config, asset) for asset in config.assets)
    members = daily + intervals
    ordered = tuple(
        next(item for item in members if (item.asset, item.timeframe) == cohort)
        for cohort in (
            ("TAOUSDT", "1d"),
            ("ETHUSDT", "1d"),
            ("SOLUSDT", "1d"),
            ("TAOUSDT", "12h"),
            ("ETHUSDT", "12h"),
            ("SOLUSDT", "12h"),
        )
    )
    return V23SourceBundle(BASE_COMMIT, config.config_hash, ordered)


@pytest.fixture
def synthetic_frame(config):
    return FakeFrame(synthetic_provider_rows(config, "TAOUSDT"))
