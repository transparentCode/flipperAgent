"""Conductor CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from conductor.agents.local_agent import LocalAgent
from conductor.agents.remote_agent import RemoteAgent
from conductor.agents.stub_agent import StubAgent
from conductor.contracts import GateDecision, WorkflowStage
from conductor.settings import ConductorSettings
from conductor.squad_client import SquadClient
from conductor.storage import ConductorStorage
from conductor.workflow import WorkflowEngine
from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger, configure_logging

logger = bind_logger(__name__, system_component="CONDUCTOR")


def _build_agents(
    settings: ConductorSettings,
    squad_client: SquadClient,
    storage: ConductorStorage,
) -> dict[str, object]:
    """Construct the default agent map for local and remote roles."""
    agents: dict[str, object] = {}

    local_specs = dict(settings.agent_commands)

    output_dir = settings.conductor_dir / "runs"
    for role, command in local_specs.items():
        if command == ["stub"]:
            agents[role] = StubAgent(
                role=role,
                output_dir=output_dir,
                stage_transitions=settings.workflow_config.stub_stage_transitions,
            )
            continue
        agents[role] = LocalAgent(
            role=role,
            cli_command=command,
            squad_client=squad_client,
            one_shot=(command[0] == "codex"),
            timeout_config=settings.timeout_config,
            storage=storage,
            output_dir=output_dir,
        )

    # Remote web agents via devspace file bridge.
    for role in settings.default_remote_roles:
        agents[role] = RemoteAgent(
            role=role,
            tasks_dir=settings.remote_tasks_dir(),
            poll_seconds=settings.remote_poll_seconds,
            timeout_seconds=settings.remote_timeout_seconds,
            timeout_config=settings.timeout_config,
        )

    return agents


def _load_config_manager(args: argparse.Namespace) -> ConfigManager | dict:
    """Resolve config source from CLI args (directory or YAML file)."""
    if not args.config:
        return ConfigManager()
    path = Path(args.config)
    if path.is_dir():
        return ConfigManager(config_dir=str(path))
    if not path.is_file():
        raise SystemExit(f"Config path does not exist: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _settings_from_args(args: argparse.Namespace) -> ConductorSettings:
    config = _load_config_manager(args)
    return ConductorSettings.from_config(config_manager=config)


def _make_engine(args: argparse.Namespace) -> WorkflowEngine:
    settings = _settings_from_args(args)
    settings.ensure_dirs()
    storage = ConductorStorage(settings.conductor_dir / "conductor.db")
    squad_client = SquadClient(settings.squad_binary, cwd=settings.workspace_root)
    agents = _build_agents(settings, squad_client, storage)
    return WorkflowEngine(settings, storage, squad_client, agents)


async def _run_workflow(args: argparse.Namespace) -> None:
    settings = _settings_from_args(args)
    settings.ensure_dirs()

    configure_logging(
        level=settings.log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )

    engine = _make_engine(args)

    if args.seed_handoff:
        seed = Path(args.seed_handoff)
        state = engine.create_workflow(
            id=args.workflow_id,
            name=args.name or seed.stem,
            seed_handoff=seed,
            metadata={"trigger": "cli"},
        )
        state = await engine.run_workflow(state.id)
    elif args.workflow_id:
        state = await engine.run_workflow(args.workflow_id)
    else:
        raise SystemExit("Provide --workflow-id or --seed-handoff")

    if state.current_stage.value.startswith("human_"):
        checkpoint_path = state.metadata.get("last_checkpoint_path")
        print(
            f"Workflow {state.id} paused at {state.current_stage.value}. "
            f"Checkpoint: {checkpoint_path}",
        )
        logger.info(
            "workflow_paused_for_human_gate: %s stage=%s checkpoint=%s",
            state.id,
            state.current_stage.value,
            checkpoint_path,
        )
    else:
        logger.info(
            "workflow_completed: %s stage=%s",
            state.id,
            state.current_stage.value,
        )


def _status(args: argparse.Namespace) -> None:
    engine = _make_engine(args)
    state = engine.storage.load_workflow(args.workflow_id)
    if state is None:
        raise SystemExit(f"Workflow {args.workflow_id} not found")

    checkpoint_path = state.metadata.get("last_checkpoint_path")
    print(f"Workflow: {state.id}")
    print(f"Name: {state.name}")
    print(f"Current stage: {state.current_stage.value}")
    print(f"Pending gate: {state.pending_gate.value if state.pending_gate else 'None'}")
    print(f"Last gate decision: {state.gate_decision.value if state.gate_decision else 'None'}")
    if checkpoint_path:
        print(f"Checkpoint: {checkpoint_path}")


def _approve(args: argparse.Namespace) -> None:
    engine = _make_engine(args)
    state = engine.apply_human_decision(
        args.workflow_id,
        decision=GateDecision.APPROVED,
        reason=args.reason,
    )
    print(f"Workflow {state.id} approved. Next stage: {state.current_stage.value}")


def _reject(args: argparse.Namespace) -> None:
    if not args.reason:
        raise SystemExit("--reason is required for reject")
    engine = _make_engine(args)
    state = engine.apply_human_decision(
        args.workflow_id,
        decision=GateDecision.REJECTED,
        reason=args.reason,
    )
    print(f"Workflow {state.id} rejected. Returned to: {state.current_stage.value}")


def _requeue(args: argparse.Namespace) -> None:
    if not args.reason:
        raise SystemExit("--reason is required for requeue")
    if args.to is None:
        raise SystemExit("--to is required for requeue")
    engine = _make_engine(args)
    state = engine.apply_human_decision(
        args.workflow_id,
        decision=GateDecision.REQUEUED,
        reason=args.reason,
        target_stage=WorkflowStage(args.to),
    )
    print(f"Workflow {state.id} requeued to {state.current_stage.value}")


def _abort(args: argparse.Namespace) -> None:
    engine = _make_engine(args)
    state = engine.apply_human_decision(
        args.workflow_id,
        decision=GateDecision.ABORTED,
        reason=args.reason,
    )
    print(f"Workflow {state.id} aborted at {state.current_stage.value}")


def _unblock(args: argparse.Namespace) -> None:
    if not args.reason:
        raise SystemExit("--reason is required for unblock")
    if args.to is None:
        raise SystemExit("--to is required for unblock")
    engine = _make_engine(args)
    state = engine.apply_human_decision(
        args.workflow_id,
        decision=GateDecision.REQUEUED,
        reason=args.reason,
        target_stage=WorkflowStage(args.to),
    )
    print(f"Workflow {state.id} unblocked and moved to {state.current_stage.value}")


def _retry(args: argparse.Namespace) -> None:
    engine = _make_engine(args)
    state = engine.storage.load_workflow(args.workflow_id)
    if state is None:
        raise SystemExit(f"Workflow {args.workflow_id} not found")

    # Reset retry counter for the current stage so the task can run again.
    stage_retries = state.metadata.setdefault("stage_retries", {})
    stage_retries[state.current_stage.value] = 0
    state.updated_at = datetime.now(timezone.utc)
    engine.storage.save_workflow(state)
    print(f"Workflow {state.id} retry counter reset for {state.current_stage.value}")


def _list_workflows(args: argparse.Namespace) -> None:
    settings = _settings_from_args(args)
    storage = ConductorStorage(settings.conductor_dir / "conductor.db")
    for row in storage.list_workflows():
        print(f"{row['id']} | {row['name']} | {row['current_stage']} | {row['updated_at']}")


def _extract_config_arg(argv: list[str]) -> tuple[list[str], Path | None]:
    """Pull --config out of argv so it can appear before or after subcommands."""
    config_path: Path | None = None
    cleaned: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--config":
            if i + 1 >= len(argv):
                raise SystemExit("--config requires a value")
            config_path = Path(argv[i + 1])
            i += 2
        elif argv[i].startswith("--config="):
            config_path = Path(argv[i].split("=", 1)[1])
            i += 1
        else:
            cleaned.append(argv[i])
            i += 1
    return cleaned, config_path


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    cleaned_argv, config_path = _extract_config_arg(raw_argv)

    parser = argparse.ArgumentParser(prog="flipper-conductor", description="flipperAgent multi-agent conductor")
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help="Path to a config directory or a single YAML config file",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Create or resume a workflow")
    run_parser.add_argument("--name", help="Workflow name")
    run_parser.add_argument("--seed-handoff", type=Path, help="Path to a handoff markdown file")
    run_parser.add_argument("--workflow-id", help="Resume an existing workflow")
    run_parser.set_defaults(func=_run_workflow)

    status_parser = sub.add_parser("status", help="Show workflow status")
    status_parser.add_argument("workflow_id", help="Workflow id")
    status_parser.set_defaults(func=_status)

    approve_parser = sub.add_parser("approve", help="Approve a human checkpoint gate")
    approve_parser.add_argument("workflow_id", help="Workflow id")
    approve_parser.add_argument("--reason", help="Optional reason for approval")
    approve_parser.set_defaults(func=_approve)

    reject_parser = sub.add_parser("reject", help="Reject and return to producer stage")
    reject_parser.add_argument("workflow_id", help="Workflow id")
    reject_parser.add_argument("--reason", required=True, help="Reason for rejection")
    reject_parser.set_defaults(func=_reject)

    requeue_parser = sub.add_parser("requeue", help="Requeue workflow to a specific stage")
    requeue_parser.add_argument("workflow_id", help="Workflow id")
    requeue_parser.add_argument("--to", required=True, help="Target stage (e.g. architect, coder)")
    requeue_parser.add_argument("--reason", required=True, help="Reason for requeue")
    requeue_parser.set_defaults(func=_requeue)

    abort_parser = sub.add_parser("abort", help="Abort a workflow")
    abort_parser.add_argument("workflow_id", help="Workflow id")
    abort_parser.add_argument("--reason", help="Optional reason for abort")
    abort_parser.set_defaults(func=_abort)

    unblock_parser = sub.add_parser("unblock", help="Unblock a HUMAN_BLOCKED workflow")
    unblock_parser.add_argument("workflow_id", help="Workflow id")
    unblock_parser.add_argument("--to", required=True, help="Target stage")
    unblock_parser.add_argument("--reason", required=True, help="Reason for unblocking")
    unblock_parser.set_defaults(func=_unblock)

    retry_parser = sub.add_parser("retry", help="Reset retry counter for the current stage")
    retry_parser.add_argument("workflow_id", help="Workflow id")
    retry_parser.set_defaults(func=_retry)

    list_parser = sub.add_parser("list", help="List workflows")
    list_parser.set_defaults(func=_list_workflows)

    args = parser.parse_args(cleaned_argv)
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
