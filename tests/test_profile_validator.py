"""Unit tests for ProfileValidator stage dependency rules."""

from __future__ import annotations

from web.backend.services.profile_validator import ProfileValidator
from workflow_models import WorkflowProfile


def test_empty_enabled_stages() -> None:
    errors = ProfileValidator.validate(WorkflowProfile(enabled_stages=[]))
    assert any("empty" in error for error in errors)


def test_develop_requires_techproject_or_input() -> None:
    errors = ProfileValidator.validate(
        WorkflowProfile(enabled_stages=["develop"]))
    assert any("tech-project" in error for error in errors)

    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["develop"],
        stage_inputs={"tech-project": "existing design"}))
    assert ok == []


def test_cr_only_requires_develop_input() -> None:
    errors = ProfileValidator.validate(
        WorkflowProfile(enabled_stages=["cr"]))
    assert any("develop" in error for error in errors)

    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["cr"],
        stage_inputs={"develop": "impl output"}))
    assert ok == []


def test_develop_cr_loop_ok() -> None:
    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["develop", "cr"],
        stage_inputs={"tech-project": "design"}))
    assert ok == []


def test_git_push_requires_authorize_and_cr() -> None:
    errors = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["git-push"],
        authorize_push=False))
    assert any("authorize_push" in error for error in errors)

    errors2 = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["git-push"],
        authorize_push=True))
    assert any("cr" in error for error in errors2)

    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["git-push"],
        authorize_push=True,
        stage_inputs={"cr": "cr ok"}))
    assert ok == []


def test_tests_require_upstream() -> None:
    errors = ProfileValidator.validate(
        WorkflowProfile(enabled_stages=["scenariusze-testowe"]))
    assert any("scenariusze-testowe" in error for error in errors)


def test_db_context_with_techproject_ok() -> None:
    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["tech-project", "db-context"]))
    assert ok == []


def test_profile_without_db_context_ok() -> None:
    ok = ProfileValidator.validate(WorkflowProfile(
        enabled_stages=["develop", "cr"],
        stage_inputs={"tech-project": "existing design"}))
    assert ok == []
