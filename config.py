"""Runtime configuration resolution for Szponti."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SzpontiConfig:
    """Resolved runtime configuration for AgentOrchestrator."""

    workspace_dir: Path
    state_dir: Path
    skills_dir: Path
    mcp_config_file: Path
    api_key: str
    model: str


@dataclass(frozen=True)
class ConfigOverrides:
    """Per-run configuration overrides for the web panel.

    Empty fields mean "keep defaults / environment values".
    """

    workspace: Path | None = None
    env_file: Path | None = None
    skills_dir: Path | None = None
    mcp_config_file: Path | None = None
    model: str | None = None
    api_key: str | None = None


def load_env_file(env_file: Path) -> None:
    """Load key=value pairs from env file without overriding OS variables."""
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    """Return environment variable value or raise ValueError."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Environment variable {name} is not set")
    return value


def detect_workspace(start_dir: Path | None = None) -> Path:
    """Detect workspace directory by walking up from start directory."""
    current = (start_dir or Path.cwd()).resolve()
    candidate = current
    while True:
        if (candidate / ".git").exists():
            return candidate
        if (candidate / ".cursor" / "skills").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return current


def resolve_env_files(
    workspace: Path,
    env_file: Path | None = None,
) -> list[Path]:
    """Resolve environment files for workspace."""
    if env_file is not None:
        return [env_file.resolve()]
    agent_dir = Path(__file__).resolve().parent
    candidates = [
        workspace / ".env",
        agent_dir / ".env",
        workspace / ".szponti.env"]
    return [path for path in candidates if path.exists()]


def apply_default_paths(workspace: Path) -> None:
    """Set default path env vars only when not already defined."""
    defaults = {
        "AGENT_WORKSPACE_DIR": str(workspace),
        "MCP_TOOLS_SKILLS_DIR": str(workspace / ".cursor" / "skills"),
        "MCP_TOOLS_MCP_CONFIG_FILE": str(workspace / ".cursor" / "mcp.json"),
        "SZPONTI_STATE_DIR": str(workspace / ".szponti")}
    for key, value in defaults.items():
        if key not in os.environ:
            os.environ[key] = value


def _default_paths_for(workspace: Path) -> dict[str, Path]:
    """Return default path values for a workspace without mutating env."""
    return {
        "AGENT_WORKSPACE_DIR": workspace,
        "MCP_TOOLS_SKILLS_DIR": workspace / ".cursor" / "skills",
        "MCP_TOOLS_MCP_CONFIG_FILE": workspace / ".cursor" / "mcp.json",
        "SZPONTI_STATE_DIR": workspace / ".szponti"}


def _read_env_file_values(env_file: Path) -> dict[str, str]:
    """Parse env file into a dict without mutating os.environ."""
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in values:
            values[key] = value
    return values


def _merged_env_values(
    workspace: Path,
    env_file: Path | None,
) -> dict[str, str]:
    """Merge env file values without writing into os.environ."""
    merged: dict[str, str] = {}
    for env_path in resolve_env_files(workspace, env_file):
        for key, value in _read_env_file_values(env_path).items():
            if key not in merged:
                merged[key] = value
    return merged


def _resolve_value(
    overrides: ConfigOverrides | None,
    attr: str,
    env_key: str,
    file_values: dict[str, str],
    default: str | None = None,
    required: bool = True,
) -> str:
    """Resolve a single config value: override > os.environ > file > default."""
    if overrides is not None:
        override_value = getattr(overrides, attr, None)
        if override_value is not None:
            return str(override_value)
    if env_key in os.environ and os.environ[env_key]:
        return os.environ[env_key]
    if env_key in file_values and file_values[env_key]:
        return file_values[env_key]
    if default is not None:
        return default
    if required:
        raise ValueError(f"Environment variable {env_key} is not set")
    return ""


def resolve_config(
    workspace: Path | None = None,
    env_file: Path | None = None,
    overrides: ConfigOverrides | None = None,
) -> SzpontiConfig:
    """Resolve configuration for workspace.

    When overrides are provided, paths/model/api_key are applied per-run
    without mutating os.environ (safe for concurrent web runs).
    """
    effective_env_file = env_file
    if overrides is not None and overrides.env_file is not None:
        effective_env_file = overrides.env_file

    if overrides is not None and overrides.workspace is not None:
        workspace = overrides.workspace.resolve()
    elif workspace is None:
        explicit = os.environ.get("AGENT_WORKSPACE_DIR")
        workspace = (
            Path(explicit).resolve() if explicit else detect_workspace())
    else:
        workspace = workspace.resolve()

    # ścieżka CLI: ładujemy env do procesu jak dotychczas
    if overrides is None:
        for env_path in resolve_env_files(workspace, effective_env_file):
            load_env_file(env_path)
        apply_default_paths(workspace)
        state_dir = Path(require_env("SZPONTI_STATE_DIR"))
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "cache").mkdir(parents=True, exist_ok=True)
        (state_dir / "runs").mkdir(parents=True, exist_ok=True)
        return SzpontiConfig(
            workspace_dir=Path(require_env("AGENT_WORKSPACE_DIR")),
            state_dir=state_dir,
            skills_dir=Path(require_env("MCP_TOOLS_SKILLS_DIR")),
            mcp_config_file=Path(require_env("MCP_TOOLS_MCP_CONFIG_FILE")),
            api_key=require_env("CURSOR_API_KEY"),
            model=require_env("AGENT_MODEL"))

    # ścieżka web: per-run bez mutacji os.environ
    file_values = _merged_env_values(workspace, effective_env_file)
    defaults = _default_paths_for(workspace)
    workspace_dir = Path(_resolve_value(
        overrides,
        "workspace",
        "AGENT_WORKSPACE_DIR",
        file_values,
        default=str(defaults["AGENT_WORKSPACE_DIR"])))
    state_dir = Path(
        os.environ.get("SZPONTI_STATE_DIR")
        or file_values.get("SZPONTI_STATE_DIR")
        or str(defaults["SZPONTI_STATE_DIR"]))
    skills_dir = Path(_resolve_value(
        overrides,
        "skills_dir",
        "MCP_TOOLS_SKILLS_DIR",
        file_values,
        default=str(defaults["MCP_TOOLS_SKILLS_DIR"])))
    mcp_config_file = Path(_resolve_value(
        overrides,
        "mcp_config_file",
        "MCP_TOOLS_MCP_CONFIG_FILE",
        file_values,
        default=str(defaults["MCP_TOOLS_MCP_CONFIG_FILE"])))
    api_key = _resolve_value(
        overrides, "api_key", "CURSOR_API_KEY", file_values)
    model = _resolve_value(
        overrides, "model", "AGENT_MODEL", file_values)

    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "cache").mkdir(parents=True, exist_ok=True)
    (state_dir / "runs").mkdir(parents=True, exist_ok=True)

    return SzpontiConfig(
        workspace_dir=workspace_dir,
        state_dir=state_dir,
        skills_dir=skills_dir,
        mcp_config_file=mcp_config_file,
        api_key=api_key,
        model=model)
