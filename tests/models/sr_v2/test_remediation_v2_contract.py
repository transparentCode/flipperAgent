"""Contract regressions for strict authorities and research-only boundaries."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.sr_v2.config import (
    SRV2ConfigError,
    SRV2ConfigResolver,
    load_sr_v2_yaml,
)
from libs.models.sr_v2.domain.state import create_initial_state
from libs.models.sr_v2.research.splits import purge_lineage_intervals
from libs.models.sr_v2.research.studies import load_trial_config
from libs.models.sr_v2.research_lab.config import (
    SRV2ResearchNotebookConfigResolver,
    load_research_notebook_yaml,
    normalize_display_policy,
)
from libs.models.sr_v2.serialization.state_codec import decode_state, encode_state


def test_model_trial_and_notebook_authorities_reject_duplicate_keys(tmp_path):
    model = tmp_path / "model.yaml"
    model.write_text("version: 2\nversion: 2\n", encoding="utf-8")
    with pytest.raises(SRV2ConfigError, match="duplicate"):
        load_sr_v2_yaml(model)

    trial = tmp_path / "trial.yaml"
    trial.write_text("version: 2\nversion: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_trial_config(trial)

    notebook = tmp_path / "notebook.yaml"
    notebook.write_text("version: 2\nversion: 2\n", encoding="utf-8")
    with pytest.raises(SRV2ConfigError, match="duplicate"):
        load_research_notebook_yaml(notebook)


def test_model_has_single_strict_structural_authority():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    assert set(raw) == {"version", "runtime", "kernels", "lifecycle", "state_bounds"}
    assert raw["runtime"]["ladder"] == ["1d", "6h", "4h", "1h", "30m", "15m"]
    with pytest.raises(SRV2ConfigError, match="unknown"):
        SRV2ConfigResolver({**raw, "forecast": {}}).resolve()


def test_trial_references_model_without_duplicate_model_block():
    trial = load_trial_config("configs/sr_v2_trials/phase1.yaml")
    assert trial.model_config_fingerprint
    assert trial.model_catalog_fingerprint
    assert trial.model_path.endswith("configs/sr_v2.yaml")


def test_notebook_authority_has_explicit_display_policy():
    config = SRV2ResearchNotebookConfigResolver.from_yaml(
        "configs/sr_v2_research_notebook.yaml"
    ).resolve()
    assert config.version == 2
    assert set(config.display) == {
        "iframe_height",
        "candle_limit",
        "initial_mode",
        "show_zones",
        "show_candidates",
        "show_inspector",
        "show_history",
        "volume_pane_fraction",
        "volume_pane_min_height",
    }
    assert dict(config.display) == dict(normalize_display_policy(config.display))
    missing_history = dict(config.display)
    missing_history.pop("show_history")
    with pytest.raises(SRV2ConfigError, match="missing.*show_history"):
        normalize_display_policy(missing_history)


def test_checked_in_notebook_display_covers_configured_window_at_trigger_duration():
    model = SRV2ConfigResolver.from_yaml("configs/sr_v2.yaml").resolve()
    notebook = SRV2ResearchNotebookConfigResolver.from_yaml(
        "configs/sr_v2_research_notebook.yaml"
    ).resolve()
    expected_candles = int(
        (notebook.knowledge_cutoff - notebook.analysis_start) / model.trigger_duration
    ) + 1
    assert notebook.display["candle_limit"] >= expected_candles


def test_state_codec_is_canonical_and_rejects_legacy_fields():
    state = create_initial_state(
        config_fingerprint="config",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    payload = encode_state(state)
    restored = decode_state(
        payload,
        expected_config_fingerprint="config",
        expected_venue="binance_usdm",
        expected_instrument_id="BTCUSDT",
        expected_asset="BTCUSDT",
    )
    assert restored == state
    assert encode_state(restored) == payload
    legacy = payload[:-1] + b',"forecast_issuances":[]}'
    with pytest.raises(ValueError):
        decode_state(legacy)


def test_split_purge_is_half_open_and_embargo_aware():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    boundary = start + timedelta(days=10)
    intervals = (
        (start, start + timedelta(days=1)),
        (boundary - timedelta(hours=1), boundary + timedelta(hours=1)),
        (boundary + timedelta(days=2), boundary + timedelta(days=3)),
    )
    assert purge_lineage_intervals(intervals, boundary=boundary, embargo=timedelta(days=1)) == (
        intervals[0],
        intervals[2],
    )
