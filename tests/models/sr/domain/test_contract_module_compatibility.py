"""Compatibility locks for split SR domain contract modules."""

from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

import libs.models.sr.domain as public_domain
from libs.models.sr.domain import contracts as legacy_contracts
from libs.models.sr.domain.bars import ClosedBar, SRStateKey
from libs.models.sr.domain.candidates import CandidateLevel
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.events import SREvent, SREventType
from libs.models.sr.domain.geometry import ZoneGeometry
from libs.models.sr.domain.identity import ContractValidationError as IdentityError
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.state import SRState
from libs.models.sr.domain.zones import (
    ZoneDefinition,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        (legacy_contracts.ContractValidationError, ContractValidationError),
        (legacy_contracts.SRStateKey, SRStateKey),
        (legacy_contracts.ClosedBar, ClosedBar),
        (legacy_contracts.ZoneGeometry, ZoneGeometry),
        (legacy_contracts.CandidateLevel, CandidateLevel),
        (legacy_contracts.ZoneSide, ZoneSide),
        (legacy_contracts.ZoneStatus, ZoneStatus),
        (legacy_contracts.ZoneDefinition, ZoneDefinition),
        (legacy_contracts.ZoneRuntimeState, ZoneRuntimeState),
        (legacy_contracts.ZoneRecord, ZoneRecord),
        (legacy_contracts.SREventType, SREventType),
        (legacy_contracts.SREvent, SREvent),
        (legacy_contracts.SRState, SRState),
        (legacy_contracts.SRSnapshot, SRSnapshot),
    ],
)
def test_contracts_facade_exports_exact_canonical_objects(
    legacy: object,
    canonical: object,
) -> None:
    assert legacy is canonical


def test_public_domain_package_exports_exact_canonical_objects() -> None:
    assert public_domain.CandidateLevel is CandidateLevel
    assert public_domain.ClosedBar is ClosedBar
    assert public_domain.ContractValidationError is ContractValidationError
    assert public_domain.SREvent is SREvent
    assert public_domain.SRState is SRState
    assert public_domain.SRSnapshot is SRSnapshot
    assert public_domain.ZoneDefinition is ZoneDefinition
    assert public_domain.ZoneGeometry is ZoneGeometry
    assert public_domain.ZoneRecord is ZoneRecord
    assert public_domain.ZoneRuntimeState is ZoneRuntimeState


def test_contracts_facade_keeps_exact_public_exports() -> None:
    assert legacy_contracts.__all__ == [
        "ContractValidationError",
        "ZoneSide",
        "ZoneStatus",
        "SR_SCHEMA_VERSION",
        "SREventType",
        "SRStateKey",
        "ClosedBar",
        "ZoneGeometry",
        "CandidateLevel",
        "ZoneDefinition",
        "ZoneRuntimeState",
        "ZoneRecord",
        "SREvent",
        "SRState",
        "SRSnapshot",
        "canonical_json",
        "deterministic_hash",
    ]


def test_contract_validation_error_keeps_identity_compatibility() -> None:
    assert IdentityError is ContractValidationError
    assert legacy_contracts.ContractValidationError is ContractValidationError


@pytest.mark.parametrize(
    ("contract", "field_names"),
    [
        (SRStateKey, ("venue", "symbol", "timeframe")),
        (
            ClosedBar,
            (
                "state_key",
                "bar_id",
                "closed_at",
                "open",
                "high",
                "low",
                "close",
                "atr_at_close",
            ),
        ),
        (ZoneGeometry, ("center", "half_width")),
        (
            CandidateLevel,
            (
                "state_key",
                "side",
                "geometry",
                "source",
                "formed_at",
                "available_at",
                "atr_at_creation",
                "candidate_id",
            ),
        ),
        (
            ZoneDefinition,
            (
                "state_key",
                "side",
                "geometry",
                "source",
                "created_at",
                "available_at",
                "atr_at_creation",
                "config_hash",
                "zone_id",
            ),
        ),
        (
            ZoneRuntimeState,
            (
                "zone_id",
                "status",
                "touch_count",
                "fakeout_count",
                "pending_breach_count",
                "age_bars",
                "last_interaction_at",
                "updated_at",
            ),
        ),
        (ZoneRecord, ("definition", "runtime")),
        (SREvent, ("zone_id", "event_type", "timestamp", "price", "bar_id", "event_id")),
        (
            SRState,
            (
                "schema_version",
                "state_key",
                "config_hash",
                "last_processed_bar",
                "zones",
                "recent_bars",
            ),
        ),
        (
            SRSnapshot,
            (
                "schema_version",
                "state_key",
                "config_hash",
                "as_of",
                "zones",
                "events",
                "snapshot_id",
            ),
        ),
    ],
)
def test_moved_dataclasses_keep_field_order_and_constructor_signature(
    contract: type,
    field_names: tuple[str, ...],
) -> None:
    assert tuple(field.name for field in fields(contract)) == field_names
    assert inspect.signature(legacy_contracts.__dict__[contract.__name__]) == inspect.signature(contract)


def test_moved_enums_keep_exact_member_order_and_values() -> None:
    assert tuple((item.name, item.value) for item in ZoneSide) == (
        ("SUPPORT", "SUPPORT"),
        ("RESISTANCE", "RESISTANCE"),
    )
    assert tuple((item.name, item.value) for item in ZoneStatus) == (
        ("ACTIVE", "ACTIVE"),
        ("BREACH_PENDING", "BREACH_PENDING"),
        ("BROKEN", "BROKEN"),
        ("EXPIRED", "EXPIRED"),
    )
    assert tuple((item.name, item.value) for item in SREventType) == (
        ("CREATED", "CREATED"),
        ("TOUCHED", "TOUCHED"),
        ("BREACH_STARTED", "BREACH_STARTED"),
        ("FALSE_BREAKOUT", "FALSE_BREAKOUT"),
        ("BREAK_CONFIRMED", "BREAK_CONFIRMED"),
        ("EXPIRED", "EXPIRED"),
    )
