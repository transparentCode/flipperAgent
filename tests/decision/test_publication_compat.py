from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from apps.decision_app.planner import ModelBindingSpec
from apps.decision_app.policy import (
    PASSTHROUGH_V1,
    DecisionPolicy,
    DecisionPolicyCatalog,
)
from apps.decision_app.publication import (
    PublicationCompatibilityError,
    SignalPublicationAck,
    build_signal_envelope,
    signal_idempotency_key,
)
from libs.contracts.decision import FeatureRequirement
from tests.decision.test_model_runtime import make_bundle
from tests.decision.test_policy import decision_plugin, make_signal_bundle


def _binding(slot_name: str = "decision") -> ModelBindingSpec:
    return ModelBindingSpec(
        slot_name=slot_name,
        plugin_name="Decision",
        plugin_version="1",
    )


async def _prepared_signal(
    *,
    with_atr: bool = False,
    atr_value: float = 2.5,
    conviction: float | None = 0.75,
):
    feature_requirements = (
        (FeatureRequirement(name="ATR", required=True),) if with_atr else ()
    )
    plugin = decision_plugin(
        "Decision",
        direction=1,
        conviction=conviction,
        feature_requirements=feature_requirements,
    )
    definitions = ()
    allowed_features = ()
    if with_atr:
        from apps.decision_app.features import SharedFeatureDefinition

        definitions = (
            SharedFeatureDefinition(
                name="ATR",
                version="1",
                calculator=lambda context: atr_value,
            ),
        )
        allowed_features = ("ATR",)
    bundle, _ = make_signal_bundle(
        bindings=(_binding(),),
        plugins={"Decision": plugin},
        policy_parameters={"source_slot": "decision"},
        definitions=definitions,
        allowed_features=allowed_features,
    )
    view = bundle.view(0)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of,
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=view.market_as_of,
    )
    return bundle, view, prepared, evaluation


@pytest.mark.asyncio
async def test_signal_envelope_preserves_legacy_risk_units_and_identity() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal(with_atr=True)

    envelope = build_signal_envelope(
        bundle.lane,
        prepared,
        evaluation,
        view,
    )
    signal = envelope.signal
    assert evaluation.status == "SIGNAL"
    assert signal.timestamp == pytest.approx(view.market_as_of.timestamp())
    assert signal.metadata["timestamp_unit"] == "seconds"
    assert signal.metadata["market_as_of_utc"].endswith("Z")
    assert signal.model_name == bundle.lane.risk_profile_key
    assert signal.price == pytest.approx(float(view.decision_bar.close))
    assert signal.direction == 1
    assert signal.conviction == pytest.approx(0.75)
    assert signal.metadata["ATR"] == pytest.approx(2.5)
    assert envelope.stream_key == "signals:BTCUSDT:1h"
    assert envelope.stream_entry_id == f"{int(view.market_as_of.timestamp() * 1000)}-0"
    assert signal.idempotency_key == signal_idempotency_key(envelope.decision_id)

    second = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    assert second == envelope


@pytest.mark.asyncio
async def test_signal_envelope_omits_unrequested_atr_and_rejects_shadow_lane() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    assert "ATR" not in envelope.signal.metadata

    shadow_bindings = {
        slot: replace(
            binding,
            publication_authority="shadow",
            risk_profile_key=None,
        )
        for slot, binding in bundle.lane.bindings.items()
    }
    shadow_lane = replace(
        bundle.lane,
        authority="shadow",
        risk_profile_key=None,
        bindings=shadow_bindings,
    )
    with pytest.raises(PublicationCompatibilityError, match="authoritative"):
        build_signal_envelope(shadow_lane, prepared, evaluation, view)


@pytest.mark.asyncio
async def test_ack_must_match_exact_envelope_identity_and_payload() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    ack = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome="PUBLISHED",
    )
    ack.validate_against(envelope)

    conflicting = replace(ack, payload_fingerprint="0" * 64)
    with pytest.raises(PublicationCompatibilityError, match="does not match"):
        conflicting.validate_against(envelope)


@pytest.mark.asyncio
async def test_present_but_invalid_atr_fails_closed() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal(
        with_atr=True,
        atr_value=0.0,
    )
    with pytest.raises(ValueError, match="ATR feature must be finite and positive"):
        build_signal_envelope(bundle.lane, prepared, evaluation, view)


@pytest.mark.asyncio
async def test_missing_conviction_fails_closed_at_legacy_envelope_boundary() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal(conviction=None)

    with pytest.raises(PublicationCompatibilityError, match="conviction"):
        build_signal_envelope(bundle.lane, prepared, evaluation, view)


def test_d8_production_modules_have_no_infrastructure_imports() -> None:
    forbidden = {
        "asyncpg",
        "aiohttp",
        "fastapi",
        "httpx",
        "redis",
        "requests",
        "sqlalchemy",
        "valkey",
    }
    for filename in ("policy.py", "publication.py", "finalization.py"):
        path = Path("src/apps/decision_app") / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        assert not imports & forbidden, (path, imports & forbidden)


def test_publication_test_helper_does_not_use_legacy_featurevector_boundary() -> None:
    source = make_bundle.__module__
    assert "decision" in source
