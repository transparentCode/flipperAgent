"""Pydantic contracts for the conductor."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentKind(str, enum.Enum):
    """Runtime kind of an agent participant."""

    LOCAL = "local"
    REMOTE = "remote"
    STUB = "stub"


class AgentStatus(str, enum.Enum):
    """Lifecycle status of a dispatched agent task."""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(str, enum.Enum):
    """Quant workflow stages supported by the conductor."""

    INTAKE = "intake"
    RESEARCH = "research"
    ARCHITECT = "architect"
    CODE = "code"
    REVIEW = "review"
    APPROVAL = "approval"
    DONE = "done"

    # Human checkpoint stages.
    HUMAN_READY = "human_ready"
    HUMAN_REVIEW = "human_review"
    HUMAN_BLOCKED = "human_blocked"
    HUMAN_ABORTED = "human_aborted"


class Verdict(str, enum.Enum):
    """Review / approval verdict."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_INFO = "needs_info"
    TIMEOUT = "timeout"
    STALLED = "stalled"


class GateDecision(str, enum.Enum):
    """Human decision at a checkpoint gate."""

    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEUED = "requeued"
    ABORTED = "aborted"


class Handoff(BaseModel):
    """A parsed quant handoff document."""

    model_config = ConfigDict(extra="allow")

    path: Path | None = Field(default=None, description="Filesystem path of the handoff.")
    goal: str = Field(..., description="Short goal statement from frontmatter.")
    stage: str = Field(..., description="Handoff stage, e.g. 'architect-to-coder'.")
    date_created: str | None = Field(default=None)
    owner: str | None = Field(default=None)
    status: str = Field(default="Draft")
    tags: list[str] = Field(default_factory=list)
    target_agent: str | None = Field(default=None)
    objective: str | None = Field(default=None)
    scope_boundaries: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    body: str = Field(default="", description="Markdown body below the frontmatter.")

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        return list(v)

    def is_ready(self) -> bool:
        """Return True if the handoff is ready for the next stage."""
        return self.status.lower() in {"ready", "approved", "done"}


class Task(BaseModel):
    """A unit of work dispatched to an agent."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Unique task id.")
    workflow_id: str = Field(..., description="Parent workflow id.")
    stage: WorkflowStage
    role: str = Field(..., description="Squad role or remote role name.")
    kind: AgentKind
    handoff: Handoff
    context: dict[str, Any] = Field(default_factory=dict)
    status: AgentStatus = Field(default=AgentStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    assigned_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    result_summary: str | None = Field(default=None)
    verdict: Verdict | None = Field(default=None)

    # Timeout / stall tracking.
    started_at: datetime | None = Field(default=None)
    last_seen_at: datetime | None = Field(default=None)
    deadline_at: datetime | None = Field(default=None)
    retry_count: int = Field(default=0)
    stall_count: int = Field(default=0)
    last_error: str | None = Field(default=None)
    last_agent_output_path: Path | None = Field(default=None)


class AgentResult(BaseModel):
    """Result returned by an agent after processing a task."""

    task_id: str
    verdict: Verdict = Verdict.PASS
    summary: str = ""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    handoff_path: Path | None = Field(default=None)
    error: str | None = Field(default=None)


class WorkflowState(BaseModel):
    """Persisted state of a quant workflow."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    current_stage: WorkflowStage = WorkflowStage.INTAKE
    handoffs: dict[WorkflowStage, list[Path]] = Field(default_factory=dict)
    tasks: list[Task] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Human checkpoint state.
    pending_gate: WorkflowStage | None = Field(default=None)
    gate_decision: GateDecision | None = Field(default=None)
    gate_reason: str | None = Field(default=None)
    gate_target_stage: WorkflowStage | None = Field(default=None)


class GatePolicy(BaseModel):
    """Policy controlling when human checkpoint gates are required."""

    model_config = ConfigDict(extra="allow")

    before_code: bool = Field(default=True)
    before_approval: bool = Field(default=True)
    auto_advance_low_risk_architect_pass: bool = Field(default=False)
    auto_advance_low_risk_review_pass: bool = Field(default=False)
    force_human_if_changed_paths: list[str] = Field(default_factory=list)
    force_human_if_keywords: list[str] = Field(default_factory=list)

    def requires_gate(
        self,
        stage: WorkflowStage,
        handoff: Handoff,
        changed_paths: list[str] | None = None,
    ) -> bool:
        """Return True if a human gate is required before advancing."""
        if stage == WorkflowStage.ARCHITECT and self.before_code:
            return True
        if stage == WorkflowStage.REVIEW and self.before_approval:
            return True

        if not self.auto_advance_low_risk_architect_pass and stage == WorkflowStage.ARCHITECT:
            return True
        if not self.auto_advance_low_risk_review_pass and stage == WorkflowStage.REVIEW:
            return True

        return self._has_risk_signal(handoff, changed_paths or [])

    def _has_risk_signal(
        self,
        handoff: Handoff,
        changed_paths: list[str],
    ) -> bool:
        text = " ".join(
            [
                handoff.goal,
                handoff.objective or "",
                handoff.body,
                " ".join(handoff.tags),
                " ".join(handoff.acceptance_criteria),
                " ".join(handoff.known_risks),
            ],
        ).lower()

        for keyword in self.force_human_if_keywords:
            if keyword.lower() in text:
                return True

        for changed in changed_paths:
            changed_lower = changed.lower()
            for prefix in self.force_human_if_changed_paths:
                if changed_lower.startswith(prefix.lower().rstrip("/") + "/") or changed_lower == prefix.lower().rstrip("/"):
                    return True

        return False


