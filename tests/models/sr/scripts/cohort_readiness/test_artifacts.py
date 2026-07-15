from __future__ import annotations

import json

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json
from libs.models.sr.scripts.cohort_readiness.artifacts import (
    load_source_bundle,
    publish_source_bundle,
    validate_evaluation_bundle,
)
from libs.models.sr.scripts.cohort_readiness.contracts import (
    APPROVED_ASSETS,
    AssetSource,
    SourceBundle,
    bars_sha256,
    grid_sha256,
)
from libs.models.sr.scripts.cohort_readiness.metrics import evaluate_cohort
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar


def _bundle(cohort_config, resolved_configs, tao_source):
    _, _, hashes = resolved_configs
    sources = [tao_source]
    for asset in APPROVED_ASSETS[1:]:
        bars = tuple(SourceBar(open_time=bar.open_time, closed_at=bar.closed_at, open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume, bar_id=f"binance_usdm:{asset}:1d:{int(bar.open_time.timestamp() * 1000)}") for bar in tao_source.bars)
        bar_hash = bars_sha256(bars)
        grid_hash = grid_sha256(bars)
        from libs.models.sr.domain.identity import deterministic_hash
        source_id = deterministic_hash({"asset": asset, "bars_sha256": bar_hash, "grid_sha256": grid_hash, "source_kind": "provider"})
        sources.append(AssetSource(asset=asset, venue="binance_usdm", timeframe="1d", source_id=source_id, source_bundle_id=source_id, bars_sha256=bar_hash, row_count=629, first_open_time=bars[0].open_time, last_closed_at=bars[-1].closed_at, grid_sha256=grid_hash, requested_since=cohort_config.source_since, requested_until=cohort_config.source_until, provider_calls=1, provider_request_since_ms=1712793600000, provider_request_until_ms=1767139199999, adapter_limit=1000, source_kind="provider", resolved_sr_config_hash=hashes[asset][0], resolved_input_hash=hashes[asset][1], bars=bars))
    return SourceBundle(implementation_commit="a" * 40, config_hash=cohort_config.config_hash, assets=tuple(sources), resolved_sr_config_hashes=tuple((asset, hashes[asset][0]) for asset in APPROVED_ASSETS), resolved_input_hashes=tuple((asset, hashes[asset][1]) for asset in APPROVED_ASSETS))


def test_source_round_trip_and_rehashed_bar_tamper_rejected(tmp_path, cohort_config, resolved_configs, tao_source):
    bundle = _bundle(cohort_config, resolved_configs, tao_source)
    _, path = publish_source_bundle(bundle, output_root=tmp_path)
    assert load_source_bundle(path, config=cohort_config, implementation_commit="a" * 40).bundle_id == bundle.bundle_id
    member = path / "BTCUSDT.json"
    payload = json.loads(member.read_text(encoding="utf-8"))
    payload["bars"][0]["open"] = payload["bars"][0]["close"]
    member.write_bytes((canonical_json(payload) + "\n").encode("utf-8"))
    with pytest.raises(ContractValidationError):
        load_source_bundle(path, config=cohort_config, implementation_commit="a" * 40)


def test_evaluation_validator_recomputes_rehashed_semantics(tmp_path, cohort_config, resolved_configs, tao_source):
    from libs.models.sr.scripts.cohort_readiness.artifacts import publish_evaluation_bundle
    bundle = _bundle(cohort_config, resolved_configs, tao_source)
    publish_source_bundle(bundle, output_root=tmp_path)
    sr_configs, _, _ = resolved_configs
    evaluation = evaluate_cohort(cohort_config, bundle, sr_configs)
    _, path = publish_evaluation_bundle(evaluation, output_root=tmp_path, config=cohort_config, source_bundle=bundle)
    payload = json.loads((path / "evaluation.json").read_text(encoding="utf-8"))
    payload["disposition"] = "READY_FOR_PARAMETER_SENSITIVITY"
    evaluation_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (path / "evaluation.json").write_bytes(evaluation_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    semantic["members"][0]["sha256"] = __import__("hashlib").sha256(evaluation_bytes).hexdigest()
    semantic["members"][0]["byte_length"] = len(evaluation_bytes)
    manifest["bundle_id"] = __import__("libs.models.sr.domain.identity", fromlist=["deterministic_hash"]).deterministic_hash(semantic)
    manifest["bundle_id_semantic_payload"] = semantic
    new_path = path.parent / manifest["bundle_id"]
    (path / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    path.rename(new_path)
    with pytest.raises(ContractValidationError):
        validate_evaluation_bundle(new_path, config=cohort_config, source_bundle=bundle, resolved_configs=sr_configs)
