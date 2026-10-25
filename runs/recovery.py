from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from runs.models import (
    AgentRun,
    AuditEvent,
    ReconciliationEvidence,
    ReconciliationOutcome,
    RunStatus,
    ToolInvocation,
    ToolInvocationStatus,
)


def _refresh_step(invocation, actor=None):
    from runs.step_lifecycle import refresh_step_lifecycle

    return refresh_step_lifecycle(
        step_id=invocation.step_id,
        actor=actor,
    )


@transaction.atomic
def recover_stale_invocations(*, stale_before, limit=100):
    """Mark stale started invocations as having an unknown outcome."""
    if not 1 <= limit <= 1000:
        raise ValidationError("Limit must be between 1 and 1000.")

    now = timezone.now()

    invocations = list(
        ToolInvocation.objects
        .select_for_update(skip_locked=True)
        .select_related("step__run")
        .filter(
            status=ToolInvocationStatus.STARTED,
            started_at__lt=stale_before,
        )
        .order_by("started_at", "id")[:limit]
    )

    recovered_ids = []

    for invocation in invocations:
        invocation.status = ToolInvocationStatus.OUTCOME_UNKNOWN
        invocation.finished_at = now
        invocation.error_code = "WORKER_INTERRUPTED"
        invocation.save(
            update_fields=["status", "finished_at", "error_code"]
        )

        AuditEvent.objects.create(
            run=invocation.step.run,
            event_type="INVOCATION_RECOVERY_REQUIRED",
            correlation_id=invocation.correlation_id,
            details={
                "invocation_id": str(invocation.id),
                "previous_status": ToolInvocationStatus.STARTED,
                "new_status": ToolInvocationStatus.OUTCOME_UNKNOWN,
                "reason": "Stale dispatch; external outcome is unconfirmed.",
            },
        )

        _refresh_step(invocation)
        recovered_ids.append(invocation.id)

    return recovered_ids


@transaction.atomic
def reconcile_invocation(
    *,
    invocation_id,
    outcome,
    source,
    external_reference="",
    details=None,
    observed_at=None,
):
    """Record evidence and resolve an unknown invocation when conclusive."""
    if outcome not in ReconciliationOutcome.values:
        raise ValidationError("Invalid reconciliation outcome.")

    if not isinstance(source, str) or not source.strip():
        raise ValidationError("Evidence source is required.")

    invocation = (
        ToolInvocation.objects
        .select_for_update()
        .select_related("step__run")
        .get(pk=invocation_id)
    )

    if invocation.status != ToolInvocationStatus.OUTCOME_UNKNOWN:
        raise ValidationError(
            "Only invocations with an unknown outcome can be reconciled."
        )

    if details is not None and not isinstance(details, dict):
        raise ValidationError("Evidence details must be a dictionary.")

    evidence = ReconciliationEvidence.objects.create(
        invocation=invocation,
        outcome=outcome,
        source=source.strip()[:100],
        external_reference=(
            external_reference.strip()[:300]
            if isinstance(external_reference, str)
            else ""
        ),
        details=details or {},
        observed_at=observed_at or timezone.now(),
    )

    if outcome == ReconciliationOutcome.SUCCEEDED:
        invocation.status = ToolInvocationStatus.SUCCEEDED
    elif outcome == ReconciliationOutcome.FAILED:
        invocation.status = ToolInvocationStatus.FAILED

    if outcome != ReconciliationOutcome.INCONCLUSIVE:
        invocation.error_code = ""
        invocation.finished_at = timezone.now()

    invocation.save(
        update_fields=["status", "error_code", "finished_at"]
    )

    AuditEvent.objects.create(
        run=invocation.step.run,
        event_type="INVOCATION_RECONCILED",
        correlation_id=invocation.correlation_id,
        details={
            "invocation_id": str(invocation.id),
            "evidence_id": str(evidence.id),
            "observed_outcome": outcome,
            "resulting_status": invocation.status,
            "source": evidence.source,
            "external_reference": evidence.external_reference,
        },
    )

    _refresh_step(invocation)
    return evidence


@transaction.atomic
def flag_stale_running_runs(*, stale_before, limit=100):
    """Audit potentially stuck runs without changing their status."""
    if not 1 <= limit <= 1000:
        raise ValidationError("Limit must be between 1 and 1000.")

    stale_runs = list(
        AgentRun.objects
        .select_for_update(skip_locked=True)
        .filter(
            status=RunStatus.RUNNING,
            updated_at__lt=stale_before,
        )
        .order_by("updated_at", "id")[:limit]
    )

    for run in stale_runs:
        AuditEvent.objects.create(
            run=run,
            event_type="RUN_STALE_DETECTED",
            details={
                "run_id": str(run.id),
                "status": run.status,
                "updated_at": run.updated_at.isoformat(),
            },
        )

    return [run.id for run in stale_runs]


@transaction.atomic
def recover_expired_invocations(*, limit=100):
    """Mark expired started invocations uncertain; never retry automatically."""
    if not 1 <= limit <= 1000:
        raise ValidationError("Limit must be between 1 and 1000.")

    now = timezone.now()

    invocations = list(
        ToolInvocation.objects
        .select_for_update(skip_locked=True)
        .select_related("step__run")
        .filter(
            status=ToolInvocationStatus.STARTED,
            lease_expires_at__isnull=False,
            lease_expires_at__lte=now,
        )
        .order_by("lease_expires_at", "id")[:limit]
    )

    recovered_ids = []

    for invocation in invocations:
        invocation.status = ToolInvocationStatus.OUTCOME_UNKNOWN
        invocation.finished_at = now
        invocation.error_code = "WORKER_LEASE_EXPIRED"
        invocation.lease_owner = None
        invocation.lease_expires_at = None
        invocation.heartbeat_at = None

        invocation.save(
            update_fields=[
                "status",
                "finished_at",
                "error_code",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
            ]
        )

        AuditEvent.objects.create(
            run=invocation.step.run,
            event_type="INVOCATION_LEASE_EXPIRED",
            correlation_id=invocation.correlation_id,
            details={
                "invocation_id": str(invocation.id),
                "error_code": invocation.error_code,
                "next_action": "reconciliation_required",
            },
        )

        _refresh_step(invocation)
        recovered_ids.append(str(invocation.id))

    return recovered_ids