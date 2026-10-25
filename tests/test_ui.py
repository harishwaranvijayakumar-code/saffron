
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from runs.models import (
    AgentRun,
    ExecutionStep,
    RunStatus,
    ToolInvocation,
    ToolInvocationStatus,
)


@pytest.fixture
def ui_user(db):
    return get_user_model().objects.create_user(
        username="ui-test-user",
        password="test-only-password",
    )


@pytest.fixture
def ui_run(ui_user):
    return AgentRun.objects.create(
        created_by=ui_user,
        objective="Investigate a failed GitHub Actions workflow",
    )


@pytest.mark.django_db
def test_login_page_uses_saffron_template(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b"Sign in" in response.content
    assert b"Saffron" in response.content


@pytest.mark.django_db
def test_successful_login_redirects_to_dashboard(client, ui_user):
    response = client.post(
        reverse("login"),
        {
            "username": "ui-test-user",
            "password": "test-only-password",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("runs-dashboard")


@pytest.mark.django_db
def test_logout_redirects_to_login(client, ui_user):
    client.force_login(ui_user)

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert response.url == reverse("login")

    dashboard_response = client.get(reverse("runs-dashboard"))
    assert dashboard_response.status_code == 302
    assert reverse("login") in dashboard_response.url


@pytest.mark.django_db
def test_dashboard_requires_authentication(client):
    response = client.get(reverse("runs-dashboard"))

    assert response.status_code == 302
    assert reverse("login") in response.url


@pytest.mark.django_db
def test_dashboard_shows_only_current_users_runs(
    client,
    ui_user,
    ui_run,
):
    other_user = get_user_model().objects.create_user(
        username="other-ui-user",
        password="test-only-password",
    )
    other_run = AgentRun.objects.create(
        created_by=other_user,
        objective="Private run belonging to another user",
    )

    client.force_login(ui_user)
    response = client.get(reverse("runs-dashboard"))

    assert response.status_code == 200
    assert response.context["total_runs"] == 1
    assert ui_run.objective in response.content.decode()
    assert other_run.objective not in response.content.decode()


@pytest.mark.django_db
def test_dashboard_counts_run_statuses(client, ui_user, ui_run):
    ui_run.status = RunStatus.RUNNING
    ui_run.save(update_fields=["status"])

    AgentRun.objects.create(
        created_by=ui_user,
        objective="Completed workflow",
        status=RunStatus.SUCCEEDED,
    )

    client.force_login(ui_user)
    response = client.get(reverse("runs-dashboard"))

    assert response.status_code == 200
    assert response.context["total_runs"] == 2
    assert response.context["status_counts"]["RUNNING"] == 1
    assert response.context["status_counts"]["SUCCEEDED"] == 1


@pytest.mark.django_db
def test_dashboard_counts_unresolved_invocations(
    client,
    ui_user,
    ui_run,
):
    step = ExecutionStep.objects.create(
        run=ui_run,
        sequence=1,
        name="Inspect workflow",
    )

    ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        status=ToolInvocationStatus.OUTCOME_UNKNOWN,
    )

    client.force_login(ui_user)
    response = client.get(reverse("runs-dashboard"))

    assert response.status_code == 200
    assert response.context["unresolved_outcomes"] == 1


@pytest.mark.django_db
def test_run_detail_displays_steps_and_invocations(
    client,
    ui_user,
    ui_run,
):
    step = ExecutionStep.objects.create(
        run=ui_run,
        sequence=1,
        name="Inspect workflow",
        input_summary={"workflow_run_id": 123},
    )

    ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        status=ToolInvocationStatus.RECORDED,
        request_summary={"workflow_run_id": 123},
    )

    client.force_login(ui_user)
    response = client.get(
        reverse("run-detail", kwargs={"run_id": ui_run.id})
    )

    assert response.status_code == 200
    assert b"Inspect workflow" in response.content
    assert b"github.get_workflow_run" in response.content
    assert b"Audit trail" in response.content


@pytest.mark.django_db
def test_run_detail_requires_authentication(client, ui_run):
    response = client.get(
        reverse("run-detail", kwargs={"run_id": ui_run.id})
    )

    assert response.status_code == 302
    assert reverse("login") in response.url


@pytest.mark.django_db
def test_user_cannot_view_another_users_run(client, ui_user):
    other_user = get_user_model().objects.create_user(
        username="private-run-owner",
        password="test-only-password",
    )
    private_run = AgentRun.objects.create(
        created_by=other_user,
        objective="Private workflow",
    )

    client.force_login(ui_user)
    response = client.get(
        reverse("run-detail", kwargs={"run_id": private_run.id})
    )

    assert response.status_code == 404
