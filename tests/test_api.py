"""API tests for FastAPI config/validate and health endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app import create_app


def test_health(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_validate_rejects_empty_profile(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/config/validate",
        json={"profile": {"enabled_stages": []}})
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["errors"]


def test_validate_rejects_path_outside_workspace(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    outside = tmp_path.parent / "outside-task.yaml"
    outside.write_text(
        "signature: EB-X\ntask_description: no\n",
        encoding="utf-8")
    response = client.post(
        "/api/config/validate",
        json={
            "task_config_path": str(outside),
            "profile": {"enabled_stages": ["tech-project"]}})
    assert response.status_code == 400
    assert any("task_config_path" in err for err in response.json()["errors"])


def test_task_preview(tmp_path: Path) -> None:
    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        "signature: EB-9\ntask_description: Preview me\n",
        encoding="utf-8")
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/tasks/preview",
        json={"task_config_path": str(task_file)})
    assert response.status_code == 200
    assert response.json()["signature"] == "EB-9"


def test_validate_accepts_db_context_stage(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/config/validate",
        json={"profile": {"enabled_stages": ["tech-project", "db-context"]}})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_validate_accepts_profile_without_db_context(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/config/validate",
        json={
            "profile": {
                "enabled_stages": ["develop", "cr"],
                "stage_inputs": {"tech-project": "existing design"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
