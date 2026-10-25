import pytest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from runs.models import AgentRun, AuditEvent, RunStatus


@pytest.fixture
def creator(db):
    return get_user_model().objects.create_user(
        username="workflow-creator",
        password="test-only-password",
    )


@pytest.fixture
def valid_form_data():
    return {
        "objective": "Investigate a failed workflow",
        "max_steps": 12,
        "max_tool_invocations": 30,
        "max_runtime_seconds": 600,
    }


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


def generate_preview(client, proposed_plan, data):
    with patch(
        "runs.views.generate_plan",
        return_value=proposed_plan,
    ) as generate:
        response = client.post(reverse("run-create"), data)

    generate.assert_called_once()
    return response


@pytest.mark.django_db
def test_create_run_page_requires_login(client):
    response = client.get(reverse("run-create"))

    assert response.status_code == 302
    assert reverse("login") in response.url


@pytest.mark.django_db
def test_create_run_get_renders_form(client, creator):
    client.force_login(creator)

    response = client.get(reverse("run-create"))

    assert response.status_code == 200
    assert b"Workflow objective" in response.content
    assert b"Execution budgets" in response.content


@pytest.mark.django_db
def test_valid_submission_previews_plan_without_creating_run(
    client,
    creator,
    valid_form_data,
    proposed_plan,
):
    client.force_login(creator)

    response = generate_preview(client, proposed_plan, valid_form_data)

    assert response.status_code == 200
    assert "runs/plan_preview.html" in [
        template.name for template in response.templates
    ]
    assert response.context["plan"] == proposed_plan
    assert not AgentRun.objects.filter(created_by=creator).exists()
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_confirmed_plan_creates_queued_run_and_audit_event(
    client,
    creator,
    valid_form_data,
    proposed_plan,
):
    client.force_login(creator)

    preview = generate_preview(client, proposed_plan, valid_form_data)
    assert preview.status_code == 200

    token = preview.context["plan_token"]
    response = client.post(
        reverse("run-confirm-plan"),
        {"plan_token": token},
    )

    run = AgentRun.objects.get(created_by=creator)

    assert response.status_code == 302
    assert response.url == reverse(
        "run-detail",
        kwargs={"run_id": run.id},
    )
    assert run.objective == valid_form_data["objective"]
    assert run.status == RunStatus.QUEUED
    assert run.max_steps == valid_form_data["max_steps"]
    assert run.max_tool_invocations == valid_form_data["max_tool_invocations"]
    assert run.max_runtime_seconds == valid_form_data["max_runtime_seconds"]

    event = AuditEvent.objects.get(
        run=run,
        event_type="RUN_CREATED",
    )
    assert event.actor == creator
    assert event.details["status"] == RunStatus.QUEUED

    assert AuditEvent.objects.filter(
        run=run,
        event_type="PLAN_PERSISTED",
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("objective", ""),
        ("max_steps", 0),
        ("max_steps", 101),
        ("max_tool_invocations", 501),
        ("max_runtime_seconds", 86401),
    ],
)
def test_invalid_submission_does_not_create_run(
    client,
    creator,
    field,
    value,
):
    client.force_login(creator)

    data = {
        "objective": "Investigate a failed workflow",
        "max_steps": 20,
        "max_tool_invocations": 50,
        "max_runtime_seconds": 900,
    }
    data[field] = value

    with patch("runs.views.generate_plan") as generate:
        response = client.post(reverse("run-create"), data)

    assert response.status_code == 200
    assert AgentRun.objects.filter(created_by=creator).count() == 0
    assert AuditEvent.objects.count() == 0
    generate.assert_not_called()


@pytest.mark.django_db
def test_created_run_belongs_only_to_requesting_user(
    client,
    creator,
    valid_form_data,
    proposed_plan,
):
    client.force_login(creator)

    preview = generate_preview(client, proposed_plan, valid_form_data)
    assert preview.status_code == 200

    response = client.post(
        reverse("run-confirm-plan"),
        {"plan_token": preview.context["plan_token"]},
    )
    assert response.status_code == 302

    run = AgentRun.objects.get(created_by=creator)

    other_user = get_user_model().objects.create_user(
        username="different-user",
        password="test-only-password",
    )

    client.force_login(other_user)
    response = client.get(
        reverse("run-detail", kwargs={"run_id": run.id})
    )

    assert response.status_code == 404