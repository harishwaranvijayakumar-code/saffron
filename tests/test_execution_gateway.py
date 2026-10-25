from datetime import timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from runs.approval_services import (
    create_approval_request,
    decide_approval,
)
from runs.execution_gateway import (
    _finish_invocation,
    execute_simulated_tool,
)
from runs.leases import claim_invocation_lease
from runs.models import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    ExecutionStep,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.policy import evaluate_tool_request
from runs.services import transition_run


@pytest.fixture
def actors(db):
    user_model = get_user_model()

    requester = user_model.objects.create_user(
        username="gateway-requester",
        password="test-only-password",
    )
    approver = user_model.objects.create_user(
        username="gateway-approver",
        password="test-only-password",
        is_staff=True,
    )
    other_user = user_model.objects.create_user(
        username="gateway-other-user",
        password="test-only-password",
    )

    return requester, approver, other_user


def make_run(requester):
    run = AgentRun.objects.create(
        created_by=requester,
        objective="Investigate a failed workflow",
    )
    transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
        actor=requester,
    )

    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow",
    )

    return run, step


def attach_lease(invocation):
    worker_id = uuid.uuid4()
    lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
    )
    return worker_id, lease["fencing_token"]


@pytest.fixture
def read_action(actors):
    requester, _, _ = actors
    run, step = make_run(requester)

    payload = {"workflow_run_id": 123}
    target = "repository:example/project/actions/runs/123"

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    invocation.refresh_from_db()
    worker_id, fencing_token = attach_lease(invocation)

    return {
        "run": run,
        "step": step,
        "invocation": invocation,
        "requester": requester,
        "payload": payload,
        "target": target,
        "worker_id": worker_id,
        "fencing_token": fencing_token,
    }


@pytest.fixture
def approved_write_action(actors):
    requester, approver, _ = actors
    run, step = make_run(requester)

    payload = {
        "issue_number": 42,
        "body": "The workflow failed during testing.",
    }
    target = "repository:example/project/issues/42"

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.create_issue_comment",
        tool_version="1",
        side_effect_class=SideEffectClass.IDEMPOTENT_WRITE,
    )

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    request = create_approval_request(
        decision_id=decision.id,
        requested_by=requester,
        payload=payload,
        target_resource=target,
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=True,
    )

    invocation.refresh_from_db()
    worker_id, fencing_token = attach_lease(invocation)

    return {
        "run": run,
        "invocation": invocation,
        "request": request,
        "requester": requester,
        "payload": payload,
        "target": target,
        "worker_id": worker_id,
        "fencing_token": fencing_token,
    }


@pytest.mark.django_db
def test_read_only_tool_dispatch_succeeds(read_action):
    data = read_action

    result = execute_simulated_tool(
        invocation_id=data["invocation"].id,
        actor=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
        worker_id=data["worker_id"],
        fencing_token=data["fencing_token"],
    )

    data["invocation"].refresh_from_db()

    assert result["simulated"] is True
    assert result["conclusion"] == "failure"
    assert data["invocation"].status == ToolInvocationStatus.SUCCEEDED
    assert data["invocation"].finished_at is not None
    assert data["invocation"].lease_owner is None
    assert data["invocation"].lease_expires_at is None


@pytest.mark.django_db
def test_dispatch_records_start_and_finish_events(read_action):
    data = read_action

    execute_simulated_tool(
        invocation_id=data["invocation"].id,
        actor=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
        worker_id=data["worker_id"],
        fencing_token=data["fencing_token"],
    )

    event_types = set(
        AuditEvent.objects.filter(run=data["run"])
        .values_list("event_type", flat=True)
    )

    assert "TOOL_DISPATCH_STARTED" in event_types
    assert "TOOL_DISPATCH_FINISHED" in event_types


@pytest.mark.django_db
def test_successful_invocation_cannot_be_dispatched_twice(read_action):
    data = read_action

    execute_simulated_tool(
        invocation_id=data["invocation"].id,
        actor=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
        worker_id=data["worker_id"],
        fencing_token=data["fencing_token"],
    )

    with pytest.raises(ValidationError):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=data["requester"],
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )


@pytest.mark.django_db
def test_changed_payload_is_rejected(read_action):
    data = read_action

    with pytest.raises(ValidationError):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=data["requester"],
            payload={"workflow_run_id": 999},
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )

    data["invocation"].refresh_from_db()
    assert data["invocation"].status == ToolInvocationStatus.AUTHORIZED


@pytest.mark.django_db
def test_other_user_cannot_dispatch(read_action, actors):
    data = read_action
    _, _, other_user = actors

    with pytest.raises(PermissionDenied):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=other_user,
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )


