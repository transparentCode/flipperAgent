"""Durable task queues for SR sidecar profiling."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class ProfileTask:
    """A single profiling request for one symbol/timeframe pair."""

    symbol: str
    timeframe: str
    reason: str
    timestamp: str
    id: Optional[int] = None


class SQLiteProfileTaskQueue:
    """Simple durable queue backed by SQLite."""

    def __init__(self, db_path: str):
        self._path = Path(db_path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path))
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """,
            )

    def enqueue(self, task: ProfileTask) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM profile_tasks WHERE symbol = ? AND timeframe = ? AND state IN ('pending', 'processing')",
                (task.symbol, task.timeframe),
            )
            connection.execute(
                "INSERT INTO profile_tasks(symbol, timeframe, reason, timestamp, state, attempts) VALUES (?, ?, ?, ?, 'pending', 0)",
                (task.symbol, task.timeframe, task.reason, task.timestamp),
            )

    def dequeue(self, limit: int = 1) -> List[ProfileTask]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, symbol, timeframe, reason, timestamp FROM profile_tasks WHERE state = 'pending' ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            task_ids = [(int(row["id"]),) for row in rows]
            if task_ids:
                connection.executemany(
                    "UPDATE profile_tasks SET state = 'processing', attempts = attempts + 1 WHERE id = ?",
                    task_ids,
                )

        return [
            ProfileTask(
                id=int(row["id"]),
                symbol=str(row["symbol"]),
                timeframe=str(row["timeframe"]),
                reason=str(row["reason"]),
                timestamp=str(row["timestamp"]),
            )
            for row in rows
        ]

    def ack(self, task_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM profile_tasks WHERE id = ?", (task_id,))

    def requeue(self, task_id: int, reason: Optional[str] = None) -> None:
        with self._connect() as connection:
            if reason is None:
                connection.execute(
                    "UPDATE profile_tasks SET state = 'pending' WHERE id = ?",
                    (task_id,),
                )
            else:
                connection.execute(
                    "UPDATE profile_tasks SET state = 'pending', reason = ? WHERE id = ?",
                    (reason, task_id),
                )

    def list_pending(self) -> List[ProfileTask]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, symbol, timeframe, reason, timestamp FROM profile_tasks WHERE state = 'pending' ORDER BY id ASC",
            ).fetchall()
        return [
            ProfileTask(
                id=int(row["id"]),
                symbol=str(row["symbol"]),
                timeframe=str(row["timeframe"]),
                reason=str(row["reason"]),
                timestamp=str(row["timestamp"]),
            )
            for row in rows
        ]

    def close(self) -> None:
        """Present for API symmetry; SQLite uses short-lived connections."""


def create_profile_task_queue(
    backend: str = "sqlite",
    queue_path: Optional[str] = None,
) -> SQLiteProfileTaskQueue:
    """Create the configured profile-task queue."""
    if backend != "sqlite":
        raise ValueError(f"Unsupported sidecar queue backend: {backend}")

    if queue_path is None:
        queue_path = str(
            Path(__file__).resolve().parents[1] / "config" / "sr_sidecar.sqlite3",
        )
    return SQLiteProfileTaskQueue(queue_path)