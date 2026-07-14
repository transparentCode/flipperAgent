"""Tests for human checkpoint gates and workflow engine gate logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from conductor.contracts import (
    AgentKind,
    AgentResult,
    AgentStatus,
    GateDecision,
    GatePolicy,
    Handoff,
    Task,
    Verdict,
    WorkflowStage,
    WorkflowState,
)
from conductor.settings import ConductorSettings
from conductor.squad_client import SquadClient
from conductor.storage import ConductorStorage
from conductor.workflow import WorkflowEngine


class FakeAgent:
    """Test agent that returns a pre-configured result."""

    kind = AgentKind.LOCAL.value

    def __init__(self, role: str, result: AgentResult) -> None:
        self.role = role
        self.result = result

    async def dispatch(self, task: Task) -> AgentResult:
        task.status = AgentStatus.RUNNING
        return self.result


@pytest.fixture
def tmp_settings(tmp_path: Path) -> ConductorSettings:
    return ConductorSettings(
        workspace_root=tmp_path,
        plans_dir=tmp_path / "plans",
        conductor_dir=tmp_path / ".conductor",
        squad_db=tmp_path / ".squad/messages.db",
        squad_binary="squad",
        remote_poll_seconds=1.0,
        remote_timeout_seconds=60.0,
        default_remote_roles=(),
        log_level="INFO",
        gate_policy=GatePolicy(
            before_code=True,
            before_approval=True,
            force_human_if_changed_paths=["src/libs/risk"],
            force_human_if_keywords=["leverage"],
        ),
        soft_timeout_seconds=300.0,
        hard_timeout_seconds=1800.0,
        max_retries=2,
        max_stalls=2,
    )


@pytest.fixture
def engine(tmp_settings: ConductorSettings) -> WorkflowEngine:
    storage = ConductorStorage(tmp_settings.conductor_dir / "conductor.db")
    squad_client = SquadClient("squad", cwd=tmp_settings.workspace_root)
    return WorkflowEngine(tmp_settings, storage, squad_client, {})


def make_handoff(goal: str = "Test", stage: str = "architect-to-coder") -> Handoff:
    return Handoff(goal=goal, stage=stage)


@pytest.mark.asyncio
async def test_architect_pass_pauses_at_human_ready(engine: WorkflowEngine, tmp_settings: ConductorSettings) -> None:
    seed = make_handoff(stage="researcher-to-architect")
    state = engine.create_workflow("test", metadata={"trigger": "test"})
    state.handoffs[WorkflowStage.ARCHITECT] = [Path("/tmp/fake.md")]
    state.current_stage = WorkflowStage.ARCHITECT
    engine.storage.save_workflow(state)

    fake_agent = FakeAgent(
        "architect",
        AgentResult(task_id="t-1", verdict=Verdict.PASS, handoff_path=Path("/tmp/fake.md")),
    )
    engine.agent_factory = {"architect": fake_agent}

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_READY
    assert state.pending_gate == WorkflowStage.HUMAN_READY
    assert state.gate_target_stage == WorkflowStage.CODE


@pytest.mark.asyncio
async def test_human_approve_advances_to_code(engine: WorkflowEngine) -> None:
    seed = make_handoff(stage="researcher-to-architect")
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.ARCHITECT] = [Path("/tmp/fake.md")]
    state.current_stage = WorkflowStage.ARCHITECT
    engine.storage.save_workflow(state)

    fake_agent = FakeAgent(
        "architect",
        AgentResult(task_id="t-1", verdict=Verdict.PASS, handoff_path=Path("/tmp/fake.md")),
    )
    engine.agent_factory = {"architect": fake_agent}

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_READY

    state = engine.apply_human_decision(state.id, GateDecision.APPROVED)
    assert state.current_stage == WorkflowStage.CODE
    assert state.pending_gate is None


@pytest.mark.asyncio
async def test_human_reject_returns_to_architect(engine: WorkflowEngine) -> None:
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.ARCHITECT] = [Path("/tmp/fake.md")]
    state.current_stage = WorkflowStage.ARCHITECT
    engine.storage.save_workflow(state)

    fake_agent = FakeAgent(
        "architect",
        AgentResult(task_id="t-1", verdict=Verdict.PASS),
    )
    engine.agent_factory = {"architect": fake_agent}

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_READY

    state = engine.apply_human_decision(state.id, GateDecision.REJECTED, reason="Scope too broad")
    assert state.current_stage == WorkflowStage.ARCHITECT
    assert state.gate_decision == GateDecision.REJECTED


def test_apply_requeue_requires_target(engine: WorkflowEngine) -> None:
    state = engine.create_workflow("test")
    state.current_stage = WorkflowStage.HUMAN_READY
    state.pending_gate = WorkflowStage.HUMAN_READY
    engine.storage.save_workflow(state)

    with pytest.raises(ValueError, match="--to stage is required"):
        engine.apply_human_decision(state.id, GateDecision.REQUEUED)


def test_apply_abort_stops_workflow(engine: WorkflowEngine) -> None:
    state = engine.create_workflow("test")
    state.current_stage = WorkflowStage.HUMAN_READY
    state.pending_gate = WorkflowStage.HUMAN_READY
    engine.storage.save_workflow(state)

    state = engine.apply_human_decision(state.id, GateDecision.ABORTED, reason="Too risky")
    assert state.current_stage == WorkflowStage.HUMAN_ABORTED


def test_gate_policy_keyword_trigger() -> None:
    policy = GatePolicy(force_human_if_keywords=["leverage"])
    handoff = make_handoff(goal="Adjust leverage scaling")
    assert policy.requires_gate(WorkflowStage.ARCHITECT, handoff) is True


def test_gate_policy_path_trigger() -> None:
    policy = GatePolicy(force_human_if_changed_paths=["src/libs/risk"])
    handoff = make_handoff(goal="Safe refactor")
    assert policy.requires_gate(WorkflowStage.ARCHITECT, handoff, changed_paths=["src/libs/risk/sizer.py"]) is True


def test_generate_checkpoint(tmp_settings: ConductorSettings) -> None:
    storage = ConductorStorage(tmp_settings.conductor_dir / "conductor.db")
    engine = WorkflowEngine(tmp_settings, storage, SquadClient("squad"), {})
    state = engine.create_workflow("checkpoint-test")
    state.current_stage = WorkflowStage.HUMAN_READY
    state.pending_gate = WorkflowStage.HUMAN_READY
    state.gate_target_stage = WorkflowStage.CODE
    state.gate_reason = "Architecture approval required"
    storage.save_workflow(state)

    checkpoint = engine.generate_checkpoint(state.id)
    assert checkpoint.run_id == state.id
    assert checkpoint.current_stage == WorkflowStage.HUMAN_READY
    md = checkpoint.to_markdown()
    assert "flipper-conductor approve" in md
    assert "Architecture approval required" in md
    assert state.id in md
