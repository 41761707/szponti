"""Unit tests for config overrides resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import ConfigOverrides, resolve_config


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    (tmp_path / ".cursor" / "mcp.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_overrides_do_not_mutate_environ(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "env-key")
    monkeypatch.setenv("AGENT_MODEL", "env-model")
    before = dict(os.environ)

    config = resolve_config(
        workspace=workspace,
        overrides=ConfigOverrides(
            model="override-model",
            api_key="override-key",
            skills_dir=workspace / ".cursor" / "skills"))

    assert config.model == "override-model"
    assert config.api_key == "override-key"
    assert config.skills_dir == workspace / ".cursor" / "skills"
    assert os.environ.get("AGENT_MODEL") == "env-model"
    assert os.environ.get("CURSOR_API_KEY") == "env-key"
    # kluczowe zmienne ścieżkowe nie powinny być dopisane przez overrides
    for key in ("MCP_TOOLS_SKILLS_DIR", "AGENT_WORKSPACE_DIR"):
        assert os.environ.get(key) == before.get(key)


def test_overrides_missing_api_key_raises(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    env_file = workspace / "empty.env"
    env_file.write_text("AGENT_MODEL=composer-2.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CURSOR_API_KEY"):
        resolve_config(
            workspace=workspace,
            overrides=ConfigOverrides(
                env_file=env_file,
                model="composer-2.5"))
