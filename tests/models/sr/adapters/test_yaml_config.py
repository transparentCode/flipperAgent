from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr import ContractValidationError, SRConfigResolver
from libs.models.sr.adapters.yaml_config import load_sr_config


_REPO_ROOT = Path(__file__).resolve().parents[4]
_REAL_CONFIG = _REPO_ROOT / "configs" / "sr.yaml"


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
    assert resolved.to_dict()["resolved_config_hash"] == resolved.resolved_config_hash


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
