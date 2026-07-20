from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.relative_salience_rank_utility.artifacts import (
    load_source_bundle,
    publish_source_bundle,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.config import (
    COHORTS,
    load_relative_salience_rank_config,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.contracts import (
    IntervalBar,
    SourceBundle,
    SourceMember,
)


def _bundle() -> SourceBundle:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    start = datetime(2025, 12, 31, tzinfo=timezone.utc)
    members = []
    for asset, timeframe in COHORTS:
        cadence = timedelta(days=1) if timeframe == "1d" else timedelta(hours=12)
        bar = IntervalBar(start, start + cadence, 100.0, 101.0, 99.0, 100.0, 1.0, f"binance_usdm:{asset}:{timeframe}:{int(start.timestamp() * 1000)}")
        members.append(SourceMember(asset, timeframe, (bar,), (), 0, "frozen_history"))
    return SourceBundle("a" * 40, config.config_hash, tuple(members))


def test_source_artifact_round_trip_and_member_tamper_rejection(tmp_path) -> None:
    bundle = _bundle()
    bundle_id, path = publish_source_bundle(bundle, output_root=tmp_path)
    assert load_source_bundle(path, expected_bundle_id=bundle_id) == bundle
    member = path / "TAOUSDT_1d.json"
    member.write_bytes(member.read_bytes() + b" ")
    with pytest.raises(ContractValidationError, match="member hash mismatch"):
        load_source_bundle(path)


def test_source_artifact_rejects_symlink_member(tmp_path) -> None:
    bundle = _bundle()
    _, path = publish_source_bundle(bundle, output_root=tmp_path)
    member = path / "TAOUSDT_1d.json"
    replacement = path / "replacement.json"
    replacement.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(replacement.name)
    with pytest.raises(ContractValidationError):
        load_source_bundle(path)
