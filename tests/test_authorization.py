import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from runs.approval_services import (
    create_approval_request,
    decide_approval,
    validate_approval_for_execution,
)
from runs.models import (
    AgentRun,
    ApprovalStatus,
    AuditEvent,
    ExecutionStep,
    PolicyDecisionStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.policy import evaluate_tool_request


@pytest.fixture
def actors(db):
    user_model = get_user_model()

    requester = user_model.objects.create_user(
        username="authorization-requester",
        password="test-only-password",
    )
    approver = user_model.objects.create_user(
        username="authorization-approver",
        password="test-only-password",
        is_staff=True,
    )
    ordinary_user = user_model.objects.create_user(
        username="authorization-ordinary-user",
        password="test-only-password",
    )

    return requester, approver, ordinary_user


@pytest.fixture
def write_action(actors):
    requester, _, _ = actors

    run = AgentRun.objects.create(
        created_by=requester,
        objective="Investigate a failed workflow",
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Draft a workflow issue comment",
    )
    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.create_issue_comment",
        tool_version="1",
        side_effect_class=SideEffectClass.IDEMPOTENT_WRITE,
    )

    payload = {
        "issue_number": 42,
        "body": "The workflow failed during testing.",
    }
    target = "repository:example/project/issues/42"

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload=payload,
        target_resource=target,
    )

    return {
        "run": run,
        "invocation": invocation,
        "requester": requester,
        "payload": payload,
        "target": target,
        "decision": decision,
    }


@pytest.mark.django_db
def test_unknown_tool_is_denied(actors):
    requester, _, _ = actors
    run = AgentRun.objects.create(
        created_by=requester,
        objective="Test default deny",
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Unknown tool",
    )
    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="unknown.execute",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload={},
        target_resource="test:resource",
    )

    invocation.refresh_from_db()

    assert decision.status == PolicyDecisionStatus.DENY
    assert invocation.status == ToolInvocationStatus.DENIED


@pytest.mark.django_db
def test_allowlisted_read_only_tool_is_authorized(actors):
    requester, _, _ = actors
    run = AgentRun.objects.create(
        created_by=requester,
        objective="Test read-only access",
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow",
    )
    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    decision = evaluate_tool_request(
        invocation_id=invocation.id,
        actor=requester,
        payload={"workflow_run_id": 123},
        target_resource="repository:example/project/actions/runs/123",
    )

    invocation.refresh_from_db()

    assert decision.status == PolicyDecisionStatus.ALLOW
    assert invocation.status == ToolInvocationStatus.AUTHORIZED


@pytest.mark.django_db
def test_actor_cannot_authorize_another_users_run(actors):
    requester, _, ordinary_user = actors
    run = AgentRun.objects.create(
        created_by=requester,
        objective="Private run",
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow",
    )
    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    with pytest.raises(ValidationError):
        evaluate_tool_request(
            invocation_id=invocation.id,
            actor=ordinary_user,
            payload={},
            target_resource="test:resource",
        )


@pytest.mark.django_db
def test_write_action_requires_approval(write_action):
    decision = write_action["decision"]

    assert decision.status == PolicyDecisionStatus.REQUIRES_APPROVAL
    assert decision.policy_version
    assert decision.payload_hash
    assert decision.context_hash


@pytest.mark.django_db
def test_requester_cannot_change_approved_payload(write_action):
    data = write_action

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    with pytest.raises(ValidationError):
        create_approval_request(
            decision_id=data["decision"].id,
            requested_by=data["requester"],
            payload={"issue_number": 42, "body": "Changed text"},
            target_resource=data["target"],
        )

    assert request.status == ApprovalStatus.PENDING


@pytest.mark.django_db
def test_requester_cannot_approve_own_action(write_action, actors):
    data = write_action

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    with pytest.raises(PermissionDenied):
        decide_approval(
            request_id=request.id,
            approver=data["requester"],
            approve=True,
        )


@pytest.mark.django_db
def test_non_staff_user_cannot_approve(write_action, actors):
    data = write_action
    _, _, ordinary_user = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    with pytest.raises(PermissionDenied):
        decide_approval(
            request_id=request.id,
            approver=ordinary_user,
            approve=True,
        )


@pytest.mark.django_db
def test_approved_action_passes_revalidation(write_action, actors):
    data = write_action
    _, approver, _ = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=True,
        note="Approved for the specified issue.",
    )

    assert validate_approval_for_execution(
        request_id=request.id,
        payload=data["payload"],
        target_resource=data["target"],
    )

    assert AuditEvent.objects.filter(
        run=data["run"],
        event_type="APPROVAL_REVALIDATED",
    ).exists()


@pytest.mark.django_db
def test_changed_payload_fails_revalidation(write_action, actors):
    data = write_action
    _, approver, _ = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=True,
    )

    changed_payload = {
        "issue_number": 42,
        "body": "A different action than the one approved.",
    }

    with pytest.raises(ValidationError):
        validate_approval_for_execution(
            request_id=request.id,
            payload=changed_payload,
            target_resource=data["target"],
        )


@pytest.mark.django_db
def test_changed_target_fails_revalidation(write_action, actors):
    data = write_action
    _, approver, _ = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=True,
    )

    with pytest.raises(ValidationError):
        validate_approval_for_execution(
            request_id=request.id,
            payload=data["payload"],
            target_resource="repository:another-project/issues/42",
        )


@pytest.mark.django_db
def test_rejected_action_cannot_be_revalidated(write_action, actors):
    data = write_action
    _, approver, _ = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=False,
        note="Insufficient evidence.",
    )

    with pytest.raises(ValidationError):
        validate_approval_for_execution(
            request_id=request.id,
            payload=data["payload"],
            target_resource=data["target"],
        )


@pytest.mark.django_db
def test_policy_and_approval_events_are_audited(write_action, actors):
    data = write_action
    _, approver, _ = actors

    request = create_approval_request(
        decision_id=data["decision"].id,
        requested_by=data["requester"],
        payload=data["payload"],
        target_resource=data["target"],
    )

    decide_approval(
        request_id=request.id,
        approver=approver,
        approve=True,
    )

    event_types = set(
        AuditEvent.objects.filter(run=data["run"])
        .values_list("event_type", flat=True)
    )

    assert "TOOL_POLICY_DECISION" in event_types
    assert "APPROVAL_REQUESTED" in event_types
    assert "APPROVAL_DECIDED" in event_types
