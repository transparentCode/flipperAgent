from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import inspect
import math
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import canonical_json
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.scripts.atr_calibration.metrics import FirstTouchOutcome as LegacyFirstTouchOutcome


def _completed(**changes) -> FirstTouchOutcome:
    values = {
        "zone_id": "zone-1",
        "side": ZoneSide.SUPPORT,
        "first_touch_at": datetime(2024, 7, 1, tzinfo=timezone.utc),
        "touch_bar_id": "bar-1",
        "anchor_close": 100.0,
        "reference_atr_14": 2.0,
        "completed": True,
        "right_censored": False,
        "tenth_outcome_bar_closed_at": datetime(2024, 7, 11, tzinfo=timezone.utc),
        "favorable_reference_atr": 1.25,
        "adverse_reference_atr": 0.25,
        "quality_reference_atr": 1.0,
        "invalidated": False,
    }
    values.update(changes)
    return FirstTouchOutcome(**values)


def test_legacy_first_touch_reexports_canonical_class_with_exact_signature() -> None:
    fields = (
        "zone_id",
        "side",
        "first_touch_at",
        "touch_bar_id",
        "anchor_close",
        "reference_atr_14",
        "completed",
        "right_censored",
        "tenth_outcome_bar_closed_at",
        "favorable_reference_atr",
        "adverse_reference_atr",
        "quality_reference_atr",
        "invalidated",
    )
    assert LegacyFirstTouchOutcome is FirstTouchOutcome
    assert tuple(inspect.signature(FirstTouchOutcome).parameters) == fields
    assert tuple(FirstTouchOutcome.__dataclass_fields__) == fields


def test_completed_outcome_is_immutable_signed_zero_normalized_and_payload_equivalent() -> None:
    canonical = _completed(favorable_reference_atr=-0.0, adverse_reference_atr=-0.0, quality_reference_atr=0.0)
    legacy = LegacyFirstTouchOutcome(**{name: getattr(canonical, name) for name in canonical.__dataclass_fields__})

    assert legacy == canonical
    assert math.copysign(1.0, canonical.favorable_reference_atr) == 1.0
    assert canonical.to_payload() == legacy.to_payload()
    assert canonical_json(canonical.to_payload()) == canonical_json(legacy.to_payload())
    with pytest.raises(FrozenInstanceError):
        canonical.zone_id = "mutated"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"side": "support"}, "outcome.side must be exactly ZoneSide"),
        ({"completed": False, "right_censored": False}, "outcome must be exactly completed or right-censored"),
        ({"favorable_reference_atr": 1.0, "quality_reference_atr": 0.5}, "quality must equal favorable minus adverse"),
        (
            {
                "completed": False,
                "right_censored": True,
                "tenth_outcome_bar_closed_at": None,
                "favorable_reference_atr": 1.0,
                "adverse_reference_atr": None,
                "quality_reference_atr": None,
            },
            "right-censored outcome cannot contain completed metrics",
        ),
    ),
)
def test_first_touch_completed_and_censored_invariants_remain_strict(changes, message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        _completed(**changes)


def test_first_touch_normalizes_aware_timestamps_to_utc() -> None:
    outcome = _completed(
        first_touch_at=datetime(2024, 7, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        tenth_outcome_bar_closed_at=datetime(2024, 7, 11, 1, tzinfo=timezone(timedelta(hours=1))),
    )
    assert outcome.first_touch_at == datetime(2024, 7, 1, tzinfo=timezone.utc)
    assert outcome.tenth_outcome_bar_closed_at == datetime(2024, 7, 11, tzinfo=timezone.utc)


def test_first_touch_contract_imports_no_studies_or_io(monkeypatch) -> None:
    import libs.models.sr.research.metrics.first_touch as first_touch_module

    parsed = ast.parse(inspect.getsource(first_touch_module))
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

    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("outcome contract performed I/O"))
    assert _completed().to_payload()["zone_id"] == "zone-1"


def test_production_modules_do_not_import_replay_or_outcome_types_from_atr_study() -> None:
    root = Path(__file__).parents[5]
    violations: list[str] = []
    for path in sorted((root / "src/libs/models/sr").rglob("*.py")):
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            imported = {alias.name for alias in node.names}
            if (
                node.module == "libs.models.sr.scripts.atr_calibration.contracts"
                and "CandidateReplay" in imported
            ) or (
                node.module == "libs.models.sr.scripts.atr_calibration.metrics"
                and "FirstTouchOutcome" in imported
            ):
                violations.append(str(path.relative_to(root)))

    assert violations == []
