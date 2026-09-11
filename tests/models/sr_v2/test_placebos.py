from datetime import UTC, datetime
from decimal import Decimal

from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.zones import lineage_from_candidate
from libs.models.sr_v2.research.placebos import matched_random_price_placebos


def test_placebos_are_deterministic():
    now = datetime(2024, 1, 1, tzinfo=UTC)
    candidate = Candidate(
        candidate_key="z", venue="v", instrument_id="i", asset="a",
        source_timeframe="15m", kernel_id="k", kernel_version="1",
        side=ZoneSide.SUPPORT, center=Decimal(100), lower=Decimal(99),
        upper=Decimal(101), formed_at=now, available_at=now,
        source_evidence_id="e", creation_atr=Decimal(1),
    )
    zone = lineage_from_candidate(candidate, config_fingerprint="c")
    assert matched_random_price_placebos(
        [zone], seed="s", max_abs_shift_atr=Decimal(1)
    )[0].zone_id == matched_random_price_placebos(
        [zone], seed="s", max_abs_shift_atr=Decimal(1)
    )[0].zone_id
