"""Configuration panel and task browser routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from config import (
    ConfigOverrides,
    detect_workspace,
    resolve_config,
    resolve_env_files,
)
from task_loader import resolve_task_input
from tools import Tools
from web.backend.path_security import (
    ensure_task_path,
    is_under_root,
    allowed_roots,
    validate_override_paths,
)
from web.backend.schemas import (
    ConfigDefaultsResponse,
    SkillsResponse,
    TaskConfigSchema,
    TaskPreviewBody,
    ValidateConfigBody,
    ValidateConfigResponse,
    WorkflowProfileSchema,
)
from web.backend.services.profile_validator import ProfileValidator
from workflow_models import WorkflowProfile

router = APIRouter(prefix="/api", tags=["config"])


def _workspace_root(request: Request) -> Path:
    explicit = getattr(request.app.state, "workspace", None)
    if explicit is not None:
        return Path(explicit)
    return detect_workspace()


def _overrides_from_schema(
    schema: ValidateConfigBody | None,
) -> ConfigOverrides | None:
    if schema is None or schema.config is None:
        return None
    raw = schema.config.model_dump()
    return ConfigOverrides(
        workspace=Path(raw["workspace"]) if raw.get("workspace") else None,
        env_file=Path(raw["env_file"]) if raw.get("env_file") else None,
        skills_dir=Path(raw["skills_dir"]) if raw.get("skills_dir") else None,
        mcp_config_file=(
            Path(raw["mcp_config_file"])
            if raw.get("mcp_config_file") else None),
        model=raw.get("model"),
        api_key=raw.get("api_key"))


def _profile_from_schema(
    schema: WorkflowProfileSchema | None,
) -> WorkflowProfile | None:
    if schema is None:
        return None
    return WorkflowProfile(
        enabled_stages=list(schema.enabled_stages),
        stage_inputs=dict(schema.stage_inputs),
        authorize_push=schema.authorize_push,
        cr_max_iterations=schema.cr_max_iterations,
        db_context_max_iterations=schema.db_context_max_iterations,
        techproject_feedback=schema.techproject_feedback)


@router.get("/health")
async def health() -> dict[str, str]:
    """Backend healthcheck."""
    return {"status": "ok"}


@router.get("/config/defaults", response_model=ConfigDefaultsResponse)
async def config_defaults(request: Request) -> ConfigDefaultsResponse:
    """Return detected defaults without exposing api_key."""
    workspace = _workspace_root(request)
    env_files = [str(path) for path in resolve_env_files(workspace)]
    skills_dir = os.environ.get(
        "MCP_TOOLS_SKILLS_DIR",
        str(workspace / ".cursor" / "skills"))
    mcp_config = os.environ.get(
        "MCP_TOOLS_MCP_CONFIG_FILE",
        str(workspace / ".cursor" / "mcp.json"))
    model = os.environ.get("AGENT_MODEL", "")
    return ConfigDefaultsResponse(
        workspace=str(workspace),
        skills_dir=skills_dir,
        mcp_config_file=mcp_config,
        model=model,
        env_files=env_files,
        api_key="")


@router.post("/config/validate", response_model=None)
async def validate_config(
    body: ValidateConfigBody,
    request: Request,
):
    """Validate paths, task file and profile dependencies."""
    errors: list[str] = []
    warnings: list[str] = []
    task_preview: TaskConfigSchema | None = None
    workspace = _workspace_root(request)
    overrides = _overrides_from_schema(body)
    errors.extend(validate_override_paths(overrides, workspace))

    # istnienie ścieżek overrides sprawdzane w validate_override_paths
    if body.task_config_path:
        try:
            task_workspace = workspace
            if overrides is not None and overrides.workspace is not None:
                task_workspace = Path(overrides.workspace).expanduser().resolve()
            ensure_task_path(body.task_config_path, task_workspace)
            task = resolve_task_input(body.task_config_path)
            task_preview = TaskConfigSchema(
                signature=task.signature,
                task_description=task.task_description)
        except (RuntimeError, FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))

    profile = _profile_from_schema(body.profile)
    if profile is not None:
        errors.extend(ProfileValidator.validate(profile))

    payload = ValidateConfigResponse(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        task_preview=task_preview)
    if errors:
        # plan §6.6: błędy walidacji jako 400
        return JSONResponse(
            status_code=400,
            content=payload.model_dump(mode="json"))
    return payload


@router.get("/config/skills", response_model=SkillsResponse)
async def list_skills(
    request: Request,
    skills_dir: str | None = Query(default=None),
) -> SkillsResponse:
    """List available skills under the given or default skills directory."""
    workspace = _workspace_root(request)
    if skills_dir:
        path = Path(skills_dir).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"skills_dir not found: {path}")
    else:
        path = workspace / ".cursor" / "skills"
    try:
        if skills_dir:
            config = resolve_config(
                workspace=workspace,
                overrides=ConfigOverrides(skills_dir=path))
        else:
            config = resolve_config(
                workspace=workspace,
                overrides=ConfigOverrides())
    except ValueError:
        # brak API key w środowisku — budujemy minimalny config lokalny
        from config import SzpontiConfig

        config = SzpontiConfig(
            workspace_dir=workspace,
            state_dir=workspace / ".szponti",
            skills_dir=path,
            mcp_config_file=workspace / ".cursor" / "mcp.json",
            api_key="unused",
            model="unused")
    skills = Tools(config).list_available_skills()
    return SkillsResponse(skills=skills, skills_dir=str(path))


@router.get("/tasks/browse")
async def browse_tasks(
    request: Request,
    root: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> dict[str, list[str]]:
    """Limited file browser for task YAML files under allowed roots."""
    workspace = _workspace_root(request)
    allowed = allowed_roots(workspace)
    search_root = Path(root) if root else workspace
    if not is_under_root(search_root, allowed):
        raise HTTPException(
            status_code=400,
            detail="root must be under the workspace")
    if not search_root.exists():
        raise HTTPException(status_code=404, detail="root not found")

    matches: list[str] = []
    query = (q or "").casefold()
    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".yaml", ".yml"):
            continue
        if query and query not in path.name.casefold():
            continue
        if is_under_root(path, allowed):
            matches.append(str(path.resolve()))
        if len(matches) >= 100:
            break
    return {"files": matches}


@router.post("/tasks/preview", response_model=TaskConfigSchema)
async def preview_task(
    body: TaskPreviewBody,
    request: Request,
) -> TaskConfigSchema:
    """Preview signature and description from a task config path."""
    workspace = _workspace_root(request)
    try:
        ensure_task_path(body.task_config_path, workspace)
        task = resolve_task_input(body.task_config_path)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskConfigSchema(
        signature=task.signature,
        task_description=task.task_description)
