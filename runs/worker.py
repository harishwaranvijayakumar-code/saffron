
import uuid

from django.core.exceptions import ValidationError
from django.utils import timezone

from runs.budgets import enforce_run_budget
from runs.execution_gateway import execute_simulated_tool
from runs.leases import claim_invocation_lease
from runs.models import (
    ApprovalRequest,
    ApprovalStatus,
    PolicyDecision,
    PolicyDecisionStatus,
    RunStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.step_lifecycle import refresh_step_lifecycle


MAX_CANDIDATES_PER_POLL = 50
LEASE_DURATION_SECONDS = 60


def _is_eligible(invocation, now):
    if invocation.step.run.status != RunStatus.RUNNING:
        return False

    decision = PolicyDecision.objects.filter(
        invocation_id=invocation.id
    ).first()
    if decision is None:
        return False

    if decision.status == PolicyDecisionStatus.ALLOW:
        return invocation.status == ToolInvocationStatus.AUTHORIZED

    if decision.status != PolicyDecisionStatus.REQUIRES_APPROVAL:
        return False

    if invocation.status != ToolInvocationStatus.RECORDED:
        return False

    approval = ApprovalRequest.objects.filter(
        decision_id=decision.id
    ).first()
    if approval is None:
        return False

    return bool(
        approval.status == ApprovalStatus.APPROVED
        and approval.expires_at > now
        and approval.decided_at is not None
        and approval.decided_by_id is not None
        and approval.decided_by_id != approval.requested_by_id
        and approval.payload_hash == decision.payload_hash
        and approval.target_resource == decision.target_resource
        and approval.policy_version == decision.policy_version
        and approval.context_hash == decision.context_hash
    )


def process_next_invocation(*, worker_id=None):
    """Process at most one eligible simulated tool invocation."""
    worker_id = worker_id or uuid.uuid4()
    now = timezone.now()

    candidate_ids = list(
        ToolInvocation.objects.filter(
            status__in=[
                ToolInvocationStatus.RECORDED,
                ToolInvocationStatus.AUTHORIZED,
            ],
            step__run__status=RunStatus.RUNNING,
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:MAX_CANDIDATES_PER_POLL]
    )

    for invocation_id in candidate_ids:
        invocation = (
            ToolInvocation.objects
            .select_related("step__run__created_by")
            .filter(pk=invocation_id)
            .first()
        )
        if invocation is None:
            continue

        budget_reason = enforce_run_budget(invocation.step.run_id)
        if budget_reason is not None:
            continue

        invocation.refresh_from_db()
        invocation.step.run.refresh_from_db()

        if not _is_eligible(invocation, now):
            continue

        try:
            lease = claim_invocation_lease(
                invocation_id=invocation_id,
                worker_id=worker_id,
                lease_seconds=LEASE_DURATION_SECONDS,
            )
        except ValidationError:
            continue

        invocation.refresh_from_db()
        invocation.step.run.refresh_from_db()

        decision = PolicyDecision.objects.filter(
            invocation_id=invocation.id
        ).first()
        if decision is None:
            return {
                "worker_id": str(worker_id),
                "invocation_id": str(invocation.id),
                "status": "BLOCKED",
                "reason": "Policy decision not found after lease claim.",
            }

        try:
            result = execute_simulated_tool(
                invocation_id=invocation.id,
                actor=invocation.step.run.created_by,
                payload=invocation.request_payload,
                target_resource=decision.target_resource,
                worker_id=worker_id,
                fencing_token=lease["fencing_token"],
            )
        except Exception as exc:
            invocation.refresh_from_db()
            step = refresh_step_lifecycle(
                step_id=invocation.step_id,
                actor=invocation.step.run.created_by,
            )
            return {
                "worker_id": str(worker_id),
                "invocation_id": str(invocation.id),
                "status": invocation.status,
                "step_status": step.status,
                "error_type": type(exc).__name__,
            }

        invocation.refresh_from_db()
        step = refresh_step_lifecycle(
            step_id=invocation.step_id,
            actor=invocation.step.run.created_by,
        )

        return {
            "worker_id": str(worker_id),
            "invocation_id": str(invocation.id),
            "status": invocation.status,
            "step_status": step.status,
            "result": result,
        }

    return {
        "worker_id": str(worker_id),
        "status": "IDLE",
    }
