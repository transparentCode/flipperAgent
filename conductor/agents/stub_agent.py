"""Stub agent for dry runs and testing."""

from __future__ import annotations

from pathlib import Path

from conductor.agents.base import Agent
from conductor.contracts import AgentResult, Task, Verdict


class StubAgent(Agent):
    """Agent that immediately returns a configurable verdict.

    Useful for dry-running the conductor without spawning real AI agents.
    When ``output_dir`` is set, the stub writes a trivial handoff file for the
    next stage and returns its path.
    """

    kind = "stub"

    def __init__(
        self,
        role: str,
        verdict: Verdict = Verdict.PASS,
        summary: str = "dry-run stub pass",
        handoff_path: Path | None = None,
        output_dir: Path | None = None,
        stage_transitions: dict[str, str] | None = None,
    ) -> None:
        super().__init__(role)
        self.verdict = verdict
        self.summary = summary
        self.handoff_path = handoff_path
        self.output_dir = output_dir
        self.stage_transitions = stage_transitions or {}

    def _write_handoff(self, task: Task) -> Path | None:
        if self.output_dir is None:
            return None
        next_stage = self.stage_transitions.get(task.role)
        if next_stage is None:
            return None
        handoff_dir = self.output_dir / task.workflow_id
        handoff_dir.mkdir(parents=True, exist_ok=True)
        path = handoff_dir / f"{task.role}-to-{next_stage}.md"
        path.write_text(
            f"---\n"
            f"goal: 'Dry-run handoff from {task.role} to {next_stage}'\n"
            f"stage: '{task.role}-to-{next_stage}'\n"
            f"---\n\n"
            f"# {task.role.title()} output\n\n"
            f"Dry-run stub result for workflow {task.workflow_id}.\n",
            encoding="utf-8",
        )
        return path

    async def dispatch(self, task: Task) -> AgentResult:
        handoff_path = self.handoff_path or self._write_handoff(task)
        return AgentResult(
            task_id=task.id,
            verdict=self.verdict,
            summary=self.summary,
            handoff_path=handoff_path,
        )
