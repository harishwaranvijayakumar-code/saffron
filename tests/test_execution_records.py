import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    ExecutionStepStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.services import transition_run


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="execution-record-test-user",
        password="test-only-password",
    )


@pytest.fixture
def run(user):
    return AgentRun.objects.create(
        created_by=user,
        objective="Investigate a failed workflow",
    )


@pytest.fixture
def step(run):
    return ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow run",
        input_summary={"workflow_run_id": 123},
    )


@pytest.mark.django_db
def test_execution_step_persists(run, step):
    saved = ExecutionStep.objects.get(pk=step.pk)

    assert saved.run_id == run.pk
    assert saved.sequence == 1
    assert saved.status == ExecutionStepStatus.PENDING
    assert saved.input_summary == {"workflow_run_id": 123}


@pytest.mark.django_db
def test_duplicate_step_sequence_is_rejected(run):
    ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="First step",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ExecutionStep.objects.create(
                run=run,
                sequence=1,
                name="Duplicate step",
            )


@pytest.mark.django_db
def test_tool_invocation_records_side_effect_class(step):
    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.RECORDED,
        request_summary={"workflow_run_id": 123},
    )

    saved = ToolInvocation.objects.get(pk=invocation.pk)

    assert saved.side_effect_class == SideEffectClass.READ_ONLY
    assert saved.status == ToolInvocationStatus.RECORDED
    assert saved.response_summary == {}


@pytest.mark.django_db
def test_duplicate_attempt_number_is_rejected(step):
    ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        attempt_number=1,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ToolInvocation.objects.create(
                step=step,
                tool_name="github.get_workflow_run",
                tool_version="1",
                attempt_number=1,
            )


@pytest.mark.django_db
def test_run_transition_creates_audit_event(run):
    updated = transition_run(
        run.id,
        expected_version=0,
        new_status="RUNNING",
    )

    event = AuditEvent.objects.get(run=run)

    assert updated.state_version == 1
    assert event.event_type == "RUN_STATE_TRANSITION"
    assert event.details == {
        "from": "QUEUED",
        "to": "RUNNING",
    }
    assert event.state_version == 1


@pytest.mark.django_db
def test_audit_event_has_correlation_id(run):
    event = AuditEvent.objects.create(
        run=run,
        event_type="TEST_EVENT",
        details={"source": "test"},
    )

    assert event.correlation_id is not None
    assert event.details["source"] == "test"
