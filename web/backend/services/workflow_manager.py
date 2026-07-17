"""Active workflow lifecycle manager for the web API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from AgentOrchestrator import AgentOrchestrator
from config import ConfigOverrides, resolve_config
from task_loader import TaskConfig, resolve_task_input
from web.backend.path_security import (
    ensure_task_path,
    validate_override_paths,
)
from web.backend.services.profile_validator import ProfileValidator
from web.backend.storage.run_store import RunStore
from workflow_models import (
    WorkflowCommand,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowProfile,
    WorkflowRun,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)

_TERMINAL = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
}


@dataclass
class StartWorkflowRequest:
    """Payload for starting a new workflow."""

    task: TaskConfig
    profile: WorkflowProfile
    config: ConfigOverrides | None = None


class _ManagerEventSink:
    """EventSink adapter bound to a WorkflowManager instance."""

    def __init__(self, manager: WorkflowManager, workflow_id: str):
        self._manager = manager
        self._workflow_id = workflow_id

    async def emit(self, event: WorkflowEvent) -> None:
        await self._manager.emit_event(self._workflow_id, event)


class WorkflowManager:
    """Manage active runs, event queues and orchestrator instances."""

    def __init__(
        self,
        store: RunStore,
        default_workspace: Path | None = None,
    ):
        self.store = store
        self.default_workspace = default_workspace
        self._runs: dict[str, WorkflowRun] = {}
        self._orchestrators: dict[str, AgentOrchestrator] = {}
        self._queues: dict[str, list[asyncio.Queue[WorkflowEvent | None]]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start_workflow(
        self,
        request: StartWorkflowRequest,
    ) -> WorkflowRun:
        """Validate profile, create orchestrator and start the run."""
        errors = ProfileValidator.validate(request.profile)
        if errors:
            raise ValueError("; ".join(errors))
        workspace = self.default_workspace or Path.cwd()
        path_errors = validate_override_paths(request.config, workspace)
        if path_errors:
            raise ValueError("; ".join(path_errors))

        if request.config is None:
            config = resolve_config(workspace=self.default_workspace)
        else:
            config = resolve_config(
                workspace=self.default_workspace,
                overrides=request.config)

        workflow_id = str(uuid4())
        now = datetime.now(timezone.utc)
        workflow = WorkflowRun(
            id=workflow_id,
            task=request.task,
            profile=request.profile,
            status=WorkflowStatus.QUEUED,
            stages=[],
            created_at=now,
            updated_at=now)
        self._runs[workflow_id] = workflow
        self._queues[workflow_id] = []
        self.store.save_workflow(workflow)

        orchestrator = AgentOrchestrator(config)
        self._orchestrators[workflow_id] = orchestrator
        sink = _ManagerEventSink(self, workflow_id)
        task = asyncio.create_task(
            self._run_workflow_task(
                workflow_id,
                orchestrator,
                request.profile,
                request.task,
                sink))
        self._tasks[workflow_id] = task
        return workflow

    async def _run_workflow_task(
        self,
        workflow_id: str,
        orchestrator: AgentOrchestrator,
        profile: WorkflowProfile,
        task: TaskConfig,
        sink: _ManagerEventSink,
    ) -> None:
        """Background task executing run_workflow on the shared run object."""
        run = self._runs[workflow_id]
        run.status = WorkflowStatus.RUNNING
        run.touch()
        self.store.save_workflow(run)
        try:
            # ten sam obiekt co w GET /workflows/{id} — live stages
            result = await orchestrator.run_workflow(
                profile,
                task,
                event_sink=sink,
                interactive=False,
                workflow=run)
            self._runs[workflow_id] = result
            self.store.save_workflow(result)
        except Exception as exc:
            logger.exception(
                "Workflow %s failed: %s", workflow_id, exc)
            run.status = WorkflowStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.touch()
            self.store.save_workflow(run)
            detail = str(exc).strip() or type(exc).__name__
            await sink.emit(WorkflowEvent.create(
                workflow_id,
                WorkflowEventType.WORKFLOW_FAILED,
                detail,
                payload={"error_type": type(exc).__name__}))
        finally:
            await self._close_subscribers(workflow_id)

    async def subscribe(
        self,
        workflow_id: str,
    ) -> AsyncIterator[WorkflowEvent]:
        """Yield historical then live events for SSE (deduped by id)."""
        if (
            workflow_id not in self._runs
            and self.store.get_workflow(workflow_id) is None
        ):
            raise KeyError(workflow_id)

        queue: asyncio.Queue[WorkflowEvent | None] = asyncio.Queue()
        # rejestracja przed historią — eventy live nie giną
        self._queues.setdefault(workflow_id, []).append(queue)
        seen: set[str] = set()

        for event in self.store.list_events(workflow_id):
            seen.add(event.id)
            yield event

        if self._is_workflow_finished(workflow_id):
            while not queue.empty():
                item = queue.get_nowait()
                if item is None:
                    break
                if item.id not in seen:
                    seen.add(item.id)
                    yield item
            subscribers = self._queues.get(workflow_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
            return

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
        finally:
            subscribers = self._queues.get(workflow_id, [])
            if queue in subscribers:
                subscribers.remove(queue)

    def _is_workflow_finished(self, workflow_id: str) -> bool:
        """Return True when the run is terminal and its task is done."""
        run = self.get_workflow(workflow_id)
        if run is None or run.status not in _TERMINAL:
            return False
        task = self._tasks.get(workflow_id)
        return task is None or task.done()

    async def send_command(
        self,
        workflow_id: str,
        command: WorkflowCommand,
    ) -> WorkflowRun:
        """Handle stop / retry_stage commands."""
        orchestrator = self._orchestrators.get(workflow_id)
        run = self.get_workflow(workflow_id)
        if run is None:
            raise KeyError(workflow_id)

        if command.type == "stop":
            if orchestrator is not None:
                await orchestrator.request_stop(workflow_id)
            run.status = WorkflowStatus.CANCELLED
            run.touch()
            self.store.save_workflow(run)
            return run

        if command.type == "retry_stage":
            if orchestrator is None:
                raise RuntimeError("Workflow is not active for retry")
            stage_name = command.stage_name or ""
            feedback = None
            if command.payload:
                feedback = command.payload.get("feedback")
            # rebind shared run + sink — retry działa też po completed/failed
            orchestrator._active_workflow = run
            orchestrator._profile = run.profile
            orchestrator._event_sink = _ManagerEventSink(self, workflow_id)
            # _run_techproject_once / _dispatch_retry same zapisują stage
            await orchestrator.retry_stage(
                workflow_id, stage_name, feedback=feedback)
            run.touch()
            self.store.save_workflow(run)
            return run

        raise ValueError(f"Unknown command type: {command.type}")

    def get_workflow(self, workflow_id: str) -> WorkflowRun | None:
        """Return in-memory or persisted workflow."""
        if workflow_id in self._runs:
            return self._runs[workflow_id]
        return self.store.get_workflow(workflow_id)

    def list_workflows(self, limit: int = 50) -> list[WorkflowRun]:
        """List recent workflows from memory and store."""
        stored = {run.id: run for run in self.store.list_workflows(limit)}
        stored.update(self._runs)
        runs = sorted(
            stored.values(),
            key=lambda item: item.created_at,
            reverse=True)
        return runs[:limit]

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Stop an active run if needed and remove it from history."""
        run = self.get_workflow(workflow_id)
        if run is None:
            return False

        orchestrator = self._orchestrators.get(workflow_id)
        if orchestrator is not None and run.status not in _TERMINAL:
            try:
                await orchestrator.request_stop(workflow_id)
            except Exception:
                logger.exception(
                    "Failed to stop workflow %s before delete",
                    workflow_id)

        task = self._tasks.pop(workflow_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._close_subscribers(workflow_id)
        self._queues.pop(workflow_id, None)
        self._runs.pop(workflow_id, None)
        self._orchestrators.pop(workflow_id, None)
        return self.store.delete_workflow(workflow_id)

    async def emit_event(
        self,
        workflow_id: str,
        event: WorkflowEvent,
    ) -> None:
        """Persist and fan-out an event to subscribers."""
        self.store.append_event(event)
        run = self._runs.get(workflow_id)
        if run is not None:
            run.touch()
            # unikamy zapisu całego runa przy każdym chunku outputu
            if event.type != WorkflowEventType.OUTPUT_CHUNK:
                self.store.save_workflow(run)
        for queue in list(self._queues.get(workflow_id, [])):
            await queue.put(event)

    async def _close_subscribers(self, workflow_id: str) -> None:
        for queue in list(self._queues.get(workflow_id, [])):
            await queue.put(None)


def resolve_task_from_payload(
    payload: dict[str, Any],
    workspace: Path | None = None,
) -> TaskConfig:
    """Build TaskConfig from API task payload variants."""
    if "task_config_path" in payload and payload["task_config_path"]:
        path_value = str(payload["task_config_path"])
        if workspace is not None:
            ensure_task_path(path_value, workspace)
        return resolve_task_input(path_value)
    description = payload.get("task_description")
    signature = payload.get("signature")
    if isinstance(description, str) and isinstance(signature, str):
        if description.strip() and signature.strip():
            return TaskConfig(
                signature=signature.strip(),
                task_description=description.strip())
    raise ValueError(
        "task must include task_config_path or "
        "task_description + signature")
