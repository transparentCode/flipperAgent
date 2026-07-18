from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.windows.folds import CohortFold
from libs.models.sr.scripts.cohort_readiness.contracts import CohortFold as LegacyCohortFold


def _fold(**changes) -> CohortFold:
    values = {
        "name": "2024_q3",
        "start": datetime(2024, 7, 1, tzinfo=timezone.utc),
        "end": datetime(2024, 10, 1, tzinfo=timezone.utc),
    }
    values.update(changes)
    return CohortFold(**values)


def test_legacy_cohort_fold_reexports_the_canonical_class_with_exact_signature() -> None:
    assert LegacyCohortFold is CohortFold
    assert tuple(inspect.signature(CohortFold).parameters) == ("name", "start", "end")
    assert tuple(CohortFold.__dataclass_fields__) == ("name", "start", "end")


def test_cohort_fold_is_immutable_and_preserves_payload_format() -> None:
    fold = _fold()

    assert LegacyCohortFold(name=fold.name, start=fold.start, end=fold.end) == fold
    assert fold.to_payload() == {
        "name": "2024_q3",
        "start": "2024-07-01T00:00:00Z",
        "end": "2024-10-01T00:00:00Z",
    }
    with pytest.raises(FrozenInstanceError):
        fold.name = "mutated"


@pytest.mark.parametrize(
    "changes",
    (
        {"name": " "},
        {"start": datetime(2024, 7, 1)},
        {
            "start": datetime(2024, 10, 1, tzinfo=timezone.utc),
            "end": datetime(2024, 10, 1, tzinfo=timezone.utc),
        },
    ),
)
def test_cohort_fold_rejects_invalid_name_timestamps_and_ordering(changes) -> None:
    with pytest.raises(ContractValidationError):
        _fold(**changes)


def test_cohort_fold_normalizes_aware_timestamps_to_utc() -> None:
    fold = _fold(
        start=datetime(2024, 7, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        end=datetime(2024, 10, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    )
    assert fold.start == datetime(2024, 7, 1, tzinfo=timezone.utc)
    assert fold.end == datetime(2024, 10, 1, tzinfo=timezone.utc)


def test_fold_contract_imports_no_studies_and_performs_no_io(monkeypatch) -> None:
    import libs.models.sr.research.windows.folds as folds_module

    parsed = ast.parse(inspect.getsource(folds_module))
    imported_modules = [
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert not any(module.startswith("libs.models.sr.scripts") for module in imported_modules)
    assert not {"os", "pathlib", "subprocess"} & set(imported_modules)

    def fail_open(*args, **kwargs):
        raise AssertionError("fold contract performed I/O")

    monkeypatch.setattr(builtins, "open", fail_open)
    assert _fold().to_payload()["name"] == "2024_q3"


def test_production_modules_no_longer_import_shared_types_from_sibling_studies() -> None:
    root = Path(__file__).parents[5]
    violations: list[str] = []
    for path in sorted((root / "src/libs/models/sr").rglob("*.py")):
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            imported = {alias.name for alias in node.names}
            if (
                node.module == "libs.models.sr.scripts.baseline_trial.contracts"
                and "SourceBar" in imported
            ) or (
                node.module == "libs.models.sr.scripts.cohort_readiness.contracts"
                and "CohortFold" in imported
            ):
                violations.append(str(path.relative_to(root)))

    assert violations == []
