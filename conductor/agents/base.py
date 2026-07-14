"""Base agent interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from conductor.contracts import AgentResult, Task


class Agent(ABC):
    """Abstract agent that can process a conductor task."""

    def __init__(self, role: str) -> None:
        self.role = role

    @abstractmethod
    async def dispatch(self, task: Task) -> AgentResult:
        """Dispatch ``task`` to the agent and return its result."""

    @property
    @abstractmethod
    def kind(self) -> str:
        """Human-readable agent kind."""
