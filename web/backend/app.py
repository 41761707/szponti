"""FastAPI application for the Szponti web UI backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import detect_workspace
from web.backend.routes import config as config_routes
from web.backend.routes import workflows as workflow_routes
from web.backend.services.workflow_manager import WorkflowManager
from web.backend.storage.run_store import RunStore


def create_app(workspace: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    workspace_dir = (workspace or detect_workspace()).resolve()
    state_dir = workspace_dir / ".szponti" / "runs"
    store = RunStore(state_dir / "workflows.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.workspace = workspace_dir
        app.state.workflow_manager = WorkflowManager(
            store=store,
            default_workspace=workspace_dir)
        yield

    app = FastAPI(
        title="Szponti Orchestrator API",
        version="0.1.0",
        lifespan=lifespan)
    # dostępne od razu (TestClient bez lifespan / przed yield)
    app.state.workspace = workspace_dir
    app.state.workflow_manager = WorkflowManager(
        store=store,
        default_workspace=workspace_dir)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"])
    app.include_router(workflow_routes.router)
    app.include_router(config_routes.router)
    return app


app = create_app()
