"""Cursor SDK multi-agent workflow orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cursor_sdk import AsyncAgent, AsyncClient, CursorAgentError, LocalAgentOptions

from config import SzpontiConfig, resolve_config
from task_loader import TaskConfig, resolve_task_input
from tools import Tools, ToolResult
from workflow_models import (
    ALL_STAGES,
    EventSink,
    StageRun,
    StageStatus,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowProfile,
    WorkflowRun,
    WorkflowStatus,
)


class StageRunError(RuntimeError):
    """Raised when a workflow stage fails."""

    def __init__(self, stage_run: StageRun):
        self.stage_run = stage_run
        super().__init__(
            f"Stage failed: {stage_run.name} [{stage_run.worker_name}] "
            f"status={stage_run.status}, run_id={stage_run.run_id}")


class WorkflowCancelledError(RuntimeError):
    """Raised when a workflow is cancelled via request_stop."""


CR_STATUS_OK = "CR_STATUS: OK"
CR_STATUS_POPRAWKI = "CR_STATUS: POPRAWKI"
DB_STATUS_NEEDED = "DB_STATUS: POTRZEBNE_DANE"
# Nie usuwaj "_" — niszczy markery CR_STATUS / DB_STATUS.
_MARKDOWN_EMPHASIS_RE = re.compile(r"[*`]")
_CR_STATUS_LINE_RE = re.compile(
    r"^CR_STATUS:\s*(OK|POPRAWKI)\s*\.?\s*$",
    re.IGNORECASE)
_DB_STATUS_LINE_RE = re.compile(
    r"^DB_STATUS:\s*POTRZEBNE_DANE\s*\.?\s*$",
    re.IGNORECASE)


def _normalize_status_line(line: str) -> str:
    """Strip markdown emphasis without breaking underscore markers."""
    return _MARKDOWN_EMPHASIS_RE.sub("", line.strip())


def _parse_cr_statuses(output: str) -> list[str]:
    """Return CR status tokens from dedicated status lines, in order."""
    statuses: list[str] = []
    for line in output.splitlines():
        normalized = _normalize_status_line(line)
        match = _CR_STATUS_LINE_RE.match(normalized)
        if match:
            statuses.append(match.group(1).upper())
    return statuses


def _strip_markdown(line: str) -> str:
    """Remove common markdown markers from a line for status detection."""
    return _normalize_status_line(line).upper()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _failure_message(exc: BaseException) -> str:
    """Build a non-empty failure message for events and UI."""
    text = str(exc).strip()
    if text:
        return text
    return f"{type(exc).__name__}: workflow failed (no details from exception)"


def _map_sdk_status(status: str) -> str:
    """Map Cursor SDK run status to StageStatus value."""
    if status == "finished":
        return StageStatus.COMPLETED.value
    return StageStatus.FAILED.value


class AgentOrchestrator:
    """Coordinates Cursor SDK runs for the local multi-agent workflow."""

    def __init__(self, config: SzpontiConfig):
        self.config = config
        self.workspace_dir = str(config.workspace_dir)
        self.api_key = config.api_key
        self.model = config.model
        self.tools = Tools(config)
        self._bridge_lock: asyncio.Lock | None = None
        self._stop_requested = False
        # flaga stop per workflow_id — działa też przed startem run_workflow
        self._stop_flags: set[str] = set()
        self._active_workflow: WorkflowRun | None = None
        self._event_sink: EventSink | None = None
        self._profile: WorkflowProfile | None = None
        self._develop_agent: AsyncAgent | None = None
        self._cr_agent: AsyncAgent | None = None
        self._client: AsyncClient | None = None
        self._last_techproject_output: str = ""
        self._last_develop_output: str = ""
        self._last_cr_output: str = ""

    async def run_default_workflow(
        self,
        task_description: str,
        signature: str,
        include_push: bool = False,
        push_confirmed: bool = False,
        event_sink: EventSink | None = None,
    ) -> WorkflowRun:
        """Run full CLI workflow; wrapper around run_workflow."""
        stages = list(ALL_STAGES) if include_push else list(ALL_STAGES[:-1])
        if "db-context" not in stages:
            stages = [*stages, "db-context"]
        # CLI: --push oznacza zgodę (plan: authorize_push=include_push)
        profile = WorkflowProfile(
            enabled_stages=stages,
            authorize_push=include_push or push_confirmed)
        task = TaskConfig(
            signature=signature,
            task_description=task_description)
        return await self.run_workflow(
            profile,
            task,
            event_sink=event_sink,
            interactive=True)

    async def run_workflow(
        self,
        profile: WorkflowProfile,
        task: TaskConfig,
        event_sink: EventSink | None = None,
        interactive: bool = False,
        workflow_id: str | None = None,
        workflow: WorkflowRun | None = None,
    ) -> WorkflowRun:
        """Dispatch only enabled stages using stage_inputs for skipped deps."""
        self._event_sink = event_sink
        self._profile = profile
        if workflow is not None:
            # jedno źródło prawdy z WorkflowManager
            active = workflow
            active.task = task
            active.profile = profile
            active.status = WorkflowStatus.RUNNING
            active.touch()
        else:
            active = WorkflowRun(
                id=workflow_id or str(uuid4()),
                task=task,
                profile=profile,
                status=WorkflowStatus.RUNNING,
                stages=[],
                created_at=_utc_now(),
                updated_at=_utc_now())
        self._active_workflow = active
        # nie resetuj ślepo — respektuj stop ustawiony przed startem
        self._stop_requested = active.id in self._stop_flags
        self._stop_flags.discard(active.id)
        self._bridge_lock = asyncio.Lock()
        if self._stop_requested:
            active.status = WorkflowStatus.CANCELLED
            active.finished_at = _utc_now()
            active.touch()
            await self._emit(
                WorkflowEventType.WORKFLOW_CANCELLED,
                "Workflow cancelled before start")
            self._bridge_lock = None
            return active
        await self._emit(
            WorkflowEventType.WORKFLOW_STARTED,
            "Workflow started")
        try:
            async with await self.launch_client() as client:
                self._client = client
                await self._execute_profile(client, profile, task, interactive)
            if self._stop_requested:
                active.status = WorkflowStatus.CANCELLED
                await self._emit(
                    WorkflowEventType.WORKFLOW_CANCELLED,
                    "Workflow cancelled")
            else:
                active.status = WorkflowStatus.COMPLETED
                await self._emit(
                    WorkflowEventType.WORKFLOW_COMPLETED,
                    "Workflow completed")
        except WorkflowCancelledError:
            active.status = WorkflowStatus.CANCELLED
            await self._emit(
                WorkflowEventType.WORKFLOW_CANCELLED,
                "Workflow cancelled")
        except (StageRunError, CursorAgentError, FileNotFoundError) as exc:
            active.status = WorkflowStatus.FAILED
            message = _failure_message(exc)
            if isinstance(exc, StageRunError):
                message = (
                    exc.stage_run.error_message
                    or f"Stage failed: {exc.stage_run.name}")
                # _execute_tool_run może już zapisać stage przed raise
                self._record_stage(exc.stage_run)
            await self._emit(
                WorkflowEventType.WORKFLOW_FAILED,
                message,
                payload={"error_type": type(exc).__name__})
        except Exception as exc:
            # np. błąd bridge'a SDK poza CursorAgentError
            active.status = WorkflowStatus.FAILED
            message = _failure_message(exc)
            await self._emit(
                WorkflowEventType.WORKFLOW_FAILED,
                message,
                payload={"error_type": type(exc).__name__})
            # nie re-raise — unikamy podwójnego workflow_failed w managerze
        finally:
            active.finished_at = _utc_now()
            active.touch()
            self._bridge_lock = None
            self._client = None
            self._develop_agent = None
            self._cr_agent = None
        return active

    async def _execute_profile(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        interactive: bool,
    ) -> None:
        """Run enabled stages in order and mark others as skipped."""
        enabled = set(profile.enabled_stages)
        for stage_name in ALL_STAGES:
            if stage_name not in enabled:
                await self._append_skipped(stage_name)

        tech_output = await self._resolve_techproject(
            client, profile, task, interactive, enabled)
        self._raise_if_stopped()

        develop_output, cr_output = await self._resolve_develop_cr(
            client, profile, task, tech_output, enabled)
        self._raise_if_stopped()

        await self._resolve_tests(
            client, profile, task, develop_output, cr_output, enabled)
        self._raise_if_stopped()

        await self._resolve_push(
            client, profile, task, cr_output or develop_output, enabled)

    async def _resolve_techproject(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        interactive: bool,
        enabled: set[str],
    ) -> str:
        """Return tech-project output from stage, input, or empty."""
        if "tech-project" not in enabled:
            output = profile.stage_inputs.get("tech-project", "")
            self._last_techproject_output = output
            return output
        if interactive:
            result = await self.run_techproject_review_loop(
                client,
                task.task_description,
                task.signature)
            self._record_stage(result)
            self._last_techproject_output = result.output
            return result.output
        result = await self._run_techproject_once(
            client,
            task,
            feedback=profile.techproject_feedback)
        self._last_techproject_output = result.output
        return result.output

    async def _run_techproject_once(
        self,
        client: AsyncClient,
        task: TaskConfig,
        feedback: str | None = None,
        previous_result: str = "",
        iteration: int = 1,
    ) -> StageRun:
        """Run a single tech-project iteration (web / retry path)."""
        tool = self.tools.prepare_techproject(
            task.task_description,
            task.signature,
            feedback,
            previous_result)
        result = await self.run_stage_agent(
            client, "techproject", tool, iteration=iteration)
        result = await self._maybe_db_context_for_standalone(
            client, result, task, iteration)
        self._record_stage(result)
        return result

    async def _resolve_develop_cr(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        tech_output: str,
        enabled: set[str],
    ) -> tuple[str, str]:
        """Run develop/CR loop or use stage_inputs for skipped stages."""
        want_develop = "develop" in enabled
        want_cr = "cr" in enabled
        if not want_develop and not want_cr:
            develop = profile.stage_inputs.get("develop", "")
            cr = profile.stage_inputs.get("cr", "")
            self._last_develop_output = develop
            self._last_cr_output = cr
            return develop, cr
        if want_develop and want_cr:
            results = await self.run_develop_cr_loop(
                client,
                task.task_description,
                task.signature,
                tech_output or profile.stage_inputs.get("tech-project", ""),
                max_iterations=profile.cr_max_iterations,
                db_max=profile.db_context_max_iterations)
            for stage in results:
                self._record_stage(stage)
            develop_out = self._last_output_for(results, "develop")
            cr_out = self._last_output_for(results, "cr")
            self._last_develop_output = develop_out
            self._last_cr_output = cr_out
            return develop_out, cr_out
        if want_develop and not want_cr:
            return await self._run_develop_only(
                client, profile, task, tech_output)
        return await self._run_cr_only(client, profile, task)

    async def _run_develop_only(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        tech_output: str,
    ) -> tuple[str, str]:
        """Run a single develop stage without CR."""
        tool = self.tools.run_develop(
            task.task_description,
            task.signature,
            tech_output or profile.stage_inputs.get("tech-project", ""))
        develop = await self.run_stage_agent(client, "develop", tool, iteration=1)
        develop = await self._maybe_db_context_for_standalone(
            client, develop, task, 1)
        self._record_stage(develop)
        self._last_develop_output = develop.output
        cr = profile.stage_inputs.get("cr", "")
        self._last_cr_output = cr
        return develop.output, cr

    async def _run_cr_only(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
    ) -> tuple[str, str]:
        """Run CR against provided develop output (cr_only profile)."""
        develop_output = profile.stage_inputs.get("develop", "")
        self._last_develop_output = develop_output
        tool = self.tools.run_cr(
            task.task_description,
            task.signature,
            develop_output)
        cr = await self.run_stage_agent(client, "cr", tool, iteration=1)
        cr = await self._maybe_db_context_for_standalone(
            client, cr, task, 1, develop_output=develop_output)
        if not self._is_cr_accepted(cr.output):
            cr = StageRun(
                name=cr.name,
                status=StageStatus.NEEDS_CHANGES.value,
                output=cr.output,
                worker_name=cr.worker_name,
                agent_id=cr.agent_id,
                run_id=cr.run_id,
                started_at=cr.started_at,
                finished_at=cr.finished_at,
                attempt=cr.attempt)
            await self._emit(
                WorkflowEventType.STAGE_NEEDS_CHANGES,
                "CR requires changes",
                stage_name=cr.name)
        self._record_stage(cr)
        self._last_cr_output = cr.output
        return develop_output, cr.output

    async def _resolve_tests(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        develop_output: str,
        cr_output: str,
        enabled: set[str],
    ) -> None:
        """Run test scenarios stage when enabled."""
        if "scenariusze-testowe" not in enabled:
            return
        context = (
            cr_output
            or develop_output
            or profile.stage_inputs.get("cr", "")
            or profile.stage_inputs.get("develop", ""))
        result = await self.run_stage_agent(
            client,
            "scenariusze-testowe",
            self.tools.run_test_scenarios(
                task.task_description,
                task.signature,
                context))
        self._record_stage(result)

    async def _resolve_push(
        self,
        client: AsyncClient,
        profile: WorkflowProfile,
        task: TaskConfig,
        cr_output: str,
        enabled: set[str],
    ) -> None:
        """Run git-push when enabled and authorized."""
        if "git-push" not in enabled:
            return
        context = cr_output or profile.stage_inputs.get("cr", "")
        results = await self._run_push_stage(
            client,
            task.task_description,
            task.signature,
            context,
            push_confirmed=profile.authorize_push)
        for stage in results:
            if stage.status == "blocked":
                # web: authorize_push jest wymagane przez ProfileValidator
                failed = StageRun(
                    name=stage.name,
                    status=StageStatus.FAILED.value,
                    output=stage.output,
                    worker_name=stage.worker_name,
                    error_message="git-push requires authorize_push=true")
                self._record_stage(failed)
                raise StageRunError(failed)
            self._record_stage(stage)

    async def request_stop(self, workflow_id: str) -> None:
        """Request cancellation; safe before run_workflow starts."""
        self._stop_flags.add(workflow_id)
        if (
            self._active_workflow is not None
            and self._active_workflow.id == workflow_id
        ):
            self._stop_requested = True

    async def retry_stage(
        self,
        workflow_id: str,
        stage_name: str,
        feedback: str | None = None,
    ) -> StageRun:
        """Retry a stage on a controlled path (new client after finish OK)."""
        workflow = self._active_workflow
        if workflow is None or workflow.id != workflow_id:
            raise RuntimeError(f"No active workflow: {workflow_id}")
        base = self._normalize_stage_base(stage_name)
        last = self._find_last_stage(base)
        retryable = {
            StageStatus.FAILED.value,
            StageStatus.NEEDS_CHANGES.value,
            StageStatus.COMPLETED.value}
        if last is not None and last.status not in retryable:
            raise RuntimeError(
                f"Stage {stage_name} status={last.status} is not retryable")
        attempt = self._next_attempt(base)
        workflow.status = WorkflowStatus.RUNNING
        workflow.finished_at = None
        workflow.touch()
        self._stop_requested = False
        self._stop_flags.discard(workflow_id)

        owns_client = self._client is None
        client_cm = None
        try:
            if owns_client:
                client_cm = await self.launch_client()
                self._client = await client_cm.__aenter__()
            client = self._client
            if client is None:
                raise RuntimeError("No active client for retry")
            result = await self._dispatch_retry(
                client, workflow, base, attempt, feedback)
            if result.status == StageStatus.FAILED.value:
                workflow.status = WorkflowStatus.FAILED
            else:
                workflow.status = WorkflowStatus.COMPLETED
            workflow.finished_at = _utc_now()
            workflow.touch()
            return result
        except (StageRunError, CursorAgentError, FileNotFoundError) as exc:
            workflow.status = WorkflowStatus.FAILED
            workflow.finished_at = _utc_now()
            workflow.touch()
            if isinstance(exc, StageRunError):
                self._record_stage(exc.stage_run)
                return exc.stage_run
            raise
        finally:
            if owns_client and client_cm is not None:
                await client_cm.__aexit__(None, None, None)
                self._client = None

    async def _dispatch_retry(
        self,
        client: AsyncClient,
        workflow: WorkflowRun,
        base: str,
        attempt: int,
        feedback: str | None,
    ) -> StageRun:
        """Run a single retry for a normalized stage base name."""
        task = workflow.task
        profile = workflow.profile
        if base == "tech-project":
            result = await self._run_techproject_once(
                client,
                task,
                feedback=feedback,
                previous_result=self._last_techproject_output,
                iteration=attempt)
            self._last_techproject_output = result.output
            return result
        if base == "develop":
            tech = (
                self._last_techproject_output
                or profile.stage_inputs.get("tech-project", ""))
            tool = self.tools.run_develop(
                task.task_description, task.signature, tech)
            develop = await self.run_stage_agent(
                client, "develop", tool, iteration=attempt)
            develop = await self._maybe_db_context_for_standalone(
                client, develop, task, attempt)
            self._record_stage(develop)
            self._last_develop_output = develop.output
            return develop
        if base == "cr":
            develop_output = (
                self._last_develop_output
                or profile.stage_inputs.get("develop", ""))
            tool = self.tools.run_cr(
                task.task_description, task.signature, develop_output)
            cr = await self.run_stage_agent(
                client, "cr", tool, iteration=attempt)
            cr = await self._maybe_db_context_for_standalone(
                client, cr, task, attempt, develop_output=develop_output)
            if not self._is_cr_accepted(cr.output):
                cr = StageRun(
                    name=cr.name,
                    status=StageStatus.NEEDS_CHANGES.value,
                    output=cr.output,
                    worker_name=cr.worker_name,
                    agent_id=cr.agent_id,
                    run_id=cr.run_id,
                    started_at=cr.started_at,
                    finished_at=cr.finished_at,
                    attempt=cr.attempt)
                await self._emit(
                    WorkflowEventType.STAGE_NEEDS_CHANGES,
                    "CR requires changes",
                    stage_name=cr.name)
            self._record_stage(cr)
            self._last_cr_output = cr.output
            return cr
        if base == "scenariusze-testowe":
            context = (
                self._last_cr_output
                or self._last_develop_output
                or profile.stage_inputs.get("cr", "")
                or profile.stage_inputs.get("develop", ""))
            result = await self.run_stage_agent(
                client,
                "scenariusze-testowe",
                self.tools.run_test_scenarios(
                    task.task_description, task.signature, context),
                iteration=attempt)
            self._record_stage(result)
            return result
        if base == "git-push":
            context = (
                self._last_cr_output
                or profile.stage_inputs.get("cr", ""))
            results = await self._run_push_stage(
                client,
                task.task_description,
                task.signature,
                context,
                push_confirmed=profile.authorize_push)
            for stage in results:
                if stage.status == "blocked":
                    failed = StageRun(
                        name=stage.name,
                        status=StageStatus.FAILED.value,
                        output=stage.output,
                        worker_name=stage.worker_name,
                        attempt=attempt,
                        error_message=(
                            "git-push requires authorize_push=true"))
                    self._record_stage(failed)
                    raise StageRunError(failed)
                self._record_stage(stage)
                return stage
            raise RuntimeError("git-push retry produced no stage")
        raise RuntimeError(f"Retry not supported for stage: {base}")

    @staticmethod
    def _normalize_stage_base(stage_name: str) -> str:
        """Map UI / tool stage names to a canonical retry base."""
        raw = stage_name.split("#", 1)[0].strip().casefold()
        aliases = {
            "tech-project": "tech-project",
            "techproject": "tech-project",
            "prepare_techproject": "tech-project",
            "develop": "develop",
            "run_develop": "develop",
            "continue_develop": "develop",
            "cr": "cr",
            "run_cr": "cr",
            "continue_cr": "cr",
            "scenariusze-testowe": "scenariusze-testowe",
            "run_test_scenarios": "scenariusze-testowe",
            "git-push": "git-push",
            "prepare_git_push": "git-push",
            "db-context": "db-context",
            "run_db_context": "db-context"}
        if raw not in aliases:
            raise RuntimeError(f"Retry not supported for stage: {stage_name}")
        return aliases[raw]

    def _stage_matches_base(self, stage: StageRun, base: str) -> bool:
        """Return True when a StageRun belongs to the given base stage."""
        worker = (stage.worker_name or "").casefold()
        name = stage.name.split("#", 1)[0].casefold()
        groups = {
            "tech-project": {
                "tech-project", "techproject", "prepare_techproject"},
            "develop": {"develop", "run_develop", "continue_develop"},
            "cr": {"cr", "run_cr", "continue_cr"},
            "scenariusze-testowe": {
                "scenariusze-testowe", "run_test_scenarios"},
            "git-push": {"git-push", "prepare_git_push"},
            "db-context": {"db-context", "run_db_context"}}
        tokens = groups.get(base, {base})
        return worker in tokens or name in tokens

    def _find_last_stage(self, base: str) -> StageRun | None:
        """Return the last recorded stage matching a base name."""
        workflow = self._active_workflow
        if workflow is None:
            return None
        for stage in reversed(workflow.stages):
            if self._stage_matches_base(stage, base):
                return stage
        return None

    def _next_attempt(self, base: str) -> int:
        """Return the next attempt number for a stage base."""
        workflow = self._active_workflow
        if workflow is None:
            return 1
        highest = 0
        for stage in workflow.stages:
            if not self._stage_matches_base(stage, base):
                continue
            if stage.attempt is not None:
                highest = max(highest, stage.attempt)
            else:
                # fallback z sufiksu name#N
                if "#" in stage.name:
                    suffix = stage.name.rsplit("#", 1)[-1]
                    if suffix.isdigit():
                        highest = max(highest, int(suffix))
        return highest + 1

    async def _run_push_stage(
        self,
        client: AsyncClient,
        task_description: str,
        signature: str,
        cr_output: str,
        push_confirmed: bool,
    ) -> list[StageRun]:
        """Run the push stage."""
        push_tool = self.tools.prepare_git_push(
            task_description,
            signature,
            cr_output,
            push_confirmed)
        if push_tool.requires_human_confirmation:
            return [StageRun(
                name=push_tool.tool_name,
                status="blocked",
                output=push_tool.prompt,
                worker_name="git-push")]
        return [await self.run_stage_agent(client, "git-push", push_tool)]

    async def run_db_context(
        self,
        task_description: str,
        signature: str | None = None,
        question: str | None = None,
        previous_result: str | None = None,
    ) -> StageRun:
        """Run the db context stage."""
        async with await self.launch_client() as client:
            self._bridge_lock = asyncio.Lock()
            try:
                return await self.run_stage_agent(
                    client,
                    "db-context",
                    self.tools.run_db_context(
                        task_description,
                        signature,
                        question,
                        previous_result))
            finally:
                self._bridge_lock = None

    async def launch_client(self) -> AsyncClient:
        """Launch a new Cursor SDK client (local bridge subprocess)."""
        try:
            return await AsyncClient.launch_bridge(
                workspace=self.workspace_dir)
        except NotImplementedError as exc:
            # Windows + uvicorn --reload -> SelectorEventLoop bez subprocess
            raise RuntimeError(
                "Cursor bridge cannot spawn on this asyncio event loop "
                "(NotImplementedError). On Windows run uvicorn WITHOUT "
                "--reload, e.g.: uvicorn web.backend.app:app --port 8000"
            ) from exc

    def local_options(self) -> LocalAgentOptions:
        """Local agent options."""
        return LocalAgentOptions(
            cwd=self.workspace_dir,
            setting_sources=["project"])

    async def run_techproject_review_loop(
        self,
        client: AsyncClient,
        task_description: str,
        signature: str,
    ) -> StageRun:
        """Run the interactive techproject review loop (CLI)."""
        previous_result = ""
        review_feedback = ""
        iteration = 1
        db_max = (
            self._profile.db_context_max_iterations
            if self._profile else 3)
        db_count = 0
        while True:
            self._raise_if_stopped()
            tool = self.tools.prepare_techproject(
                task_description,
                signature,
                review_feedback,
                previous_result)
            result = await self.run_stage_agent(
                client, "techproject", tool, iteration=iteration)
            if self._is_db_context_needed(result.output):
                if not self._is_db_context_enabled():
                    feedback = self._read_console_feedback(
                        "\nProjekt techniczny gotowy. Wpisz akceptacje albo "
                        "poproś o poprawki: ")
                    if self._is_techproject_accepted(feedback):
                        print(
                            "\n[Projekt techniczny zaakceptowany. "
                            "Start implementacji]\n",
                            flush=True)
                        return result
                    previous_result = result.output
                    review_feedback = feedback
                    iteration += 1
                    continue
                db_count += 1
                if db_count > db_max:
                    failed = StageRun(
                        name=result.name,
                        status=StageStatus.FAILED.value,
                        output=result.output,
                        worker_name=result.worker_name,
                        agent_id=result.agent_id,
                        run_id=result.run_id,
                        error_message=(
                            f"db-context exceeded max iterations ({db_max})"))
                    raise StageRunError(failed)
                print(
                    "\n[Wykryto potrzebę danych z bazy danych]\n",
                    flush=True)
                db_context = await self.run_stage_agent(
                    client,
                    "db-context",
                    self.tools.run_db_context(
                        task_description,
                        signature,
                        question=None,
                        previous_result=result.output),
                    iteration=iteration)
                self._record_stage(db_context)
                previous_result = (
                    f"{result.output}\n\n ## Kontekst bazy danych ##\n"
                    f"{db_context.output}")
                review_feedback = (
                    "Uzupełnij techproject, uwzględniając kontekst "
                    "bazy danych.")
                iteration += 1
                continue
            feedback = self._read_console_feedback(
                "\nProjekt techniczny gotowy. Wpisz akceptacje albo "
                "poproś o poprawki: ")
            if self._is_techproject_accepted(feedback):
                print(
                    "\n[Projekt techniczny zaakceptowany. "
                    "Start implementacji]\n",
                    flush=True)
                return result
            previous_result = result.output
            review_feedback = feedback
            iteration += 1

    async def run_develop_cr_loop(
        self,
        client: AsyncClient,
        task_description: str,
        signature: str,
        techproject_result: str,
        max_iterations: int = 5,
        db_max: int = 3,
    ) -> list[StageRun]:
        """Run the develop/CR loop with iteration limits."""
        results: list[StageRun] = []
        cr_feedback = None
        iteration = 1
        async with await AsyncAgent.create(
            api_key=self.api_key,
            model=self.model,
            local=self.local_options(),
            client=client) as develop_agent:
            async with await AsyncAgent.create(
                api_key=self.api_key,
                model=self.model,
                local=self.local_options(),
                client=client) as cr_agent:
                self._develop_agent = develop_agent
                self._cr_agent = cr_agent
                develop_agent_id = self._agent_id(develop_agent)
                cr_agent_id = self._agent_id(cr_agent)
                while True:
                    self._raise_if_stopped()
                    if iteration > max_iterations:
                        raise StageRunError(StageRun(
                            name=f"develop-cr#{iteration}",
                            status=StageStatus.FAILED.value,
                            output="",
                            worker_name="develop-cr",
                            error_message=(
                                f"CR loop exceeded max iterations "
                                f"({max_iterations})")))
                    develop, cr = await self._develop_cr_iteration(
                        client,
                        develop_agent,
                        cr_agent,
                        task_description,
                        signature,
                        techproject_result,
                        cr_feedback,
                        iteration,
                        develop_agent_id,
                        cr_agent_id,
                        results,
                        db_max)
                    results.append(develop)
                    results.append(cr)
                    if self._is_cr_accepted(cr.output):
                        print(
                            "\n[CR zaakceptowany. Start testów]\n",
                            flush=True)
                        return results
                    self._print_cr_feedback(cr.output)
                    cr_feedback = cr.output
                    iteration += 1

    async def _develop_cr_iteration(
        self,
        client: AsyncClient,
        develop_agent: AsyncAgent,
        cr_agent: AsyncAgent,
        task_description: str,
        signature: str,
        techproject_result: str,
        cr_feedback: str | None,
        iteration: int,
        develop_agent_id: str | None,
        cr_agent_id: str | None,
        results: list[StageRun],
        db_max: int,
    ) -> tuple[StageRun, StageRun]:
        """Execute one develop then CR iteration."""
        develop_tool = (
            self.tools.run_develop(
                task_description, signature, techproject_result)
            if iteration == 1
            else self.tools.continue_develop(cr_feedback))
        develop = await self.send_tool_result(
            develop_agent,
            "develop",
            develop_tool,
            iteration=iteration,
            agent_id=develop_agent_id)
        develop = await self._resolve_db_context_loop(
            client,
            develop_agent,
            "develop",
            develop,
            task_description,
            signature,
            iteration,
            develop_agent_id,
            results,
            is_develop=True,
            db_max=db_max)
        cr_tool = (
            self.tools.run_cr(
                task_description, signature, develop.output)
            if iteration == 1
            else self.tools.continue_cr(develop.output))
        cr = await self.send_tool_result(
            cr_agent,
            "cr",
            cr_tool,
            iteration=iteration,
            agent_id=cr_agent_id)
        cr = await self._resolve_db_context_loop(
            client,
            cr_agent,
            "cr",
            cr,
            task_description,
            signature,
            iteration,
            cr_agent_id,
            results,
            is_develop=False,
            develop_output=develop.output,
            db_max=db_max)
        return develop, cr

    def _print_cr_feedback(self, cr_output: str) -> None:
        """Log CR feedback status to console."""
        cr_statuses = _parse_cr_statuses(cr_output)
        if cr_statuses:
            print(
                f"\n[CR status: {cr_statuses[-1]} — wymaga poprawek]\n",
                flush=True)
        else:
            print(
                "\n[CR: brak linii CR_STATUS: OK/POPRAWKI — "
                "traktuję jako wymagające poprawek]\n",
                flush=True)
        print("\nCR wymaga poprawek. Ponawiam develop\n", flush=True)

    async def _resolve_db_context_loop(
        self,
        client: AsyncClient,
        agent: AsyncAgent,
        worker_name: str,
        stage_run: StageRun,
        task_description: str,
        signature: str,
        iteration: int,
        agent_id: str | None,
        results: list[StageRun],
        is_develop: bool,
        develop_output: str | None = None,
        db_max: int = 3,
    ) -> StageRun:
        """Resolve the db context loop with iteration limit."""
        if not self._is_db_context_enabled():
            return stage_run
        current = stage_run
        db_count = 0
        while self._is_db_context_needed(current.output):
            self._raise_if_stopped()
            db_count += 1
            if db_count > db_max:
                failed = StageRun(
                    name=current.name,
                    status=StageStatus.FAILED.value,
                    output=current.output,
                    worker_name=current.worker_name,
                    agent_id=current.agent_id,
                    run_id=current.run_id,
                    error_message=(
                        f"db-context exceeded max iterations ({db_max})"))
                raise StageRunError(failed)
            label = "develop" if is_develop else "CR"
            print(
                f"\n[Wykryto potrzebę danych z bazy danych dla {label}]\n",
                flush=True)
            db_context = await self.run_stage_agent(
                client,
                "db-context",
                self.tools.run_db_context(
                    task_description,
                    signature,
                    question=None,
                    previous_result=current.output),
                iteration=iteration)
            results.append(db_context)
            if is_develop:
                tool = self.tools.continue_develop(
                    db_context=db_context.output)
            else:
                tool = self.tools.continue_cr(
                    develop_result=develop_output or "",
                    db_context=db_context.output)
            current = await self.send_tool_result(
                agent,
                worker_name,
                tool,
                iteration=iteration,
                agent_id=agent_id)
        return current

    async def _maybe_db_context_for_standalone(
        self,
        client: AsyncClient,
        stage_run: StageRun,
        task: TaskConfig,
        iteration: int,
        develop_output: str | None = None,
    ) -> StageRun:
        """Auto-inject db-context for standalone stage runs."""
        if not self._is_db_context_enabled():
            return stage_run
        current = stage_run
        db_max = (
            self._profile.db_context_max_iterations
            if self._profile else 3)
        db_count = 0
        while self._is_db_context_needed(current.output):
            self._raise_if_stopped()
            db_count += 1
            if db_count > db_max:
                raise StageRunError(StageRun(
                    name=current.name,
                    status=StageStatus.FAILED.value,
                    output=current.output,
                    worker_name=current.worker_name,
                    error_message=(
                        f"db-context exceeded max iterations ({db_max})")))
            db_context = await self.run_stage_agent(
                client,
                "db-context",
                self.tools.run_db_context(
                    task.task_description,
                    task.signature,
                    question=None,
                    previous_result=current.output),
                iteration=iteration)
            self._record_stage(db_context)
            worker = current.worker_name or ""
            if worker == "develop":
                tool = self.tools.continue_develop(
                    db_context=db_context.output)
                current = await self.run_stage_agent(
                    client, "develop", tool, iteration=iteration)
            elif worker == "cr":
                tool = self.tools.continue_cr(
                    develop_result=develop_output or "",
                    db_context=db_context.output)
                current = await self.run_stage_agent(
                    client, "cr", tool, iteration=iteration)
            else:
                tool = self.tools.prepare_techproject(
                    task.task_description,
                    task.signature,
                    "Uzupełnij techproject, uwzględniając kontekst "
                    "bazy danych.",
                    f"{current.output}\n\n ## Kontekst bazy danych ##\n"
                    f"{db_context.output}")
                current = await self.run_stage_agent(
                    client, "techproject", tool, iteration=iteration + db_count)
        return current

    async def run_stage_agent(
        self,
        client: AsyncClient,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
    ) -> StageRun:
        """Run a stage agent."""
        async with await AsyncAgent.create(
            api_key=self.api_key,
            model=self.model,
            local=self.local_options(),
            client=client) as agent:
            agent_id = self._agent_id(agent)
            return await self.send_tool_result(
                agent,
                worker_name,
                tool_result,
                iteration=iteration,
                agent_id=agent_id)

    async def send_tool_result(
        self,
        agent: AsyncAgent,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
        agent_id: str | None = None,
    ) -> StageRun:
        """Send a tool result to the agent."""
        if self._bridge_lock is not None:
            async with self._bridge_lock:
                return await self._execute_tool_run(
                    agent,
                    worker_name,
                    tool_result,
                    iteration=iteration,
                    agent_id=agent_id)
        return await self._execute_tool_run(
            agent,
            worker_name,
            tool_result,
            iteration=iteration,
            agent_id=agent_id)

    async def _execute_tool_run(
        self,
        agent: AsyncAgent,
        worker_name: str,
        tool_result: ToolResult,
        iteration: int | None = None,
        agent_id: str | None = None,
    ) -> StageRun:
        """Execute a tool run with event emission and timestamps."""
        self._raise_if_stopped()
        stage_name = tool_result.tool_name
        if iteration is not None:
            stage_name = f"{stage_name}#{iteration}"
        started_at = _utc_now()
        # od razu widać running w GET /workflows/{id}
        self._record_stage(StageRun(
            name=stage_name,
            status=StageStatus.RUNNING.value,
            output="",
            worker_name=worker_name,
            agent_id=agent_id,
            started_at=started_at,
            attempt=iteration))
        await self._emit(
            WorkflowEventType.STAGE_STARTED,
            f"Stage started: {stage_name}",
            stage_name=stage_name,
            payload={"worker_name": worker_name, "attempt": iteration})
        print(f"\n ## {stage_name} [{worker_name}] \n", flush=True)
        try:
            run = await agent.send(f"/caveman\n{tool_result.prompt}")
        except CursorAgentError as exc:
            failed = StageRun(
                name=stage_name,
                status=StageStatus.FAILED.value,
                output="",
                worker_name=worker_name,
                agent_id=agent_id,
                started_at=started_at,
                finished_at=_utc_now(),
                attempt=iteration,
                error_message=str(exc))
            self._record_stage(failed)
            await self._emit(
                WorkflowEventType.STAGE_FAILED,
                str(exc),
                stage_name=stage_name)
            raise StageRunError(failed) from exc
        print(
            f"{tool_result.tool_name}: agent_id={agent_id}, "
            f"run_id={run.id}\n",
            flush=True)
        print("Przetwarzanie... \n", flush=True)
        chunks: list[str] = []
        async for text in run.iter_text():
            self._raise_if_stopped()
            if text:
                print(text, end="", flush=True)
                chunks.append(text)
                await self._emit(
                    WorkflowEventType.OUTPUT_CHUNK,
                    text,
                    stage_name=stage_name,
                    payload={"chunk": text})
        result = await run.wait()
        output = "".join(chunks) or (run.result or "")
        print(
            f"\n\n{tool_result.tool_name}: status={result.status}\n",
            flush=True)
        mapped = _map_sdk_status(result.status)
        stage_run = StageRun(
            name=stage_name,
            status=mapped,
            output=output,
            worker_name=worker_name,
            agent_id=agent_id,
            run_id=run.id,
            started_at=started_at,
            finished_at=_utc_now(),
            attempt=iteration)
        if result.status != "finished":
            self._record_stage(stage_run)
            await self._emit(
                WorkflowEventType.STAGE_FAILED,
                f"Stage failed with status={result.status}",
                stage_name=stage_name)
            raise StageRunError(stage_run)
        self._record_stage(stage_run)
        await self._emit(
            WorkflowEventType.STAGE_COMPLETED,
            f"Stage completed: {stage_name}",
            stage_name=stage_name)
        return stage_run

    def _agent_id(self, agent: AsyncAgent) -> str | None:
        """Return agent id across SDK versions."""
        for attr_name in ("agent_id", "id"):
            value = getattr(agent, attr_name, None)
            if value:
                return str(value)
        return None

    def _read_console_feedback(self, prompt: str) -> str:
        """Read feedback from the console."""
        while True:
            feedback = input(prompt).strip()
            if feedback:
                return feedback
            print("Wpisz akceptację albo poproś o poprawki: ", flush=True)

    def _is_techproject_accepted(self, feedback: str) -> bool:
        """Check if techproject is accepted."""
        normalized = feedback.casefold()
        reject_markers = ("popraw", "niegotowy", "odrzuc")
        if any(marker in normalized for marker in reject_markers):
            return False
        accept_markers = ("akcept", "projekt ok", "gotowy", "realizuj")
        return any(marker in normalized for marker in accept_markers)

    def _is_cr_accepted(self, cr_output: str) -> bool:
        """Check if CR is accepted based on the last dedicated status line."""
        statuses = _parse_cr_statuses(cr_output)
        if not statuses:
            return False
        return statuses[-1] == "OK"

    def _is_db_context_needed(self, output: str) -> bool:
        """Check if db context is needed based on a dedicated status line."""
        for line in reversed(output.splitlines()):
            normalized = _normalize_status_line(line)
            if _DB_STATUS_LINE_RE.match(normalized):
                return True
        return False

    def _is_db_context_enabled(self) -> bool:
        """Return True when db-context auto-injection is allowed."""
        profile = self._profile
        if profile is None:
            return True
        return "db-context" in profile.enabled_stages

    def _raise_if_stopped(self) -> None:
        """Raise if stop was requested."""
        if self._stop_requested:
            raise WorkflowCancelledError("Workflow stop requested")

    async def _emit(
        self,
        event_type: WorkflowEventType,
        message: str,
        stage_name: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Emit event to sink when available."""
        workflow = self._active_workflow
        if workflow is None or self._event_sink is None:
            return
        event = WorkflowEvent.create(
            workflow.id, event_type, message, stage_name, payload)
        await self._event_sink.emit(event)
        workflow.touch()

    async def _append_skipped(self, stage_name: str) -> None:
        """Append a skipped stage run and emit event."""
        stage = StageRun(
            name=stage_name,
            status=StageStatus.SKIPPED.value,
            output="",
            worker_name=stage_name)
        self._record_stage(stage)
        await self._emit(
            WorkflowEventType.STAGE_SKIPPED,
            f"Stage skipped: {stage_name}",
            stage_name=stage_name)

    def _record_stage(self, stage: StageRun) -> None:
        """Upsert stage on the active workflow (replace by name / dedupe)."""
        if self._active_workflow is None:
            return
        stages = self._active_workflow.stages
        for index in range(len(stages) - 1, -1, -1):
            existing = stages[index]
            if existing.name != stage.name:
                continue
            if existing.status == StageStatus.RUNNING.value:
                stages[index] = stage
                self._active_workflow.touch()
                return
            # aktualizacja completed -> needs_changes (ten sam attempt)
            if (
                existing.run_id == stage.run_id
                and existing.attempt == stage.attempt
            ):
                stages[index] = stage
                self._active_workflow.touch()
                return
            if (
                existing.status == stage.status
                and existing.run_id == stage.run_id
                and existing.output == stage.output
            ):
                return
        stages.append(stage)
        self._active_workflow.touch()

    @staticmethod
    def _last_output_for(results: list[StageRun], worker: str) -> str:
        """Return last output for a worker name."""
        for stage in reversed(results):
            if stage.worker_name == worker:
                return stage.output
        return ""


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AgentOrchestrator - automated programming task workflow",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "task_input",
        nargs="?",
        type=str,
        help="Path to task_config.yaml")
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Client workspace repository root")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Path to .szponti.env file")
    parser.add_argument(
        "--push",
        action="store_true",
        help="Include push stage")
    return parser


