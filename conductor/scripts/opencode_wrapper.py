#!/usr/bin/env python3
"""Conductor wrapper for the opencode CLI.

The wrapper runs as a Squad agent:
1. Joins Squad with the role provided as the first positional argument.
2. Polls for task assignments.
3. Runs opencode with the task body as a prompt.
4. Posts the result back as a Squad task completion.

Result JSON format:
{
    "verdict": "pass" | "fail" | "needs_info" | "timeout" | "stalled",
    "summary": "human-readable summary",
    "handoff_path": "optional/path/to/next/handoff.md"
}
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from conductor_wrapper_lib import (
    build_prompt,
    extract_handoff_from_output,
    next_stage,
    parse_handoff,
    write_handoff,
)


def run_opencode(prompt: str) -> tuple[int, str, str]:
    """Run opencode non-interactively with the given prompt."""
    proc = subprocess.run(
        ["opencode", "run", prompt],
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, proc.stdout, proc.stderr


def receive_task(role: str) -> dict | None:
    """Block until a task arrives for role."""
    proc = subprocess.run(
        ["squad", "receive", role, "--wait", "--json"],
        capture_output=True,
        text=True,
        timeout=86400,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("type") == "task_create":
                return msg
        except json.JSONDecodeError:
            continue
    return None


def ack_task(role: str, task_id: str) -> None:
    subprocess.run(["squad", "task", "ack", role, task_id], check=False)


def complete_task(role: str, task_id: str, result: dict) -> None:
    summary = json.dumps(result)
    subprocess.run(
        ["squad", "task", "complete", role, task_id, "--summary", summary],
        check=False,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: opencode_wrapper.py <role>", file=sys.stderr)
        return 1
    role = sys.argv[1]

    subprocess.run(["squad", "join", role, "--client", "opencode"], check=False)

    try:
        while True:
            task = receive_task(role)
            if task is None:
                time.sleep(1)
                continue

            task_id = str(task.get("task_id", task.get("id", "")))
            handoff_path = Path(task.get("body", ""))
            ack_task(role, task_id)

            next_role = next_stage(role)
            if next_role is None:
                complete_task(role, task_id, {"verdict": "fail", "summary": f"No next stage for role {role}"})
                continue

            try:
                handoff = parse_handoff(handoff_path)
                prompt = build_prompt(handoff, role, next_role)
                returncode, stdout, stderr = run_opencode(prompt)
                output = (stdout + "\n" + stderr).strip()
                if returncode != 0:
                    result = {
                        "verdict": "fail",
                        "summary": f"opencode exited {returncode}: {output[:2000]}",
                    }
                else:
                    goal, body = extract_handoff_from_output(output, role, next_role)
                    output_dir = Path(".conductor/runs") / task.get("workflow_id", "unknown")
                    out_path = output_dir / f"{role}-to-{next_role}.md"
                    write_handoff(out_path, role, next_role, goal, body)
                    result = {
                        "verdict": "pass",
                        "summary": f"Produced handoff {out_path}",
                        "handoff_path": str(out_path),
                    }
            except subprocess.TimeoutExpired:
                result = {"verdict": "timeout", "summary": "opencode exceeded wrapper timeout"}
            except Exception as exc:
                result = {"verdict": "fail", "summary": f"wrapper error: {exc}"}

            complete_task(role, task_id, result)
    finally:
        subprocess.run(["squad", "leave", role], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
