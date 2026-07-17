"""Workflow REST and SSE routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sse_starlette.sse import EventSourceResponse

from web.backend.schemas import (
    StageRunSchema,
    StartWorkflowBody,
    TaskConfigSchema,
    WorkflowCommandBody,
    WorkflowProfileSchema,
    WorkflowRunSchema,
)
from web.backend.services.workflow_manager import (
    StartWorkflowRequest,
    WorkflowManager,
    resolve_task_from_payload,
)
from workflow_models import WorkflowCommand, WorkflowProfile

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _get_manager(request: Request) -> WorkflowManager:
    return request.app.state.workflow_manager


def _to_schema(run: Any) -> WorkflowRunSchema:
    return WorkflowRunSchema(
        id=run.id,
        task=TaskConfigSchema(
            signature=run.task.signature,
            task_description=run.task.task_description),
        profile=WorkflowProfileSchema(
            enabled_stages=list(run.profile.enabled_stages),
            stage_inputs=dict(run.profile.stage_inputs),
            authorize_push=run.profile.authorize_push,
            cr_max_iterations=run.profile.cr_max_iterations,
            db_context_max_iterations=run.profile.db_context_max_iterations,
            techproject_feedback=run.profile.techproject_feedback),
        status=run.status.value if hasattr(run.status, "value") else run.status,
        stages=[
            StageRunSchema(
                name=stage.name,
                status=stage.status,
                output=stage.output,
                worker_name=stage.worker_name,
                agent_id=stage.agent_id,
                run_id=stage.run_id,
                started_at=stage.started_at,
                finished_at=stage.finished_at,
                attempt=stage.attempt,
                error_message=stage.error_message)
            for stage in run.stages],
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at)


def _profile_from_schema(schema: WorkflowProfileSchema) -> WorkflowProfile:
    return WorkflowProfile(
        enabled_stages=list(schema.enabled_stages),
        stage_inputs=dict(schema.stage_inputs),
        authorize_push=schema.authorize_push,
        cr_max_iterations=schema.cr_max_iterations,
        db_context_max_iterations=schema.db_context_max_iterations,
        techproject_feedback=schema.techproject_feedback)


@router.post("", response_model=WorkflowRunSchema)
async def start_workflow(
    body: StartWorkflowBody,
    request: Request,
) -> WorkflowRunSchema:
    """Start a workflow for the given profile and task."""
    manager = _get_manager(request)
    workspace = getattr(request.app.state, "workspace", None)
    try:
        task = resolve_task_from_payload(
            body.task.model_dump(),
            workspace=workspace)
        profile = _profile_from_schema(body.profile)
        overrides = None
        if body.config is not None:
            from pathlib import Path

            from config import ConfigOverrides

            raw = body.config.model_dump()
            overrides = ConfigOverrides(
                workspace=Path(raw["workspace"]) if raw.get("workspace") else None,
                env_file=Path(raw["env_file"]) if raw.get("env_file") else None,
                skills_dir=(
                    Path(raw["skills_dir"]) if raw.get("skills_dir") else None),
                mcp_config_file=(
                    Path(raw["mcp_config_file"])
                    if raw.get("mcp_config_file") else None),
                model=raw.get("model"),
                api_key=raw.get("api_key"))
        run = await manager.start_workflow(StartWorkflowRequest(
            task=task,
            profile=profile,
            config=overrides))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_schema(run)


@router.get("", response_model=list[WorkflowRunSchema])
async def list_workflows(request: Request) -> list[WorkflowRunSchema]:
    """List recent workflow runs."""
    manager = _get_manager(request)
    return [_to_schema(run) for run in manager.list_workflows()]


@router.get("/{workflow_id}", response_model=WorkflowRunSchema)
async def get_workflow(
    workflow_id: str,
    request: Request,
) -> WorkflowRunSchema:
    """Return current workflow state."""
    manager = _get_manager(request)
    run = manager.get_workflow(workflow_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _to_schema(run)


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: str,
    request: Request,
) -> Response:
    """Remove a workflow run from history."""
    manager = _get_manager(request)
    deleted = await manager.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return Response(status_code=204)


@router.get("/{workflow_id}/events")
async def workflow_events(
    workflow_id: str,
    request: Request,
) -> EventSourceResponse:
    """SSE stream of workflow events."""
    manager = _get_manager(request)
    if manager.get_workflow(workflow_id) is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    async def event_generator():
        try:
            async for event in manager.subscribe(workflow_id):
                payload = {
                    "id": event.id,
                    "workflow_id": event.workflow_id,
                    "type": event.type.value,
                    "stage_name": event.stage_name,
                    "message": event.message,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat()}
                yield {
                    "event": event.type.value,
                    "id": event.id,
                    "data": json.dumps(payload)}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow not found") from exc

    return EventSourceResponse(event_generator())


@router.post("/{workflow_id}/commands", response_model=WorkflowRunSchema)
async def workflow_commands(
    workflow_id: str,
    body: WorkflowCommandBody,
    request: Request,
) -> WorkflowRunSchema:
    """Send stop or retry_stage command."""
    manager = _get_manager(request)
    try:
        run = await manager.send_command(
            workflow_id,
            WorkflowCommand(
                type=body.type,
                stage_name=body.stage_name,
                payload=body.payload))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_schema(run)
