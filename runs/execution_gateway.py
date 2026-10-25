import os
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from runs.github_adapter import (
    GitHubAdapterError,
    get_workflow_run,
    list_workflow_jobs,
)
from runs.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEvent,
    PolicyDecisionStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.policy import (
    POLICY_VERSION,
    build_context_hash,
    canonical_hash,
)


@dataclass(frozen=True)
class SimulatedResult:
    summary: dict


class SimulatedToolError(Exception):
    """A definitive simulated tool failure."""


def _simulate_get_workflow_run(payload, target_resource):
    if "workflow_run_id" not in payload:
        raise SimulatedToolError("workflow_run_id is required")

    return SimulatedResult({
        "simulated": True,
        "workflow_run_id": payload["workflow_run_id"],
        "target_resource": target_resource,
        "conclusion": "failure",
    })


def _simulate_list_workflow_jobs(payload, target_resource):
    if "workflow_run_id" not in payload:
        raise SimulatedToolError("workflow_run_id is required")

    return SimulatedResult({
        "simulated": True,
        "workflow_run_id": payload["workflow_run_id"],
        "target_resource": target_resource,
        "jobs": [],
    })


def _simulate_create_issue_comment(payload, target_resource):
    if "issue_number" not in payload or "body" not in payload:
        raise SimulatedToolError(
            "issue_number and body are required"
        )

    # Simulation only. No external API call is performed.
    return SimulatedResult({
        "simulated": True,
        "created": True,
        "issue_number": payload["issue_number"],
        "target_resource": target_resource,
    })


SIMULATED_TOOLS = {
    "github.get_workflow_run": _simulate_get_workflow_run,
    "github.list_workflow_jobs": _simulate_list_workflow_jobs,
    "github.create_issue_comment": _simulate_create_issue_comment,
}

REAL_READ_ONLY_TOOLS = {
    "github.get_workflow_run": get_workflow_run,
    "github.list_workflow_jobs": list_workflow_jobs,
}

READ_ONLY_TOOLS = {
    "github.get_workflow_run",
    "github.list_workflow_jobs",
}

APPROVAL_REQUIRED_TOOLS = {
    "github.create_issue_comment",
}


def _real_github_reads_enabled():
    """Enable live GitHub reads only through explicit configuration."""
    return os.getenv(
        "SAFFRON_ENABLE_REAL_GITHUB_READS", "false"
    ).strip().lower() in {"1", "true", "yes"}


def _uses_real_github_read(tool_name):
    """Return whether this tool is currently configured for a real read."""
    return (
        tool_name in REAL_READ_ONLY_TOOLS
        and _real_github_reads_enabled()
    )


def _validate_lease(invocation, *, worker_id, fencing_token):
    now = timezone.now()

    if invocation.lease_owner != worker_id:
        raise ValidationError("Worker does not own this lease.")

    if invocation.fencing_token != fencing_token:
        raise ValidationError("Stale fencing token.")

    if (
        invocation.lease_expires_at is None
        or invocation.lease_expires_at <= now
    ):
        raise ValidationError("Worker lease has expired.")

    if invocation.heartbeat_at is None:
        raise ValidationError("Lease heartbeat is missing.")


