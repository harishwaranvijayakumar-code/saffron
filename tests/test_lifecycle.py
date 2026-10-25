
import pytest
from django.contrib.auth import get_user_model

from runs.lifecycle import reconcile_run_lifecycle
from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    ExecutionStepStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.services import transition_run


@pytest.fixture
def running_run(db):
    user = get_user_model().objects.create_user(
        username="lifecycle-test-user",
        password="test-only-password",
    )
    run = AgentRun.objects.create(
        created_by=user,
        objective="Test lifecycle reconciliation",
    )
    transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
        actor=user,
    )
    run.refresh_from_db()
    return run


@pytest.mark.django_db
def test_empty_run_is_not_marked_successful(running_run):
    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.RUNNING
    assert result.finished_at is None


@pytest.mark.django_db
def test_pending_step_does_not_finalize_run(running_run):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Pending step",
        status=ExecutionStepStatus.PENDING,
    )

    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.RUNNING
    assert result.finished_at is None


@pytest.mark.django_db
def test_failed_step_fails_run(running_run):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Failed step",
        status=ExecutionStepStatus.FAILED,
    )

    result = reconcile_run_lifecycle(
        run_id=running_run.id,
        actor=running_run.created_by,
    )

    assert result.status == RunStatus.FAILED
    assert result.finished_at is not None


@pytest.mark.django_db
def test_succeeded_step_can_complete_run_without_tool_invocations(
    running_run,
):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Completed planning step",
        status=ExecutionStepStatus.SUCCEEDED,
    )

    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.SUCCEEDED
    assert result.finished_at is not None


@pytest.mark.django_db
def test_reconciliation_does_not_change_terminal_run(running_run):
    failed = transition_run(
        running_run.id,
        expected_version=running_run.state_version,
        new_status=RunStatus.FAILED,
    )

    result = reconcile_run_lifecycle(run_id=failed.id)

    assert result.status == RunStatus.FAILED
    assert result.state_version == failed.state_version


@pytest.mark.django_db
def test_unknown_invocation_prevents_run_success(running_run):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Uncertain tool",
        status=ExecutionStepStatus.SUCCEEDED,
    )
    ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.OUTCOME_UNKNOWN,
    )

    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.OUTCOME_UNKNOWN
    assert result.finished_at is None


@pytest.mark.django_db
def test_waiting_approval_step_does_not_complete_run(running_run):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Approval required",
        status=ExecutionStepStatus.WAITING_APPROVAL,
    )

    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.RUNNING
    assert result.finished_at is None


@pytest.mark.parametrize(
    "invocation_status",
    [
        ToolInvocationStatus.RECORDED,
        ToolInvocationStatus.AUTHORIZED,
        ToolInvocationStatus.STARTED,
    ],
)
@pytest.mark.django_db
def test_unresolved_invocation_prevents_run_success(
    running_run,
    invocation_status,
):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Tool still in progress",
        status=ExecutionStepStatus.SUCCEEDED,
    )
    ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=invocation_status,
    )

    result = reconcile_run_lifecycle(run_id=running_run.id)

    assert result.status == RunStatus.RUNNING
    assert result.finished_at is None


@pytest.mark.django_db
def test_repeated_reconciliation_does_not_increment_version_again(
    running_run,
):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Completed step",
        status=ExecutionStepStatus.SUCCEEDED,
    )

    first = reconcile_run_lifecycle(run_id=running_run.id)
    first_version = first.state_version

    second = reconcile_run_lifecycle(run_id=running_run.id)

    assert first.status == RunStatus.SUCCEEDED
    assert second.status == RunStatus.SUCCEEDED
    assert second.state_version == first_version



@pytest.mark.django_db
def test_reconciliation_records_single_transition_event(running_run):
    ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Completed step",
        status=ExecutionStepStatus.SUCCEEDED,
    )

    reconcile_run_lifecycle(run_id=running_run.id)
    reconcile_run_lifecycle(run_id=running_run.id)

    successful_transitions = AuditEvent.objects.filter(
        run=running_run,
        event_type="RUN_STATE_TRANSITION",
        details__to=RunStatus.SUCCEEDED,
    )

    assert successful_transitions.count() == 1
