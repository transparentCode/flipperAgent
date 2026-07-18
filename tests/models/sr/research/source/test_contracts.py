from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta, timezone
import inspect
import math

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar as LegacySourceBar


def _bar(**changes) -> SourceBar:
    values = {
        "open_time": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "closed_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "bar_id": "binance_usdm:TAOUSDT:1d:1704067200000",
    }
    values.update(changes)
    return SourceBar(**values)


def test_legacy_source_bar_reexports_the_canonical_class_with_exact_signature() -> None:
    assert LegacySourceBar is SourceBar
    assert tuple(inspect.signature(SourceBar).parameters) == (
        "open_time",
        "closed_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bar_id",
    )
    assert tuple(SourceBar.__dataclass_fields__) == tuple(inspect.signature(SourceBar).parameters)


def test_source_bar_instances_remain_immutable_and_legacy_equivalent() -> None:
    canonical = _bar(volume=-0.0)
    legacy = LegacySourceBar(**asdict(canonical))

    assert type(canonical) is SourceBar
    assert type(legacy) is SourceBar
    assert legacy == canonical
    assert asdict(legacy) == asdict(canonical)
    assert canonical.volume == 0.0
    assert math.copysign(1.0, canonical.volume) == 1.0
    with pytest.raises(FrozenInstanceError):
        canonical.bar_id = "mutated"


def test_source_bar_requires_one_daily_utc_interval() -> None:
    with pytest.raises(ContractValidationError, match="closed_at must equal open_time \\+ 1 day"):
        _bar(closed_at=datetime(2024, 1, 3, tzinfo=timezone.utc))
    with pytest.raises(ContractValidationError):
        _bar(open_time=datetime(2024, 1, 1))
    normalized = _bar(
        open_time=datetime(2024, 1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        closed_at=datetime(2024, 1, 2, 1, tzinfo=timezone(timedelta(hours=1))),
    )
    assert normalized.open_time == datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"open": 0.0}, "open must be positive"),
        ({"low": 103.0}, "source OHLC values"),
        ({"close": 103.0}, "source OHLC values"),
        ({"volume": -0.1}, "volume must be at least 0.0"),
        ({"bar_id": "   "}, "bar_id must be a non-empty string"),
    ),
)
def test_source_bar_rejects_invalid_ohlc_volume_and_identifier(changes, message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        _bar(**changes)


def test_source_contract_imports_no_studies_and_performs_no_io(monkeypatch) -> None:
    import libs.models.sr.research.source.contracts as source_module

    parsed = ast.parse(inspect.getsource(source_module))
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
        raise AssertionError("source contract performed I/O")

    monkeypatch.setattr(builtins, "open", fail_open)
    assert _bar().bar_id == "binance_usdm:TAOUSDT:1d:1704067200000"
