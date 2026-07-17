"""Path containment helpers for API-supplied filesystem paths."""

from __future__ import annotations

from pathlib import Path

from config import ConfigOverrides


def is_under_root(path: Path, roots: list[Path]) -> bool:
    """Return True when resolved path is equal to or under any root."""
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def allowed_roots(workspace: Path) -> list[Path]:
    """Return the allowlist of roots for task browse / task files."""
    return [workspace.resolve()]


def ensure_under_roots(
    path: Path,
    roots: list[Path],
    label: str,
) -> Path:
    """Resolve path and raise ValueError when outside allowed roots."""
    resolved = path.expanduser().resolve()
    if not is_under_root(resolved, roots):
        raise ValueError(
            f"{label} must be under the workspace: {resolved}")
    return resolved


def validate_override_paths(
    overrides: ConfigOverrides | None,
    workspace: Path,
) -> list[str]:
    """Validate ConfigOverrides path shapes.

    skills_dir / mcp_config_file / env_file may live outside the agent
    workspace (central szponti install). Only task browse stays sandboxed.
    """
    if overrides is None:
        return []
    errors: list[str] = []

    if overrides.workspace is not None:
        ws = Path(overrides.workspace).expanduser().resolve()
        if not ws.exists() or not ws.is_dir():
            errors.append(f"workspace is not a directory: {ws}")

    if overrides.env_file is not None:
        env_path = Path(overrides.env_file).expanduser().resolve()
        if not env_path.exists() or not env_path.is_file():
            errors.append(f"env_file not found: {env_path}")

    if overrides.skills_dir is not None:
        skills = Path(overrides.skills_dir).expanduser().resolve()
        if not skills.exists() or not skills.is_dir():
            errors.append(f"skills_dir not found: {skills}")

    if overrides.mcp_config_file is not None:
        mcp = Path(overrides.mcp_config_file).expanduser().resolve()
        if not mcp.exists() or not mcp.is_file():
            errors.append(f"mcp_config_file not found: {mcp}")

    return errors


def ensure_task_path(task_config_path: str, workspace: Path) -> Path:
    """Resolve and contain a task_config_path under the workspace."""
    return ensure_under_roots(
        Path(task_config_path),
        allowed_roots(workspace),
        "task_config_path")
