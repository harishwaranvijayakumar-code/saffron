import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from runs.models import (
    AuditEvent,
    ToolInvocation,
    ToolInvocationStatus,
)


MAX_LEASE_SECONDS = 300


def _validate_lease_duration(seconds):
    if not 1 <= seconds <= MAX_LEASE_SECONDS:
        raise ValidationError(
            f"Lease duration must be between 1 and {MAX_LEASE_SECONDS} seconds."
        )


@transaction.atomic
def claim_invocation_lease(*, invocation_id, worker_id, lease_seconds=60):
    """
    Claim an eligible invocation or reclaim an expired lease.

    Every successful claim increments the fencing token.
    """
    _validate_lease_duration(lease_seconds)

    invocation = (
        ToolInvocation.objects
        .select_for_update()
        .select_related("step__run")
        .get(pk=invocation_id)
    )

    now = timezone.now()

    if invocation.status not in {
        ToolInvocationStatus.RECORDED,
        ToolInvocationStatus.AUTHORIZED,
    }:
        raise ValidationError(
            "Only undispatched invocations can be leased."
        )

    if (
        invocation.lease_owner is not None
        and invocation.lease_expires_at is not None
        and invocation.lease_expires_at > now
    ):
        raise ValidationError("Invocation already has an active lease.")

    invocation.fencing_token += 1
    invocation.lease_owner = worker_id
    invocation.lease_expires_at = now + timedelta(seconds=lease_seconds)
    invocation.heartbeat_at = now
    invocation.save(
        update_fields=[
            "fencing_token",
            "lease_owner",
            "lease_expires_at",
            "heartbeat_at",
        ]
    )

    AuditEvent.objects.create(
        run=invocation.step.run,
        event_type="INVOCATION_LEASE_CLAIMED",
        correlation_id=invocation.correlation_id,
        details={
            "invocation_id": str(invocation.id),
            "worker_id": str(worker_id),
            "fencing_token": invocation.fencing_token,
            "lease_expires_at": invocation.lease_expires_at.isoformat(),
        },
    )

    return {
        "invocation_id": invocation.id,
        "worker_id": worker_id,
        "fencing_token": invocation.fencing_token,
        "lease_expires_at": invocation.lease_expires_at,
    }


@transaction.atomic
def heartbeat_invocation_lease(
    *,
    invocation_id,
    worker_id,
    fencing_token,
    lease_seconds=60,
):
    _validate_lease_duration(lease_seconds)

    invocation = (
        ToolInvocation.objects
        .select_for_update()
        .select_related("step__run")
        .get(pk=invocation_id)
    )

    now = timezone.now()

    if invocation.lease_owner != worker_id:
        raise ValidationError("Worker does not own this lease.")

    if invocation.fencing_token != fencing_token:
        raise ValidationError("Stale fencing token.")

    if (
        invocation.lease_expires_at is None
        or invocation.lease_expires_at <= now
    ):
        raise ValidationError("Lease has expired and cannot be renewed.")

    if invocation.status not in {
        ToolInvocationStatus.RECORDED,
        ToolInvocationStatus.AUTHORIZED,
        ToolInvocationStatus.STARTED,
    }:
        raise ValidationError("Invocation is no longer eligible for a heartbeat.")

    invocation.heartbeat_at = now
    invocation.lease_expires_at = now + timedelta(seconds=lease_seconds)
    invocation.save(update_fields=["heartbeat_at", "lease_expires_at"])

    return invocation.lease_expires_at


@transaction.atomic
def validate_invocation_lease(
    *,
    invocation_id,
    worker_id,
    fencing_token,
):
    invocation = ToolInvocation.objects.select_for_update().get(
        pk=invocation_id
    )

    now = timezone.now()

    if invocation.lease_owner != worker_id:
        raise ValidationError("Worker does not own this lease.")

    if invocation.fencing_token != fencing_token:
        raise ValidationError("Stale fencing token.")

    if (
        invocation.lease_expires_at is None
        or invocation.lease_expires_at <= now
    ):
        raise ValidationError("Lease has expired.")

    return True
