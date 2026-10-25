import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from runs.models import AgentRun, RunStatus
from runs.services import transition_run


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="saffron-test-user",
        password="test-only-password",
    )


@pytest.fixture
def run(user):
    return AgentRun.objects.create(
        created_by=user,
        objective="Investigate a failed GitHub Actions workflow",
    )


@pytest.mark.django_db
def test_new_run_starts_queued(run):
    assert run.status == RunStatus.QUEUED
    assert run.state_version == 0
    assert run.finished_at is None


@pytest.mark.django_db
def test_run_can_transition_to_running(run):
    updated = transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
    )

    assert updated.status == RunStatus.RUNNING
    assert updated.state_version == 1
    assert updated.started_at is not None


@pytest.mark.django_db
def test_invalid_transition_is_rejected(run):
    with pytest.raises(ValidationError):
        transition_run(
            run.id,
            expected_version=0,
            new_status=RunStatus.SUCCEEDED,
        )

    run.refresh_from_db()
    assert run.status == RunStatus.QUEUED
    assert run.state_version == 0


@pytest.mark.django_db
def test_stale_version_is_rejected(run):
    transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
    )

    with pytest.raises(ValidationError):
        transition_run(
            run.id,
            expected_version=0,
            new_status=RunStatus.SUCCEEDED,
        )

    run.refresh_from_db()
    assert run.status == RunStatus.RUNNING


@pytest.mark.django_db
def test_success_sets_finish_time(run):
    running = transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
    )

    completed = transition_run(
        running.id,
        expected_version=running.state_version,
        new_status=RunStatus.SUCCEEDED,
    )

    assert completed.status == RunStatus.SUCCEEDED
    assert completed.finished_at is not None


@pytest.mark.django_db
def test_terminal_run_cannot_transition_again(run):
    running = transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
    )
    completed = transition_run(
        running.id,
        expected_version=running.state_version,
        new_status=RunStatus.SUCCEEDED,
    )

    with pytest.raises(ValidationError):
        transition_run(
            completed.id,
            expected_version=completed.state_version,
            new_status=RunStatus.RUNNING,
        )
