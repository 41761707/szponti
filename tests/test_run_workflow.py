"""Mocked unit tests for AgentOrchestrator.run_workflow profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from AgentOrchestrator import AgentOrchestrator
from task_loader import TaskConfig
from tools import ToolResult
from workflow_models import (
    StageRun,
    StageStatus,
    WorkflowEvent,
    WorkflowProfile,
    WorkflowStatus,
)


@dataclass
class _FakeConfig:
    workspace_dir: str = "."
    skills_dir: str = "."
    mcp_config_file: str = "."
    api_key: str = "test-key"
    model: str = "test-model"


class _CollectingSink:
    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    async def emit(self, event: WorkflowEvent) -> None:
        self.events.append(event)


def _make_orchestrator() -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.config = _FakeConfig()  # type: ignore[assignment]
    orch.workspace_dir = "."
    orch.api_key = "test-key"
    orch.model = "test-model"
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
async def test_run_workflow_techproject_only() -> None:
    orch = _make_orchestrator()
    sink = _CollectingSink()
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
            f"{tool_result.tool_name}#{iteration or 1}",
            worker_name,
            "tech output")

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]
    orch.launch_client = AsyncMock()  # type: ignore[method-assign]
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = MagicMock()
    client_cm.__aexit__.return_value = None
    orch.launch_client.return_value = client_cm

    profile = WorkflowProfile(enabled_stages=["tech-project"])
    task = TaskConfig(signature="EB-1", task_description="Task")
    result = await orch.run_workflow(profile, task, event_sink=sink)

    assert result.status == WorkflowStatus.COMPLETED
    skipped = [stage for stage in result.stages if stage.status == "skipped"]
    assert len(skipped) == 4
    assert any(stage.worker_name == "techproject" for stage in result.stages)
    assert any(event.type.value == "workflow_completed" for event in sink.events)


@pytest.mark.asyncio
async def test_run_workflow_cr_only_uses_stage_input() -> None:
    orch = _make_orchestrator()
    orch.tools.run_cr.return_value = ToolResult(tool_name="run_cr", prompt="cr")

    async def fake_run_stage(
        client: Any,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        return _stage("run_cr#1", worker_name, "CR_STATUS: OK")

    orch.run_stage_agent = AsyncMock(side_effect=fake_run_stage)  # type: ignore[method-assign]
    orch.launch_client = AsyncMock()  # type: ignore[method-assign]
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = MagicMock()
    client_cm.__aexit__.return_value = None
    orch.launch_client.return_value = client_cm

    profile = WorkflowProfile(
        enabled_stages=["cr"],
        stage_inputs={"develop": "existing impl"})
    task = TaskConfig(signature="EB-2", task_description="CR only")
    result = await orch.run_workflow(profile, task)

    assert result.status == WorkflowStatus.COMPLETED
    orch.tools.run_cr.assert_called_once()
    assert orch._last_develop_output == "existing impl"
