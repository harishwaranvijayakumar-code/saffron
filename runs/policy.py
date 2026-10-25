import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction

from runs.models import (
    AuditEvent,
    PolicyDecision,
    PolicyDecisionStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)


POLICY_VERSION = "saffron-policy-v1"

READ_ONLY_TOOLS = {
    "github.get_workflow_run",
    "github.list_workflow_jobs",
}

APPROVAL_REQUIRED_TOOLS = {
    "github.create_issue_comment",
}


def canonical_hash(value):
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_context_hash(
    *,
    actor_id,
    tool_name,
    target_resource,
    policy_version,
):
    return canonical_hash({
        "actor_id": str(actor_id),
        "tool_name": tool_name,
        "target_resource": target_resource,
        "policy_version": policy_version,
    })


@transaction.atomic
def evaluate_tool_request(
    *,
    invocation_id,
    actor,
    payload,
    target_resource,
):
    invocation = (
        ToolInvocation.objects
        .select_for_update()
        .select_related("step__run")
        .get(pk=invocation_id)
    )

    if not actor or not actor.is_authenticated:
        raise ValidationError("An authenticated actor is required.")

    if invocation.step.run.created_by_id != actor.pk:
        raise ValidationError("Actor is not authorized for this run.")

    if PolicyDecision.objects.filter(invocation=invocation).exists():
        raise ValidationError(
            "A policy decision already exists for this invocation."
        )

    if not isinstance(payload, dict):
        raise ValidationError("The tool payload must be a JSON object.")

    if not isinstance(target_resource, str) or not target_resource.strip():
        raise ValidationError("A target resource is required.")

    payload_hash = canonical_hash(payload)
    context_hash = build_context_hash(
        actor_id=actor.pk,
        tool_name=invocation.tool_name,
        target_resource=target_resource,
        policy_version=POLICY_VERSION,
    )

    if invocation.tool_name in READ_ONLY_TOOLS:
        if invocation.side_effect_class != SideEffectClass.READ_ONLY:
            status = PolicyDecisionStatus.DENY
            reason = "Tool side-effect classification does not match policy."
        else:
            status = PolicyDecisionStatus.ALLOW
            reason = "Tool is allowlisted as read-only."

    elif invocation.tool_name in APPROVAL_REQUIRED_TOOLS:
        if invocation.side_effect_class not in {
            SideEffectClass.IDEMPOTENT_WRITE,
            SideEffectClass.NON_IDEMPOTENT_WRITE,
        }:
            status = PolicyDecisionStatus.DENY
            reason = "Write tool has an invalid side-effect classification."
        else:
            status = PolicyDecisionStatus.REQUIRES_APPROVAL
            reason = "A separate human approval is required."

    else:
        status = PolicyDecisionStatus.DENY
        reason = "Tool is not allowlisted."

    decision = PolicyDecision.objects.create(
        invocation=invocation,
        actor=actor,
        status=status,
        reason=reason,
        policy_version=POLICY_VERSION,
        payload_hash=payload_hash,
        target_resource=target_resource,
        context_hash=context_hash,
    )

    # Only non-secret simulator input should be stored here.
    invocation.request_payload = payload

    if status == PolicyDecisionStatus.ALLOW:
        invocation.status = ToolInvocationStatus.AUTHORIZED
    elif status == PolicyDecisionStatus.DENY:
        invocation.status = ToolInvocationStatus.DENIED

    invocation.save(update_fields=["request_payload", "status"])

    AuditEvent.objects.create(
        run=invocation.step.run,
        actor=actor,
        event_type="TOOL_POLICY_DECISION",
        correlation_id=invocation.correlation_id,
        details={
            "invocation_id": str(invocation.id),
            "decision_id": str(decision.id),
            "status": status,
            "reason": reason,
            "policy_version": POLICY_VERSION,
            "target_resource": target_resource,
            "payload_hash": payload_hash,
        },
    )

    return decision
