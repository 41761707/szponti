"""Validation of WorkflowProfile stage dependencies."""

from __future__ import annotations

from workflow_models import WorkflowProfile


class ProfileValidator:
    """Validate enabled stages and required stage_inputs."""

    @staticmethod
    def validate(profile: WorkflowProfile) -> list[str]:
        """Return a list of validation errors (empty means valid)."""
        errors: list[str] = []
        enabled = list(profile.enabled_stages)
        inputs = profile.stage_inputs or {}

        if not enabled:
            errors.append("enabled_stages must not be empty")
            return errors

        if "develop" in enabled:
            if (
                "tech-project" not in enabled
                and not inputs.get("tech-project", "").strip()
            ):
                errors.append(
                    "develop requires enabled tech-project or "
                    "stage_inputs['tech-project']")

        if "cr" in enabled and "develop" not in enabled:
            if not inputs.get("develop", "").strip():
                errors.append(
                    "cr without develop requires stage_inputs['develop']")

        if "scenariusze-testowe" in enabled:
            has_upstream = (
                "develop" in enabled
                or "cr" in enabled
                or bool(inputs.get("cr", "").strip())
                or bool(inputs.get("develop", "").strip()))
            if not has_upstream:
                errors.append(
                    "scenariusze-testowe requires develop/cr enabled or "
                    "stage_inputs['cr'] / stage_inputs['develop']")

        if "git-push" in enabled:
            if not profile.authorize_push:
                errors.append("git-push requires authorize_push=true")
            if "cr" not in enabled and not inputs.get("cr", "").strip():
                errors.append(
                    "git-push requires cr enabled or stage_inputs['cr']")

        if profile.cr_max_iterations < 1:
            errors.append("cr_max_iterations must be >= 1")
        if profile.db_context_max_iterations < 1:
            errors.append("db_context_max_iterations must be >= 1")

        return errors
