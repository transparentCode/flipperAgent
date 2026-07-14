"""Tests for conductor SQLite storage."""

from __future__ import annotations

from pathlib import Path


from conductor.contracts import AgentKind, Handoff, Task, WorkflowStage, WorkflowState
from conductor.storage import ConductorStorage


def test_save_and_load_workflow(tmp_path: Path) -> None:
    db = ConductorStorage(tmp_path / "conductor.db")
    state = WorkflowState(
        id="wf-1",
        name="test workflow",
        current_stage=WorkflowStage.CODE,
    )
    db.save_workflow(state)
    loaded = db.load_workflow("wf-1")
    assert loaded is not None
    assert loaded.name == "test workflow"
    assert loaded.current_stage == WorkflowStage.CODE


def test_save_and_load_task(tmp_path: Path) -> None:
    db = ConductorStorage(tmp_path / "conductor.db")
    handoff = Handoff(goal="G", stage="architect-to-coder")
    task = Task(
        id="t-1",
        workflow_id="wf-1",
        stage=WorkflowStage.CODE,
        role="coder",
        kind=AgentKind.LOCAL,
        handoff=handoff,
    )
    db.save_task(task)
    loaded_tasks = db.load_tasks("wf-1")
    assert len(loaded_tasks) == 1
    assert loaded_tasks[0].role == "coder"
    assert loaded_tasks[0].kind == AgentKind.LOCAL