def _claim_invocation(
    *,
    invocation_id,
    actor,
    payload,
    target_resource,
    worker_id,
    fencing_token,
):
    with transaction.atomic():
        invocation = (
            ToolInvocation.objects
            .select_for_update()
            .select_related("step__run")
            .get(pk=invocation_id)
        )
        run = invocation.step.run

        if not actor or not actor.is_authenticated:
            raise PermissionDenied("An authenticated actor is required.")

        if run.created_by_id != actor.pk:
            raise PermissionDenied("Actor does not own this run.")

        if run.status != RunStatus.RUNNING:
            raise ValidationError(
                "The run must be RUNNING to dispatch a tool."
            )

        if invocation.status not in {
            ToolInvocationStatus.RECORDED,
            ToolInvocationStatus.AUTHORIZED,
        }:
            raise ValidationError(
                "This invocation is not eligible for dispatch."
            )

        _validate_lease(
            invocation,
            worker_id=worker_id,
            fencing_token=fencing_token,
        )

        # The simulator registry defines the complete supported tool set.
        if invocation.tool_name not in SIMULATED_TOOLS:
            raise PermissionDenied("Tool is not registered.")

        if invocation.side_effect_class == SideEffectClass.UNKNOWN:
            raise PermissionDenied(
                "Unknown side-effect classifications are denied."
            )

        if invocation.tool_name in READ_ONLY_TOOLS:
            if invocation.side_effect_class != SideEffectClass.READ_ONLY:
                raise PermissionDenied(
                    "Tool registration and side-effect classification disagree."
                )
        elif invocation.tool_name in APPROVAL_REQUIRED_TOOLS:
            if invocation.side_effect_class not in {
                SideEffectClass.IDEMPOTENT_WRITE,
                SideEffectClass.NON_IDEMPOTENT_WRITE,
            }:
                raise PermissionDenied(
                    "Write tool has an invalid side-effect classification."
                )
        else:
            raise PermissionDenied("Tool is not allowlisted.")

        try:
            decision = invocation.policy_decision
        except Exception as exc:
            raise PermissionDenied(
                "A recorded policy decision is required."
            ) from exc

        if decision.actor_id != actor.pk:
            raise PermissionDenied(
                "Policy decision belongs to another actor."
            )

        if decision.policy_version != POLICY_VERSION:
            raise PermissionDenied(
                "Policy decision uses a stale policy version."
            )

        if decision.payload_hash != canonical_hash(payload):
            raise ValidationError(
                "Payload differs from the evaluated request."
            )

        if decision.target_resource != target_resource:
            raise ValidationError(
                "Target differs from the evaluated request."
            )

        expected_context = build_context_hash(
            actor_id=actor.pk,
            tool_name=invocation.tool_name,
            target_resource=target_resource,
            policy_version=POLICY_VERSION,
        )

        if decision.context_hash != expected_context:
            raise ValidationError(
                "Policy context does not match the request."
            )

        if decision.status == PolicyDecisionStatus.DENY:
            raise PermissionDenied("Policy denied this operation.")

        if decision.status == PolicyDecisionStatus.ALLOW:
            if invocation.status != ToolInvocationStatus.AUTHORIZED:
                raise PermissionDenied(
                    "Invocation is not authorized."
                )

            if invocation.tool_name not in READ_ONLY_TOOLS:
                raise PermissionDenied(
                    "This policy decision cannot authorize a write tool."
                )

        elif decision.status == PolicyDecisionStatus.REQUIRES_APPROVAL:
            if invocation.tool_name not in APPROVAL_REQUIRED_TOOLS:
                raise PermissionDenied(
                    "This tool is not configured for approval-gated dispatch."
                )

            approval = (
                ApprovalRequest.objects
                .select_for_update()
                .filter(decision=decision)
                .first()
            )

            if (
                approval is None
                or approval.status != ApprovalStatus.APPROVED
            ):
                raise PermissionDenied("A valid approval is required.")

            if timezone.now() >= approval.expires_at:
                raise PermissionDenied("Approval has expired.")

            if approval.decided_by_id is None:
                raise PermissionDenied(
                    "Approval has no recorded approver."
                )

            if approval.decided_by_id == approval.requested_by_id:
                raise PermissionDenied(
                    "Self-approval is not permitted."
                )

            if approval.policy_version != POLICY_VERSION:
                raise PermissionDenied(
                    "Approval uses a stale policy version."
                )

            if approval.payload_hash != canonical_hash(payload):
                raise ValidationError(
                    "Approved payload has changed."
                )

            if approval.payload_hash != decision.payload_hash:
                raise ValidationError(
                    "Approved payload differs from the policy decision."
                )

            if approval.target_resource != target_resource:
                raise ValidationError(
                    "Approved target has changed."
                )

            if approval.context_hash != expected_context:
                raise ValidationError(
                    "Approved context has changed."
                )

            if decision.status != PolicyDecisionStatus.REQUIRES_APPROVAL:
                raise PermissionDenied(
                    "Decision is not approval-gated."
                )

        else:
            raise PermissionDenied("Unrecognized policy decision.")

        # Claim the invocation before making any external request.
        invocation.status = ToolInvocationStatus.STARTED
        invocation.started_at = timezone.now()
        invocation.save(update_fields=["status", "started_at"])

        AuditEvent.objects.create(
            run=run,
            actor=actor,
            event_type="TOOL_DISPATCH_STARTED",
            correlation_id=invocation.correlation_id,
            details={
                "invocation_id": str(invocation.id),
                "tool_name": invocation.tool_name,
                "target_resource": target_resource,
                "worker_id": str(worker_id),
                "fencing_token": fencing_token,
                "simulated": not _uses_real_github_read(
                    invocation.tool_name
                ),
            },
        )

        return invocation.id, invocation.tool_name


