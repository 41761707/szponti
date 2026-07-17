"""Tests for WorkflowManager live state, stop race, retry and path security."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from AgentOrchestrator import AgentOrchestrator
from config import ConfigOverrides
from task_loader import TaskConfig
from tools import ToolResult
from web.backend.path_security import (
    ensure_task_path,
    is_under_root,
    validate_override_paths,
)
from web.backend.services.workflow_manager import (
    StartWorkflowRequest,
    WorkflowManager,
)
from web.backend.storage.run_store import RunStore
from workflow_models import (
    StageRun,
    StageStatus,
    WorkflowCommand,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowProfile,
    WorkflowRun,
    WorkflowStatus,
)


def _stage(
    name: str,
    worker: str,
    output: str = "ok",
    status: str = StageStatus.COMPLETED.value,
    attempt: int = 1,
) -> StageRun:
    now = datetime.now(timezone.utc)
    return StageRun(
        name=name,
        status=status,
        output=output,
        worker_name=worker,
        started_at=now,
        finished_at=now,
        attempt=attempt)


def _make_orch() -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = MagicMock()
    orch.workspace_dir = "."
    orch.api_key = "k"
    orch.model = "m"
    orch.tools = MagicMock()
    orch._bridge_lock = None
    orch._stop_requested = False
    orch._stop_flags = set()
    orch._active_workflow = None
    orch._event_sink = None
    orch._profile = None
    orch._develop_agent = None
    orch._cr_agent = None
    orch._client = None
    orch._last_techproject_output = ""
    orch._last_develop_output = ""
    orch._last_cr_output = ""
    return orch


@pytest.mark.asyncio
async def test_manager_shares_run_object_with_live_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    (tmp_path / ".cursor" / "mcp.json").write_text("{}", encoding="utf-8")

    store = RunStore(tmp_path / "runs.db")
    manager = WorkflowManager(store=store, default_workspace=tmp_path)
    profile = WorkflowProfile(enabled_stages=["tech-project"])
    task = TaskConfig(signature="EB-L", task_description="live")

    async def fake_run_workflow(
        self: Any,
        profile: WorkflowProfile,
        task: TaskConfig,
        event_sink: Any = None,
        interactive: bool = False,
        workflow_id: str | None = None,
        workflow: WorkflowRun | None = None,
    ) -> WorkflowRun:
        assert workflow is not None
        workflow.stages.append(_stage("prepare_techproject#1", "techproject"))
        workflow.status = WorkflowStatus.COMPLETED
        if event_sink is not None:
            await event_sink.emit(WorkflowEvent.create(
                workflow.id,
                WorkflowEventType.STAGE_COMPLETED,
                "done",
                stage_name="prepare_techproject#1"))
        return workflow

    monkeypatch.setattr(
        AgentOrchestrator,
        "run_workflow",
        fake_run_workflow)

    run = await manager.start_workflow(StartWorkflowRequest(
        task=task, profile=profile))
    for _ in range(40):
        live = manager.get_workflow(run.id)
        if live and live.stages:
            break
        await asyncio.sleep(0.025)
    live = manager.get_workflow(run.id)
    assert live is not None
    assert live.stages, "live stages must be visible on shared run object"
    assert live.stages[0].worker_name == "techproject"


@pytest.mark.asyncio
async def test_stop_before_start_cancels_workflow() -> None:
    orch = _make_orch()
    workflow_id = "wf-stop-early"
    await orch.request_stop(workflow_id)
    profile = WorkflowProfile(enabled_stages=["tech-project"])
    task = TaskConfig(signature="EB-S", task_description="stop")
    shared = WorkflowRun(
        id=workflow_id,
        task=task,
        profile=profile,
        status=WorkflowStatus.QUEUED,
        stages=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc))
    result = await orch.run_workflow(profile, task, workflow=shared)
    assert result.status == WorkflowStatus.CANCELLED
    assert result.id == workflow_id


@pytest.mark.asyncio
async def test_retry_techproject_attempt_and_new_client() -> None:
    orch = _make_orch()
    orch.tools.prepare_techproject.return_value = ToolResult(
        tool_name="prepare_techproject", prompt="tp")
    profile = WorkflowProfile(enabled_stages=["tech-project"])
    task = TaskConfig(signature="EB-R", task_description="retry")
    workflow = WorkflowRun(
        id="wf-retry",
        task=task,
        profile=profile,
        status=WorkflowStatus.COMPLETED,
        stages=[_stage("prepare_techproject#1", "techproject", attempt=1)],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc))
    orch._active_workflow = workflow
    orch._profile = profile
    orch._last_techproject_output = "prev"
    orch._client = None

    async def fake_run_stage(
        client: Any,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        assert iteration == 2
        return _stage(
            f"{tool_result.tool_name}#{iteration}",
            worker_name,
            "retry out",
            attempt=iteration or 1)

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = MagicMock()
    client_cm.__aexit__.return_value = None
    orch.launch_client = AsyncMock(return_value=client_cm)  # type: ignore[method-assign]

    result = await orch.retry_stage("wf-retry", "tech-project", feedback="fix")
    assert result.attempt == 2
    assert orch.launch_client.await_count == 1
    tech_stages = [
        stage for stage in workflow.stages
        if stage.worker_name == "techproject"]
    assert len(tech_stages) == 2


@pytest.mark.asyncio
async def test_run_workflow_develop_cr_profile() -> None:
    orch = _make_orch()
    orch.run_develop_cr_loop = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            _stage("run_develop#1", "develop", "impl"),
            _stage("run_cr#1", "cr", "CR_STATUS: OK")])
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = MagicMock()
    client_cm.__aexit__.return_value = None
    orch.launch_client = AsyncMock(return_value=client_cm)  # type: ignore[method-assign]

    profile = WorkflowProfile(
        enabled_stages=["develop", "cr"],
        stage_inputs={"tech-project": "existing design"})
    task = TaskConfig(signature="EB-DC", task_description="loop")
    result = await orch.run_workflow(profile, task)
    assert result.status == WorkflowStatus.COMPLETED
    skipped = [s for s in result.stages if s.status == "skipped"]
    assert any(s.name == "tech-project" for s in skipped)
    orch.run_develop_cr_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_workflow_full_profile_marks_skipped() -> None:
    orch = _make_orch()
    orch.tools.prepare_techproject.return_value = ToolResult(
        tool_name="prepare_techproject", prompt="tp")
    orch.run_develop_cr_loop = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            _stage("run_develop#1", "develop", "impl"),
            _stage("run_cr#1", "cr", "CR_STATUS: OK")])
    orch.tools.run_test_scenarios.return_value = ToolResult(
        tool_name="run_test_scenarios", prompt="t")

    async def fake_run_stage(
        client: Any,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        return _stage(
            f"{tool_result.tool_name}#{iteration or 1}",
            worker_name,
            "out")

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = MagicMock()
    client_cm.__aexit__.return_value = None
    orch.launch_client = AsyncMock(return_value=client_cm)  # type: ignore[method-assign]

    profile = WorkflowProfile(
        enabled_stages=[
            "tech-project", "develop", "cr", "scenariusze-testowe"])
    task = TaskConfig(signature="EB-F", task_description="full")
    result = await orch.run_workflow(profile, task)
    assert result.status == WorkflowStatus.COMPLETED
    skipped = [s.name for s in result.stages if s.status == "skipped"]
    assert skipped == ["git-push"]


def test_path_containment_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "secret.yaml"
    outside.write_text("x: 1\n", encoding="utf-8")
    assert is_under_root(workspace / "a.yaml", [workspace])
    with pytest.raises(ValueError, match="task_config_path"):
        ensure_task_path(str(outside), workspace)
    # skills poza workspace są dozwolone, o ile katalog istnieje
    external_skills = tmp_path / "central_skills"
    external_skills.mkdir()
    assert validate_override_paths(
        ConfigOverrides(skills_dir=external_skills),
        workspace) == []
    # nieistniejący katalog skills nadal jest błędem
    errors = validate_override_paths(
        ConfigOverrides(skills_dir=tmp_path / "elsewhere"),
        workspace)
    assert errors


@pytest.mark.asyncio
async def test_manager_retry_does_not_double_append(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    manager = WorkflowManager(store=store, default_workspace=tmp_path)
    profile = WorkflowProfile(enabled_stages=["tech-project"])
    task = TaskConfig(signature="EB-D", task_description="dedupe")
    now = datetime.now(timezone.utc)
    run = WorkflowRun(
        id="wf-dedupe",
        task=task,
        profile=profile,
        status=WorkflowStatus.COMPLETED,
        stages=[_stage("prepare_techproject#1", "techproject")],
        created_at=now,
        updated_at=now)
    manager._runs[run.id] = run

    orch = _make_orch()

    async def fake_retry(
        workflow_id: str,
        stage_name: str,
        feedback: str | None = None,
    ) -> StageRun:
        stage = _stage("prepare_techproject#2", "techproject", attempt=2)
        run.stages.append(stage)
        return stage

    orch.retry_stage = AsyncMock(side_effect=fake_retry)  # type: ignore[method-assign]
    manager._orchestrators[run.id] = orch

    updated = await manager.send_command(
        run.id,
        WorkflowCommand(type="retry_stage", stage_name="tech-project"))
    tech = [
        stage for stage in updated.stages
        if stage.worker_name == "techproject"]
    assert len(tech) == 2


@pytest.mark.asyncio
async def test_cli_authorize_push_follows_include_push() -> None:
    """Plan: authorize_push=include_push for CLI wrapper."""
    orch = _make_orch()
    captured: dict[str, Any] = {}

    async def fake_run_workflow(
        profile: WorkflowProfile,
        task: TaskConfig,
        event_sink: Any = None,
        interactive: bool = False,
        workflow_id: str | None = None,
        workflow: WorkflowRun | None = None,
    ) -> WorkflowRun:
        captured["authorize_push"] = profile.authorize_push
        captured["interactive"] = interactive
        return WorkflowRun(
            id="x",
            task=task,
            profile=profile,
            status=WorkflowStatus.COMPLETED,
            stages=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc))

    orch.run_workflow = AsyncMock(side_effect=fake_run_workflow)  # type: ignore[method-assign]
    await orch.run_default_workflow("desc", "EB-P", include_push=True)
    assert captured["authorize_push"] is True
    assert captured["interactive"] is True
