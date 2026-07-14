#!/usr/bin/env python3
"""Conductor wrapper for the codex CLI (one-shot).

Joins Squad as role, waits for one task, runs `codex exec <body>`,
and posts the JSON result back.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conductor_wrapper_lib import (
    build_prompt,
    extract_handoff_from_output,
    next_stage,
    parse_handoff,
    write_handoff,
)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: codex_wrapper.py <role>", file=sys.stderr)
        return 1
    role = sys.argv[1]

    subprocess.run(["squad", "join", role, "--client", "codex"], check=False)

    try:
        proc = subprocess.run(
            ["squad", "receive", role, "--wait", "--json"],
            capture_output=True,
            text=True,
            timeout=86400,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return 0

        task = None
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "task_create":
                    task = msg
                    break
            except json.JSONDecodeError:
                continue

        if task is None:
            return 0

        task_id = str(task.get("task_id", task.get("id", "")))
        handoff_path = Path(task.get("body", ""))

        subprocess.run(["squad", "task", "ack", role, task_id], check=False)

        next_role = next_stage(role)
        if next_role is None:
            result = {"verdict": "fail", "summary": f"No next stage for role {role}"}
            subprocess.run(
                ["squad", "task", "complete", role, task_id, "--summary", json.dumps(result)],
                check=False,
            )
            return 0

        try:
            handoff = parse_handoff(handoff_path)
            prompt = build_prompt(handoff, role, next_role)
            run_proc = subprocess.run(
                ["codex", "exec", prompt],
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (run_proc.stdout + "\n" + run_proc.stderr).strip()
            if run_proc.returncode != 0:
                result = {
                    "verdict": "fail",
                    "summary": f"codex exited {run_proc.returncode}: {output[:2000]}",
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
            result = {"verdict": "timeout", "summary": "codex exceeded wrapper timeout"}
        except Exception as exc:
            result = {"verdict": "fail", "summary": f"wrapper error: {exc}"}

        subprocess.run(
            ["squad", "task", "complete", role, task_id, "--summary", json.dumps(result)],
            check=False,
        )
    finally:
        subprocess.run(["squad", "leave", role], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
