from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from app.sr.sidecar.daemon import SRSidecarDaemon
from app.sr.sidecar.queue import ProfileTask, create_profile_task_queue


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = np.cumsum(rng.randn(n)) + 100.0
    opens = closes + rng.uniform(-0.5, 0.5, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    volumes = rng.uniform(100, 2000, n)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


def test_sidecar_daemon_materializes_profile_and_acks_task(tmp_path: Path):
    yaml_path = tmp_path / "sr.yaml"
    yaml_path.write_text("assets: {}\n")
    queue_path = tmp_path / "sr_sidecar.sqlite3"

    queue = create_profile_task_queue("sqlite", str(queue_path))
    queue.enqueue(
        ProfileTask(
            symbol="BTCUSDT",
            timeframe="1h",
            reason="missing_microstructure_profile",
            timestamp="2026-05-07T14:32:00Z",
        ),
    )

    daemon = SRSidecarDaemon(
        config_path=str(yaml_path),
        queue_path=str(queue_path),
        fetcher=lambda *args, **kwargs: _make_ohlcv(),
    )

    processed = daemon.run_once()
    assert processed == 1
    assert create_profile_task_queue("sqlite", str(queue_path)).list_pending() == []

    with yaml_path.open() as handle:
        config = yaml.safe_load(handle)

    asset_tf = config["assets"]["BTCUSDT"]["1h"]
    assert "_profiler_meta" in asset_tf
    assert asset_tf["_profiler_meta"]["last_profiled_at"]
    assert asset_tf["_profiler_meta"]["wick_p75_atr"] > 0
    assert asset_tf["pipeline"]["merge_threshold_pct_atr"] > 0
    assert asset_tf["pipeline"]["dedup_proximity_atr"] > 0
    assert asset_tf["pipeline"]["zone_half_width_atr"] > 0
    assert asset_tf["lifecycle"]["breakout_atr_threshold"] > 0
    assert asset_tf["lifecycle"]["touch_proximity_atr"] > 0
    assert asset_tf["lifecycle"]["false_breakout_recovery_bars"] >= 6
    assert asset_tf["enhancement"]["volume_spike_threshold"] >= 1.0


def test_sidecar_daemon_uses_timeframe_aware_lookback_by_default(tmp_path: Path):
    yaml_path = tmp_path / "sr.yaml"
    yaml_path.write_text("assets: {}\n")
    queue_path = tmp_path / "sr_sidecar.sqlite3"

    queue = create_profile_task_queue("sqlite", str(queue_path))
    queue.enqueue(
        ProfileTask(
            symbol="BTCUSDT",
            timeframe="1d",
            reason="missing_microstructure_profile",
            timestamp="2026-05-07T14:32:00Z",
        ),
    )

    captured: dict[str, int] = {}

    def fetcher(*args, **kwargs):
        captured["lookback_days"] = kwargs["lookback_days"]
        return _make_ohlcv()

    daemon = SRSidecarDaemon(
        config_path=str(yaml_path),
        queue_path=str(queue_path),
        fetcher=fetcher,
    )

    processed = daemon.run_once()
    assert processed == 1
    assert captured["lookback_days"] == 365