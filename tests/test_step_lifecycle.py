
import pytest
from django.contrib.auth import get_user_model

from runs.models import (
    AgentRun,
    ExecutionStep,
    ExecutionStepStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.services import transition_run
from runs.step_lifecycle import refresh_step_lifecycle


@pytest.fixture
def running_step(db):
    user = get_user_model().objects.create_user(
        username="step-lifecycle-test-user",
    )
    run = AgentRun.objects.create(
        created_by=user,
        objective="Verify execution lifecycle",
    )
    transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
        actor=user,
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow",
    )
    return run, step


def make_invocation(step, status):
    return ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=status,
    )


@pytest.mark.django_db
def test_successful_invocation_completes_step_but_not_run(running_step):
    run, step = running_step
    make_invocation(step, ToolInvocationStatus.SUCCEEDED)

    result = refresh_step_lifecycle(step_id=step.id)

    run.refresh_from_db()

    assert result.status == ExecutionStepStatus.SUCCEEDED
    assert run.status == RunStatus.RUNNING


@pytest.mark.django_db
def test_unknown_invocation_keeps_step_uncertain(running_step):
    _, step = running_step
    make_invocation(step, ToolInvocationStatus.OUTCOME_UNKNOWN)

    result = refresh_step_lifecycle(step_id=step.id)

    assert result.status == ExecutionStepStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db
def test_failed_invocation_fails_step(running_step):
    _, step = running_step
    make_invocation(step, ToolInvocationStatus.FAILED)

    result = refresh_step_lifecycle(step_id=step.id)

    assert result.status == ExecutionStepStatus.FAILED


@pytest.mark.django_db
def test_active_invocation_keeps_step_running(running_step):
    _, step = running_step
    make_invocation(step, ToolInvocationStatus.STARTED)

    result = refresh_step_lifecycle(step_id=step.id)

    assert result.status == ExecutionStepStatus.RUNNING
    assert result.started_at is not None


@pytest.mark.django_db
def test_empty_step_is_not_marked_successful(running_step):
    _, step = running_step

    result = refresh_step_lifecycle(step_id=step.id)

    assert result.status == ExecutionStepStatus.PENDING


@pytest.mark.django_db
def test_repeated_refresh_does_not_duplicate_audit_event(running_step):
    run, step = running_step
    make_invocation(step, ToolInvocationStatus.FAILED)

    refresh_step_lifecycle(step_id=step.id)
    refresh_step_lifecycle(step_id=step.id)

    assert run.audit_events.filter(
        event_type="EXECUTION_STEP_STATUS_CHANGED",
    ).count() == 1
