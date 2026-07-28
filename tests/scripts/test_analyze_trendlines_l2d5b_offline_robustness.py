"""Network-free D5B runner tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import analyze_trendlines_l2d5b_offline_robustness as d5b


def test_source_matrix_readback_uses_committed_fresh_members() -> None:
    matrix, _ = d5b.load_source_matrix()
    assert tuple(spec.name for spec in matrix.member_specs[1:]) == (
        "temporal-btcusdt-1h-20250401-v1",
        "cross-asset-ethusdt-1h-20250401-v1",
        "cross-asset-solusdt-1h-20250401-v1",
        "cross-timeframe-btcusdt-4h-20250401-v1",
    )


def test_protocol_is_explicit_and_provider_free() -> None:
    protocol = d5b._protocol()
    assert protocol.include_signals is True
    assert protocol.stochastic_baseline_specs[0].repetitions == 32
    assert protocol.stochastic_baseline_specs[1].repetitions == 32
    assert protocol.quantile_probabilities == (0.05, 0.95)


def test_fixed_member_order_is_preserved() -> None:
    matrix, _ = d5b.load_source_matrix()
    calls: list[str] = []

    def runner(spec, evidence, protocol):
        calls.append(spec.name)
        return spec.name

    result = d5b.run_member_sequence(matrix, d5b._protocol(), runner)
    assert result == tuple(calls)
    assert calls == list(matrix.member_specs[1:][index].name for index in range(4))


def test_member_sequence_stops_after_first_failure() -> None:
    matrix, _ = d5b.load_source_matrix()
    calls: list[str] = []

    def runner(spec, evidence, protocol):
        calls.append(spec.name)
        if len(calls) == 2:
            raise RuntimeError("synthetic member failure")
        return spec.name

    with pytest.raises(RuntimeError, match="synthetic member failure"):
        d5b.run_member_sequence(matrix, d5b._protocol(), runner)
    assert calls == [matrix.member_specs[1].name, matrix.member_specs[2].name]


def test_member_sequence_does_not_retry_failed_member() -> None:
    matrix, _ = d5b.load_source_matrix()
    calls: list[str] = []

    def runner(spec, evidence, protocol):
        calls.append(spec.name)
        raise RuntimeError("no retry")

    with pytest.raises(RuntimeError, match="no retry"):
        d5b.run_member_sequence(matrix, d5b._protocol(), runner)
    assert calls == [matrix.member_specs[1].name]


def test_runner_has_no_provider_construction_path() -> None:
    source = Path(d5b.__file__).read_text(encoding="utf-8")
    assert "BinanceNativeAdapter" not in source
    assert "BinanceTrendlineResearchLoader" not in source
    assert "run_causal_replay" in source


def test_output_root_overwrite_is_rejected(tmp_path: Path) -> None:
    output_root = tmp_path / "published"
    output_root.mkdir()
    with pytest.raises(RuntimeError, match="overwrite is forbidden"):
        d5b.run_study(output_root=output_root)


def test_d5a_checksum_inventory_is_nonempty() -> None:
    _, entries = d5b.load_source_matrix()
    assert entries
    assert all(entry["sha256"] == entry["sha256"].lower() for entry in entries)


def test_no_d5c_or_d5d_execution_path_in_script() -> None:
    source = Path(d5b.__file__).read_text(encoding="utf-8")
    assert "run_sensitivity" not in source
    assert "run_d5c" not in source.lower()
    assert "run_d5d" not in source.lower()
