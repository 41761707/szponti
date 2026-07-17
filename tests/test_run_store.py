"""Unit tests for RunStore persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from task_loader import TaskConfig
from web.backend.storage.run_store import RunStore
from workflow_models import (
    StageRun,
    StageStatus,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowProfile,
    WorkflowRun,
    WorkflowStatus,
)


def test_save_and_get_workflow(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    now = datetime.now(timezone.utc)
    workflow = WorkflowRun(
        id="wf-1",
        task=TaskConfig(signature="EB-1", task_description="Do thing"),
        profile=WorkflowProfile(
            enabled_stages=["cr"],
            stage_inputs={"develop": "impl"}),
        status=WorkflowStatus.COMPLETED,
        stages=[
            StageRun(
                name="cr",
                status=StageStatus.COMPLETED.value,
                output="CR_STATUS: OK",
                worker_name="cr")],
        created_at=now,
        updated_at=now,
        finished_at=now)
    store.save_workflow(workflow)
    store.append_event(WorkflowEvent.create(
        "wf-1",
        WorkflowEventType.WORKFLOW_COMPLETED,
        "done"))

    loaded = store.get_workflow("wf-1")
    assert loaded is not None
    assert loaded.task.signature == "EB-1"
    assert loaded.profile.enabled_stages == ["cr"]
    assert loaded.stages[0].output == "CR_STATUS: OK"
    events = store.list_events("wf-1")
    assert len(events) == 1
    assert store.get_workflow("missing") is None


def test_delete_workflow_removes_run_stages_and_events(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    now = datetime.now(timezone.utc)
    workflow = WorkflowRun(
        id="wf-del",
        task=TaskConfig(signature="EB-DEL", task_description="Remove me"),
        profile=WorkflowProfile(
            enabled_stages=["cr"],
            stage_inputs={"develop": "impl"}),
        status=WorkflowStatus.COMPLETED,
        stages=[
            StageRun(
                name="cr",
                status=StageStatus.COMPLETED.value,
                output="ok",
                worker_name="cr")],
        created_at=now,
        updated_at=now,
        finished_at=now)
    store.save_workflow(workflow)
    store.append_event(WorkflowEvent.create(
        "wf-del",
        WorkflowEventType.WORKFLOW_COMPLETED,
        "done"))

    assert store.delete_workflow("wf-del") is True
    assert store.get_workflow("wf-del") is None
    assert store.list_events("wf-del") == []
    assert store.delete_workflow("wf-del") is False
    assert store.delete_workflow("missing") is False
