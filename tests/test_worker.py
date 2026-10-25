import pytest
from django.contrib.auth import get_user_model

from runs.approval_services import create_approval_request, decide_approval
from runs.models import (
    AgentRun,
    ExecutionStep,
    PolicyDecisionStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.policy import evaluate_tool_request
from runs.services import transition_run
from runs.worker import process_next_invocation


@pytest.fixture
def worker_actors(db):
    user_model = get_user_model()

    requester = user_model.objects.create_user(
        username="worker-requester",
        password="test-only-password",
    )
    approver = user_model.objects.create_user(
        username="worker-approver",
        password="test-only-password",
        is_staff=True,
    )
    return requester, approver


def make_running_step(requester):
    run = AgentRun.objects.create(
        created_by=requester,
        objective="Test durable worker",
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


@pytest.mark.django_db
def test_worker_executes_allowlisted_read_tool(worker_actors):
    requester, _ = worker_actors
    _, step = make_running_step(requester)

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    payload = {"workflow_run_id": 321}
    target = "repository:example/project/actions/runs/321"

    evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    result = process_next_invocation()

    invocation.refresh_from_db()

    assert result["invocation_id"] == str(invocation.id)
    assert invocation.status == ToolInvocationStatus.SUCCEEDED
    assert invocation.response_summary["simulated"] is True


@pytest.mark.django_db
def test_worker_skips_write_without_approval(worker_actors):
    requester, _ = worker_actors
    _, step = make_running_step(requester)

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.create_issue_comment",
        tool_version="1",
        side_effect_class=SideEffectClass.IDEMPOTENT_WRITE,
    )

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload={
            "issue_number": 42,
            "body": "Simulated comment",
        },
        target_resource="repository:example/project/issues/42",
    )

    result = process_next_invocation()

    invocation.refresh_from_db()

    assert decision.status == PolicyDecisionStatus.REQUIRES_APPROVAL
    assert result["status"] == "IDLE"
    assert invocation.status == ToolInvocationStatus.RECORDED


@pytest.mark.django_db
def test_worker_executes_approved_simulated_write(worker_actors):
    requester, approver = worker_actors
    _, step = make_running_step(requester)

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.create_issue_comment",
        tool_version="1",
        side_effect_class=SideEffectClass.IDEMPOTENT_WRITE,
    )

    payload = {
        "issue_number": 42,
        "body": "Simulated comment",
    }
    target = "repository:example/project/issues/42"

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    approval = create_approval_request(
        decision_id=decision.id,
        requested_by=requester,
        payload=payload,
        target_resource=target,
    )

    decide_approval(
        request_id=approval.id,
        approver=approver,
        approve=True,
    )

    result = process_next_invocation()

    invocation.refresh_from_db()

    assert result["invocation_id"] == str(invocation.id)
    assert invocation.status == ToolInvocationStatus.SUCCEEDED
    assert invocation.response_summary["simulated"] is True
    assert invocation.response_summary["created"] is True
