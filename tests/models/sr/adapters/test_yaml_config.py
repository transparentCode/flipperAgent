from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from libs.models.sr import ContractValidationError, SRConfigResolver
from libs.models.sr.adapters.yaml_config import load_sr_config


_REPO_ROOT = Path(__file__).resolve().parents[4]
_REAL_CONFIG = _REPO_ROOT / "configs" / "sr.yaml"


def test_real_sr_yaml_bytes_are_frozen_for_the_modular_refactor() -> None:
    assert hashlib.sha256(_REAL_CONFIG.read_bytes()).hexdigest() == (
        "0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119"
    )


def test_real_sr_yaml_loads_and_resolves() -> None:
    raw = load_sr_config(_REAL_CONFIG)
    resolved = SRConfigResolver(raw).resolve(asset="BTCUSDT", timeframe="1h")

    assert raw["version"] == "1"
    assert resolved.detection.pivot_span_bars == 5
    assert resolved.detection.zone_half_width_atr == 0.25
    assert resolved.association.merge_distance_atr == 0.5
    assert resolved.lifecycle.touch_tolerance_atr == 0.25
    assert resolved.lifecycle.break_buffer_atr == 0.25
    assert resolved.lifecycle.break_confirm_closes == 2
    assert resolved.lifecycle.max_age_bars == 50
    assert resolved.runtime.max_active_zones == 8
    assert len(resolved.field_provenance) == 8
    assert set(dict(resolved.field_provenance).values()) == {"defaults"}
    assert resolved.resolved_config_hash == (
        "ad37f8204714a4613135f695cc02a7dd2b3280fe9e57c01cef640b8638f5ba51"
    )
    assert resolved.to_dict()["resolved_config_hash"] == resolved.resolved_config_hash


@pytest.mark.parametrize(
    ("asset", "timeframe", "expected_hash"),
    [
        (
            "BTCUSDT",
            "1h",
            "ad37f8204714a4613135f695cc02a7dd2b3280fe9e57c01cef640b8638f5ba51",
        ),
        (
            "TAOUSDT",
            "1d",
            "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299",
        ),
    ],
)
def test_frozen_sr_yaml_resolution_payloads_remain_unchanged(
    asset: str, timeframe: str, expected_hash: str
) -> None:
    resolved = SRConfigResolver(load_sr_config(_REAL_CONFIG)).resolve(
        asset=asset, timeframe=timeframe
    )

    assert resolved.to_dict() == {
        "version": "1",
        "asset": asset,
        "timeframe": timeframe,
        "detection": {"pivot_span_bars": 5, "zone_half_width_atr": 0.25},
        "association": {"merge_distance_atr": 0.5},
        "lifecycle": {
            "touch_tolerance_atr": 0.25,
            "break_buffer_atr": 0.25,
            "break_confirm_closes": 2,
            "max_age_bars": 50,
        },
        "runtime": {"max_active_zones": 8},
        "field_provenance": {
            "association.merge_distance_atr": "defaults",
            "detection.pivot_span_bars": "defaults",
            "detection.zone_half_width_atr": "defaults",
            "lifecycle.break_buffer_atr": "defaults",
            "lifecycle.break_confirm_closes": "defaults",
            "lifecycle.max_age_bars": "defaults",
            "lifecycle.touch_tolerance_atr": "defaults",
            "runtime.max_active_zones": "defaults",
        },
        "resolved_config_hash": expected_hash,
    }


def test_legacy_yaml_adapter_is_a_canonical_loader_reexport() -> None:
    from libs.models.sr.config.loader import load_sr_config as canonical_load_sr_config

    assert load_sr_config is canonical_load_sr_config


def test_yaml_adapter_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError):
        load_sr_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "content",
    [
        'version: "1"\nversion: "1"\n',
        'version: "1"\ndefaults:\n  detection: {}\n  detection: {}\n',
        (
            'version: "1"\ndefaults:\n  detection:\n'
            '    pivot_span_bars: 5\n    pivot_span_bars: 7\n'
        ),
    ],
)
def test_yaml_adapter_rejects_duplicate_keys(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ContractValidationError, match="invalid SR YAML"):
        load_sr_config(path)


@pytest.mark.parametrize("content", ["", "{}", "[]", "version: [1"])
def test_yaml_adapter_rejects_empty_malformed_or_non_mapping(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ContractValidationError):
        load_sr_config(path)


@pytest.mark.parametrize(
    "content",
    [
        'version: "1"\n',
        'version: "2"\ndefaults: {}\n',
    ],
)
def test_yaml_schema_failures_are_rejected_by_resolver(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "invalid-schema.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ContractValidationError):
        SRConfigResolver(load_sr_config(path))
