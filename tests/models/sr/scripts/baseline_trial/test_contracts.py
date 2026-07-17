from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.models.sr import ContractValidationError
from libs.models.sr.scripts.baseline_trial.contracts import (
    BundleMember,
    ResolvedInputConfig,
    SourceBar,
    TrialSpec,
    ViewerConfig,
)


def test_large_numeric_values_fail_at_contract_boundary() -> None:
    with pytest.raises(ContractValidationError):
        SourceBar(
            open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=10**400,
            high=10**400,
            low=10**399,
            close=10**400,
            volume=1.0,
            bar_id="bar-1",
        )


def test_input_hash_is_content_addressed_and_signed_zero_normalized() -> None:
    provenance = (
        ("atr.method", "defaults"),
        ("atr.period", "defaults"),
        ("atr.seed", "defaults"),
    )
    first = ResolvedInputConfig.create(
        version="1",
        asset="TAOUSDT",
        timeframe="1d",
        atr_method="wilder_rma",
        atr_period=14,
        atr_seed="sma",
        field_provenance=provenance,
    )
    second = ResolvedInputConfig.create(
        version="1",
        asset="TAOUSDT",
        timeframe="1d",
        atr_method="wilder_rma",
        atr_period=14,
        atr_seed="sma",
        field_provenance=provenance,
    )
    assert first.resolved_input_hash == second.resolved_input_hash


def test_viewer_and_trial_contracts_reject_invalid_paths_and_limits() -> None:
    with pytest.raises(ContractValidationError):
        BundleMember(name="../manifest.json", sha256="a" * 64, byte_length=0)

    with pytest.raises(ContractValidationError):
        ViewerConfig(
            library="lightweight-charts",
            library_version="5.2.0",
            attribution_logo=True,
            live_zone_extent="viewport_right_edge",
            show_terminal_by_default=False,
            show_events_by_default=True,
            background_color="#131722",
            text_color="#d1d4dc",
            grid_color="#2a2e39",
            support_border_color="#26a69a",
            support_fill_color="rgba(38, 166, 154, 0.18)",
            resistance_border_color="#ef5350",
            resistance_fill_color="rgba(239, 83, 80, 0.18)",
            pending_border_color="#f2c94c",
            terminal_opacity=2.0,
            zone_line_width=2,
        )

    with pytest.raises(ContractValidationError):
        TrialSpec(
            version="1",
            trial_name="trial",
            venue="binance_usdm",
            symbol="TAOUSDT",
            timeframe="1d",
            requested_since=datetime(2024, 1, 1, tzinfo=timezone.utc),
            requested_until=datetime(2024, 1, 2, tzinfo=timezone.utc),
            adapter_limit=1501,
            gap_policy="reject",
            sr_config_path="configs/sr.yaml",
            input_config_path="configs/sr_inputs.yaml",
            output_root="research/tmp",
            viewer=ViewerConfig(
                library="lightweight-charts",
                library_version="5.2.0",
                attribution_logo=True,
                live_zone_extent="viewport_right_edge",
                show_terminal_by_default=False,
                show_events_by_default=True,
                background_color="#131722",
                text_color="#d1d4dc",
                grid_color="#2a2e39",
                support_border_color="#26a69a",
                support_fill_color="rgba(38, 166, 154, 0.18)",
                resistance_border_color="#ef5350",
                resistance_fill_color="rgba(239, 83, 80, 0.18)",
                pending_border_color="#f2c94c",
                terminal_opacity=0.35,
                zone_line_width=2,
            ),
        )
