"""Thin wrapper around the Squad CLI."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any



class SquadClientError(Exception):
    """Raised when a Squad CLI invocation fails."""


class SquadClient:
    """Invoke ``squad`` commands and parse their output."""

    def __init__(self, squad_binary: str = "squad", cwd: Path | None = None) -> None:
        self.squad_binary = squad_binary
        self.cwd = cwd

    def _run(
        self,
        *args: str,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.squad_binary, *args]
        try:
            return subprocess.run(
                cmd,
                cwd=self.cwd,
                check=check,
                capture_output=capture,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stdout = exc.stdout.strip() if exc.stdout else ""
            stderr = exc.stderr.strip() if exc.stderr else ""
            raise SquadClientError(
                f"squad {' '.join(shlex.quote(a) for a in args)} failed: {stderr or stdout}",
            ) from exc
        except FileNotFoundError as exc:
            raise SquadClientError(
                f"Squad binary '{self.squad_binary}' not found in PATH",
            ) from exc

    def agents(self) -> list[dict[str, Any]]:
        """List currently online Squad agents."""
        proc = self._run("agents", "--json")
        if not proc.stdout.strip():
            return []
        agents: list[dict[str, Any]] = []
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                agents.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SquadClientError(f"Invalid JSON from squad agents: {exc}") from exc
        return agents

    def send(self, sender: str, recipient: str, body: str) -> None:
        """Send a message from ``sender`` to ``recipient``."""
        self._run("send", sender, recipient, body)

    def task_create(
        self,
        sender: str,
        recipient: str,
        title: str,
        body: str,
    ) -> str:
        """Create a tracked task and return the task id."""
        proc = self._run(
            "task",
            "create",
            sender,
            recipient,
            "--title",
            title,
            "--body",
            body,
            "--json",
        )
        data = json.loads(proc.stdout or "{}")
        return str(data.get("id", ""))

    def task_ack(self, role: str, task_id: str) -> None:
        """Acknowledge a task as ``role``."""
        self._run("task", "ack", role, task_id)

    def task_complete(self, role: str, task_id: str, summary: str) -> None:
        """Mark a task complete with a summary."""
        self._run("task", "complete", role, task_id, "--summary", summary)

    def receive(self, role: str, wait: bool = False, timeout: int | None = None) -> list[dict[str, Any]]:
        """Receive messages for ``role``.

        Args:
            role: Squad role to receive for.
            wait: Block waiting for at least one message.
            timeout: Optional wait timeout in seconds.

        Returns:
            List of message dictionaries.
        """
        args = ["receive", role]
        if wait:
            args.append("--wait")
        if timeout is not None:
            args.extend(["--timeout", str(timeout)])
        args.append("--json")
        proc = self._run(*args, check=False)
        if proc.returncode != 0:
            return []
        messages: list[dict[str, Any]] = []
        for line in (proc.stdout or "").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return messages

    def task_list(self, role: str, status: str | None = None) -> list[dict[str, Any]]:
        """List tasks for ``role``.

        Args:
            role: Squad role to list tasks for.
            status: Optional status filter (e.g. completed, queued).

        Returns:
            List of task dictionaries.
        """
        args = ["task", "list", "--agent", role, "--json"]
        if status:
            args.extend(["--status", status])
        proc = self._run(*args, check=False)
        if proc.returncode != 0:
            return []
        tasks: list[dict[str, Any]] = []
        for line in (proc.stdout or "").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return tasks
