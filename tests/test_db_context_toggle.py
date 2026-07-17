"""Unit tests for db-context toggle in AgentOrchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from AgentOrchestrator import AgentOrchestrator, DB_STATUS_NEEDED
from task_loader import TaskConfig
from tools import ToolResult
from workflow_models import StageRun, StageStatus, WorkflowProfile


def _make_orchestrator(profile: WorkflowProfile | None = None) -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = MagicMock()
    orch.workspace_dir = "."
    orch.api_key = "test-key"
    orch.model = "test-model"
    orch.tools = MagicMock()
    orch._bridge_lock = None
    orch._stop_requested = False
    orch._stop_flags = set()
    orch._active_workflow = None
    orch._event_sink = None
    orch._profile = profile
    orch._develop_agent = None
    orch._cr_agent = None
    orch._client = None
    orch._last_techproject_output = ""
    orch._last_develop_output = ""
    orch._last_cr_output = ""
    return orch


def _stage(name: str, worker: str, output: str) -> StageRun:
    now = datetime.now(timezone.utc)
    return StageRun(
        name=name,
        status=StageStatus.COMPLETED.value,
        output=output,
        worker_name=worker,
        started_at=now,
        finished_at=now,
        attempt=1)


@pytest.mark.asyncio
async def test_maybe_db_context_skipped_when_disabled() -> None:
    profile = WorkflowProfile(
        enabled_stages=["develop", "cr"],
        db_context_max_iterations=3)
    orch = _make_orchestrator(profile)
    orch.run_stage_agent = AsyncMock()  # type: ignore[method-assign]

    original = _stage("develop#1", "develop", f"output\n{DB_STATUS_NEEDED}")
    task = TaskConfig(signature="TEST-1", task_description="Task")
    result = await orch._maybe_db_context_for_standalone(
        MagicMock(),
        original,
        task,
        iteration=1)

    assert result is original
    orch.run_stage_agent.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_db_context_runs_when_enabled() -> None:
    profile = WorkflowProfile(
        enabled_stages=["develop", "cr", "db-context"],
        db_context_max_iterations=3)
    orch = _make_orchestrator(profile)
    orch.tools.run_db_context.return_value = ToolResult(
        tool_name="run_db_context",
        prompt="db")
    orch.tools.continue_develop.return_value = ToolResult(
        tool_name="continue_develop",
        prompt="cont")

    async def fake_run_stage(
        client: Any,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        if worker_name == "db-context":
            return _stage("run_db_context#1", "db-context", "db data")
        return _stage("develop#1", "develop", "done without db request")

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]

    original = _stage("develop#1", "develop", f"output\n{DB_STATUS_NEEDED}")
    task = TaskConfig(signature="TEST-1", task_description="Task")
    await orch._maybe_db_context_for_standalone(
        MagicMock(),
        original,
        task,
        iteration=1)

    db_calls = [
        call
        for call in orch.run_stage_agent.call_args_list
        if call.args[1] == "db-context"
    ]
    assert len(db_calls) == 1


@pytest.mark.asyncio
async def test_resolve_db_context_loop_skipped_when_disabled() -> None:
    profile = WorkflowProfile(
        enabled_stages=["develop"],
        db_context_max_iterations=3)
    orch = _make_orchestrator(profile)
    orch.run_stage_agent = AsyncMock()  # type: ignore[method-assign]

    original = _stage("develop#1", "develop", f"output\n{DB_STATUS_NEEDED}")
    result = await orch._resolve_db_context_loop(
        MagicMock(),
        MagicMock(),
        "develop",
        original,
        "Task",
        "TEST-1",
        1,
        None,
        [],
        is_develop=True,
        db_max=3)

    assert result is original
    orch.run_stage_agent.assert_not_called()


@pytest.mark.asyncio
async def test_techproject_review_loop_skips_db_context_when_disabled() -> None:
    profile = WorkflowProfile(
        enabled_stages=["tech-project"],
        db_context_max_iterations=3)
    orch = _make_orchestrator(profile)
    orch.tools.prepare_techproject.return_value = ToolResult(
        tool_name="prepare_techproject",
        prompt="tp")

    async def fake_run_stage(
        client: Any,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        return _stage(
            f"{worker_name}#{iteration or 1}",
            worker_name,
            f"tech output\n{DB_STATUS_NEEDED}")

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]
    orch._read_console_feedback = MagicMock(return_value="akceptuję projekt")  # type: ignore[method-assign]

    result = await orch.run_techproject_review_loop(
        MagicMock(),
        "Task",
        "TEST-1")

    assert result.worker_name == "techproject"
    db_calls = [
        call
        for call in orch.run_stage_agent.call_args_list
        if call.args[1] == "db-context"
    ]
    assert db_calls == []


@pytest.mark.asyncio
async def test_run_default_workflow_profile_includes_db_context() -> None:
    orch = _make_orchestrator()
    orch.run_workflow = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]

    await orch.run_default_workflow("Task", "TEST-1")

    profile = orch.run_workflow.call_args.args[0]
    assert "db-context" in profile.enabled_stages

