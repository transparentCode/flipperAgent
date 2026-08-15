from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.decision_app.domain.identity import binding_config_fingerprint
from libs.contracts.decision import (
    CausalBarView,
    DataRequirement,
    DecisionContext,
    DecisionModelPlugin,
    FeatureSnapshot,
    ModelArtifact,
    ModelDecision,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _context() -> DecisionContext:
    bar = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(hours=1),
        market_as_of=BASE + timedelta(hours=1),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="BTCUSDT:1h",
        binding_id="boundary-1",
        market_as_of=bar.market_as_of,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=True,
        causal_bar_views={"1h": (bar,)},
        shared_features={
            "close": FeatureSnapshot(
                name="close",
                version="1",
                market_as_of=bar.market_as_of,
                value=Decimal(105),
            )
        },
        external_data={},
        upstream_artifacts={},
        provenance={},
    )


class AnalyticalPlugin:
    spec = ModelSpec(
        name="BoundaryModel",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="boundary.v1",
    )

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[DataRequirement, ...]:
        return (
            DataRequirement(
                concept="OPEN_INTEREST",
            ),
        )

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type="boundary",
                value={
                    "level": context.decision_bar.close
                    if context.decision_bar
                    else None
                },
            )
        )


class StatefulPlugin:
    spec = ModelSpec(
        name="StatefulModel",
        version="1",
        stateful=True,
        output_kind="decision_capable",
        produces_artifact_type="stateful.v1",
        intrinsic_data_requirements=(
            DataRequirement(
                concept="OPEN_INTEREST",
                required=True,
                replay_support_required=True,
            ),
        ),
    )

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[DataRequirement, ...]:
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        decision = ModelDecision(
            binding_id=context.binding_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            signal_time=context.market_as_of,
            direction_hint=1,
            conviction=0.5,
        )
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type="state",
                value={"state": state_snapshot or {}},
            ),
            decision=decision,
            proposed_next_state={"seen": True},
        )


def test_stateless_analytical_and_stateful_plugins_share_one_structural_protocol() -> (
    None
):
    analytical = AnalyticalPlugin()
    stateful = StatefulPlugin()
    assert isinstance(analytical, DecisionModelPlugin)
    assert isinstance(stateful, DecisionModelPlugin)
    assert all(
        isinstance(requirement, DataRequirement)
        for requirement in analytical.data_requests(_context())
    )
    assert analytical.evaluate(_context()).decision is None
    assert stateful.evaluate(_context()).decision is not None


def test_plugin_contract_has_no_infrastructure_imports() -> None:
    import ast
    from pathlib import Path

    paths = (
        Path("src/libs/contracts/decision.py"),
        Path("src/apps/decision_app/domain/contracts.py"),
        Path("src/apps/decision_app/domain/identity.py"),
    )
    pure_plugin_paths = {
        Path("src/libs/contracts/decision.py"),
        Path("src/apps/decision_app/domain/identity.py"),
    }
    forbidden = {"asyncpg", "valkey", "redis", "httpx", "requests"}
    for path in paths:
        tree = ast.parse(path.read_text())
        imports = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not imports & forbidden, (path, imports & forbidden)
        if path in pure_plugin_paths:
            assert "apps" not in imports, (path, imports)


def test_identity_helper_is_used_for_synthetic_binding_provenance() -> None:
    fingerprint = binding_config_fingerprint({"threshold": Decimal("1.0")})
    assert len(fingerprint) == 64
