from __future__ import annotations

import pytest

from libs.models.trendline_family.config_loader import load_trendline_family_config
from libs.models.trendline_family.contracts import ContractValidationError


def test_loader_returns_raw_mapping(tmp_path) -> None:
    path = tmp_path / "trendline_family.yaml"
    path.write_text("version: 1\ndefaults: {}\n", encoding="utf-8")
    assert load_trendline_family_config(path)["version"] == 1


def test_loader_rejects_non_mapping_root_and_invalid_yaml(tmp_path) -> None:
    non_mapping = tmp_path / "non_mapping.yaml"
    non_mapping.write_text("- invalid\n", encoding="utf-8")
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("defaults: [\n", encoding="utf-8")
    with pytest.raises(ContractValidationError, match="root must be a mapping"):
        load_trendline_family_config(non_mapping)
    with pytest.raises(ContractValidationError, match="invalid trendline-family YAML"):
        load_trendline_family_config(invalid)
