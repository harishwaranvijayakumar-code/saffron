from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from runs.step_lifecycle import refresh_step_lifecycle

from runs.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEvent,
    PolicyDecisionStatus,
)
from runs.policy import (
    POLICY_VERSION,
    build_context_hash,
    canonical_hash,
)


@transaction.atomic
def create_approval_request(
    *,
    decision_id,
    requested_by,
    payload,
    target_resource,
    expires_in_minutes=15,
):
    from runs.models import PolicyDecision

    decision = (
        PolicyDecision.objects
        .select_for_update()
        .select_related("invocation__step__run")
        .get(pk=decision_id)
    )

    if decision.status != PolicyDecisionStatus.REQUIRES_APPROVAL:
        raise ValidationError(
            "Only actions requiring approval can create approval requests."
        )

    if decision.actor_id != requested_by.pk:
        raise PermissionDenied(
            "Only the original requesting actor can submit this approval request."
        )

    if decision.policy_version != POLICY_VERSION:
        raise ValidationError("The policy version has changed.")

    if canonical_hash(payload) != decision.payload_hash:
        raise ValidationError("The action payload does not match the policy decision.")

    if target_resource != decision.target_resource:
        raise ValidationError("The target resource does not match the policy decision.")

    if hasattr(decision, "approval_request"):
        raise ValidationError("An approval request already exists for this decision.")

    if not 1 <= expires_in_minutes <= 60:
        raise ValidationError("Approval expiry must be between 1 and 60 minutes.")

    request = ApprovalRequest.objects.create(
        decision=decision,
        requested_by=requested_by,
        payload_hash=decision.payload_hash,
        target_resource=decision.target_resource,
        policy_version=decision.policy_version,
        context_hash=decision.context_hash,
        expires_at=timezone.now() + timedelta(minutes=expires_in_minutes),
    )

    AuditEvent.objects.create(
        run=decision.invocation.step.run,
        actor=requested_by,
        event_type="APPROVAL_REQUESTED",
        correlation_id=decision.invocation.correlation_id,
        details={
            "approval_request_id": str(request.id),
            "decision_id": str(decision.id),
            "target_resource": request.target_resource,
            "expires_at": request.expires_at.isoformat(),
        },
    )

    return request


@transaction.atomic
def decide_approval(*, request_id, approver, approve, note=""):
    from django.db import transaction

    if not approver or not approver.is_authenticated:
        raise PermissionDenied("An authenticated approver is required.")

    if not approver.is_staff:
        raise PermissionDenied("Approver must have staff privileges.")

    with transaction.atomic():
        request = (
            ApprovalRequest.objects
            .select_for_update()
            .select_related("decision__invocation__step__run")
            .get(pk=request_id)
        )

        if approver.pk == request.requested_by_id:
            raise PermissionDenied("The requester cannot approve their own action.")

        if request.status != ApprovalStatus.PENDING:
            raise ValidationError("This approval request is no longer pending.")

        now = timezone.now()

        if now >= request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            request.decided_at = now
            request.save(update_fields=["status", "decided_at"])

            AuditEvent.objects.create(
                run=request.decision.invocation.step.run,
                actor=approver,
                event_type="APPROVAL_EXPIRED",
                correlation_id=request.decision.invocation.correlation_id,
                details={"approval_request_id": str(request.id)},
            )
            expired = True
        else:
            request.status = (
                ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
            )
            request.decided_by = approver
            request.decided_at = now
            request.decision_note = note[:300]
            request.save(
                update_fields=[
                    "status",
                    "decided_by",
                    "decided_at",
                    "decision_note",
                ]
            )

            AuditEvent.objects.create(
                run=request.decision.invocation.step.run,
                actor=approver,
                event_type="APPROVAL_DECIDED",
                correlation_id=request.decision.invocation.correlation_id,
                details={
                    "approval_request_id": str(request.id),
                    "status": request.status,
                    "note": request.decision_note,
                },
            )
            expired = False

    if expired:
        raise ValidationError("Approval request has expired.")

    refresh_step_lifecycle(
        step_id=request.decision.invocation.step_id,
        actor=approver,
    )
    return request


@transaction.atomic
def validate_approval_for_execution(
    *,
    request_id,
    payload,
    target_resource,
):
    request = (
        ApprovalRequest.objects
        .select_for_update()
        .select_related("decision__invocation__step__run")
        .get(pk=request_id)
    )

    decision = request.decision

    if request.status != ApprovalStatus.APPROVED:
        raise ValidationError("A valid approval is required.")

    if timezone.now() >= request.expires_at:
        request.status = ApprovalStatus.EXPIRED
        request.save(update_fields=["status"])
        raise ValidationError("Approval has expired.")

    if decision.status != PolicyDecisionStatus.REQUIRES_APPROVAL:
        raise ValidationError("The policy decision is not approval-gated.")

    if request.policy_version != POLICY_VERSION:
        raise ValidationError("The policy version has changed.")

    if decision.policy_version != POLICY_VERSION:
        raise ValidationError("The decision uses a stale policy version.")

    current_payload_hash = canonical_hash(payload)

    if current_payload_hash != request.payload_hash:
        raise ValidationError("The approved payload has changed.")

    if current_payload_hash != decision.payload_hash:
        raise ValidationError("The payload no longer matches the policy decision.")

    if target_resource != request.target_resource:
        raise ValidationError("The approved target resource has changed.")

    if target_resource != decision.target_resource:
        raise ValidationError("The target no longer matches the policy decision.")

    expected_context_hash = build_context_hash(
        actor_id=decision.actor_id,
        tool_name=decision.invocation.tool_name,
        target_resource=target_resource,
        policy_version=POLICY_VERSION,
    )

    if request.context_hash != expected_context_hash:
        raise ValidationError("The approval context has changed.")

    if decision.context_hash != expected_context_hash:
        raise ValidationError("The policy decision context has changed.")

    AuditEvent.objects.create(
        run=decision.invocation.step.run,
        actor=request.decided_by,
        event_type="APPROVAL_REVALIDATED",
        correlation_id=decision.invocation.correlation_id,
        details={
            "approval_request_id": str(request.id),
            "target_resource": target_resource,
            "policy_version": POLICY_VERSION,
        },
    )

    return True
