"""Local CLI agent runner using Squad messaging with timeout/stall handling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import json

from conductor.agents.base import Agent
from conductor.contracts import AgentKind, AgentResult, Task, TimeoutConfig, Verdict
from conductor.squad_client import SquadClient, SquadClientError

if TYPE_CHECKING:
    from conductor.storage import ConductorStorage


class LocalAgent(Agent):
    """Run a local coding agent via its native CLI and Squad task queue."""

    def __init__(
        self,
        role: str,
        cli_command: list[str],
        squad_client: SquadClient,
        one_shot: bool = False,
        startup_timeout: float = 60.0,
        poll_interval: float = 5.0,
        timeout_config: TimeoutConfig | None = None,
        storage: "ConductorStorage | None" = None,
        output_dir: Path | None = None,
    ) -> None:
        super().__init__(role)
        self.cli_command = cli_command
        self.squad_client = squad_client
        self.one_shot = one_shot
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self.timeout_config = timeout_config
        self.storage = storage
        self.output_dir = output_dir
        self._process: asyncio.subprocess.Process | None = None
        self._checkpoint_sent = False

    @property
    def kind(self) -> str:
        return AgentKind.LOCAL.value

    async def dispatch(self, task: Task) -> AgentResult:
        if self.one_shot:
            return await self._dispatch_one_shot(task)
        return await self._dispatch_long_lived(task)

    async def _dispatch_one_shot(self, task: Task) -> AgentResult:
        """Run the CLI once with the handoff path and collect output."""
        hard_timeout = self._hard_timeout_for(task)
        handoff_path = str(task.handoff.path) if task.handoff.path else ""
        command = [*self.cli_command, handoff_path]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=hard_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return AgentResult(
                task_id=task.id,
                verdict=Verdict.TIMEOUT,
                summary=f"One-shot agent exceeded hard timeout ({hard_timeout}s)",
            )

        output = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()

        if proc.returncode != 0:
            return AgentResult(
                task_id=task.id,
                verdict=Verdict.FAIL,
                summary=output or f"CLI exited with code {proc.returncode}",
            )

        return AgentResult(
            task_id=task.id,
            verdict=Verdict.PASS,
            summary=output,
        )

    async def _dispatch_long_lived(self, task: Task) -> AgentResult:
        """Spawn or reuse a long-lived agent and track via Squad tasks."""
        if self._process is None or self._process.returncode is not None:
            self._process = await self._spawn_agent()

        handoff_path = str(task.handoff.path) if task.handoff.path else ""
        try:
            squad_task_id = self.squad_client.task_create(
                sender="conductor",
                recipient=self.role,
                title=f"{task.stage.value}: {task.handoff.goal}",
                body=handoff_path,
            )
        except SquadClientError as exc:
            return AgentResult(
                task_id=task.id,
                verdict=Verdict.FAIL,
                summary=f"Failed to create Squad task: {exc}",
            )

        timeouts = self.timeout_config.for_stage(task.stage) if self.timeout_config else None
        soft_timeout = timeouts.soft_timeout_seconds if timeouts else None
        hard_timeout = timeouts.hard_timeout_seconds if timeouts else None
        task.started_at = datetime.now(timezone.utc)
        if hard_timeout:
            task.deadline_at = task.started_at.replace(second=0, microsecond=0) + timedelta(seconds=hard_timeout)
        self._checkpoint_sent = False
        self._save_task(task)

        soft_deadline = datetime.now(timezone.utc).timestamp() + soft_timeout if soft_timeout else None
        hard_deadline = datetime.now(timezone.utc).timestamp() + hard_timeout if hard_timeout else None
        while True:
            await asyncio.sleep(self.poll_interval)
            now = datetime.now(timezone.utc).timestamp()

            messages = self.squad_client.receive(self.role, wait=False)
            task.last_seen_at = datetime.now(timezone.utc)
            for msg in messages:
                if msg.get("task_id") == squad_task_id and msg.get("type") == "task_complete":
                    return self._parse_result(task, msg.get("summary", ""))

            completed_tasks = self.squad_client.task_list(self.role, status="completed")
            for completed in completed_tasks:
                if str(completed.get("id")) == squad_task_id:
                    return self._parse_result(task, completed.get("summary", ""))

            self._save_task(task)

            if soft_deadline and now >= soft_deadline and not self._checkpoint_sent:
                self._send_checkpoint_request(task, squad_task_id)
                self._checkpoint_sent = True

            if hard_deadline and now >= hard_deadline:
                log_path = self._capture_logs(task)
                await self.stop()
                return AgentResult(
                    task_id=task.id,
                    verdict=Verdict.TIMEOUT,
                    summary=f"Long-lived agent exceeded hard timeout ({hard_timeout}s). Logs: {log_path}",
                    artifacts={"log_path": str(log_path)} if log_path else {},
                )

    def _parse_result(self, task: Task, summary: str) -> AgentResult:
        """Parse wrapper JSON output from a completed Squad task summary."""
        summary = summary.strip()
        if summary.startswith("{"):
            try:
                data = json.loads(summary)
                verdict = Verdict(data.get("verdict", "pass"))
                return AgentResult(
                    task_id=task.id,
                    verdict=verdict,
                    summary=data.get("summary", summary),
                    handoff_path=Path(data["handoff_path"]) if data.get("handoff_path") else None,
                    artifacts=data.get("artifacts", {}),
                )
            except (json.JSONDecodeError, ValueError):
                pass
        verdict = Verdict.PASS if summary.upper().startswith("PASS") else Verdict.FAIL
        return AgentResult(task_id=task.id, verdict=verdict, summary=summary)

    def _send_checkpoint_request(self, task: Task, squad_task_id: str) -> None:
        """Ask the agent for a progress checkpoint."""
        try:
            self.squad_client.send(
                "conductor",
                self.role,
                f"Checkpoint request for task {squad_task_id} ({task.stage.value}). "
                "Reply with status or complete the task.",
            )
        except SquadClientError:
            pass

    def _capture_logs(self, task: Task) -> Path | None:
        """Capture any available agent output to disk."""
        if self.output_dir is None:
            return None
        log_dir = self.output_dir / task.workflow_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{task.id}_agent_output.log"
        chunks: list[str] = []
        if self._process is not None:
            # Long-running process stdout may be buffered; read what is available without blocking.
            if self._process.stdout:
                try:
                    chunks.append(self._process.stdout.read(64_000))
                except Exception:
                    pass
            if self._process.stderr:
                try:
                    chunks.append(self._process.stderr.read(64_000))
                except Exception:
                    pass
        log_path.write_text("\n".join(chunks), encoding="utf-8")
        task.last_agent_output_path = log_path
        return log_path

    def _hard_timeout_for(self, task: Task) -> float:
        if self.timeout_config is None:
            return 3600.0
        cfg = self.timeout_config.for_stage(task.stage)
        return cfg.hard_timeout_seconds or 3600.0

    def _save_task(self, task: Task) -> None:
        if self.storage is not None:
            self.storage.save_task(task)

    async def _spawn_agent(self) -> asyncio.subprocess.Process:
        """Start the agent wrapper in receive mode."""
        command = [
            *self.cli_command,
            self.role,
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait briefly for the agent to join Squad.
        for _ in range(int(self.startup_timeout / 0.5)):
            await asyncio.sleep(0.5)
            agents = self.squad_client.agents()
            if any(a.get("role") == self.role for a in agents):
                return process
            if process.returncode is not None:
                stdout = (await process.stdout.read()).decode("utf-8", errors="replace") if process.stdout else ""
                stderr = (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
                raise RuntimeError(
                    f"Agent {self.role} exited early. stdout={stdout}, stderr={stderr}",
                )

        # Continue even if we could not confirm; the agent may still join.
        return process

    async def stop(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(
                    self._process.wait(),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                self._process.kill()
