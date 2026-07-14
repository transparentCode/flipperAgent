"""Tests for conductor contracts."""

from __future__ import annotations



from conductor.contracts import AgentKind, Handoff, Task, Verdict, WorkflowStage


def test_handoff_parses_coerced_tags() -> None:
    handoff = Handoff(
        goal="Test",
        stage="architect-to-coder",
        tags="alpha, beta, gamma",
    )
    assert handoff.tags == ["alpha", "beta", "gamma"]


def test_handoff_ready_status() -> None:
    assert Handoff(goal="G", stage="s", status="Ready").is_ready()
    assert Handoff(goal="G", stage="s", status="Approved").is_ready()
    assert not Handoff(goal="G", stage="s", status="Draft").is_ready()


def test_task_defaults() -> None:
    task = Task(
        id="t-1",
        workflow_id="wf-1",
        stage=WorkflowStage.CODE,
        role="coder",
        kind=AgentKind.LOCAL,
        handoff=Handoff(goal="G", stage="architect-to-coder"),
    )
    assert task.status.value == "pending"
    assert task.verdict is None


def test_verdict_enum() -> None:
    assert Verdict.PASS.value == "pass"
    assert Verdict.FAIL.value == "fail"
