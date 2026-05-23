"""Shared typing primitives for stable commons boundaries."""

from __future__ import annotations

from os import PathLike as OsPathLike
from typing import TypeAlias, TypedDict


PathLike: TypeAlias = str | OsPathLike[str]
LogContextValue: TypeAlias = str | int | float | bool | None


class LogContext(TypedDict, total=False):
    trace_id: str
    traceId: str
    run_id: str
    job_name: str
    system_component: str
    systemComponent: str
    component: str
    source: str
    dataset: str
    symbol: str
    interval: str
    window: str
    attempt: int
