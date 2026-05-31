"""Tests for HMMClassifier."""

import numpy as np
import pandas as pd
import pytest

from app.regime.hmm_classifier import HMMClassifier, HMMConfig
from app.regime.models import HMMState


def _make_df(n=500, seed=42):
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    return pd.DataFrame({"close": close})


class TestHMMClassifier:
    def test_returns_hmm_state(self):
        clf = HMMClassifier()
        df = _make_df()
        state = clf.classify(df)
        assert isinstance(state, HMMState)

    def test_probabilities_sum_to_one(self):
        clf = HMMClassifier()
        state = clf.classify(_make_df())
        assert abs(state.p_trending + state.p_non_trending - 1.0) < 1e-6

    def test_regime_label_consistent_with_prob(self):
        clf = HMMClassifier()
        state = clf.classify(_make_df())
        expected = "TRENDING" if state.p_trending >= 0.5 else "NON_TRENDING"
        assert state.hmm_regime == expected

    def test_insufficient_data_returns_default(self):
        clf = HMMClassifier()
        df = _make_df(n=10)
        state = clf.classify(df)
        assert state.p_trending == 0.5

    def test_classify_series_returns_correct_columns(self):
        clf = HMMClassifier()
        df = _make_df()
        result = clf.classify_series(df)
        assert "hmm_p_trending" in result.columns
        assert "hmm_regime" in result.columns
        assert len(result) == len(df)

    def test_force_retrain_resets_model_age(self):
        clf = HMMClassifier(HMMConfig(retrain_window=1000))
        df = _make_df()
        # Build up age > 1
        for _ in range(5):
            clf.classify(df)
        age_before = clf._model_age
        assert age_before > 1
        clf.force_retrain()
        clf.classify(df)
        # After forced retrain, model_age resets to 0 then increments once → 1
        assert clf._model_age < age_before

    def test_model_age_increments(self):
        clf = HMMClassifier()
        df = _make_df()
        clf.classify(df)
        age1 = clf._model_age
        clf.classify(df)
        age2 = clf._model_age
        assert age2 > age1
