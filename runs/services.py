import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from runs.models import (
    AgentRun,
    AuditEvent,
    RunStatus,
    TERMINAL_STATES,
)


@transaction.atomic
def transition_run(
    run_id,
    expected_version,
    new_status,
    *,
    actor=None,
    correlation_id=None,
):
    run = AgentRun.objects.select_for_update().get(pk=run_id)

    if run.state_version != expected_version:
        raise ValidationError(
            "Run state changed. Reload it before retrying the transition."
        )

    previous_status = run.status
    run.transition_to(new_status)

    now = timezone.now()

    if new_status == RunStatus.RUNNING and run.started_at is None:
        run.started_at = now

    if new_status in TERMINAL_STATES:
        run.finished_at = now

    run.save(
        update_fields=[
            "status",
            "state_version",
            "updated_at",
            "started_at",
            "finished_at",
        ]
    )

    AuditEvent.objects.create(
        run=run,
        actor=actor,
        event_type="RUN_STATE_TRANSITION",
        correlation_id=correlation_id or uuid.uuid4(),
        state_version=run.state_version,
        details={
            "from": previous_status,
            "to": new_status,
        },
    )

    return run



@transaction.atomic
def create_run(*, actor, objective, max_steps=20,
               max_tool_invocations=50, max_runtime_seconds=900):
    """Create a queued run and its initial audit event atomically."""
    if actor is None or not actor.is_authenticated:
        raise ValidationError("An authenticated user is required.")

    run = AgentRun.objects.create(
        created_by=actor,
        objective=objective,
        max_steps=max_steps,
        max_tool_invocations=max_tool_invocations,
        max_runtime_seconds=max_runtime_seconds,
    )

    AuditEvent.objects.create(
        run=run,
        actor=actor,
        event_type="RUN_CREATED",
        state_version=run.state_version,
        details={
            "status": run.status,
            "objective": run.objective,
            "budgets": {
                "max_steps": run.max_steps,
                "max_tool_invocations": run.max_tool_invocations,
                "max_runtime_seconds": run.max_runtime_seconds,
            },
        },
    )

    return run