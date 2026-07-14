"""Agent runners for local CLI and remote web agents."""

from conductor.agents.base import Agent
from conductor.agents.local_agent import LocalAgent
from conductor.agents.remote_agent import RemoteAgent

__all__ = ["Agent", "LocalAgent", "RemoteAgent"]
