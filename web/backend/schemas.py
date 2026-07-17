"""Pydantic schemas for the web API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConfigOverridesSchema(BaseModel):
    """Per-run configuration overrides from the config panel."""

    workspace: str | None = None
    env_file: str | None = None
    skills_dir: str | None = None
    mcp_config_file: str | None = None
    model: str | None = None
    api_key: str | None = None


class WorkflowProfileSchema(BaseModel):
    """Workflow stage selection and limits."""

    enabled_stages: list[
        Literal[
            "tech-project",
            "develop",
            "cr",
            "scenariusze-testowe",
            "git-push",
            "db-context"]]
    stage_inputs: dict[str, str] = Field(default_factory=dict)
    authorize_push: bool = False
    cr_max_iterations: int = 5
    db_context_max_iterations: int = 3
    techproject_feedback: str | None = None


class TaskPayloadSchema(BaseModel):
    """Task identity: path or inline description."""

    task_config_path: str | None = None
    task_description: str | None = None
    signature: str | None = None


class StartWorkflowBody(BaseModel):
    """POST /api/workflows body."""

    task: TaskPayloadSchema
    profile: WorkflowProfileSchema
    config: ConfigOverridesSchema | None = None


class WorkflowCommandBody(BaseModel):
    """POST /api/workflows/{id}/commands body."""

    type: Literal["stop", "retry_stage"]
    stage_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class StageRunSchema(BaseModel):
    """Serialized stage run."""

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


class TaskConfigSchema(BaseModel):
    """Serialized task config (never includes secrets)."""

    signature: str
    task_description: str


class WorkflowRunSchema(BaseModel):
    """Serialized workflow run."""

    id: str
    task: TaskConfigSchema
    profile: WorkflowProfileSchema
    status: str
    stages: list[StageRunSchema]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class ValidateConfigBody(BaseModel):
    """POST /api/config/validate body."""

    config: ConfigOverridesSchema | None = None
    profile: WorkflowProfileSchema | None = None
    task_config_path: str | None = None


class ValidateConfigResponse(BaseModel):
    """Validation result for config panel."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    task_preview: TaskConfigSchema | None = None


class ConfigDefaultsResponse(BaseModel):
    """Detected defaults for the config panel."""

    workspace: str
    skills_dir: str
    mcp_config_file: str
    model: str
    env_files: list[str]
    api_key: str = ""


class TaskPreviewBody(BaseModel):
    """POST /api/tasks/preview body."""

    task_config_path: str


class SkillsResponse(BaseModel):
    """Available skills under a skills directory."""

    skills: list[str]
    skills_dir: str
