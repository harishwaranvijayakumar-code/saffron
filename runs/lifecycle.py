
from django.core.exceptions import ValidationError
from django.db import transaction

from runs.models import (
    AgentRun,
    AuditEvent,
    ApprovalRequest,
    ApprovalStatus,
    ExecutionStep,
    ExecutionStepStatus,
    PolicyDecision,
    PolicyDecisionStatus,
    RunStatus,
    TERMINAL_STATES,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.services import transition_run


def _derive_run_status(run):
    """
    Derive a conservative run-level status from existing execution records.

    This does not prove that the agent's objective was achieved. It only
    evaluates the recorded step and invocation states.
    """
    steps = list(
        ExecutionStep.objects.filter(run=run).order_by("sequence", "id")
    )

    if not steps:
        return None

    step_statuses = {step.status for step in steps}

    if ExecutionStepStatus.FAILED in step_statuses:
        return RunStatus.FAILED

    if ExecutionStepStatus.OUTCOME_UNKNOWN in step_statuses:
        return RunStatus.OUTCOME_UNKNOWN

    if ExecutionStepStatus.WAITING_APPROVAL in step_statuses:
        return RunStatus.WAITING_APPROVAL

    if (
        ExecutionStepStatus.PENDING in step_statuses
        or ExecutionStepStatus.RUNNING in step_statuses
    ):
        return None

    if any(
        step.status not in {
            ExecutionStepStatus.SUCCEEDED,
            ExecutionStepStatus.CANCELLED,
        }
        for step in steps
    ):
        return None

    if all(
        step.status == ExecutionStepStatus.CANCELLED
        for step in steps
    ):
        return RunStatus.CANCELLED

    for step in steps:
        if step.status == ExecutionStepStatus.CANCELLED:
            continue

        invocations = list(
            ToolInvocation.objects.filter(step=step).order_by(
                "created_at", "id"
            )
        )

        if any(
            invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN
            for invocation in invocations
        ):
            return RunStatus.OUTCOME_UNKNOWN

        if any(
            invocation.status == ToolInvocationStatus.FAILED
            for invocation in invocations
        ):
            return RunStatus.FAILED

        if any(
            invocation.status
            in {
                ToolInvocationStatus.RECORDED,
                ToolInvocationStatus.AUTHORIZED,
                ToolInvocationStatus.STARTED,
            }
            for invocation in invocations
        ):
            return None

        if any(
            invocation.status
            in {
                ToolInvocationStatus.DENIED,
            }
            for invocation in invocations
        ):
            return RunStatus.FAILED

    if all(
        step.status in {
            ExecutionStepStatus.SUCCEEDED,
            ExecutionStepStatus.CANCELLED,
        }
        for step in steps
    ):
        return RunStatus.SUCCEEDED

    return None


@transaction.atomic
def reconcile_run_lifecycle(*, run_id, actor=None, correlation_id=None):
    """
    Reconcile a run's status against its recorded execution state.

    Returns the refreshed run. A return value does not mean the objective
    was independently verified.
    """
    run = AgentRun.objects.select_for_update().get(pk=run_id)

    if run.status in TERMINAL_STATES:
        return run

    derived_status = _derive_run_status(run)

    if derived_status is None or derived_status == run.status:
        return run

    if derived_status not in {
        RunStatus.WAITING_APPROVAL,
        RunStatus.OUTCOME_UNKNOWN,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.SUCCEEDED,
    }:
        raise ValidationError(
            f"Unsupported derived run status: {derived_status}"
        )

    if derived_status == RunStatus.WAITING_APPROVAL:
        pending_approval_exists = ApprovalRequest.objects.filter(
            decision__invocation__step__run=run,
            status=ApprovalStatus.PENDING,
        ).exists()

        if not pending_approval_exists:
            # A step's waiting status alone is insufficient evidence that
            # an actionable approval request exists.
            return run

    if derived_status == RunStatus.OUTCOME_UNKNOWN:
        if not ToolInvocation.objects.filter(
            step__run=run,
            status=ToolInvocationStatus.OUTCOME_UNKNOWN,
        ).exists() and not ExecutionStep.objects.filter(
            run=run,
            status=ExecutionStepStatus.OUTCOME_UNKNOWN,
        ).exists():
            return run

    if derived_status == RunStatus.SUCCEEDED:
        # Success is allowed only when all recorded steps have succeeded
        # or are explicitly cancelled and no required tool outcome is open.
        # Independent objective verification remains a separate concern.
        if not ExecutionStep.objects.filter(
            run=run,
            status__in=[
                ExecutionStepStatus.PENDING,
                ExecutionStepStatus.RUNNING,
                ExecutionStepStatus.WAITING_APPROVAL,
                ExecutionStepStatus.FAILED,
                ExecutionStepStatus.OUTCOME_UNKNOWN,
            ],
        ).exists():
            unresolved_invocation_exists = ToolInvocation.objects.filter(
                step__run=run,
                status__in=[
                    ToolInvocationStatus.RECORDED,
                    ToolInvocationStatus.AUTHORIZED,
                    ToolInvocationStatus.STARTED,
                    ToolInvocationStatus.OUTCOME_UNKNOWN,
                    ToolInvocationStatus.FAILED,
                    ToolInvocationStatus.DENIED,
                ],
            ).exists()

            if unresolved_invocation_exists:
                return run
        else:
            return run

    return transition_run(
        run.id,
        expected_version=run.state_version,
        new_status=derived_status,
        actor=actor,
        correlation_id=correlation_id,
    )
