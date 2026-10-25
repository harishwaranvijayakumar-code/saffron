
import hmac

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from runs.dune_planner import DunePlanningError, generate_plan
from runs.forms import RunCreateForm
from runs.models import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    ExecutionStep,
    ToolInvocation,
)
from runs.plan_services import persist_plan
from runs.services import create_run


def home(request):
    return render(request, "home.html")


@login_required
def dashboard(request):
    runs = AgentRun.objects.filter(created_by=request.user)

    status_counts = {
        item["status"]: item["total"]
        for item in runs.values("status").annotate(total=Count("id"))
    }

    recent_runs = runs.order_by("-created_at")[:10]

    pending_approvals = ApprovalRequest.objects.filter(
        decision__invocation__step__run__created_by=request.user,
        status="PENDING",
    ).count()

    unresolved_outcomes = ToolInvocation.objects.filter(
        step__run__created_by=request.user,
        status="OUTCOME_UNKNOWN",
    ).count()

    return render(
        request,
        "runs/dashboard.html",
        {
            "recent_runs": recent_runs,
            "total_runs": sum(status_counts.values()),
            "status_counts": status_counts,
            "pending_approvals": pending_approvals,
            "unresolved_outcomes": unresolved_outcomes,
        },
    )


@login_required
def run_detail(request, run_id):
    run = get_object_or_404(
        AgentRun.objects.filter(created_by=request.user),
        id=run_id,
    )

    steps = ExecutionStep.objects.filter(run=run).order_by("sequence")

    invocations = (
        ToolInvocation.objects.filter(step__run=run)
        .select_related("step")
        .order_by("step__sequence", "created_at")
    )

    approvals = (
        ApprovalRequest.objects.filter(
            decision__invocation__step__run=run,
        )
        .select_related("decision", "requested_by", "decided_by")
        .order_by("-created_at")
    )

    audit_events = (
        AuditEvent.objects.filter(run=run)
        .select_related("actor")
        .order_by("-created_at")[:50]
    )

    return render(
        request,
        "runs/detail.html",
        {
            "run": run,
            "steps": steps,
            "invocations": invocations,
            "approvals": approvals,
            "audit_events": audit_events,
        },
    )


@login_required
def create_run_view(request):
    if request.method != "POST":
        return render(
            request,
            "runs/create.html",
            {"form": RunCreateForm()},
        )

    form = RunCreateForm(request.POST)

    if not form.is_valid():
        return render(request, "runs/create.html", {"form": form})

    objective = form.cleaned_data["objective"]
    budgets = {
        "max_steps": form.cleaned_data["max_steps"],
        "max_tool_invocations": form.cleaned_data[
            "max_tool_invocations"
        ],
        "max_runtime_seconds": form.cleaned_data[
            "max_runtime_seconds"
        ],
    }

    try:
        plan = generate_plan(
            objective=objective,
            max_steps=budgets["max_steps"],
            max_tool_invocations=budgets["max_tool_invocations"],
        )
    except DunePlanningError as exc:
        form.add_error(None, str(exc))
        return render(request, "runs/create.html", {"form": form})

    preview_data = {
        "objective": objective,
        "budgets": budgets,
        "plan": plan,
    }

    token = signing.dumps(
        preview_data,
        salt="saffron.dune-plan-preview",
    )
    request.session["dune_plan_token"] = token

    return render(
        request,
        "runs/plan_preview.html",
        {
            "objective": objective,
            "budgets": budgets,
            "plan": plan,
            "plan_token": token,
        },
    )


@transaction.atomic
def _create_run_with_plan(*, actor, data):
    run = create_run(
        actor=actor,
        objective=data["objective"],
        **data["budgets"],
    )

    persist_plan(
        run_id=run.id,
        actor=actor,
        plan=data["plan"],
    )

    return run


@login_required
def confirm_dune_plan_view(request):
    if request.method != "POST":
        return redirect("run-create")

    token = request.POST.get("plan_token", "")
    expected_token = request.session.get("dune_plan_token", "")

    if (
        not token
        or not expected_token
        or not hmac.compare_digest(token, expected_token)
    ):
        messages.error(
            request,
            "This plan preview is invalid or has expired. Generate it again.",
        )
        return redirect("run-create")

    try:
        data = signing.loads(
            token,
            salt="saffron.dune-plan-preview",
            max_age=600,
        )
    except signing.BadSignature:
        request.session.pop("dune_plan_token", None)
        messages.error(
            request,
            "This plan preview has expired. Generate it again.",
        )
        return redirect("run-create")

    # Prevent malformed signed data from causing unexpected errors.
    if (
        not isinstance(data, dict)
        or set(data) != {"objective", "budgets", "plan"}
        or not isinstance(data["objective"], str)
        or not isinstance(data["budgets"], dict)
        or set(data["budgets"]) != {
            "max_steps",
            "max_tool_invocations",
            "max_runtime_seconds",
        }
        or not isinstance(data["plan"], dict)
    ):
        request.session.pop("dune_plan_token", None)
        messages.error(
            request,
            "The plan preview is invalid. Generate it again.",
        )
        return redirect("run-create")

    try:
        run = _create_run_with_plan(actor=request.user, data=data)
    except (ValidationError, PermissionDenied):
        messages.error(
            request,
            "Saffron rejected this plan. Review the objective and generate "
            "a new plan before trying again.",
        )
        return redirect("run-create")

    request.session.pop("dune_plan_token", None)

    messages.success(
        request,
        "Plan accepted. Saffron persisted the steps; no tools have executed.",
    )

    return redirect("run-detail", run_id=run.id)
