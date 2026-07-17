"""Unit tests for CR/DB status parsing helpers."""

from __future__ import annotations

from AgentOrchestrator import AgentOrchestrator, _parse_cr_statuses, _strip_markdown


def _orch() -> AgentOrchestrator:
    # omijamy pełną inicjalizację zależną od Tools/Paths
    obj = object.__new__(AgentOrchestrator)
    obj.api_key = "x"
    obj.model = "x"
    obj.workspace_dir = "."
    obj.tools = None  # type: ignore[assignment]
    obj._bridge_lock = None
    obj._stop_requested = False
    obj._active_workflow = None
    obj._event_sink = None
    obj._profile = None
    return obj


def test_parse_cr_statuses_last_wins() -> None:
    output = "note\nCR_STATUS: POPRAWKI\nmore\nCR_STATUS: OK\n"
    assert _parse_cr_statuses(output) == ["POPRAWKI", "OK"]
    assert _orch()._is_cr_accepted(output) is True


def test_cr_poprawki_not_accepted() -> None:
    output = "CR_STATUS: POPRAWKI\n"
    assert _orch()._is_cr_accepted(output) is False


def test_db_status_needed() -> None:
    output = "analysis\nDB_STATUS: POTRZEBNE_DANE\n"
    assert _orch()._is_db_context_needed(output) is True


def test_strip_markdown() -> None:
    assert _strip_markdown("**CR_STATUS: OK**") == "CR_STATUS: OK"
