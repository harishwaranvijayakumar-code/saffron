from django.db import transaction
from django.utils import timezone

from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    RunStatus,
    ToolInvocation,
)


@transaction.atomic
def enforce_run_budget(run_id):
    """
    Return None if the run is within budget.

    If a running run exceeds its limits, transition it to FAILED,
    record an audit event, and return the reason.
    """
    run = AgentRun.objects.select_for_update().get(pk=run_id)

    if run.status != RunStatus.RUNNING:
        return "Run is not in the RUNNING state."

    now = timezone.now()

    step_count = ExecutionStep.objects.filter(run=run).count()
    invocation_count = ToolInvocation.objects.filter(
        step__run=run
    ).count()

    reason = None

    if step_count > run.max_steps:
        reason = "Maximum step count exceeded."
    elif invocation_count > run.max_tool_invocations:
        reason = "Maximum tool invocation count exceeded."
    elif run.started_at is not None:
        elapsed = (now - run.started_at).total_seconds()
        if elapsed > run.max_runtime_seconds:
            reason = "Maximum run duration exceeded."

    if reason is None:
        return None

    run.transition_to(RunStatus.FAILED)
    run.finished_at = now
    run.save(
        update_fields=[
            "status",
            "state_version",
            "finished_at",
            "updated_at",
        ]
    )

    AuditEvent.objects.create(
        run=run,
        event_type="RUN_BUDGET_EXCEEDED",
        state_version=run.state_version,
        details={
            "reason": reason,
            "step_count": step_count,
            "invocation_count": invocation_count,
            "max_steps": run.max_steps,
            "max_tool_invocations": run.max_tool_invocations,
            "max_runtime_seconds": run.max_runtime_seconds,
        },
    )

    return reason
