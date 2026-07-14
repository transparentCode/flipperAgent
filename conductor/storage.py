"""SQLite persistence layer for conductor workflows and tasks."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from conductor.contracts import AgentKind, AgentStatus, GateDecision, Handoff, Task, Verdict, WorkflowStage, WorkflowState


_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    handoffs TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    pending_gate TEXT,
    gate_decision TEXT,
    gate_reason TEXT,
    gate_target_stage TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    handoff_path TEXT,
    context TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    verdict TEXT,
    result_summary TEXT,
    started_at TEXT,
    last_seen_at TEXT,
    deadline_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    stall_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_agent_output_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    assigned_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks(workflow_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

_MIGRATIONS = [
    "ALTER TABLE workflows ADD COLUMN pending_gate TEXT;",
    "ALTER TABLE workflows ADD COLUMN gate_decision TEXT;",
    "ALTER TABLE workflows ADD COLUMN gate_reason TEXT;",
    "ALTER TABLE workflows ADD COLUMN gate_target_stage TEXT;",
    "ALTER TABLE tasks ADD COLUMN started_at TEXT;",
    "ALTER TABLE tasks ADD COLUMN last_seen_at TEXT;",
    "ALTER TABLE tasks ADD COLUMN deadline_at TEXT;",
    "ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE tasks ADD COLUMN stall_count INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE tasks ADD COLUMN last_error TEXT;",
    "ALTER TABLE tasks ADD COLUMN last_agent_output_path TEXT;",
]


class ConductorStorage:
    """Persistent SQLite store for workflows and tasks."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            for migration in _MIGRATIONS:
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # Column already exists.
            conn.commit()

    def save_workflow(self, state: WorkflowState) -> None:
        now = _utcnow()
        handoffs_json = json.dumps(
            {stage.value: [str(p) for p in paths] for stage, paths in state.handoffs.items()},
            default=str,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows (
                    id, name, current_stage, handoffs, metadata,
                    pending_gate, gate_decision, gate_reason, gate_target_stage,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    current_stage=excluded.current_stage,
                    handoffs=excluded.handoffs,
                    metadata=excluded.metadata,
                    pending_gate=excluded.pending_gate,
                    gate_decision=excluded.gate_decision,
                    gate_reason=excluded.gate_reason,
                    gate_target_stage=excluded.gate_target_stage,
                    updated_at=excluded.updated_at
                """,
                (
                    state.id,
                    state.name,
                    state.current_stage.value,
                    handoffs_json,
                    json.dumps(state.metadata, default=str),
                    state.pending_gate.value if state.pending_gate else None,
                    state.gate_decision.value if state.gate_decision else None,
                    state.gate_reason,
                    state.gate_target_stage.value if state.gate_target_stage else None,
                    state.created_at.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

    def load_workflow(self, workflow_id: str) -> WorkflowState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None:
            return None

        handoffs_raw = json.loads(row["handoffs"] or "{}")
        handoffs = {
            WorkflowStage(stage): [Path(p) for p in paths]
            for stage, paths in handoffs_raw.items()
        }
        return WorkflowState(
            id=row["id"],
            name=row["name"],
            current_stage=WorkflowStage(row["current_stage"]),
            handoffs=handoffs,
            tasks=self.load_tasks(workflow_id),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"] or "{}"),
            pending_gate=WorkflowStage(row["pending_gate"]) if row["pending_gate"] else None,
            gate_decision=GateDecision(row["gate_decision"]) if row["gate_decision"] else None,
            gate_reason=row["gate_reason"],
            gate_target_stage=WorkflowStage(row["gate_target_stage"]) if row["gate_target_stage"] else None,
        )

    def save_task(self, task: Task) -> None:
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, workflow_id, stage, role, kind, handoff_path, context, status,
                    verdict, result_summary, started_at, last_seen_at, deadline_at,
                    retry_count, stall_count, last_error, last_agent_output_path,
                    created_at, updated_at, assigned_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    stage=excluded.stage,
                    role=excluded.role,
                    kind=excluded.kind,
                    handoff_path=excluded.handoff_path,
                    context=excluded.context,
                    status=excluded.status,
                    verdict=excluded.verdict,
                    result_summary=excluded.result_summary,
                    started_at=excluded.started_at,
                    last_seen_at=excluded.last_seen_at,
                    deadline_at=excluded.deadline_at,
                    retry_count=excluded.retry_count,
                    stall_count=excluded.stall_count,
                    last_error=excluded.last_error,
                    last_agent_output_path=excluded.last_agent_output_path,
                    updated_at=excluded.updated_at,
                    assigned_at=excluded.assigned_at,
                    completed_at=excluded.completed_at
                """,
                (
                    task.id,
                    task.workflow_id,
                    task.stage.value,
                    task.role,
                    task.kind.value,
                    str(task.handoff.path) if task.handoff.path else None,
                    json.dumps(task.context, default=str),
                    task.status.value,
                    task.verdict.value if task.verdict else None,
                    task.result_summary,
                    task.started_at.isoformat() if task.started_at else None,
                    task.last_seen_at.isoformat() if task.last_seen_at else None,
                    task.deadline_at.isoformat() if task.deadline_at else None,
                    task.retry_count,
                    task.stall_count,
                    task.last_error,
                    str(task.last_agent_output_path) if task.last_agent_output_path else None,
                    task.created_at.isoformat(),
                    now.isoformat(),
                    task.assigned_at.isoformat() if task.assigned_at else None,
                    task.completed_at.isoformat() if task.completed_at else None,
                ),
            )
            conn.commit()

    def load_tasks(self, workflow_id: str) -> list[Task]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY created_at",
                (workflow_id,),
            ).fetchall()
        return [_row_to_task(row) for row in rows]

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, current_stage, updated_at FROM workflows ORDER BY updated_at DESC",
            ).fetchall()
        return [dict(row) for row in rows]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_task(row: sqlite3.Row) -> Task:
    from conductor.handoff import parse_handoff

    handoff_path = Path(row["handoff_path"]) if row["handoff_path"] else None
    if handoff_path and handoff_path.exists():
        handoff = parse_handoff(handoff_path)
    else:
        handoff = Handoff(goal="unknown", stage="unknown")

    return Task(
        id=row["id"],
        workflow_id=row["workflow_id"],
        stage=WorkflowStage(row["stage"]),
        role=row["role"],
        kind=AgentKind(row["kind"]),
        handoff=handoff,
        context=json.loads(row["context"] or "{}"),
        status=AgentStatus(row["status"]),
        verdict=Verdict(row["verdict"]) if row["verdict"] else None,
        result_summary=row["result_summary"],
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None,
        deadline_at=datetime.fromisoformat(row["deadline_at"]) if row["deadline_at"] else None,
        retry_count=int(row["retry_count"] or 0),
        stall_count=int(row["stall_count"] or 0),
        last_error=row["last_error"],
        last_agent_output_path=Path(row["last_agent_output_path"]) if row["last_agent_output_path"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        assigned_at=datetime.fromisoformat(row["assigned_at"]) if row["assigned_at"] else None,
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )
