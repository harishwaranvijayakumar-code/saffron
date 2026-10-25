
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from runs.models import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    ExecutionStep,
    ExecutionStepStatus,
    PolicyDecision,
    PolicyDecisionStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.plan_services import persist_plan


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="plan-owner",
        password="test-only-password",
    )


@pytest.fixture
def run(user):
    return AgentRun.objects.create(
        created_by=user,
        objective="Investigate a failed GitHub Actions workflow",
    )


def read_plan():
    return {
        "steps": [
            {
                "name": "Inspect workflow run",
                "tool_name": "github.get_workflow_run",
                "target_resource": "repo/example/project/actions/runs/123",
                "payload": {"workflow_run_id": 123},
            }
        ]
    }


@pytest.mark.django_db
def test_persist_plan_creates_step_invocation_and_policy_decision(
    user, run
):
    steps = persist_plan(run_id=run.id, actor=user, plan=read_plan())

    assert len(steps) == 1
    step = steps[0]
    invocation = ToolInvocation.objects.get(step=step)
    decision = PolicyDecision.objects.get(invocation=invocation)

    run.refresh_from_db()
    assert run.status == RunStatus.QUEUED
    assert step.sequence == 1
    assert step.name == "Inspect workflow run"
    assert step.status == ExecutionStepStatus.PENDING
    assert invocation.status == ToolInvocationStatus.AUTHORIZED
    assert invocation.side_effect_class == SideEffectClass.READ_ONLY
    assert invocation.request_payload == {"workflow_run_id": 123}
    assert decision.status == PolicyDecisionStatus.ALLOW
    assert not invocation.started_at

    event = AuditEvent.objects.get(
        run=run,
        event_type="PLAN_PERSISTED",
    )
    assert event.details["execution_started"] is False


@pytest.mark.django_db
def test_approval_required_tool_creates_pending_approval(user, run):
    plan = {
        "steps": [
            {
                "name": "Draft issue comment",
                "tool_name": "github.create_issue_comment",
                "target_resource": "repo/example/project/issues/123",
                "payload": {
                    "issue_number": 123,
                    "body": "The workflow failure is under investigation.",
                },
            }
        ]
    }

    steps = persist_plan(run_id=run.id, actor=user, plan=plan)
    invocation = ToolInvocation.objects.get(step=steps[0])
    decision = PolicyDecision.objects.get(invocation=invocation)
    approval = ApprovalRequest.objects.get(decision=decision)

    assert decision.status == PolicyDecisionStatus.REQUIRES_APPROVAL
    assert invocation.status == ToolInvocationStatus.RECORDED
    assert invocation.side_effect_class == SideEffectClass.IDEMPOTENT_WRITE
    assert approval.status == "PENDING"
    assert approval.requested_by == user
    assert steps[0].status == ExecutionStepStatus.WAITING_APPROVAL


@pytest.mark.django_db
@pytest.mark.parametrize(
    "plan",
    [
        {},
        {"steps": []},
        {"steps": "not-a-list"},
        {
            "steps": [
                {
                    "name": "Unknown",
                    "tool_name": "github.delete_repository",
                    "target_resource": "repo/example/project",
                    "payload": {},
                }
            ]
        },
        {
            "steps": [
                {
                    "name": "Bad ID",
                    "tool_name": "github.get_workflow_run",
                    "target_resource": "repo/example/project/actions/runs/0",
                    "payload": {"workflow_run_id": 0},
                }
            ]
        },
        {
            "steps": [
                {
                    "name": "Missing payload",
                    "tool_name": "github.get_workflow_run",
                    "target_resource": "repo/example/project/actions/runs/123",
                    "payload": [],
                }
            ]
        },
        {
            "steps": [
                {
                    "name": "Extra field",
                    "tool_name": "github.get_workflow_run",
                    "target_resource": "repo/example/project/actions/runs/123",
                    "payload": {"workflow_run_id": 123},
                    "execute_now": True,
                }
            ]
        },
    ],
)
def test_invalid_plan_creates_no_execution_records(user, run, plan):
    with pytest.raises(ValidationError):
        persist_plan(run_id=run.id, actor=user, plan=plan)

    assert ExecutionStep.objects.filter(run=run).count() == 0
    assert ToolInvocation.objects.filter(step__run=run).count() == 0
    assert PolicyDecision.objects.filter(
        invocation__step__run=run
    ).count() == 0
    assert not AuditEvent.objects.filter(
        run=run,
        event_type="PLAN_PERSISTED",
    ).exists()


@pytest.mark.django_db
def test_plan_cannot_exceed_step_budget(user, run):
    run.max_steps = 1
    run.save(update_fields=["max_steps"])

    plan = read_plan()
    plan["steps"].append({
        "name": "Inspect workflow jobs",
        "tool_name": "github.list_workflow_jobs",
        "target_resource": "repo/example/project/actions/runs/123/jobs",
        "payload": {"workflow_run_id": 123},
    })

    with pytest.raises(ValidationError, match="step budget"):
        persist_plan(run_id=run.id, actor=user, plan=plan)

    assert not run.steps.exists()


@pytest.mark.django_db
def test_other_user_cannot_persist_plan(run):
    other_user = get_user_model().objects.create_user(
        username="different-plan-owner",
        password="test-only-password",
    )

    with pytest.raises(PermissionDenied):
        persist_plan(
            run_id=run.id,
            actor=other_user,
            plan=read_plan(),
        )

    assert not run.steps.exists()


@pytest.mark.django_db
def test_plan_cannot_be_persisted_twice(user, run):
    persist_plan(run_id=run.id, actor=user, plan=read_plan())

    with pytest.raises(ValidationError, match="already has"):
        persist_plan(run_id=run.id, actor=user, plan=read_plan())

    assert run.steps.count() == 1
    assert ToolInvocation.objects.filter(step__run=run).count() == 1
