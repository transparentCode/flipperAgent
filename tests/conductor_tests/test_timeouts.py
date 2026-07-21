"""Tests for timeout/stall handling in LocalAgent, RemoteAgent, and WorkflowEngine."""

from __future__ import annotations

from pathlib import Path

import pytest

from conductor.contracts import (
    AgentKind,
    AgentResult,
    AgentStatus,
    GateDecision,
    GatePolicy,
    Task,
    TimeoutConfig,
    Verdict,
    WorkflowStage,
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


class CountingFakeAgent:
    """Test agent that returns timeout N times then a pass result."""

    kind = AgentKind.LOCAL.value

    def __init__(self, role: str, timeouts_before_pass: int, pass_result: AgentResult) -> None:
        self.role = role
        self.timeouts_before_pass = timeouts_before_pass
        self.pass_result = pass_result
        self.calls = 0

    async def dispatch(self, task: Task) -> AgentResult:
        task.status = AgentStatus.RUNNING
        self.calls += 1
        if self.calls <= self.timeouts_before_pass:
            return AgentResult(task_id=task.id, verdict=Verdict.TIMEOUT, summary=f"timeout {self.calls}")
        return self.pass_result


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
        timeout_config=TimeoutConfig(
            soft_timeout_seconds=1.0,
            hard_timeout_seconds=2.0,
            max_retry_count=1,
            max_stall_count=1,
        ),
        agent_commands={
            "orchestrator": ["stub"],
            "architect": ["stub"],
            "coder": ["stub"],
        },
        workflow_config=_workflow_config(),
    )


def _workflow_config():
    from conductor.settings import WorkflowConfig
    return WorkflowConfig(
        role_for_stage={
            WorkflowStage.INTAKE: "orchestrator",
            WorkflowStage.RESEARCH: "architect",
            WorkflowStage.ARCHITECT: "architect",
            WorkflowStage.CODE: "coder",
            WorkflowStage.REVIEW: "orchestrator",
            WorkflowStage.APPROVAL: "orchestrator",
        },
        next_stage={
            WorkflowStage.INTAKE: WorkflowStage.ARCHITECT,
            WorkflowStage.RESEARCH: WorkflowStage.ARCHITECT,
            WorkflowStage.ARCHITECT: WorkflowStage.CODE,
            WorkflowStage.CODE: WorkflowStage.REVIEW,
            WorkflowStage.REVIEW: WorkflowStage.DONE,
            WorkflowStage.APPROVAL: WorkflowStage.DONE,
            WorkflowStage.DONE: WorkflowStage.DONE,
        },
        gate_stage_for={
            WorkflowStage.ARCHITECT: WorkflowStage.HUMAN_READY,
            WorkflowStage.REVIEW: WorkflowStage.HUMAN_REVIEW,
        },
        gate_target={
            WorkflowStage.HUMAN_READY: WorkflowStage.CODE,
            WorkflowStage.HUMAN_REVIEW: WorkflowStage.DONE,
        },
        retry_stage={
            WorkflowStage.REVIEW: WorkflowStage.CODE,
            WorkflowStage.APPROVAL: WorkflowStage.ARCHITECT,
            WorkflowStage.CODE: WorkflowStage.ARCHITECT,
        },
        retry_stage_for_gate={
            WorkflowStage.HUMAN_READY: WorkflowStage.ARCHITECT,
            WorkflowStage.HUMAN_REVIEW: WorkflowStage.CODE,
        },
        stub_stage_transitions={
            "architect": "coder",
            "coder": "orchestrator",
            "orchestrator": "done",
        },
    )


@pytest.fixture
def engine(tmp_settings: ConductorSettings) -> WorkflowEngine:
    storage = ConductorStorage(tmp_settings.conductor_dir / "conductor.db")
    squad_client = SquadClient("squad", cwd=tmp_settings.workspace_root)
    return WorkflowEngine(tmp_settings, storage, squad_client, {})


@pytest.fixture
def engine_no_gates(tmp_path: Path) -> WorkflowEngine:
    settings = ConductorSettings(
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
            before_code=False,
            before_approval=False,
            auto_advance_low_risk_architect_pass=True,
            auto_advance_low_risk_review_pass=True,
        ),
        timeout_config=TimeoutConfig(
            soft_timeout_seconds=1.0,
            hard_timeout_seconds=2.0,
            max_retry_count=2,
            max_stall_count=1,
        ),
        agent_commands={
            "orchestrator": ["stub"],
            "architect": ["stub"],
            "coder": ["stub"],
        },
        workflow_config=_workflow_config(),
    )
    storage = ConductorStorage(settings.conductor_dir / "conductor.db")
    squad_client = SquadClient("squad", cwd=settings.workspace_root)
    return WorkflowEngine(settings, storage, squad_client, {})


