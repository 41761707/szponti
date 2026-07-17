"""Unit tests for task_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from task_loader import load_task_config, resolve_task_input


def test_load_task_config_english_keys(tmp_path: Path) -> None:
    path = tmp_path / "task.yaml"
    path.write_text(
        "signature: EB-1\ntask_description: |\n  Do the thing\n",
        encoding="utf-8")
    task = load_task_config(path)
    assert task.signature == "EB-1"
    assert "Do the thing" in task.task_description


def test_load_task_config_polish_keys(tmp_path: Path) -> None:
    path = tmp_path / "task.yml"
    path.write_text(
        "sygnatura: EB-2\nopis: Opis PL\n",
        encoding="utf-8")
    task = load_task_config(path)
    assert task.signature == "EB-2"
    assert task.task_description == "Opis PL"


def test_missing_keys(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("signature: EB-3\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="opis"):
        load_task_config(path)


def test_resolve_task_input(tmp_path: Path) -> None:
    path = tmp_path / "task.yaml"
    path.write_text(
        "signature: EB-4\ntask_description: X\n",
        encoding="utf-8")
    task = resolve_task_input(str(path))
    assert task.signature == "EB-4"