@pytest.mark.django_db
def test_write_action_requires_approved_request(actors):
    requester, _, _ = actors
    run, step = make_run(requester)

    payload = {"issue_number": 42, "body": "Test"}
    target = "repository:example/project/issues/42"

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.create_issue_comment",
        tool_version="1",
        side_effect_class=SideEffectClass.IDEMPOTENT_WRITE,
    )

    evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    worker_id, fencing_token = attach_lease(invocation)

    with pytest.raises(PermissionDenied):
        execute_simulated_tool(
            invocation_id=invocation.id,
            actor=requester,
            payload=payload,
            target_resource=target,
            worker_id=worker_id,
            fencing_token=fencing_token,
        )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.RECORDED


@pytest.mark.django_db
def test_approved_write_action_uses_simulator(approved_write_action):
    data = approved_write_action

    result = execute_simulated_tool(
        invocation_id=data["invocation"].id,
        actor=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
        worker_id=data["worker_id"],
        fencing_token=data["fencing_token"],
    )

    data["invocation"].refresh_from_db()

    assert result["simulated"] is True
    assert result["created"] is True
    assert data["invocation"].status == ToolInvocationStatus.SUCCEEDED


@pytest.mark.django_db
def test_unexpected_adapter_error_marks_outcome_unknown(
    read_action,
    monkeypatch,
):
    import runs.execution_gateway as gateway

    data = read_action

    def broken_adapter(payload, target_resource):
        raise RuntimeError("Simulated interrupted adapter")

    monkeypatch.setitem(
        gateway.SIMULATED_TOOLS,
        "github.get_workflow_run",
        broken_adapter,
    )

    with pytest.raises(RuntimeError):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=data["requester"],
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )

    data["invocation"].refresh_from_db()

    assert data["invocation"].status == ToolInvocationStatus.OUTCOME_UNKNOWN
    assert data["invocation"].finished_at is not None
    assert AuditEvent.objects.filter(
        run=data["run"],
        event_type="TOOL_DISPATCH_FINISHED",
        details__status=ToolInvocationStatus.OUTCOME_UNKNOWN,
    ).exists()


@pytest.mark.django_db
def test_definitive_simulated_error_marks_failed(
    read_action,
    monkeypatch,
):
    import runs.execution_gateway as gateway

    data = read_action

    def rejected_adapter(payload, target_resource):
        raise gateway.SimulatedToolError("Invalid simulated input")

    monkeypatch.setitem(
        gateway.SIMULATED_TOOLS,
        "github.get_workflow_run",
        rejected_adapter,
    )

    with pytest.raises(ValidationError):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=data["requester"],
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )

    data["invocation"].refresh_from_db()

    assert data["invocation"].status == ToolInvocationStatus.FAILED
    assert data["invocation"].error_code == "Invalid simulated input"


@pytest.mark.django_db
def test_expired_approval_cannot_dispatch(approved_write_action):
    data = approved_write_action

    ApprovalRequest.objects.filter(pk=data["request"].pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(PermissionDenied):
        execute_simulated_tool(
            invocation_id=data["invocation"].id,
            actor=data["requester"],
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )

    data["invocation"].refresh_from_db()
    assert data["invocation"].status == ToolInvocationStatus.RECORDED


@pytest.mark.django_db
def test_old_worker_cannot_dispatch_after_lease_reclaim(read_action):
    data = read_action
    invocation = data["invocation"]

    ToolInvocation.objects.filter(pk=invocation.pk).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )

    new_worker = uuid.uuid4()
    new_lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=new_worker,
    )

    assert new_lease["fencing_token"] > data["fencing_token"]

    with pytest.raises(ValidationError):
        execute_simulated_tool(
            invocation_id=invocation.id,
            actor=data["requester"],
            payload=data["payload"],
            target_resource=data["target"],
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
        )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.AUTHORIZED


@pytest.mark.django_db
def test_expired_worker_cannot_finalize(read_action):
    data = read_action
    invocation = data["invocation"]

    ToolInvocation.objects.filter(pk=invocation.pk).update(
        status=ToolInvocationStatus.STARTED,
        started_at=timezone.now() - timedelta(minutes=2),
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    with pytest.raises(ValidationError):
        _finish_invocation(
            invocation_id=invocation.id,
            actor=data["requester"],
            status=ToolInvocationStatus.SUCCEEDED,
            worker_id=data["worker_id"],
            fencing_token=data["fencing_token"],
            response_summary={"simulated": True},
        )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.STARTED
