"""Compatibility locks for split SR evaluation contract modules."""

from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from libs.models.sr.evaluation import contracts as legacy_contracts
from libs.models.sr.evaluation.observations import (
    ObservedEvent,
    SnapshotReference,
    ZoneObservation,
    ZoneRenderKind,
)
from libs.models.sr.evaluation.traces import SREvaluationTrace


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        (legacy_contracts.SnapshotReference, SnapshotReference),
        (legacy_contracts.ObservedEvent, ObservedEvent),
        (legacy_contracts.ZoneObservation, ZoneObservation),
        (legacy_contracts.SREvaluationTrace, SREvaluationTrace),
        (legacy_contracts.ZoneRenderKind, ZoneRenderKind),
    ],
)
def test_contracts_facade_exports_exact_canonical_objects(
    legacy: object,
    canonical: object,
) -> None:
    assert legacy is canonical


@pytest.mark.parametrize(
    ("contract", "field_names"),
    [
        (SnapshotReference, ("snapshot_id", "as_of")),
        (
            ObservedEvent,
            (
                "snapshot_id",
                "snapshot_as_of",
                "event_id",
                "zone_id",
                "event_type",
                "timestamp",
                "price",
                "bar_id",
            ),
        ),
        (
            ZoneObservation,
            (
                "schema_version",
                "state_key",
                "config_hash",
                "snapshot_id",
                "as_of",
                "zone_id",
                "side",
                "source",
                "atr_at_creation",
                "render_kind",
                "lower_bound",
                "center",
                "upper_bound",
                "created_at",
                "available_at",
                "visible_from",
                "visible_until",
                "status",
                "touch_count",
                "fakeout_count",
                "pending_breach_count",
                "age_bars",
                "last_interaction_at",
                "runtime_updated_at",
                "observation_id",
            ),
        ),
        (
            SREvaluationTrace,
            (
                "schema_version",
                "state_key",
                "config_hash",
                "field_provenance",
                "snapshots",
                "zone_observations",
                "events",
                "trace_id",
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


def test_render_kind_keeps_exact_member_order_and_values() -> None:
    assert tuple((item.name, item.value) for item in ZoneRenderKind) == (
        ("LINE", "LINE"),
        ("BAND", "BAND"),
    )
