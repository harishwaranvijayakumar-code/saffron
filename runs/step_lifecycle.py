
from django.db import transaction
from django.utils import timezone

from runs.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEvent,
    ExecutionStep,
    ExecutionStepStatus,
    PolicyDecision,
    PolicyDecisionStatus,
    RunStatus,
    ToolInvocation,
    ToolInvocationStatus,
)


@transaction.atomic
def refresh_step_lifecycle(*, step_id, actor=None):
    step = (
        ExecutionStep.objects
        .select_for_update()
        .select_related("run")
        .get(pk=step_id)
    )
    run = step.run

    if run.status in {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }:
        return step

    invocations = list(
        ToolInvocation.objects
        .filter(step_id=step.id)
        .order_by("created_at", "id")
    )

    if not invocations:
        return step

    statuses = {invocation.status for invocation in invocations}

    pending_approval = ApprovalRequest.objects.filter(
        decision__invocation__step_id=step.id,
        status=ApprovalStatus.PENDING,
    ).exists()

    requires_approval = PolicyDecision.objects.filter(
        invocation__step_id=step.id,
        status=PolicyDecisionStatus.REQUIRES_APPROVAL,
    ).exists()

    if ToolInvocationStatus.OUTCOME_UNKNOWN in statuses:
        new_status = ExecutionStepStatus.OUTCOME_UNKNOWN

    elif ToolInvocationStatus.STARTED in statuses:
        new_status = ExecutionStepStatus.RUNNING

    elif pending_approval and requires_approval:
        new_status = ExecutionStepStatus.WAITING_APPROVAL

    elif (
        ToolInvocationStatus.RECORDED in statuses
        or ToolInvocationStatus.AUTHORIZED in statuses
    ):
        new_status = ExecutionStepStatus.PENDING

    elif (
        ToolInvocationStatus.FAILED in statuses
        or ToolInvocationStatus.DENIED in statuses
    ):
        new_status = ExecutionStepStatus.FAILED

    elif all(
        status == ToolInvocationStatus.SUCCEEDED
        for status in statuses
    ):
        new_status = ExecutionStepStatus.SUCCEEDED

    else:
        return step

    if step.status == new_status:
        return step

    now = timezone.now()
    previous_status = step.status
    step.status = new_status

    if (
        new_status == ExecutionStepStatus.RUNNING
        and step.started_at is None
    ):
        step.started_at = now

    if new_status in {
        ExecutionStepStatus.SUCCEEDED,
        ExecutionStepStatus.FAILED,
        ExecutionStepStatus.OUTCOME_UNKNOWN,
        ExecutionStepStatus.CANCELLED,
    }:
        step.finished_at = now
    elif new_status in {
        ExecutionStepStatus.RUNNING,
        ExecutionStepStatus.PENDING,
        ExecutionStepStatus.WAITING_APPROVAL,
    }:
        step.finished_at = None

    step.save(
        update_fields=["status", "started_at", "finished_at"]
    )

    correlation_id = invocations[-1].correlation_id

    AuditEvent.objects.create(
        run=run,
        actor=actor,
        event_type="EXECUTION_STEP_STATUS_CHANGED",
        correlation_id=correlation_id,
        details={
            "step_id": str(step.id),
            "previous_status": previous_status,
            "new_status": new_status,
        },
    )

    if new_status in {
        ExecutionStepStatus.FAILED,
        ExecutionStepStatus.OUTCOME_UNKNOWN,
        ExecutionStepStatus.WAITING_APPROVAL,
    }:
        from runs.lifecycle import reconcile_run_lifecycle

        run.refresh_from_db()

        if run.status == RunStatus.RUNNING:
            reconcile_run_lifecycle(
                run_id=run.id,
                actor=actor,
                correlation_id=correlation_id,
            )

    return step
