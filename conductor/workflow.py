"""Quant workflow engine with stage gates."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conductor.agents.base import Agent
from conductor.contracts import (
    AgentKind,
    AgentResult,
    AgentStatus,
    GateDecision,
    Handoff,
    HumanCheckpoint,
    Task,
    Verdict,
    WorkflowStage,
    WorkflowState,
)
from conductor.handoff import find_handoffs, parse_handoff
from conductor.settings import ConductorSettings
from conductor.change_detector import summarize_changes_and_tests
from conductor.squad_client import SquadClient
from conductor.storage import ConductorStorage


# Map workflow stages to the handoff stage name used in plans/ files.
_STAGE_HANDOFF_MAP: dict[WorkflowStage, str] = {
    WorkflowStage.RESEARCH: "orchestrator-to-researcher",
    WorkflowStage.ARCHITECT: "researcher-to-architect",
    WorkflowStage.CODE: "architect-to-coder",
    WorkflowStage.REVIEW: "coder-to-review",
    WorkflowStage.APPROVAL: "review-to-approval",
}


class WorkflowEngine:
    """Drive a quant workflow through research → architect → code → review → approval."""

    def __init__(
        self,
        settings: ConductorSettings,
        storage: ConductorStorage,
        squad_client: SquadClient,
        agent_factory: dict[str, Agent],
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.squad_client = squad_client
        self.agent_factory = agent_factory

    def create_workflow(
        self,
        name: str,
        id: str | None = None,
        seed_handoff: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowState:
        workflow_id = id or f"wf-{uuid.uuid4().hex[:12]}"
        state = WorkflowState(
            id=workflow_id,
            name=name,
            metadata=metadata or {},
        )
        if seed_handoff:
            handoff = parse_handoff(seed_handoff)
            stage = self._infer_stage(handoff)
            state.handoffs.setdefault(stage, []).append(seed_handoff)
            state.current_stage = stage
        self.storage.save_workflow(state)
        return state

    async def run_workflow(self, workflow_id: str) -> WorkflowState:
        state = self.storage.load_workflow(workflow_id)
        if state is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        while state.current_stage not in {
            WorkflowStage.DONE,
            WorkflowStage.HUMAN_BLOCKED,
            WorkflowStage.HUMAN_ABORTED,
        }:
            stage = state.current_stage
            if self._is_human_stage(stage):
                state = self._pause_for_human_gate(state)
                self.storage.save_workflow(state)
                return state

            task = await self._dispatch_stage(state, stage)
            result = await self._wait_for_result(task)
            state = self._apply_result(state, task, result)
            self.storage.save_workflow(state)

        return state

    def apply_human_decision(
        self,
        workflow_id: str,
        decision: GateDecision,
        reason: str | None = None,
        target_stage: WorkflowStage | None = None,
    ) -> WorkflowState:
        """Apply a human decision at a checkpoint gate and advance the workflow."""
        state = self.storage.load_workflow(workflow_id)
        if state is None:
            raise ValueError(f"Workflow {workflow_id} not found")
        if not self._is_human_stage(state.current_stage):
            raise ValueError(
                f"Workflow {workflow_id} is not at a human gate (stage={state.current_stage.value})",
            )

        current_gate = state.current_stage
        state.gate_decision = decision
        state.gate_reason = reason

        if decision == GateDecision.ABORTED:
            state.current_stage = WorkflowStage.HUMAN_ABORTED
        elif decision == GateDecision.REJECTED:
            state.current_stage = self._retry_stage_for_gate(current_gate)
        elif decision == GateDecision.REQUEUED:
            if target_stage is None:
                raise ValueError("--to stage is required for requeue")
            state.current_stage = target_stage
            state.gate_target_stage = target_stage
        elif decision == GateDecision.APPROVED:
            state.current_stage = state.gate_target_stage or self._gate_target(current_gate)
        else:
            raise ValueError(f"Unsupported gate decision: {decision}")

        state.pending_gate = None
        state.updated_at = datetime.now(timezone.utc)
        self.storage.save_workflow(state)
        return state

    def generate_checkpoint(self, workflow_id: str) -> HumanCheckpoint:
        """Generate a human-readable checkpoint for the current gate."""
        state = self.storage.load_workflow(workflow_id)
        if state is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        previous_task = self._last_completed_task(state)
        previous_stage = previous_task.stage if previous_task else None
        previous_role = previous_task.role if previous_task else None
        previous_verdict = previous_task.verdict if previous_task else None
        handoff_path = previous_task.handoff.path if previous_task and previous_task.handoff.path else None

        risk_flags = self._detect_risk_flags(state)
        changed_files = state.metadata.get("changed_files", [])
        test_status = state.metadata.get("test_status")
        reviewer_verdict = None
        if previous_stage == WorkflowStage.REVIEW:
            reviewer_verdict = previous_verdict

        approve_cmd = f"flipper-conductor approve {state.id}"
        reject_cmd = f"flipper-conductor reject {state.id} --reason \"...\""
        requeue_cmd = f"flipper-conductor requeue {state.id} --to <stage> --reason \"...\""
        abort_cmd = f"flipper-conductor abort {state.id}"

        if state.current_stage == WorkflowStage.HUMAN_READY:
            gate_reason = state.gate_reason or "Architecture complete; human approval required before coding."
            suggested = f"Review the architect handoff, then run: {approve_cmd}"
        elif state.current_stage == WorkflowStage.HUMAN_REVIEW:
            gate_reason = state.gate_reason or "Review complete; human approval required before final approval."
            suggested = f"Inspect review findings, then run: {approve_cmd}"
        else:
            gate_reason = state.gate_reason or "Workflow paused for human input."
            suggested = approve_cmd

        return HumanCheckpoint(
            run_id=state.id,
            workflow_name=state.name,
            current_stage=state.current_stage,
            previous_stage=previous_stage,
            previous_result=previous_verdict,
            previous_agent=previous_role,
            previous_task_id=previous_task.id if previous_task else None,
            handoff_path=handoff_path,
            changed_files=changed_files,
            risk_flags=risk_flags,
            test_status=test_status,
            reviewer_verdict=reviewer_verdict,
            gate_reason=gate_reason,
            suggested_action=suggested,
            approve_command=approve_cmd,
            reject_command=reject_cmd,
            requeue_command=requeue_cmd,
            abort_command=abort_cmd,
        )

    async def _dispatch_stage(
        self,
        state: WorkflowState,
        stage: WorkflowStage,
    ) -> Task:
        handoff = self._current_handoff(state, stage)
        if handoff is None:
            raise ValueError(f"No handoff available for stage {stage.value}")

        role = self._role_for_stage(stage)
        agent = self.agent_factory.get(role)
        if agent is None:
            raise ValueError(f"No agent configured for role {role}")

        task = Task(
            id=f"task-{uuid.uuid4().hex[:12]}",
            workflow_id=state.id,
            stage=stage,
            role=role,
            kind=AgentKind(agent.kind),
            handoff=handoff,
            context={"workflow_name": state.name},
            status=AgentStatus.PENDING,
        )
        task.status = AgentStatus.RUNNING
        task.assigned_at = datetime.now(timezone.utc)
        task.started_at = datetime.now(timezone.utc)
        task.deadline_at = datetime.now(timezone.utc).replace(
            second=0, microsecond=0,
        )  # placeholder; updated by agent runner
        self.storage.save_task(task)

        # Local agents update status via Squad; remote agents stage a pack; stub agents are ready.
        if task.kind == AgentKind.REMOTE:
            task.status = AgentStatus.PENDING  # waiting for human to open devspace
        elif task.kind == AgentKind.STUB:
            task.status = AgentStatus.RUNNING
        self.storage.save_task(task)
        return task

    async def _wait_for_result(self, task: Task) -> AgentResult:
        agent = self.agent_factory[task.role]
        result = await agent.dispatch(task)

        task.result_summary = result.summary[:2000] if result.summary else None
        task.verdict = result.verdict
        task.completed_at = datetime.now(timezone.utc)
        task.status = AgentStatus.RESPONDED
        task.last_seen_at = datetime.now(timezone.utc)
        self.storage.save_task(task)
        return result

    def _apply_result(
        self,
        state: WorkflowState,
        task: Task,
        result: AgentResult,
    ) -> WorkflowState:
        if result.verdict == Verdict.PASS:
            next_stage = self._next_stage(task.stage)
            if result.handoff_path:
                state.handoffs.setdefault(next_stage, []).append(result.handoff_path)

            if task.stage == WorkflowStage.CODE:
                self._update_change_and_test_state(state)

            if self._requires_gate(task.stage, task.handoff):
                state.current_stage = self._gate_stage_for(task.stage)
                state.pending_gate = state.current_stage
                state.gate_target_stage = next_stage
                state.gate_reason = self._gate_reason(task.stage, task.handoff)
            else:
                state.current_stage = next_stage
        elif result.verdict == Verdict.FAIL:
            # Failed review/approval goes back to the previous producer stage.
            state.current_stage = self._retry_stage(task.stage)
        elif result.verdict in {Verdict.TIMEOUT, Verdict.STALLED}:
            state = self._handle_timeout(state, task, result)
        else:  # NEEDS_INFO
            state.current_stage = WorkflowStage.INTAKE

        state.updated_at = datetime.now(timezone.utc)
        return state

    def _update_change_and_test_state(self, state: WorkflowState) -> None:
        """Capture git diff and a scoped test/lint status after the coder stage."""
        changed, test_result = summarize_changes_and_tests(
            self.settings.workspace_root,
            test_command=[
                "ruff",
                "check",
                "conductor",
                "tests/conductor_tests",
            ],
        )
        state.metadata["changed_files"] = changed
        state.metadata["test_status"] = test_result.to_markdown()
        state.metadata["test_passed"] = test_result.passed

    def _handle_timeout(
        self,
        state: WorkflowState,
        task: Task,
        result: AgentResult,
    ) -> WorkflowState:
        """Escalate a timeout: retry, switch agent, or block for human."""
        stage_retries = state.metadata.setdefault("stage_retries", {})
        retry_count = stage_retries.get(task.stage.value, 0) + 1
        stage_retries[task.stage.value] = retry_count

        task.retry_count = retry_count
        task.last_error = result.summary
        self.storage.save_task(task)

        max_retries = self.settings.timeout_config.max_retry_count
        if retry_count > max_retries:
            state.current_stage = WorkflowStage.HUMAN_BLOCKED
            state.gate_reason = (
                f"Task {task.id} for {task.role} timed out after {retry_count} retries. "
                f"Last summary: {result.summary}"
            )
            return state

        # Requeue the same stage. The next run will spawn/restart the agent.
        state.current_stage = task.stage
        state.gate_reason = None
        return state

    def _pause_for_human_gate(self, state: WorkflowState) -> WorkflowState:
        """Generate the checkpoint file and leave the workflow paused."""
        checkpoint = self.generate_checkpoint(state.id)
        checkpoint_dir = self.settings.conductor_dir / "runs" / state.id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / "human_checkpoint.md"
        checkpoint_path.write_text(checkpoint.to_markdown(), encoding="utf-8")
        state.metadata["last_checkpoint_path"] = str(checkpoint_path)
        state.updated_at = datetime.now(timezone.utc)
        return state

    def _requires_gate(self, stage: WorkflowStage, handoff: Handoff) -> bool:
        if stage == WorkflowStage.ARCHITECT and self.settings.gate_policy.before_code:
            return True
        if stage == WorkflowStage.REVIEW and self.settings.gate_policy.before_approval:
            return True
        return self.settings.gate_policy.requires_gate(stage, handoff)

    def _gate_reason(self, stage: WorkflowStage, handoff: Handoff) -> str:
        if stage == WorkflowStage.ARCHITECT:
            return "Human gate before coding: architecture approval required."
        if stage == WorkflowStage.REVIEW:
            return "Human gate before approval: inspect review findings."
        risk = self.settings.gate_policy._has_risk_signal(handoff, [])
        if risk:
            return "Risk signal detected; human approval required."
        return "Policy requires human approval before advancing."

    def _detect_risk_flags(self, state: WorkflowState) -> list[str]:
        flags: list[str] = []
        previous_task = self._last_completed_task(state)
        if previous_task is None:
            return flags

        handoff = previous_task.handoff
        policy = self.settings.gate_policy
        text = f"{handoff.goal} {handoff.objective or ''} {handoff.body} {' '.join(handoff.tags)}".lower()

        for keyword in policy.force_human_if_keywords:
            if keyword.lower() in text:
                flags.append(f"Keyword trigger: {keyword}")

        for changed in state.metadata.get("changed_files", []):
            changed_lower = changed.lower()
            for prefix in policy.force_human_if_changed_paths:
                prefix_normalized = prefix.lower().rstrip("/") + "/"
                if changed_lower.startswith(prefix_normalized) or changed_lower == prefix.lower().rstrip("/"):
                    flags.append(f"Changed path trigger: {changed}")

        return flags

    def _last_completed_task(self, state: WorkflowState) -> Task | None:
        completed = [t for t in state.tasks if t.completed_at is not None]
        if not completed:
            return None
        return sorted(completed, key=lambda t: t.completed_at)[-1]

    def _current_handoff(
        self,
        state: WorkflowState,
        stage: WorkflowStage,
    ) -> Handoff | None:
        paths = state.handoffs.get(stage, [])
        if not paths:
            # Try to discover a matching handoff from plans/.
            handoff_stage = _STAGE_HANDOFF_MAP.get(stage)
            if handoff_stage:
                paths = find_handoffs(self.settings.plans_dir, stage=handoff_stage)
                if paths:
                    state.handoffs[stage] = paths
        if not paths:
            return None
        return parse_handoff(paths[-1])

    def _role_for_stage(self, stage: WorkflowStage) -> str:
        return self.settings.workflow_config.role_for_stage.get(stage, "worker")

    def _next_stage(self, stage: WorkflowStage) -> WorkflowStage:
        return self.settings.workflow_config.next_stage.get(stage, WorkflowStage.DONE)

    def _gate_stage_for(self, stage: WorkflowStage) -> WorkflowStage:
        return self.settings.workflow_config.gate_stage_for.get(stage, WorkflowStage.HUMAN_BLOCKED)

    def _gate_target(self, gate_stage: WorkflowStage) -> WorkflowStage:
        return self.settings.workflow_config.gate_target.get(gate_stage, WorkflowStage.HUMAN_BLOCKED)

    def _retry_stage(self, stage: WorkflowStage) -> WorkflowStage:
        return self.settings.workflow_config.retry_stage.get(stage, WorkflowStage.INTAKE)

    def _retry_stage_for_gate(self, gate_stage: WorkflowStage) -> WorkflowStage:
        return self.settings.workflow_config.retry_stage_for_gate.get(gate_stage, WorkflowStage.INTAKE)

    def _infer_stage(self, handoff: Handoff) -> WorkflowStage:
        stage_map = {v: k for k, v in _STAGE_HANDOFF_MAP.items()}
        return stage_map.get(handoff.stage, WorkflowStage.INTAKE)

    @staticmethod
    def _is_human_stage(stage: WorkflowStage) -> bool:
        return stage in {
            WorkflowStage.HUMAN_READY,
            WorkflowStage.HUMAN_REVIEW,
            WorkflowStage.HUMAN_BLOCKED,
            WorkflowStage.HUMAN_ABORTED,
        }
