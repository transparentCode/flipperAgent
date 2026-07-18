from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, SREventType, ZoneSide
from libs.models.sr.scripts.context_audit.contracts import AuditResult
from libs.models.sr.research.evidence.lifecycle_utility import extraction
from libs.models.sr.scripts.lifecycle_utility.config import (
    FROZEN_SOURCE_ID,
    V10_TRACE_ID,
    V10_UPSTREAM_SOURCE_BUNDLE_ID,
)
from libs.models.sr.research.evidence.lifecycle_utility.extraction import (
    extract_first_resolution_events,
    load_validated_inputs,
)

from conftest import digest, simple_case, simple_event


def validated_audit(cases):
    audit = object.__new__(AuditResult)
    object.__setattr__(audit, "cases", tuple(cases))
    return audit


def test_first_resolution_and_zone_deduplication(make_bars, lifecycle_config):
    bars = make_bars(40, datetime(2024, 6, 15, tzinfo=timezone.utc))
    zone_one = digest("zone-one")
    event_one = simple_event(
        event_id=digest("event-one-false"),
        zone_id=zone_one,
        event_type=SREventType.FALSE_BREAKOUT,
        timestamp=bars[16].closed_at,
        bar_id=bars[16].bar_id,
    )
    later_event = simple_event(
        event_id=digest("event-one-break"),
        zone_id=zone_one,
        event_type=SREventType.BREAK_CONFIRMED,
        timestamp=bars[17].closed_at,
        bar_id=bars[17].bar_id,
    )
    case = simple_case(zone_id=zone_one, side=ZoneSide.SUPPORT, events=(later_event, event_one), available_at=bars[10].closed_at)
    audit = validated_audit((case,))
    events = extract_first_resolution_events(audit, bars, config=lifecycle_config)
    assert len(events) == 1
    assert events[0].event_class == "FALSE_BREAKOUT"
    assert events[0].effective_side is ZoneSide.SUPPORT

    duplicate_case = simple_case(zone_id=zone_one, side=ZoneSide.SUPPORT, events=(later_event,), available_at=bars[10].closed_at)
    with pytest.raises(ContractValidationError):
        extract_first_resolution_events(validated_audit((case, duplicate_case)), bars, config=lifecycle_config)


def test_break_confirmation_flips_side_and_requires_causal_bar(make_bars, lifecycle_config):
    bars = make_bars(40, datetime(2024, 6, 15, tzinfo=timezone.utc))
    zone_id = digest("break-zone")
    event = simple_event(
        event_id=digest("break-event"),
        zone_id=zone_id,
        event_type=SREventType.BREAK_CONFIRMED,
        timestamp=bars[16].closed_at,
        bar_id=bars[16].bar_id,
    )
    case = simple_case(zone_id=zone_id, side=ZoneSide.RESISTANCE, events=(event,), available_at=bars[10].closed_at)
    extracted = extract_first_resolution_events(validated_audit((case,)), bars, config=lifecycle_config)
    assert extracted[0].original_side is ZoneSide.RESISTANCE
    assert extracted[0].effective_side is ZoneSide.SUPPORT

    bad_event = simple_event(
        event_id=digest("unknown-bar-event"),
        zone_id=zone_id,
        event_type=SREventType.BREAK_CONFIRMED,
        timestamp=bars[16].closed_at,
        bar_id="unknown-bar",
    )
    with pytest.raises(ContractValidationError):
        extract_first_resolution_events(validated_audit((simple_case(zone_id=zone_id, side=ZoneSide.RESISTANCE, events=(bad_event,), available_at=bars[10].closed_at),)), bars, config=lifecycle_config)


def test_upstream_semantic_validation_precedes_frozen_context_consumption(monkeypatch, lifecycle_config, tmp_path):
    calls = []
    fake_audit = SimpleNamespace(
        audit_id=lifecycle_config.v10_audit_id,
        trace_id=V10_TRACE_ID,
        source_bundle_id=V10_UPSTREAM_SOURCE_BUNDLE_ID,
        source_id=FROZEN_SOURCE_ID,
    )
    monkeypatch.setattr(extraction, "_validate_upstream_artifact_files", lambda *args, **kwargs: calls.append("artifact-files"))
    monkeypatch.setattr(extraction, "_validate_v10_config", lambda *args, **kwargs: calls.append("v10-config") or object())
    monkeypatch.setattr(extraction, "validate_audit_bundle", lambda *args, **kwargs: calls.append("v10-audit") or fake_audit)
    monkeypatch.setattr(extraction, "load_frozen_context", lambda *args, **kwargs: calls.append("frozen-context") or object())
    monkeypatch.setattr(extraction, "_validate_source", lambda *args, **kwargs: calls.append("source") or tuple())
    monkeypatch.setattr(extraction, "_null_cells", lambda *args, **kwargs: calls.append("nulls") or tuple())

    result = load_validated_inputs(lifecycle_config, repo_root=tmp_path, implementation_commit="a" * 40)
    assert result.v10_audit is fake_audit
    assert calls == ["artifact-files", "v10-config", "v10-audit", "frozen-context", "source", "nulls"]
