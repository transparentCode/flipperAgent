from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.geometry_sensitivity.candidate_grid import (
    build_candidate_grid,
    build_effective_config,
    orthogonal_neighbors,
)
from libs.models.sr.scripts.geometry_sensitivity.config import (
    APPROVED_PIVOT_SPANS,
    APPROVED_SELECTION_THRESHOLDS,
    APPROVED_ZONE_HALF_WIDTHS,
    parse_geometry_config,
)


def test_real_config_is_strict_and_content_addressed(geometry_config):
    assert geometry_config.config_hash == "86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7"
    assert geometry_config.assets == ("TAOUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert geometry_config.v17_config_hash == "370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7"


def test_selection_thresholds_match_approved_payload(geometry_config):
    assert geometry_config.selection.to_payload() == dict(APPROVED_SELECTION_THRESHOLDS)


@pytest.mark.parametrize("field_name", tuple(APPROVED_SELECTION_THRESHOLDS))
def test_selection_threshold_mutation_fails_closed(field_name, repo_root):
    raw = deepcopy(load_sr_config(repo_root / "configs/sr_trials/sr_v1_8_1d_geometry_sensitivity.yaml"))
    value = raw["selection"][field_name]
    raw["selection"][field_name] = value + 1 if type(value) is int else value + 0.01
    with pytest.raises(ContractValidationError):
        parse_geometry_config(raw)


def test_recursive_duplicate_yaml_key_fails_closed(tmp_path, geometry_config):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "version: '1'\nversion: '1'\n",
        encoding="utf-8",
    )
    from libs.models.sr.scripts.geometry_sensitivity.config import load_geometry_config

    with pytest.raises(ContractValidationError):
        load_geometry_config(path)


def test_grid_is_exact_ordered_unique_cartesian_product():
    grid = build_candidate_grid()
    assert [(item.pivot_span_bars, item.zone_half_width_atr) for item in grid] == [
        (pivot, width)
        for pivot in APPROVED_PIVOT_SPANS
        for width in APPROVED_ZONE_HALF_WIDTHS
    ]
    assert len({item.candidate_id for item in grid}) == 9
    assert sum(item.baseline for item in grid) == 1
    assert grid[4].baseline


def test_effective_config_changes_only_detection_and_preserves_provenance(frozen_inputs):
    base = frozen_inputs.resolved_configs["TAOUSDT"]
    challenger = build_candidate_grid()[0]
    effective = build_effective_config(base, challenger)
    assert effective.resolved_config_hash != base.resolved_config_hash
    assert effective.detection.pivot_span_bars == 3
    assert effective.detection.zone_half_width_atr == 0.15
    assert effective.association == base.association
    assert effective.lifecycle == base.lifecycle
    assert effective.runtime == base.runtime
    assert effective.field_provenance == base.field_provenance
    baseline = build_effective_config(base, build_candidate_grid()[4])
    assert baseline.resolved_config_hash == base.resolved_config_hash


def test_neighbor_relation_is_orthogonal_only():
    grid = build_candidate_grid()
    center = grid[4]
    neighbors = orthogonal_neighbors(center, grid)
    assert {(item.pivot_span_bars, item.zone_half_width_atr) for item in neighbors} == {
        (3, 0.25), (7, 0.25), (5, 0.15), (5, 0.35)
    }
    assert all(item not in orthogonal_neighbors(center, grid) for item in (grid[0], grid[2], grid[6], grid[8]))


def test_effective_constructor_keeps_existing_resolved_contract():
    assert "runtime_override" not in inspect.signature(ResolvedSRConfig.create).parameters
