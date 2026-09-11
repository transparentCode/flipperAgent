from datetime import timedelta
from decimal import Decimal

from libs.models.sr_v2.contracts import LifecycleState, ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.zones import ZoneRecord, lineage_from_candidate
from libs.models.sr_v2.lifecycle.engine import advance_zone
from libs.models.sr_v2.lifecycle.rules import LifecycleRules


def test_touch_then_confirmed_break_is_terminal(sr_v2_now):
    candidate = Candidate(
        candidate_key="z",
        venue="v",
        instrument_id="i",
        asset="a",
        source_timeframe="15m",
        kernel_id="k",
        kernel_version="1",
        side=ZoneSide.RESISTANCE,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=sr_v2_now,
        available_at=sr_v2_now,
        source_evidence_id="e",
        creation_atr=Decimal(2),
    )
    record = ZoneRecord(lineage=lineage_from_candidate(candidate, config_fingerprint="c"))
    rules = LifecycleRules(break_buffer_atr=Decimal(".5"), break_confirmation_bars=2, expiry=timedelta(days=90))
    def bar(close, index):
        opened = sr_v2_now + timedelta(minutes=15 * index)
        closed = opened + timedelta(minutes=15)
        return SRBar(
            timeframe="15m", bar_open_at=opened, bar_close_at=closed,
            market_as_of=closed, open=Decimal(100), high=Decimal(103),
            low=Decimal(100), close=Decimal(str(close)), volume=Decimal(1),
            taker_buy_base=Decimal(".5"),
        )
    touched, _ = advance_zone(record, bar(100, 1), rules=rules)
    pending, _ = advance_zone(touched, bar(103, 2), rules=rules)
    broken, _ = advance_zone(pending, bar(103, 3), rules=rules)
    assert touched.lifecycle is LifecycleState.TOUCHED
    assert pending.lifecycle is LifecycleState.BREAK_PENDING
    assert broken.lifecycle is LifecycleState.BROKEN