def _write_handoff(path: Path, goal: str = "Test", stage: str = "architect-to-coder") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ngoal: '{goal}'\nstage: '{stage}'\n---\n\n# Test\n\n## Objective\nTest objective.\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_timeout_result_requeues_stage(engine_no_gates: WorkflowEngine, tmp_path: Path) -> None:
    code_handoff = _write_handoff(tmp_path / "code.md", stage="architect-to-coder")
    review_handoff = _write_handoff(tmp_path / "review.md", stage="coder-to-orchestrator")
    state = engine_no_gates.create_workflow("test")
    state.handoffs[WorkflowStage.CODE] = [code_handoff]
    state.current_stage = WorkflowStage.CODE
    engine_no_gates.storage.save_workflow(state)

    engine_no_gates.agent_factory = {
        "coder": CountingFakeAgent(
            "coder",
            timeouts_before_pass=1,
            pass_result=AgentResult(task_id="t-1", verdict=Verdict.PASS, handoff_path=review_handoff),
        ),
        "orchestrator": FakeAgent("orchestrator", AgentResult(task_id="t-2", verdict=Verdict.PASS)),
    }

    state = await engine_no_gates.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.DONE
    assert state.metadata["stage_retries"]["code"] == 1


@pytest.mark.asyncio
async def test_timeout_exhaustion_moves_to_human_blocked(engine: WorkflowEngine, tmp_path: Path) -> None:
    handoff_path = _write_handoff(tmp_path / "code.md", stage="architect-to-coder")
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.CODE] = [handoff_path]
    state.current_stage = WorkflowStage.CODE
    state.metadata["stage_retries"] = {"code": 1}
    engine.storage.save_workflow(state)

    fake_agent = FakeAgent("coder", AgentResult(task_id="t-1", verdict=Verdict.TIMEOUT, summary="timed out"))
    engine.agent_factory = {"coder": fake_agent}

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_BLOCKED
    assert "timed out" in (state.gate_reason or "")


@pytest.mark.asyncio
async def test_human_gate_does_not_timeout(engine: WorkflowEngine, tmp_path: Path) -> None:
    handoff_path = _write_handoff(tmp_path / "architect.md", stage="orchestrator-to-architect")
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.ARCHITECT] = [handoff_path]
    state.current_stage = WorkflowStage.ARCHITECT
    engine.storage.save_workflow(state)

    fake_agent = FakeAgent(
        "architect",
        AgentResult(task_id="t-1", verdict=Verdict.PASS, handoff_path=handoff_path),
    )
    engine.agent_factory = {"architect": fake_agent}

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_READY

    # Human gates remain paused; no timeout logic should act on them.
    assert WorkflowStage.HUMAN_READY not in state.metadata.get("stage_retries", {})


@pytest.mark.asyncio
async def test_remote_agent_timeout(engine: WorkflowEngine, tmp_path: Path) -> None:
    from conductor.agents.remote_agent import RemoteAgent

    settings = engine.settings
    remote_agent = RemoteAgent(
        "orchestrator",
        tasks_dir=settings.remote_tasks_dir(),
        poll_seconds=0.1,
        timeout_seconds=0.2,
    )
    engine.agent_factory = {"orchestrator": remote_agent}

    handoff_path = _write_handoff(tmp_path / "review.md", stage="coder-to-orchestrator")
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.REVIEW] = [handoff_path]
    state.current_stage = WorkflowStage.REVIEW
    engine.storage.save_workflow(state)

    state = await engine.run_workflow(state.id)
    assert state.current_stage == WorkflowStage.HUMAN_BLOCKED
    assert state.metadata["stage_retries"]["review"] == 2


def test_timeout_config_stage_override() -> None:
    cfg = TimeoutConfig(
        soft_timeout_seconds=100.0,
        hard_timeout_seconds=200.0,
        stage_timeouts={
            "code": {"soft_timeout_seconds": 300.0, "hard_timeout_seconds": 600.0},
        },
    )
    default_cfg = cfg.for_stage(WorkflowStage.INTAKE)
    assert default_cfg.soft_timeout_seconds == 100.0
    assert default_cfg.hard_timeout_seconds == 200.0

    code_cfg = cfg.for_stage(WorkflowStage.CODE)
    assert code_cfg.soft_timeout_seconds == 300.0
    assert code_cfg.hard_timeout_seconds == 600.0


def test_abort_prevents_timeout_loop(engine: WorkflowEngine, tmp_path: Path) -> None:
    handoff_path = _write_handoff(tmp_path / "architect.md", stage="orchestrator-to-architect")
    state = engine.create_workflow("test")
    state.handoffs[WorkflowStage.ARCHITECT] = [handoff_path]
    state.current_stage = WorkflowStage.HUMAN_READY
    state.pending_gate = WorkflowStage.HUMAN_READY
    state.metadata["stage_retries"] = {"code": 5}
    engine.storage.save_workflow(state)

    state = engine.apply_human_decision(state.id, decision=GateDecision.ABORTED, reason="Too risky")
    assert state.current_stage == WorkflowStage.HUMAN_ABORTED
