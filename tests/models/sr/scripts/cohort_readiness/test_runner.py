from __future__ import annotations

from .conftest import frame_for_asset
from libs.models.sr.scripts.cohort_readiness.runner import (
    evaluate_stage,
    prepare_source_stage,
)


class SpyAdapter:
    def __init__(self, source):
        self.source = source
        self.calls = []

    async def get_historical_ohlcv(self, symbol, timeframe, since=None, until=None, limit=None):
        self.calls.append(symbol)
        return frame_for_asset(self.source, symbol)


def test_prepare_then_evaluate_is_network_free_and_deterministic(tmp_path, cohort_config, tao_source, repo_root, monkeypatch):
    adapter = SpyAdapter(tao_source)
    result = prepare_source_stage(
        repo_root / "configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml",
        repo_root=repo_root,
        adapter=adapter,
        implementation_commit="a" * 40,
    )
    assert adapter.calls == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert result["provider_calls"] == {"TAOUSDT": 0, "BTCUSDT": 1, "ETHUSDT": 1, "SOLUSDT": 1}
    monkeypatch.setattr("libs.models.sr.scripts.cohort_readiness.runner.default_provider_adapter", lambda: (_ for _ in ()).throw(AssertionError("network path used during evaluation")))
    first = evaluate_stage(repo_root / "configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml", repo_root=repo_root, source_bundle_id=result["source_bundle_id"], implementation_commit="a" * 40)
    second = evaluate_stage(repo_root / "configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml", repo_root=repo_root, source_bundle_id=result["source_bundle_id"], implementation_commit="a" * 40)
    assert first["evaluation_bundle_id"] == second["evaluation_bundle_id"]
