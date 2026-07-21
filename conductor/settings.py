"""Conductor configuration and settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from conductor.contracts import GatePolicy, TimeoutConfig, WorkflowStage
from libs.common.config import ConfigManager


DEFAULT_SQUAD_DB = Path(".squad/messages.db")
DEFAULT_CONDUCTOR_DIR = Path(".conductor")
DEFAULT_PLANS_DIR = Path("plans")
DEFAULT_REMOTE_POLL_SECONDS = 30.0
DEFAULT_REMOTE_TIMEOUT_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass(frozen=True)
class WorkflowConfig:
    """Typed workflow stage/role/transition mappings."""

    role_for_stage: dict[WorkflowStage, str]
    next_stage: dict[WorkflowStage, WorkflowStage]
    gate_stage_for: dict[WorkflowStage, WorkflowStage]
    gate_target: dict[WorkflowStage, WorkflowStage]
    retry_stage: dict[WorkflowStage, WorkflowStage]
    retry_stage_for_gate: dict[WorkflowStage, WorkflowStage]
    stub_stage_transitions: dict[str, str]


@dataclass(frozen=True)
class ConductorSettings:
    """Runtime settings for the conductor."""

    workspace_root: Path
    plans_dir: Path
    conductor_dir: Path
    squad_db: Path
    squad_binary: str
    remote_poll_seconds: float
    remote_timeout_seconds: float
    default_remote_roles: tuple[str, ...]
    log_level: str
    gate_policy: GatePolicy
    timeout_config: TimeoutConfig
    agent_commands: dict[str, list[str]]
    workflow_config: WorkflowConfig

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | dict | None = None,
        workspace_root: Path | None = None,
    ) -> "ConductorSettings":
        if config_manager is None:
            manager: ConfigManager | dict = ConfigManager()
        else:
            manager = config_manager
        root = workspace_root or Path(os.environ.get("FLIPPER_WORKSPACE", ".")).resolve()

        conductor_cfg = manager.get("conductor", {}) or {}
        runtime_cfg = conductor_cfg.get("runtime", {}) or {}
        workflow_cfg = conductor_cfg.get("workflow", {}) or {}
        remote_cfg = conductor_cfg.get("remote", {}) or {}
        gate_cfg = conductor_cfg.get("human_gates", {}) or {}
        timeout_cfg = conductor_cfg.get("timeouts", {}) or {}

        default_agent_commands = {
            "orchestrator": ["opencode", "-c"],
            "architect": ["opencode", "-c"],
            "coder": ["opencode", "-c"],
        }
        agent_commands = runtime_cfg.get("agent_commands", default_agent_commands)

        workflow_config = _build_workflow_config(workflow_cfg)

        plans_dir = _resolve_path(
            runtime_cfg.get("plans_dir", "plans"),
            root,
        )
        conductor_dir = _resolve_path(
            runtime_cfg.get("conductor_dir", ".conductor"),
            root,
        )
        squad_db = _resolve_path(
            runtime_cfg.get("squad_db", ".squad/messages.db"),
            root,
        )

        gate_policy = GatePolicy.model_validate(gate_cfg)
        timeout_config = TimeoutConfig.model_validate(timeout_cfg)

        return cls(
            workspace_root=root,
            plans_dir=plans_dir,
            conductor_dir=conductor_dir,
            squad_db=squad_db,
            squad_binary=str(runtime_cfg.get("squad_binary", "squad")),
            remote_poll_seconds=float(
                remote_cfg.get("poll_seconds", DEFAULT_REMOTE_POLL_SECONDS),
            ),
            remote_timeout_seconds=float(
                remote_cfg.get("timeout_seconds", DEFAULT_REMOTE_TIMEOUT_SECONDS),
            ),
            default_remote_roles=tuple(
                runtime_cfg.get(
                    "default_remote_roles",
                    remote_cfg.get(
                        "roles",
                        [],
                    ),
                ),
            ),
            log_level=str(runtime_cfg.get("log_level", "INFO")),
            gate_policy=gate_policy,
            timeout_config=timeout_config,
            agent_commands=agent_commands,
            workflow_config=workflow_config,
        )

    def remote_tasks_dir(self) -> Path:
        """Directory where remote agent task packs are staged."""
        return self.conductor_dir / "remote_tasks"

    def ensure_dirs(self) -> None:
        """Create runtime directories if missing."""
        self.conductor_dir.mkdir(parents=True, exist_ok=True)
        self.remote_tasks_dir().mkdir(parents=True, exist_ok=True)


def _build_workflow_config(cfg: dict) -> WorkflowConfig:
    """Parse raw workflow config into typed WorkflowConfig."""
    stage_enum = {s.value: s for s in WorkflowStage}

    def _stages(raw: dict) -> dict[WorkflowStage, WorkflowStage]:
        return {
            stage_enum[k]: stage_enum[v]
            for k, v in raw.items()
            if k in stage_enum and v in stage_enum
        }

    def _role_map(raw: dict) -> dict[WorkflowStage, str]:
        return {stage_enum[k]: v for k, v in raw.items() if k in stage_enum}

    role_for_stage = _role_map(cfg.get("role_for_stage", {}))
    next_stage = _stages(cfg.get("transitions", {}).get("next_stage", {}))
    gate_stage_for = _stages(cfg.get("transitions", {}).get("gate_stage_for", {}))
    gate_target = _stages(cfg.get("transitions", {}).get("gate_target", {}))
    retry_stage = _stages(cfg.get("transitions", {}).get("retry_stage", {}))
    retry_stage_for_gate = _stages(cfg.get("transitions", {}).get("retry_stage_for_gate", {}))
    stub_stage_transitions = dict(cfg.get("stub_stage_transitions", {}))

    return WorkflowConfig(
        role_for_stage=role_for_stage,
        next_stage=next_stage,
        gate_stage_for=gate_stage_for,
        gate_target=gate_target,
        retry_stage=retry_stage,
        retry_stage_for_gate=retry_stage_for_gate,
        stub_stage_transitions=stub_stage_transitions,
    )


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()
