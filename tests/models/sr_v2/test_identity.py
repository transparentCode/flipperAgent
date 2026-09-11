from datetime import UTC, datetime
from decimal import Decimal

from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.domain.zones import lineage_from_candidate


def test_zone_identity_excludes_lifecycle_and_is_deterministic():
    now = datetime(2024, 1, 1, tzinfo=UTC)
    candidate = Candidate(
        candidate_key="source:high",
        venue="binance",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        source_timeframe="1h",
        kernel_id="previous_period_anchor",
        kernel_version="1",
        side=ZoneSide.RESISTANCE,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=now,
        available_at=now,
        source_evidence_id="source",
        creation_atr=Decimal(2),
    )
    first = lineage_from_candidate(candidate, config_fingerprint="config")
    second = lineage_from_candidate(candidate, config_fingerprint="other")
    assert first.zone_id == second.zone_id
    assert canonical_hash({"a": 1}) == canonical_hash({"a": 1})
