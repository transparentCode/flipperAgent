"""Contracts for the canonical public Trendlines namespace."""

from __future__ import annotations

import ast
import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import libs.models.trendlines as canonical
from libs.models.trendlines_v4.core_v2 import analyze_trendlines_v2
from libs.models.trendlines_v4.engine.types import TrendlineBar

ROOT = Path(__file__).resolve().parents[3]
RETAINED_ETH = (
    ROOT
    / "src/libs/models/trendlines/optimization/results/"
    / "ETHUSDT_1h_2023-01-01_2026-03-01.csv"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retained_history() -> tuple[TrendlineBar, ...]:
    with RETAINED_ETH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))[:360]
    return tuple(
        TrendlineBar(
            closed_at=datetime.fromisoformat(
                row["close_time"].replace(" ", "T")
            ).replace(tzinfo=UTC),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
    )


def test_canonical_public_surface_is_bounded_and_v2_shaped() -> None:
    assert set(canonical.__all__) == {
        "TrendlineBar",
        "TrendlineGeometry",
        "SideGeometry",
        "TrendlineSnapshot",
        "PIVOT_WINDOW",
        "HISTORY_CAPACITY_BARS",
        "analyze_trendlines",
        "analyze",
    }
    assert canonical.PIVOT_WINDOW == 3
    assert canonical.HISTORY_CAPACITY_BARS == 300
    assert canonical.analyze is canonical.analyze_trendlines
    assert canonical.SideGeometry.__name__ == "SideGeometryV2"
    assert canonical.TrendlineSnapshot.__name__ == "TrendlineSnapshotV2"


def test_canonical_analysis_is_exact_v2_parity_across_contract_cases() -> None:
    source_history = _retained_history()
    histories = (source_history[:1], source_history, source_history[-300:])

    for history in histories:
        expected = analyze_trendlines_v2(history)
        assert canonical.analyze_trendlines(history) == expected
        assert canonical.analyze(history) == expected

    snapshot = canonical.analyze_trendlines(source_history)
    assert snapshot.history_bar_count == 300
    assert snapshot.history_start_at == source_history[60].closed_at
    assert snapshot.support.structural is not None
    assert snapshot.support.current_valid is not None
    assert snapshot.support.secondary is not None
    assert snapshot.resistance.structural is not None
    assert snapshot.resistance.current_valid is not None
    assert snapshot.resistance.secondary is not None

    empty_roles = canonical.analyze_trendlines(source_history[:1])
    for side in (empty_roles.support, empty_roles.resistance):
        assert side.structural is None
        assert side.current_valid is None
        assert side.secondary is None


def test_production_code_does_not_import_v4_directly_outside_facades() -> None:
    production_roots = (ROOT / "src/apps", ROOT / "src/libs")
    canonical_root = ROOT / "src/libs/models/trendlines"
    v4_root = ROOT / "src/libs/models/trendlines_v4"
    composition = ROOT / "src/apps/decision_app/composition.py"
    expected_composition_imports = {
        (
            "libs.models.trendlines_v4.adapters.decision_plugin",
            frozenset(
                {
                    "TRENDLINES_MODEL_SPEC",
                    "TrendlinesV4DecisionPlugin",
                    "trendlines_initialization_requirement",
                }
            ),
        )
    }
    violations: list[str] = []
    for root in production_roots:
        for path in sorted(root.rglob("*.py")):
            if path.is_relative_to(v4_root) or path.is_relative_to(canonical_root):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            observed = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if (
                            alias.name == "libs.models.trendlines_v4"
                            or alias.name.startswith("libs.models.trendlines_v4.")
                        ):
                            observed.add(
                                (alias.name, frozenset({alias.asname or alias.name}))
                            )
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                    and (
                        node.module == "libs.models.trendlines_v4"
                        or node.module.startswith("libs.models.trendlines_v4.")
                    )
                ):
                    observed.add(
                        (
                            node.module,
                            frozenset(alias.name for alias in node.names),
                        )
                    )
            if path == composition:
                if _sha256(path) != (
                    "41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763"
                ):
                    violations.append(f"{path}: composition hash changed")
                if observed != expected_composition_imports:
                    violations.append(f"{path}: unexpected V4 imports {observed!r}")
            elif observed:
                violations.append(f"{path}: unexpected V4 imports {observed!r}")
    assert not violations, "\n".join(violations)
