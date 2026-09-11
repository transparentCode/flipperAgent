from dataclasses import replace
from decimal import Decimal

from libs.models.sr_v2.features.price import wilder_atr


def test_wilder_atr_is_positive_and_causal(sr_v2_bars):
    bars = sr_v2_bars["15m"]
    assert wilder_atr(bars, 14) > Decimal(0)
    changed = replace(bars[-1], high=Decimal(105), close=Decimal(104))
    assert wilder_atr(bars[:-1] + (changed,), 14) > wilder_atr(bars, 14)