def print_workflow_summary(results: list[StageRun]) -> None:
    """Print workflow summary."""
    print("\nPodsumowanie workflow:")
    for result in results:
        worker = f"[{result.worker_name}]" if result.worker_name else ""
        run_id = f"[{result.run_id}]" if result.run_id else ""
        print(f"- {result.name}{worker}: {result.status} {run_id}")


def print_stage_error(error: StageRunError) -> None:
    """Print stage error."""
    result = error.stage_run
    print(
        "\nWorkflow przerwany: etap zakonczyl sie bledem\n"
        f"Etap: {result.name} [{result.worker_name}]\n"
        f"Status: {result.status}\n"
        f"Agent ID: {result.agent_id}\n"
        f"Run ID: {result.run_id}\n",
        file=sys.stderr)
    if result.error_message:
        print(f"Error: {result.error_message}\n", file=sys.stderr)
    if result.output:
        print("Ostatni output etapu: \n", file=sys.stderr)
        print(result.output, file=sys.stderr)


def main() -> None:
    """Main CLI entry point."""
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        config = resolve_config(
            workspace=args.workspace,
            env_file=args.env_file)
    except (ValueError, RuntimeError) as exc:
        print(
            f"Błąd podczas rozpoznawania konfiguracji: {exc}",
            file=sys.stderr)
        return

    try:
        task_config = resolve_task_input(args.task_input)
    except RuntimeError as exc:
        print(
            f"Błąd podczas rozpoznawania zadania: {exc}",
            file=sys.stderr)
        return

    orchestrator = AgentOrchestrator(config)
    try:
        workflow = asyncio.run(orchestrator.run_default_workflow(
            task_config.task_description,
            task_config.signature,
            include_push=args.push))
    except StageRunError as exc:
        print_stage_error(exc)
        return
    except CursorAgentError as exc:
        print(
            f"Błąd podczas wykonywania workflow: {exc}",
            file=sys.stderr)
        return
    print_workflow_summary(workflow.stages)


if __name__ == "__main__":
    main()
