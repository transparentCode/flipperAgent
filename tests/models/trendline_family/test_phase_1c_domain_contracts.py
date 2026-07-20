from __future__ import annotations

import ast
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path
import pickle

import pytest

from libs.models.trendline.api import update_trendline_families as new_update_trendline_families
from libs.models.trendline.domain import (
    FamilyLifecycleState as DomainFamilyLifecycleState,
    FamilyRole as DomainFamilyRole,
    FamilyTransitionType as DomainFamilyTransitionType,
    TrendlineContext,
    TrendlineEvent,
    TrendlineFamily,
    TrendlineSnapshot,
    trendline_context_from_snapshot,
)
from libs.models.trendline.domain.events import FamilyTransition as DomainFamilyTransition
from libs.models.trendline.repository import InMemoryTrendlineFamilyRepository as NewRepository
from libs.models.trendline_family.api import update_trendline_families as old_update_trendline_families
from libs.models.trendline_family.contracts import (
    FamilyInteractionEvent,
    FamilyLifecycleState,
    FamilyRole,
    FamilyTransition,
    FamilyTransitionType,
    TrendlineFamilySnapshot,
    TrendlineFamilyState,
)
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository as OldRepository

from .support import candidate_ohlcv, resolved_config


_DOMAIN_ROOT = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline" / "domain"
_HISTORICAL_PICKLE = Path(__file__).parent / "fixtures" / "pre_phase_1b_family_role.pickle"
_FORBIDDEN_DOMAIN_IMPORTS = (
    "libs.models.trendline.storage",
    "libs.models.trendline.research",
    "libs.models.trendline.visualization",
    "libs.models.trendline.api",
    "libs.models.trendline_family",
    "libs.trendlines",
    "app.trendlines",
)


def _domain_imports() -> set[str]:
    imports: set[str] = set()
    for path in _DOMAIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_domain_aliases_preserve_contract_and_enum_identity() -> None:
    assert TrendlineFamily is TrendlineFamilyState
    assert TrendlineSnapshot is TrendlineFamilySnapshot
    assert TrendlineEvent is FamilyInteractionEvent
    assert DomainFamilyTransition is FamilyTransition
    assert DomainFamilyRole is FamilyRole
    assert DomainFamilyLifecycleState is FamilyLifecycleState
    assert DomainFamilyTransitionType is FamilyTransitionType
    assert tuple(DomainFamilyRole) == tuple(FamilyRole)
    assert tuple(DomainFamilyLifecycleState) == tuple(FamilyLifecycleState)
    assert tuple(DomainFamilyTransitionType) == tuple(FamilyTransitionType)


def test_snapshot_and_event_field_default_and_serialization_parity(snapshot) -> None:
    assert tuple(field.name for field in fields(TrendlineSnapshot)) == tuple(
        field.name for field in fields(TrendlineFamilySnapshot)
    )
    assert tuple((field.name, field.default) for field in fields(TrendlineEvent)) == tuple(
        (field.name, field.default) for field in fields(FamilyInteractionEvent)
    )
    assert TrendlineSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()
    assert snapshot.transitions[0].to_dict() == DomainFamilyTransition.from_dict(
        snapshot.transitions[0].to_dict()
    ).to_dict()


def test_historical_pre_migration_pickle_path_loads_to_canonical_enum() -> None:
    payload = _HISTORICAL_PICKLE.read_bytes()
    assert pickle.loads(payload) is DomainFamilyRole


def test_context_is_immutable_ordered_and_snapshot_equivalent(snapshot, family_state, timestamp) -> None:
    second = replace(family_state, family_id="family-2")
    context = TrendlineContext(
        asset="BTCUSDT",
        timeframe="4h",
        as_of=timestamp,
        families=(family_state, second),
        events=(),
    )
    assert context.families == (family_state, second)
    assert context.to_dict()["as_of"] == timestamp.isoformat()
    with pytest.raises(AttributeError):
        context.asset = "ETHUSDT"  # type: ignore[misc]
    with pytest.raises(Exception, match="deterministic"):
        TrendlineContext(
            asset="BTCUSDT",
            timeframe="4h",
            as_of=timestamp,
            families=(second, family_state),
            events=(),
        )
    with pytest.raises(Exception, match="known after"):
        TrendlineContext(
            asset="BTCUSDT",
            timeframe="4h",
            as_of=timestamp,
            families=(replace(family_state, updated_at=timestamp + timedelta(hours=1)),),
            events=(),
        )
    snapshot_context = trendline_context_from_snapshot(snapshot)
    assert snapshot_context.as_of == snapshot.timestamp
    assert snapshot_context.families == snapshot.active_families + snapshot.dormant_families
    assert snapshot_context.events == snapshot.interaction_events


def test_old_and_new_api_outputs_remain_identical_after_domain_layer() -> None:
    frame = candidate_ohlcv()
    config = resolved_config()
    old_output = old_update_trendline_families(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        repository=OldRepository(),
        config=config,
    )
    new_output = new_update_trendline_families(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        repository=NewRepository(),
        config=config,
    )
    assert old_output.to_dict() == new_output.to_dict()


def test_domain_has_no_runtime_or_presentation_dependencies() -> None:
    imports = _domain_imports()
    assert not {value for value in imports if value.startswith(_FORBIDDEN_DOMAIN_IMPORTS)}
