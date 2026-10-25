from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.utils import timezone

from runs.leases import claim_invocation_lease
from runs.models import (
    AgentRun,
    AuditEvent,
    ExecutionStep,
    ReconciliationEvidence,
    ReconciliationOutcome,
    RunStatus,
    SideEffectClass,
    ToolInvocation,
    ToolInvocationStatus,
)
from runs.policy import evaluate_tool_request
from runs.recovery import (
    reconcile_invocation,
    recover_stale_invocations,
)
from runs.services import transition_run


@pytest.fixture
def recovery_action(db):
    user = get_user_model().objects.create_user(
        username="recovery-test-user",
        password="test-only-password",
    )

    run = AgentRun.objects.create(
        created_by=user,
        objective="Investigate a workflow interruption",
    )
    transition_run(
        run.id,
        expected_version=0,
        new_status=RunStatus.RUNNING,
        actor=user,
    )

    step = ExecutionStep.objects.create(
        run=run,
        sequence=1,
        name="Inspect workflow",
    )

    invocation = ToolInvocation.objects.create(
        step=step,
        tool_name="github.get_workflow_run",
        tool_version="1",
        side_effect_class=SideEffectClass.READ_ONLY,
    )

    payload = {"workflow_run_id": 456}
    target = "repository:example/project/actions/runs/456"

    evaluate_tool_request(
        invocation_id=invocation.id,
        actor=user,
        payload=payload,
        target_resource=target,
    )

    invocation.refresh_from_db()

    return {
        "user": user,
        "run": run,
        "step": step,
        "invocation": invocation,
        "payload": payload,
        "target": target,
    }


@pytest.mark.django_db
def test_stale_started_invocation_becomes_unknown(recovery_action):
    data = recovery_action
    invocation = data["invocation"]

    invocation.status = ToolInvocationStatus.STARTED
    invocation.started_at = timezone.now() - timedelta(hours=1)
    invocation.save(update_fields=["status", "started_at"])

    recovered = recover_stale_invocations(
        stale_before=timezone.now() - timedelta(minutes=10),
    )

    invocation.refresh_from_db()

    assert invocation.id in recovered
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN
    assert invocation.error_code == "WORKER_INTERRUPTED"
    assert AuditEvent.objects.filter(
        run=data["run"],
        event_type="INVOCATION_RECOVERY_REQUIRED",
    ).exists()


@pytest.mark.django_db
def test_fresh_started_invocation_is_not_recovered(recovery_action):
    invocation = recovery_action["invocation"]

    invocation.status = ToolInvocationStatus.STARTED
    invocation.started_at = timezone.now()
    invocation.save(update_fields=["status", "started_at"])

    recovered = recover_stale_invocations(
        stale_before=timezone.now() - timedelta(minutes=10),
    )

    invocation.refresh_from_db()

    assert invocation.id not in recovered
    assert invocation.status == ToolInvocationStatus.STARTED


@pytest.mark.django_db
def test_success_evidence_resolves_unknown_invocation(recovery_action):
    invocation = recovery_action["invocation"]

    invocation.status = ToolInvocationStatus.OUTCOME_UNKNOWN
    invocation.error_code = "WORKER_INTERRUPTED"
    invocation.finished_at = timezone.now()
    invocation.save(
        update_fields=["status", "error_code", "finished_at"]
    )

    evidence = reconcile_invocation(
        invocation_id=invocation.id,
        outcome=ReconciliationOutcome.SUCCEEDED,
        source="simulator.inspect_result",
        external_reference="simulation-456",
        details={"observed": "completed"},
    )

    invocation.refresh_from_db()

    assert evidence.outcome == ReconciliationOutcome.SUCCEEDED
    assert invocation.status == ToolInvocationStatus.SUCCEEDED
    assert invocation.error_code == ""
    assert ReconciliationEvidence.objects.filter(
        invocation=invocation,
    ).exists()


@pytest.mark.django_db
def test_failure_evidence_resolves_unknown_invocation(recovery_action):
    invocation = recovery_action["invocation"]
    invocation.status = ToolInvocationStatus.OUTCOME_UNKNOWN
    invocation.save(update_fields=["status"])

    reconcile_invocation(
        invocation_id=invocation.id,
        outcome=ReconciliationOutcome.FAILED,
        source="simulator.inspect_result",
        details={"observed": "definitive_failure"},
    )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.FAILED


@pytest.mark.django_db
def test_inconclusive_evidence_preserves_unknown(recovery_action):
    invocation = recovery_action["invocation"]
    invocation.status = ToolInvocationStatus.OUTCOME_UNKNOWN
    invocation.save(update_fields=["status"])

    reconcile_invocation(
        invocation_id=invocation.id,
        outcome=ReconciliationOutcome.INCONCLUSIVE,
        source="simulator.inspect_result",
        details={"observed": "not_enough_information"},
    )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db
def test_completed_invocation_cannot_be_reconciled_again(recovery_action):
    invocation = recovery_action["invocation"]
    invocation.status = ToolInvocationStatus.SUCCEEDED
    invocation.save(update_fields=["status"])

    with pytest.raises(ValidationError):
        reconcile_invocation(
            invocation_id=invocation.id,
            outcome=ReconciliationOutcome.FAILED,
            source="simulator.inspect_result",
        )


@pytest.mark.django_db
def test_recovery_prevents_stale_worker_from_finalizing(recovery_action):
    from runs.execution_gateway import _finish_invocation

    data = recovery_action
    invocation = data["invocation"]

    worker_id = uuid.uuid4()
    lease = claim_invocation_lease(
        invocation_id=invocation.id,
        worker_id=worker_id,
    )

    invocation.refresh_from_db()
    invocation.status = ToolInvocationStatus.STARTED
    invocation.started_at = timezone.now() - timedelta(hours=1)
    invocation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    invocation.save(
        update_fields=[
            "status",
            "started_at",
            "lease_expires_at",
        ]
    )

    recover_stale_invocations(
        stale_before=timezone.now() - timedelta(minutes=10),
    )

    with pytest.raises(ValidationError):
        _finish_invocation(
            invocation_id=invocation.id,
            actor=data["user"],
            status=ToolInvocationStatus.SUCCEEDED,
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            response_summary={"simulated": True},
        )

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db(transaction=True)
def test_competing_recovery_workers_do_not_return_same_claim(recovery_action):
    data = recovery_action
    invocation = data["invocation"]

    invocation.status = ToolInvocationStatus.STARTED
    invocation.started_at = timezone.now() - timedelta(hours=1)
    invocation.save(update_fields=["status", "started_at"])

    cutoff = timezone.now() - timedelta(minutes=10)

    def recover():
        close_old_connections()
        try:
            return recover_stale_invocations(stale_before=cutoff)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(recover) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    all_ids = [item for batch in results for item in batch]

    assert all_ids.count(invocation.id) <= 1

    invocation.refresh_from_db()
    assert invocation.status == ToolInvocationStatus.OUTCOME_UNKNOWN
