
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from runs.approval_services import create_approval_request
from runs.execution_gateway import SIMULATED_TOOLS
from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    PolicyDecisionStatus,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
)
from runs.policy import (
    APPROVAL_REQUIRED_TOOLS,
    READ_ONLY_TOOLS,
    evaluate_tool_request,
)
from runs.step_lifecycle import refresh_step_lifecycle


TOOL_VERSION = "sim-v1"

TOOL_SIDE_EFFECTS = {
    **{
        name: SideEffectClass.READ_ONLY
        for name in READ_ONLY_TOOLS
    },
    **{
        name: SideEffectClass.IDEMPOTENT_WRITE
        for name in APPROVAL_REQUIRED_TOOLS
    },
}

STEP_KEYS = {
    "name",
    "tool_name",
    "target_resource",
    "payload",
}


def _validate_plan(plan, run):
    if not isinstance(plan, dict) or set(plan) != {"steps"}:
        raise ValidationError(
            "A plan must be an object containing only a 'steps' list."
        )

    steps = plan["steps"]

    if not isinstance(steps, list) or not steps:
        raise ValidationError("A plan must contain at least one step.")

    if len(steps) > run.max_steps:
        raise ValidationError("The plan exceeds the run's step budget.")

    if len(steps) > run.max_tool_invocations:
        raise ValidationError(
            "The plan exceeds the run's tool invocation budget."
        )

    normalized = []

    for index, item in enumerate(steps, start=1):
        if not isinstance(item, dict) or set(item) != STEP_KEYS:
            raise ValidationError(
                f"Step {index} must contain exactly: "
                "name, tool_name, target_resource, payload."
            )

        name = item["name"]
        tool_name = item["tool_name"]
        target = item["target_resource"]
        payload = item["payload"]

        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"Step {index} needs a name.")

        if len(name.strip()) > 200:
            raise ValidationError(
                f"Step {index} name must not exceed 200 characters."
            )

        if not isinstance(tool_name, str) or tool_name not in SIMULATED_TOOLS:
            raise ValidationError(
                f"Step {index} uses an unregistered tool."
            )

        if tool_name not in TOOL_SIDE_EFFECTS:
            raise ValidationError(
                f"Step {index} has no server-defined side-effect policy."
            )

        if not isinstance(target, str) or not target.strip():
            raise ValidationError(
                f"Step {index} needs a target resource."
            )

        if len(target.strip()) > 300:
            raise ValidationError(
                f"Step {index} target must not exceed 300 characters."
            )

        if not isinstance(payload, dict):
            raise ValidationError(
                f"Step {index} payload must be a JSON object."
            )

        try:
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise ValidationError(
                f"Step {index} payload must contain valid JSON values."
            ) from None

        _validate_tool_payload(index, tool_name, payload)

        normalized.append({
            "name": name.strip(),
            "tool_name": tool_name,
            "target_resource": target.strip(),
            "payload": payload,
            "side_effect_class": TOOL_SIDE_EFFECTS[tool_name],
        })

    return normalized


def _validate_tool_payload(index, tool_name, payload):
    if tool_name in {
        "github.get_workflow_run",
        "github.list_workflow_jobs",
    }:
        run_id = payload.get("workflow_run_id")

        if (
            isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id <= 0
        ):
            raise ValidationError(
                f"Step {index} requires a positive integer workflow_run_id."
            )

    elif tool_name == "github.create_issue_comment":
        issue_number = payload.get("issue_number")
        body = payload.get("body")

        if (
            isinstance(issue_number, bool)
            or not isinstance(issue_number, int)
            or issue_number <= 0
        ):
            raise ValidationError(
                f"Step {index} requires a positive integer issue_number."
            )

        if not isinstance(body, str) or not body.strip():
            raise ValidationError(
                f"Step {index} requires a non-empty comment body."
            )


@transaction.atomic
def persist_plan(*, run_id, actor, plan):
    """Validate and persist a plan without executing any tools."""
    if actor is None or not actor.is_authenticated:
        raise PermissionDenied("An authenticated actor is required.")

    run = (
        AgentRun.objects
        .select_for_update()
        .get(pk=run_id)
    )

    if run.created_by_id != actor.pk:
        raise PermissionDenied("Actor does not own this run.")

    if run.status != RunStatus.QUEUED:
        raise ValidationError("A plan can only be added to a queued run.")

    if run.steps.exists():
        raise ValidationError("This run already has a persisted plan.")

    steps = _validate_plan(plan, run)

    created_steps = []

    for sequence, item in enumerate(steps, start=1):
        step = ExecutionStep.objects.create(
            run=run,
            sequence=sequence,
            name=item["name"],
            input_summary={
                "tool_name": item["tool_name"],
                "target_resource": item["target_resource"],
            },
        )

        invocation = ToolInvocation.objects.create(
            step=step,
            tool_name=item["tool_name"],
            tool_version=TOOL_VERSION,
            side_effect_class=item["side_effect_class"],
            request_summary={
                "target_resource": item["target_resource"],
            },
            request_payload={},
        )

        decision = evaluate_tool_request(
            invocation_id=invocation.id,
            actor=actor,
            payload=item["payload"],
            target_resource=item["target_resource"],
        )

        if decision.status == PolicyDecisionStatus.REQUIRES_APPROVAL:
            create_approval_request(
                decision_id=decision.id,
                requested_by=actor,
                payload=item["payload"],
                target_resource=item["target_resource"],
            )

        created_steps.append(step)

    created_steps = [
        refresh_step_lifecycle(step_id=step.id, actor=actor)
        for step in created_steps
    ]

    AuditEvent.objects.create(
        run=run,
        actor=actor,
        event_type="PLAN_PERSISTED",
        state_version=run.state_version,
        details={
            "step_count": len(created_steps),
            "invocation_count": len(created_steps),
            "policy_evaluated": True,
            "execution_started": False,
        },
    )

    return created_steps
