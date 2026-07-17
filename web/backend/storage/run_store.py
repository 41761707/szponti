"""SQLite persistence for workflow runs and events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from task_loader import TaskConfig
from workflow_models import (
    StageRun,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowProfile,
    WorkflowRun,
    WorkflowStatus,
)


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _dt_from_str(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class RunStore:
    """Persist workflow runs, stages and events in SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        """Create tables if they do not exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    task_description TEXT NOT NULL,
                    signature TEXT,
                    profile_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS stage_runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    worker_name TEXT,
                    agent_id TEXT,
                    run_id TEXT,
                    attempt INTEGER,
                    output TEXT,
                    error_message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY (workflow_id) REFERENCES workflow_runs(id)
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    stage_name TEXT,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workflow_id) REFERENCES workflow_runs(id)
                );
                """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_workflow(self, workflow: WorkflowRun) -> None:
        """Insert or update a workflow run and replace its stages."""
        profile_json = json.dumps({
            "enabled_stages": list(workflow.profile.enabled_stages),
            "stage_inputs": workflow.profile.stage_inputs,
            "authorize_push": workflow.profile.authorize_push,
            "cr_max_iterations": workflow.profile.cr_max_iterations,
            "db_context_max_iterations": (
                workflow.profile.db_context_max_iterations),
            "techproject_feedback": workflow.profile.techproject_feedback})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    id, task_description, signature, profile_json,
                    status, created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    task_description=excluded.task_description,
                    signature=excluded.signature,
                    profile_json=excluded.profile_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    finished_at=excluded.finished_at
                """,
                (
                    workflow.id,
                    workflow.task.task_description,
                    workflow.task.signature,
                    profile_json,
                    workflow.status.value,
                    _dt_to_str(workflow.created_at),
                    _dt_to_str(workflow.updated_at),
                    _dt_to_str(workflow.finished_at)))
            conn.execute(
                "DELETE FROM stage_runs WHERE workflow_id = ?",
                (workflow.id,))
            for index, stage in enumerate(workflow.stages):
                conn.execute(
                    """
                    INSERT INTO stage_runs (
                        id, workflow_id, name, status, worker_name,
                        agent_id, run_id, attempt, output, error_message,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{workflow.id}:{index}:{stage.name}",
                        workflow.id,
                        stage.name,
                        stage.status,
                        stage.worker_name,
                        stage.agent_id,
                        stage.run_id,
                        stage.attempt,
                        stage.output,
                        stage.error_message,
                        _dt_to_str(stage.started_at),
                        _dt_to_str(stage.finished_at)))

    def append_event(self, event: WorkflowEvent) -> None:
        """Persist a workflow event."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_events (
                    id, workflow_id, stage_name, type,
                    message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.workflow_id,
                    event.stage_name,
                    event.type.value,
                    event.message,
                    json.dumps(event.payload),
                    _dt_to_str(event.created_at)))

    def get_workflow(self, workflow_id: str) -> WorkflowRun | None:
        """Load a workflow run by id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE id = ?",
                (workflow_id,)).fetchone()
            if row is None:
                return None
            stages = conn.execute(
                """
                SELECT * FROM stage_runs
                WHERE workflow_id = ?
                ORDER BY rowid
                """,
                (workflow_id,)).fetchall()
        return self._row_to_workflow(row, stages)

    def list_workflows(self, limit: int = 50) -> list[WorkflowRun]:
        """Return recent workflow runs."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)).fetchall()
            result: list[WorkflowRun] = []
            for row in rows:
                stages = conn.execute(
                    """
                    SELECT * FROM stage_runs
                    WHERE workflow_id = ?
                    ORDER BY rowid
                    """,
                    (row["id"],)).fetchall()
                result.append(self._row_to_workflow(row, stages))
        return result

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and related stages/events.

        Returns True when a row was removed.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM workflow_runs WHERE id = ?",
                (workflow_id,)).fetchone()
            if row is None:
                return False
            conn.execute(
                "DELETE FROM workflow_events WHERE workflow_id = ?",
                (workflow_id,))
            conn.execute(
                "DELETE FROM stage_runs WHERE workflow_id = ?",
                (workflow_id,))
            conn.execute(
                "DELETE FROM workflow_runs WHERE id = ?",
                (workflow_id,))
        return True

    def list_events(self, workflow_id: str) -> list[WorkflowEvent]:
        """Return all events for a workflow in order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_events
                WHERE workflow_id = ?
                ORDER BY created_at, rowid
                """,
                (workflow_id,)).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_workflow(
        self,
        row: sqlite3.Row,
        stage_rows: list[sqlite3.Row],
    ) -> WorkflowRun:
        profile_data: dict[str, Any] = json.loads(row["profile_json"])
        profile = WorkflowProfile(
            enabled_stages=profile_data.get("enabled_stages", []),
            stage_inputs=profile_data.get("stage_inputs", {}),
            authorize_push=bool(profile_data.get("authorize_push", False)),
            cr_max_iterations=int(
                profile_data.get("cr_max_iterations", 5)),
            db_context_max_iterations=int(
                profile_data.get("db_context_max_iterations", 3)),
            techproject_feedback=profile_data.get("techproject_feedback"))
        stages = [
            StageRun(
                name=stage["name"],
                status=stage["status"],
                output=stage["output"] or "",
                worker_name=stage["worker_name"],
                agent_id=stage["agent_id"],
                run_id=stage["run_id"],
                attempt=stage["attempt"],
                error_message=stage["error_message"],
                started_at=_dt_from_str(stage["started_at"]),
                finished_at=_dt_from_str(stage["finished_at"]))
            for stage in stage_rows]
        return WorkflowRun(
            id=row["id"],
            task=TaskConfig(
                signature=row["signature"] or "",
                task_description=row["task_description"]),
            profile=profile,
            status=WorkflowStatus(row["status"]),
            stages=stages,
            created_at=_dt_from_str(row["created_at"]) or datetime.now(),
            updated_at=_dt_from_str(row["updated_at"]) or datetime.now(),
            finished_at=_dt_from_str(row["finished_at"]))

    def _row_to_event(self, row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(
            id=row["id"],
            workflow_id=row["workflow_id"],
            type=WorkflowEventType(row["type"]),
            message=row["message"],
            stage_name=row["stage_name"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=_dt_from_str(row["created_at"]) or datetime.now())