def execute_simulated_tool(
    *,
    invocation_id,
    actor,
    payload,
    target_resource,
    worker_id,
    fencing_token,
):
    """
    Dispatch an authorized invocation through the configured adapter.

    Real GitHub access is limited to registered read-only tools and is
    disabled unless SAFFRON_ENABLE_REAL_GITHUB_READS is explicitly enabled.
    Write tools always remain simulated.
    """
    claimed_id, tool_name = _claim_invocation(
        invocation_id=invocation_id,
        actor=actor,
        payload=payload,
        target_resource=target_resource,
        worker_id=worker_id,
        fencing_token=fencing_token,
    )

    try:
        if _uses_real_github_read(tool_name):
            response_summary = REAL_READ_ONLY_TOOLS[tool_name](
                payload,
                target_resource,
            )
        elif tool_name in SIMULATED_TOOLS:
            result = SIMULATED_TOOLS[tool_name](
                payload,
                target_resource,
            )
            response_summary = result.summary
        else:
            # Defensive default-deny guard.
            raise PermissionDenied("Tool is not registered.")

        if not isinstance(response_summary, dict):
            raise TypeError(
                "Tool adapter returned an invalid response type."
            )

    except GitHubAdapterError as exc:
        # Persist only the adapter's stable, sanitized error code.
        _finish_invocation(
            invocation_id=claimed_id,
            actor=actor,
            status=ToolInvocationStatus.FAILED,
            worker_id=worker_id,
            fencing_token=fencing_token,
            error_code=exc.code[:100],
        )
        raise ValidationError({
            "detail": "GitHub read request failed.",
            "code": exc.code,
        }) from None

    except SimulatedToolError as exc:
        _finish_invocation(
            invocation_id=claimed_id,
            actor=actor,
            status=ToolInvocationStatus.FAILED,
            worker_id=worker_id,
            fencing_token=fencing_token,
            error_code=str(exc)[:100],
        )
        raise ValidationError(
            "Simulated tool failed validation."
        ) from exc

    except Exception:
        # The external operation's outcome may be uncertain after an
        # unexpected failure. Never record it as a definite success.
        _finish_invocation(
            invocation_id=claimed_id,
            actor=actor,
            status=ToolInvocationStatus.OUTCOME_UNKNOWN,
            worker_id=worker_id,
            fencing_token=fencing_token,
            error_code="UNEXPECTED_ADAPTER_ERROR",
        )
        raise

    _finish_invocation(
        invocation_id=claimed_id,
        actor=actor,
        status=ToolInvocationStatus.SUCCEEDED,
        worker_id=worker_id,
        fencing_token=fencing_token,
        response_summary=response_summary,
    )

    return response_summary


@transaction.atomic
def _finish_invocation(
    *,
    invocation_id,
    actor,
    status,
    worker_id,
    fencing_token,
    response_summary=None,
    error_code="",
):
    invocation = (
        ToolInvocation.objects
        .select_for_update()
        .select_related("step__run")
        .get(pk=invocation_id)
    )

    _validate_lease(
        invocation,
        worker_id=worker_id,
        fencing_token=fencing_token,
    )

    if invocation.status != ToolInvocationStatus.STARTED:
        raise ValidationError(
            "Invocation is no longer in the expected STARTED state."
        )

    allowed_final_statuses = {
        ToolInvocationStatus.SUCCEEDED,
        ToolInvocationStatus.FAILED,
        ToolInvocationStatus.OUTCOME_UNKNOWN,
    }
    if status not in allowed_final_statuses:
        raise ValidationError("Invalid final invocation status.")

    invocation.status = status
    invocation.finished_at = timezone.now()
    invocation.response_summary = response_summary or {}
    invocation.error_code = error_code

    # Release lease ownership when finalizing the invocation.
    invocation.lease_owner = None
    invocation.lease_expires_at = None

    invocation.save(
        update_fields=[
            "status",
            "finished_at",
            "response_summary",
            "error_code",
            "lease_owner",
            "lease_expires_at",
        ]
    )

    AuditEvent.objects.create(
        run=invocation.step.run,
        actor=actor,
        event_type="TOOL_DISPATCH_FINISHED",
        correlation_id=invocation.correlation_id,
        details={
            "invocation_id": str(invocation.id),
            "status": status,
            "error_code": error_code,
            "fencing_token": fencing_token,
        },
    )
