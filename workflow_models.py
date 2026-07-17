"""Shared workflow models for orchestrator and web API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Protocol
from uuid import uuid4

from task_loader import TaskConfig

StageName = Literal[
    "tech-project",
    "develop",
    "cr",
    "scenariusze-testowe",
    "git-push",
    "db-context"]
ALL_STAGES: tuple[StageName, ...] = (
    "tech-project",
    "develop",
    "cr",
    "scenariusze-testowe",
    "git-push")


class WorkflowStatus(str, Enum):
    """Lifecycle status of a workflow run."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class StageStatus(str, Enum):
    """Lifecycle status of a single workflow stage."""

    PENDING = "pending"
    RUNNING = "running"
    NEEDS_CHANGES = "needs_changes"
    FAILED = "failed"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageRun:
    """Output of a single workflow stage."""

    name: str
    status: str
    output: str
    worker_name: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int | None = None
    error_message: str | None = None


class WorkflowEventType(str, Enum):
    """Event types emitted during a workflow run."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_SKIPPED = "stage_skipped"
    STAGE_NEEDS_CHANGES = "stage_needs_changes"
    LOG = "log"
    OUTPUT_CHUNK = "output_chunk"


@dataclass(frozen=True)
class WorkflowProfile:
    """Controls which stages run and how loops are limited."""

    enabled_stages: list[StageName]
    stage_inputs: dict[str, str] = field(default_factory=dict)
    authorize_push: bool = False
    cr_max_iterations: int = 5
    db_context_max_iterations: int = 3
    techproject_feedback: str | None = None


@dataclass(frozen=True)
class WorkflowCommand:
    """Command sent to a running or finished workflow."""

    type: Literal["stop", "retry_stage"]
    stage_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowEvent:
    """Single event in a workflow event stream."""

    id: str
    workflow_id: str
    type: WorkflowEventType
    message: str
    stage_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(
        workflow_id: str,
        event_type: WorkflowEventType,
        message: str,
        stage_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        """Build a new workflow event with generated id and timestamp."""
        return WorkflowEvent(
            id=str(uuid4()),
            workflow_id=workflow_id,
            type=event_type,
            message=message,
            stage_name=stage_name,
            payload=payload or {},
            created_at=datetime.now(timezone.utc))


class EventSink(Protocol):
    """Receives workflow events for streaming and persistence."""

    async def emit(self, event: WorkflowEvent) -> None:
        """Emit a workflow event."""
        ...


@dataclass
class WorkflowRun:
    """Mutable snapshot of a workflow execution."""

    id: str
    task: TaskConfig
    profile: WorkflowProfile
    status: WorkflowStatus
    stages: list[StageRun]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None

    def touch(self) -> None:
        """Update the last-modified timestamp."""
        self.updated_at = datetime.now(timezone.utc)
