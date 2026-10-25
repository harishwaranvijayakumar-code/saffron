
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from runs.dune_planner import DunePlanningError
from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    RunStatus,
    ToolInvocation,
)
from unittest.mock import patch


@pytest.fixture
def planner_user(db):
    return get_user_model().objects.create_user(
        username="dune-integration-user",
        password="test-only-password",
    )


@pytest.fixture
def proposed_plan():
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


@pytest.fixture
def valid_form_data():
    return {
        "objective": "Investigate workflow run 123",
        "max_steps": 10,
        "max_tool_invocations": 20,
        "max_runtime_seconds": 900,
    }


@pytest.mark.django_db
def test_dune_preview_does_not_create_run(
    client, planner_user, proposed_plan, valid_form_data
):
    client.force_login(planner_user)

    with patch(
        "runs.views.generate_plan",
        return_value=proposed_plan,
    ) as generate:
        response = client.post(
            reverse("run-create"),
            valid_form_data,
        )

    assert response.status_code == 200
    assert "runs/plan_preview.html" in [template.name for template in response.templates]
    assert response.context["plan"] == proposed_plan
    generate.assert_called_once()
    assert not AgentRun.objects.filter(
        created_by=planner_user
    ).exists()


@pytest.mark.django_db
def test_confirm_persists_plan_without_executing_tools(
    client, planner_user, proposed_plan, valid_form_data
):
    client.force_login(planner_user)

    with patch("runs.views.generate_plan", return_value=proposed_plan):
        preview = client.post(reverse("run-create"), valid_form_data)

    token = preview.context["plan_token"]
    response = client.post(
        reverse("run-confirm-plan"),
        {"plan_token": token},
    )

    run = AgentRun.objects.get(created_by=planner_user)

    assert response.status_code == 302
    assert response.url == reverse(
        "run-detail",
        kwargs={"run_id": run.id},
    )
    assert run.status == RunStatus.QUEUED
    assert run.steps.count() == 1

    step = ExecutionStep.objects.get(run=run)
    invocation = ToolInvocation.objects.get(step=step)

    assert invocation.started_at is None
    assert AuditEvent.objects.filter(
        run=run,
        event_type="PLAN_PERSISTED",
    ).exists()
    assert "dune_plan_token" not in client.session


@pytest.mark.django_db
def test_dune_provider_error_does_not_create_run(
    client, planner_user, valid_form_data
):
    client.force_login(planner_user)

    with patch(
        "runs.views.generate_plan",
        side_effect=DunePlanningError("Dune is temporarily unavailable."),
    ):
        response = client.post(
            reverse("run-create"),
            valid_form_data,
        )

    assert response.status_code == 200
    assert not AgentRun.objects.filter(
        created_by=planner_user
    ).exists()


@pytest.mark.django_db
def test_invalid_confirmation_token_cannot_create_run(
    client, planner_user
):
    client.force_login(planner_user)

    response = client.post(
        reverse("run-confirm-plan"),
        {"plan_token": "invalid-token"},
    )

    assert response.status_code == 302
    assert not AgentRun.objects.filter(
        created_by=planner_user
    ).exists()


@pytest.mark.django_db
def test_dune_preview_requires_login(client):
    response = client.post(reverse("run-create"), {})
    assert response.status_code == 302
    assert reverse("login") in response.url
