"""Tests for LocalAgent result parsing and timeout handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from conductor.agents.local_agent import LocalAgent
from conductor.contracts import AgentResult, Handoff, Task, Verdict
from conductor.squad_client import SquadClient


def make_task(task_id: str = "t-1") -> Task:
    return Task(
        id=task_id,
        workflow_id="wf-1",
        stage="architect",  # type: ignore[arg-type]
        role="architect",
        kind="local",  # type: ignore[arg-type]
        handoff=Handoff(goal="test", stage="orchestrator-to-architect"),
    )


@pytest.fixture
def local_agent(tmp_path: Path) -> LocalAgent:
    return LocalAgent(
        role="architect",
        cli_command=["echo"],
        squad_client=SquadClient("squad", cwd=tmp_path),
        output_dir=tmp_path,
    )


def test_parse_result_json_pass(local_agent: LocalAgent) -> None:
    task = make_task()
    result = local_agent._parse_result(
        task,
        '{"verdict": "pass", "summary": "looks good", "handoff_path": "/tmp/h.md"}',
    )
    assert result == AgentResult(
        task_id=task.id,
        verdict=Verdict.PASS,
        summary="looks good",
        handoff_path=Path("/tmp/h.md"),
    )


def test_parse_result_json_fail(local_agent: LocalAgent) -> None:
    task = make_task()
    result = local_agent._parse_result(
        task,
        '{"verdict": "fail", "summary": "broken"}',
    )
    assert result.verdict == Verdict.FAIL
    assert result.summary == "broken"


def test_parse_result_plain_pass(local_agent: LocalAgent) -> None:
    task = make_task()
    result = local_agent._parse_result(task, "PASS: all good")
    assert result.verdict == Verdict.PASS
    assert result.summary == "PASS: all good"


def test_parse_result_plain_fail(local_agent: LocalAgent) -> None:
    task = make_task()
    result = local_agent._parse_result(task, "something went wrong")
    assert result.verdict == Verdict.FAIL
    assert result.summary == "something went wrong"