class HumanCheckpoint(BaseModel):
    """Snapshot shown to the operator when a workflow pauses for human input."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    workflow_name: str
    current_stage: WorkflowStage
    previous_stage: WorkflowStage | None
    previous_result: Verdict | None
    previous_agent: str | None
    previous_task_id: str | None
    handoff_path: Path | None
    changed_files: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    test_status: str | None = Field(default=None)
    reviewer_verdict: Verdict | None = Field(default=None)
    gate_reason: str | None = Field(default=None)
    suggested_action: str | None = Field(default=None)
    approve_command: str | None = Field(default=None)
    reject_command: str | None = Field(default=None)
    requeue_command: str | None = Field(default=None)
    abort_command: str | None = Field(default=None)

    def to_markdown(self) -> str:
        """Render the checkpoint as markdown for human review."""
        test_summary = self.test_status or "Unknown"
        if "FAIL" in test_summary.upper():
            test_banner = f"🔴 {test_summary}"
        elif "PASS" in test_summary.upper():
            test_banner = f"🟢 {test_summary}"
        else:
            test_banner = f"🟡 {test_summary}"

        lines = [
            f"# Human Checkpoint: {self.run_id}",
            "",
            f"**Workflow:** {self.workflow_name}",
            f"**Current stage:** {self.current_stage.value}",
            f"**Previous stage:** {self.previous_stage.value if self.previous_stage else 'N/A'}",
            f"**Previous result:** {self.previous_result.value if self.previous_result else 'N/A'}",
            f"**Previous agent:** {self.previous_agent or 'N/A'}",
            "",
            "## Validation summary",
            f"- **Changed files:** {len(self.changed_files)}",
            f"- **Test / lint status:** {test_banner}",
            f"- **Reviewer verdict:** {self.reviewer_verdict.value if self.reviewer_verdict else 'N/A'}",
            "",
            "## Handoff",
            f"- Path: `{self.handoff_path}`" if self.handoff_path else "- No handoff path recorded",
            "",
            "## Risk flags",
        ]
        if self.risk_flags:
            lines.extend(f"- {flag}" for flag in self.risk_flags)
        else:
            lines.append("- None")

        lines.extend(
            [
                "",
                "## Changed files",
            ],
        )
        if self.changed_files:
            lines.extend(f"- `{f}`" for f in self.changed_files)
        else:
            lines.append("- None recorded")

        lines.extend(
            [
                "",
                "## Reason for pause",
                self.gate_reason or "Policy requires human confirmation before advancing.",
                "",
                "## Suggested commands",
                f"```bash\n{self.approve_command or f'flipper-conductor approve {self.run_id}'}\n{self.reject_command or f'flipper-conductor reject {self.run_id} --reason \"...\"'}\n{self.requeue_command or f'flipper-conductor requeue {self.run_id} --to <stage> --reason \"...\"'}\n{self.abort_command or f'flipper-conductor abort {self.run_id}'}\n```",
            ],
        )
        return "\n".join(lines) + "\n"


class StageTimeoutConfig(BaseModel):
    """Timeout values for a specific workflow stage."""

    model_config = ConfigDict(extra="allow")

    soft_timeout_seconds: float | None = Field(default=None)
    hard_timeout_seconds: float | None = Field(default=None)


class TimeoutConfig(BaseModel):
    """Timeout configuration for the conductor."""

    model_config = ConfigDict(extra="allow")

    queued_timeout_seconds: float = Field(default=300.0)
    ack_timeout_seconds: float = Field(default=600.0)
    soft_timeout_seconds: float = Field(default=1800.0)
    hard_timeout_seconds: float = Field(default=3600.0)
    remote_timeout_seconds: float = Field(default=86400.0)
    checkpoint_grace_seconds: float = Field(default=300.0)
    max_stall_count: int = Field(default=2)
    max_retry_count: int = Field(default=2)
    stage_timeouts: dict[str, StageTimeoutConfig] = Field(default_factory=dict)

    def for_stage(self, stage: WorkflowStage) -> StageTimeoutConfig:
        """Return timeout config for ``stage``, falling back to defaults."""
        return self.stage_timeouts.get(
            stage.value,
            StageTimeoutConfig(
                soft_timeout_seconds=self.soft_timeout_seconds,
                hard_timeout_seconds=self.hard_timeout_seconds,
            ),
        )
