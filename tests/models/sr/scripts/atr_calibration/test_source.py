from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage
from libs.models.sr.scripts.atr_calibration.source import (
    load_capsule,
    load_frozen_source,
    publish_source_capsule,
)


def test_exact_frozen_source_identity(calibration_config):
    bars = load_frozen_source(calibration_config, repo_root=Path(__file__).resolve().parents[5])
    assert len(bars) == 811
    assert bars[0].open_time.isoformat() == "2024-04-11T00:00:00+00:00"
    assert bars[-1].closed_at.isoformat() == "2026-07-01T00:00:00+00:00"


def test_source_capsule_round_trip_and_member_tamper_rejection(tmp_path, calibration_config, source_capsules):
    development, _ = source_capsules
    output_root = tmp_path / "research"
    path = publish_source_capsule(development, output_root=output_root)
    loaded = load_capsule(path, expected_stage=CapsuleStage.DEVELOPMENT, expected_source=calibration_config, expected_implementation_commit=development.implementation_commit)
    assert loaded.capsule_id == development.capsule_id
    source_path = path / "source_bars.json"
    source_path.write_bytes(source_path.read_bytes() + b" ")
    with pytest.raises(ContractValidationError):
        load_capsule(path, expected_stage=CapsuleStage.DEVELOPMENT, expected_source=calibration_config, expected_implementation_commit=development.implementation_commit)


def test_source_module_has_no_provider_adapter_or_network_dependency():
    source = Path(__file__).resolve().parents[5] / "src/libs/models/sr/scripts/atr_calibration/source.py"
    text = source.read_text(encoding="utf-8")
    assert "BinanceNativeAdapter" not in text
    assert "requests" not in text
    assert "httpx" not in text
