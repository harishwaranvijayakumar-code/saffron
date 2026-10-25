from datetime import timedelta
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from runs.leases import (
    claim_invocation_lease,
    heartbeat_invocation_lease,
    validate_invocation_lease,
)
from runs.models import (
    AgentRun,
    ExecutionStep,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)


@pytest.fixture
def invocation(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="lease-test-user",
        password="test-only-password",
    )
    run = AgentRun.objects.create(
        created_by=user,
        objective="Test worker leases",
    )
    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Lease test step",
    )
    return ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )


@pytest.mark.django_db
def test_claim_creates_lease_and_fencing_token(invocation):
    worker_id = uuid.uuid4()

    lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
    )

    invocation.refresh_from_db()

    assert lease["worker_id"] == worker_id
    assert lease["fencing_token"] == 1
    assert invocation.lease_owner == worker_id
    assert invocation.lease_expires_at > timezone.now()


@pytest.mark.django_db
def test_active_lease_cannot_be_claimed_by_another_worker(invocation):
    claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=uuid.uuid4(),
    )

    with pytest.raises(ValidationError):
        claim_invocation_lease(
            invocation_id=invocation.id,
            worker_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_expired_lease_reclaim_increments_fencing_token(invocation):
    first_worker = uuid.uuid4()
    second_worker = uuid.uuid4()

    first_lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=first_worker,
    )

    ToolInvocation.objects.filter(pk=invocation.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )

    second_lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=second_worker,
    )

    assert second_lease["fencing_token"] == first_lease["fencing_token"] + 1
    assert second_lease["worker_id"] == second_worker


@pytest.mark.django_db
def test_heartbeat_extends_active_lease(invocation):
    worker_id = uuid.uuid4()
    lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
    )

    old_expiry = lease["lease_expires_at"]

    new_expiry = heartbeat_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
        fencing_token=lease["fencing_token"],
        lease_seconds=120,
    )

    assert new_expiry > old_expiry


@pytest.mark.django_db
def test_stale_fencing_token_is_rejected(invocation):
    first_worker = uuid.uuid4()

    first_lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=first_worker,
    )

    ToolInvocation.objects.filter(pk=invocation.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )

    second_lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=uuid.uuid4(),
    )

    with pytest.raises(ValidationError):
        validate_invocation_lease(
            invocation_id=invocation.id,
            worker_id=first_worker,
            fencing_token=first_lease["fencing_token"],
        )

    assert second_lease["fencing_token"] > first_lease["fencing_token"]


@pytest.mark.django_db
def test_expired_lease_cannot_heartbeat(invocation):
    worker_id = uuid.uuid4()
    lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
    )

    ToolInvocation.objects.filter(pk=invocation.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(ValidationError):
        heartbeat_invocation_lease(
            invocation_id=invocation.id,
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
        )


@pytest.mark.django_db
def test_completed_invocation_cannot_be_leased(invocation):
    ToolInvocation.objects.filter(pk=invocation.id).update(
        status=ToolInvocationStatus.SUCCEEDED,
    )

    with pytest.raises(ValidationError):
        claim_invocation_lease(
            invocation_id=invocation.id,
            worker_id=uuid.uuid4(),
        )
