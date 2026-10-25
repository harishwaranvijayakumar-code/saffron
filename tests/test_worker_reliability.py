
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from runs.budgets import enforce_run_budget
from runs.execution_gateway import _finish_invocation
from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.recovery import recover_expired_invocations
from runs.services import transition_run
from runs.worker import process_next_invocation


@pytest.fixture
def running_run(db):
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="reliability-test-user",
        password="test-only-password",
    )

    run = AgentRun.objects.create(
        created_by=user,
        objective="Test worker reliability",
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
def test_run_budget_fails_run_when_invocation_limit_exceeded(running_run):
    running_run.max_tool_invocations = 1
    running_run.save(update_fields=["max_tool_invocations"])

    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Test step",
    )

    for attempt in range(2):
        ToolInvocation.objects.create(
            step=step,
            tool_name="github.get_workflow_run",
            tool_version="1",
            attempt_number=attempt + 1,
            side_effect_class=SideEffectClass.READ_ONLY,
        )

    reason = enforce_run_budget(running_run.id)

    running_run.refresh_from_db()

    assert reason == "Maximum tool invocation count exceeded."
    assert running_run.status == RunStatus.FAILED
    assert AuditEvent.objects.filter(
        run=running_run,
        event_type="RUN_BUDGET_EXCEEDED",
    ).exists()


@pytest.mark.django_db
def test_expired_started_invocation_becomes_unknown(running_run):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Interrupted tool",
    )

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.STARTED,
        started_at=timezone.now() - timedelta(minutes=5),
        lease_owner=uuid.UUID("00000000-0000-0000-0000-000000000123"),
        lease_expires_at=timezone.now() - timedelta(minutes=1),
        heartbeat_at=timezone.now() - timedelta(minutes=2),
    )

    recovered = recover_expired_invocations()

    invocation.refresh_from_db()

    assert str(invocation.id) in recovered
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN
    assert invocation.error_code == "WORKER_LEASE_EXPIRED"
    assert invocation.lease_owner is None
    assert invocation.lease_expires_at is None
    assert invocation.heartbeat_at is None
    assert AuditEvent.objects.filter(
        run=running_run,
        event_type="INVOCATION_LEASE_EXPIRED",
    ).exists()


@pytest.mark.django_db
def test_recovery_does_not_retry_unknown_invocation(running_run):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Already uncertain",
    )

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.OUTCOME_UNKNOWN,
        finished_at=timezone.now(),
        error_code="WORKER_INTERRUPTED",
    )

    recovered = recover_expired_invocations()

    invocation.refresh_from_db()

    assert str(invocation.id) not in recovered
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db
def test_expired_worker_cannot_finalize_invocation(running_run):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Expired worker",
    )
    worker_id = uuid.uuid4()

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.STARTED,
        started_at=timezone.now() - timedelta(minutes=2),
        lease_owner=worker_id,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
        heartbeat_at=timezone.now() - timedelta(minutes=1),
        fencing_token=7,
    )

    with pytest.raises(ValidationError, match="lease has expired"):
        _finish_invocation(
            invocation_id=invocation.id,
            actor=running_run.created_by,
            status=ToolInvocationStatus.SUCCEEDED,
            worker_id=worker_id,
            fencing_token=7,
            response_summary={"simulated": True},
        )

    invocation.refresh_from_db()

    assert invocation.status == ToolInvocationStatus.STARTED
    assert invocation.fencing_token == 7
    assert not AuditEvent.objects.filter(
        run=running_run,
        event_type="TOOL_DISPATCH_FINISHED",
    ).exists()


@pytest.mark.django_db
def test_worker_does_not_dispatch_unknown_invocation(running_run):
    step = ExecutionStep.objects.create(
        run=running_run,
        sequence=1,
        name="Unknown outcome",
    )

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
        status=ToolInvocationStatus.OUTCOME_UNKNOWN,
        finished_at=timezone.now(),
        error_code="WORKER_LEASE_EXPIRED",
    )

    result = process_next_invocation()

    invocation.refresh_from_db()

    assert result["status"] == "IDLE"
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN
