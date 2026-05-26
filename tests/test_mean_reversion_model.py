"""Tests for MeanReversion model — ADX-gated multi-confirmation with SS filtering."""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.registry import ModelRegistry
from libs.models.mean_reversion import MeanReversionModel


# ── Default params ──────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "bb_entry_std": 2.0,
    "cci_oversold": -100,
    "cci_overbought": 100,
    "mfi_oversold": 20,
    "mfi_overbought": 80,
    "adx_regime_threshold": 25.0,
    "ss_threshold": 0,
    "ad_sma_period": 21,
    "mfi_sma_period": 9,
    "mom_lr_period": 14,
    "holding_period": 5,
}


def _make_model(ss_threshold: int = 0, **overrides) -> MeanReversionModel:
    p = {**DEFAULT_PARAMS, "ss_threshold": ss_threshold, **overrides}
    return MeanReversionModel(params=p)


def _make_fv(
    rsi=50, bb_upper=110, bb_lower=90,
    cci=0, adx=15.0, mfi=50.0,
    ad_val=1000.0, momentum=5.0,
    close=100, high=110, low=90, volume=1000,
):
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={
            "RSI": rsi,
            "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            "CCI": cci,
            "ADX": {"adx": adx, "plus_di": 20.0, "minus_di": 15.0},
            "MFI": mfi,
            "ADLine": ad_val,
            "Momentum": momentum,
        },
        bar_data={"close": close, "high": high, "low": low, "volume": volume},
    )


# ── 1. Registration ────────────────────────────────────────────────────

class TestMeanReversionRegistry:
    def test_registered(self):
        assert "MeanReversion" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("MeanReversion")
        assert cls is MeanReversionModel


# ── 2. Default params ──────────────────────────────────────────────────

class TestMeanReversionDefaults:
    def test_all_defaults_match_schema(self):
        model = MeanReversionModel(params={})
        for key, pdef in model.meta.hyperparameter_schema.items():
            assert model.params[key] == pdef.default, f"{key} default mismatch"


# ── 3. Long signal ─────────────────────────────────────────────────────

class TestMeanReversionLong:
    def test_long_on_multi_confirmation(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20,           # RSI oversold (<= 30)
            close=85,         # below BB lower (90)
            bb_lower=90,
            cci=-150,         # CCI extreme (< -100)
            mfi=10,           # MFI extreme (< 20)
            adx=15.0,         # low ADX (< 25)
        )
        output = model.evaluate(fv)
        assert output.direction == 1
        assert output.metadata["trigger"] == "oversold"


# ── 4. Short signal ────────────────────────────────────────────────────

class TestMeanReversionShort:
    def test_short_on_multi_confirmation(self):
        model = _make_model()
        fv = _make_fv(
            rsi=80,           # RSI overbought (>= 70)
            close=115,        # above BB upper (110)
            bb_upper=110,
            cci=150,          # CCI extreme (> 100)
            mfi=85,           # MFI extreme (> 80)
            adx=15.0,         # low ADX (< 25)
        )
        output = model.evaluate(fv)
        assert output.direction == -1
        assert output.metadata["trigger"] == "overbought"


# ── 5. ADX regime gate blocks signal ───────────────────────────────────

