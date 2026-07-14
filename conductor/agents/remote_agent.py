"""Remote web agent bridge using devspace file task packs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from conductor.agents.base import Agent
from conductor.contracts import AgentKind, AgentResult, AgentStatus, Task, TimeoutConfig, Verdict


class RemoteAgent(Agent):
    """Stage a task pack for a remote agent accessing the repo via devspace."""

    def __init__(
        self,
        role: str,
        tasks_dir: Path,
        poll_seconds: float = 30.0,
        timeout_seconds: float = 24 * 60 * 60,
        timeout_config: TimeoutConfig | None = None,
    ) -> None:
        super().__init__(role)
        self.tasks_dir = tasks_dir
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.timeout_config = timeout_config

    @property
    def kind(self) -> str:
        return AgentKind.REMOTE.value

    def stage_task(self, task: Task) -> Path:
        """Write the task pack to disk and return its directory."""
        task_dir = self.tasks_dir / task.id
        task_dir.mkdir(parents=True, exist_ok=True)

        task_md = task_dir / "task.md"
        status_json = task_dir / "status.json"
        attachments_dir = task_dir / "attachments"
        attachments_dir.mkdir(exist_ok=True)

        # Copy the source handoff into attachments for easy reading.
        if task.handoff.path and task.handoff.path.exists():
            attachment = attachments_dir / task.handoff.path.name
            attachment.write_text(task.handoff.path.read_text(encoding="utf-8"), encoding="utf-8")

        task_md.write_text(
            self._render_task_markdown(task),
            encoding="utf-8",
        )
        status_json.write_text(
            json.dumps(
                {
                    "status": AgentStatus.PENDING.value,
                    "role": self.role,
                    "stage": task.stage.value,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return task_dir

    async def dispatch(self, task: Task) -> AgentResult:
        task_dir = self.stage_task(task)
        status_path = task_dir / "status.json"
        response_path = task_dir / "response.md"

        timeout_seconds = self._timeout_for(task)
        elapsed = 0.0
        while elapsed < timeout_seconds:
            await asyncio.sleep(self.poll_seconds)
            elapsed += self.poll_seconds

            if response_path.exists():
                return self._parse_response(task, response_path, status_path)

            if status_path.exists():
                status = json.loads(status_path.read_text(encoding="utf-8"))
                if status.get("status") == AgentStatus.CANCELLED.value:
                    return AgentResult(
                        task_id=task.id,
                        verdict=Verdict.FAIL,
                        summary="Remote task was cancelled by operator.",
                    )

        # Timeout: leave the pack in place for manual recovery.
        self._write_status(status_path, AgentStatus.TIMEOUT)
        return AgentResult(
            task_id=task.id,
            verdict=Verdict.TIMEOUT,
            summary=f"Remote agent did not respond within {timeout_seconds}s. Task pack: {task_dir}",
        )

    def _timeout_for(self, task: Task) -> float:
        if self.timeout_config is None:
            return self.timeout_seconds
        cfg = self.timeout_config.for_stage(task.stage)
        return cfg.hard_timeout_seconds or self.timeout_seconds

    def _parse_response(
        self,
        task: Task,
        response_path: Path,
        status_path: Path,
    ) -> AgentResult:
        text = response_path.read_text(encoding="utf-8").strip()
        self._write_status(status_path, AgentStatus.RESPONDED)

        # Infer verdict from explicit marker or heading.
        verdict = Verdict.PASS
        upper = text.upper()
        if "FAIL" in upper[:200] or "REJECT" in upper[:200]:
            verdict = Verdict.FAIL
        elif "NEEDS_INFO" in upper[:200] or "NEEDS INFO" in upper[:200]:
            verdict = Verdict.NEEDS_INFO

        return AgentResult(
            task_id=task.id,
            verdict=verdict,
            summary=text,
            artifacts={"task_dir": str(response_path.parent)},
        )

    def _render_task_markdown(self, task: Task) -> str:
        return f"""# Remote Agent Task: {self.role}

**Task ID:** `{task.id}`
**Workflow:** `{task.workflow_id}`
**Stage:** `{task.stage.value}`
**Role:** `{self.role}`
**Created:** {datetime.now(timezone.utc).isoformat()}

## Objective

{task.handoff.goal}

## Context

{task.handoff.objective or task.handoff.body[:2000]}

## Instructions

1. Read the attached handoff in `attachments/`.
2. Perform your role responsibilities ({self.role}).
3. Write your findings to `response.md` in this directory.
4. Update `status.json` to `"status": "responded"` when done.

## Output Format

Start your `response.md` with one of:
- `PASS: <summary>`
- `FAIL: <summary>`
- `NEEDS_INFO: <summary>`

Then add detailed reasoning, concerns, and any follow-up actions.

## Acceptance Criteria

{"\n".join(f"- {c}" for c in task.handoff.acceptance_criteria) or "- Review the attached handoff and provide a clear verdict."}

## How to respond

Open this folder via devspace and write your response to `response.md`.
This task will be polled by the conductor until `response.md` appears.
"""

    @staticmethod
    def _write_status(status_path: Path, status: AgentStatus) -> None:
        data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        data["status"] = status.value
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        status_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