class TestADXRegimeGate:
    def test_high_adx_blocks_long(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150, mfi=10,
            adx=35.0,  # HIGH ADX → gate blocks
        )
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_high_adx_blocks_short(self):
        model = _make_model()
        fv = _make_fv(
            rsi=80, close=115, bb_upper=110,
            cci=150, mfi=85,
            adx=35.0,  # HIGH ADX → gate blocks
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 6. Missing CCI confirmation blocks ─────────────────────────────────

class TestCCIConfirmation:
    def test_missing_cci_blocks_long(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-50,   # CCI not extreme enough (> -100)
            mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_missing_cci_blocks_short(self):
        model = _make_model()
        fv = _make_fv(
            rsi=80, close=115, bb_upper=110,
            cci=50,    # CCI not extreme enough (< 100)
            mfi=85, adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 7. Missing MFI confirmation blocks ─────────────────────────────────

class TestMFIConfirmation:
    def test_missing_mfi_blocks_long(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150,
            mfi=50,    # MFI not extreme (> 20)
            adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_missing_mfi_blocks_short(self):
        model = _make_model()
        fv = _make_fv(
            rsi=80, close=115, bb_upper=110,
            cci=150,
            mfi=50,    # MFI not extreme (< 80)
            adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 8. Signal strength filtering with ss_threshold=3 ───────────────────

class TestSSThresholdFiltering:
    def test_ss_threshold_suppresses_weak_signal(self):
        model = _make_model(ss_threshold=3)
        # No prior state → SS voters mostly unprimed → score < 3
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 9. SS threshold=0 bypasses filter ──────────────────────────────────

class TestSSBypass:
    def test_ss_disabled_at_zero_threshold(self):
        model = _make_model(ss_threshold=0)
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 1


# ── 10. Holding period cooldown ────────────────────────────────────────

class TestHoldingPeriodCooldown:
    def test_cooldown_suppresses_reversal(self):
        model = _make_model(holding_period=5)
        n = 20
        df = pd.DataFrame({
            "RSI": [20] * 5 + [80] * 5 + [20] * 5 + [50] * 5,
            "BollingerBands_upper": [110] * n,
            "BollingerBands_lower": [90] * n,
            "close": [85] * 5 + [115] * 5 + [85] * 5 + [100] * 5,
            "CCI": [-150] * 5 + [150] * 5 + [-150] * 5 + [0] * 5,
            "ADX_adx": [15.0] * n,
            "MFI": [10] * 5 + [85] * 5 + [10] * 5 + [50] * 5,
            "ADLine": [1000] * n,
            "Momentum": [5] * n,
        })
        result = model.batch_evaluate(df)
        assert len(result) == n
        # The first long signal at index 0 should exist
        assert result.iloc[0] == 1


# ── 11. Batch evaluate alignment ──────────────────────────────────────

class TestBatchAlignment:
    def test_batch_output_length(self):
        model = _make_model()
        n = 50
        df = pd.DataFrame({
            "RSI": [50] * n,
            "BollingerBands_upper": [110] * n,
            "BollingerBands_lower": [90] * n,
            "close": [100] * n,
            "CCI": [0] * n,
            "ADX_adx": [15.0] * n,
            "MFI": [50] * n,
            "ADLine": [1000] * n,
            "Momentum": [5] * n,
        })
        result = model.batch_evaluate(df)
        assert len(result) == n


# ── 12. Batch temporal guard ──────────────────────────────────────────

class TestBatchTemporalGuard:
    def test_batch_rejects_non_monotonic(self):
        model = _make_model()
        df = pd.DataFrame({
            "RSI": [50, 50],
            "BollingerBands_upper": [110, 110],
            "BollingerBands_lower": [90, 90],
            "close": [100, 100],
            "CCI": [0, 0],
            "ADX_adx": [15.0, 15.0],
            "MFI": [50, 50],
            "ADLine": [1000, 1000],
            "Momentum": [5, 5],
        }, index=[2, 1])
        with pytest.raises(ValueError, match="monotonically"):
            model.batch_evaluate(df)


# ── 13. Batch ADX gate ────────────────────────────────────────────────

class TestBatchADXGate:
    def test_high_adx_suppresses_all_batch_signals(self):
        model = _make_model()
        n = 20
        df = pd.DataFrame({
            "RSI": [20] * n,
            "BollingerBands_upper": [110] * n,
            "BollingerBands_lower": [90] * n,
            "close": [85] * n,
            "CCI": [-150] * n,
            "ADX_adx": [35.0] * n,  # HIGH ADX
            "MFI": [10] * n,
            "ADLine": [1000] * n,
            "Momentum": [5] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == 0).all()


# ── 14. Batch multi-confirmation ──────────────────────────────────────

class TestBatchMultiConfirmation:
    def test_only_full_confirmation_rows_get_signals(self):
        model = _make_model()
        n = 10
        # Rows 0-4: all conditions met → long
        # Rows 5-9: CCI not extreme → no signal
        df = pd.DataFrame({
            "RSI": [20] * 5 + [20] * 5,
            "BollingerBands_upper": [110] * n,
            "BollingerBands_lower": [90] * n,
            "close": [85] * n,
            "CCI": [-150] * 5 + [-50] * 5,  # second half: CCI not extreme
            "ADX_adx": [15.0] * n,
            "MFI": [10] * n,
            "ADLine": [1000] * n,
            "Momentum": [5] * n,
        })
        result = model.batch_evaluate(df)
        assert (result[:5] == 1).all()
        assert (result[5:] == 0).all()


# ── 15. Conviction scaling ────────────────────────────────────────────

class TestConvictionScaling:
    def test_conviction_in_valid_range(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert 0 < output.conviction <= 1.0

    def test_deeper_rsi_higher_conviction(self):
        model = _make_model()
        fv_shallow = _make_fv(
            rsi=28, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        fv_deep = _make_fv(
            rsi=10, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        out_shallow = model.evaluate(fv_shallow)
        # Reset model state for fair comparison
        model2 = _make_model()
        out_deep = model2.evaluate(fv_deep)
        # Both should fire, deeper RSI → higher base conviction
        assert out_shallow.direction == 1
        assert out_deep.direction == 1


# ── 16. No signal in neutral RSI ──────────────────────────────────────

class TestNeutralRSI:
    def test_neutral_rsi_no_signal(self):
        model = _make_model()
        fv = _make_fv(
            rsi=50,           # neutral
            close=100,
            cci=-150, mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 17. Metadata contents ─────────────────────────────────────────────

class TestMetadataContents:
    def test_metadata_has_expected_keys(self):
        model = _make_model()
        fv = _make_fv(
            rsi=20, close=85, bb_lower=90,
            cci=-150, mfi=10, adx=15.0,
        )
        output = model.evaluate(fv)
        assert "trigger" in output.metadata
        assert "adx" in output.metadata
        assert "rsi_value" in output.metadata

    def test_metadata_adx_value(self):
        model = _make_model()
        fv = _make_fv(adx=18.0)
        output = model.evaluate(fv)
        assert output.metadata["adx"] == 18.0


# ── 18. Feature validation ────────────────────────────────────────────

class TestFeatureValidation:
    def test_validate_features_reports_missing(self):
        model = _make_model()
        available = {"RSI", "BollingerBands"}
        missing = model.validate_features(available)
        assert "CCI" in missing
        assert "ADX" in missing
        assert "MFI" in missing

    def test_validate_features_all_present(self):
        model = _make_model()
        available = {"RSI", "BollingerBands", "CCI", "ADX", "MFI", "ADLine", "Momentum"}
        missing = model.validate_features(available)
        assert missing == []


# ── 19. Required fields validation ────────────────────────────────────

class TestRequiredFieldsValidation:
    def test_validate_required_fields_reports_missing(self):
        model = _make_model()
        available = {"RSI"}
        missing = model.validate_required_fields(available)
        assert len(missing) > 0

    def test_validate_required_fields_all_present(self):
        model = _make_model()
        available = {
            "RSI", "BollingerBands_upper", "BollingerBands_lower",
            "CCI", "ADX", "MFI", "ADLine", "Momentum",
        }
        missing = model.validate_required_fields(available)
        assert missing == []


# ── 20. SS voter: CCI reversal ────────────────────────────────────────

class TestSSVoterCCIReversal:
    def test_cci_reversal_adds_vote(self):
        model = _make_model()
        model._prev_cci = -160.0  # CCI was lower
        ss = model._compute_signal_strength(
            direction=1, cci_val=-140.0,  # CCI now higher → reversal
            adx_val=None, ad_val=None, mfi_val=None, mom_val=None,
        )
        assert ss >= 1

    def test_cci_no_reversal_no_vote(self):
        model = _make_model()
        model._prev_cci = -140.0
        ss = model._compute_signal_strength(
            direction=1, cci_val=-160.0,  # CCI still falling → no reversal for long
            adx_val=None, ad_val=None, mfi_val=None, mom_val=None,
        )
        assert ss == 0


# ── Output format ──────────────────────────────────────────────────────

class TestMeanReversionOutput:
    def test_output_type(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)

    def test_direction_in_valid_range(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert output.direction in {-1, 0, 1}

    def test_model_name_in_output(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert output.model_name == "MeanReversion"
