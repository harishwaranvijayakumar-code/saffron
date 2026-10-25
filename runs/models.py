import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RunStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    RUNNING = "RUNNING", "Running"
    WAITING_APPROVAL = "WAITING_APPROVAL", "Waiting for approval"
    RECOVERING = "RECOVERING", "Recovering"
    RECONCILING = "RECONCILING", "Reconciling"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN", "Outcome unknown"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


TERMINAL_STATES = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}

ALLOWED_TRANSITIONS = {
    RunStatus.QUEUED: {
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
    },
    RunStatus.RUNNING: {
        RunStatus.WAITING_APPROVAL,
        RunStatus.RECOVERING,
        RunStatus.RECONCILING,
        RunStatus.OUTCOME_UNKNOWN,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.WAITING_APPROVAL: {
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
    },
    RunStatus.RECOVERING: {
        RunStatus.RUNNING,
        RunStatus.RECONCILING,
        RunStatus.OUTCOME_UNKNOWN,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.RECONCILING: {
        RunStatus.RUNNING,
        RunStatus.OUTCOME_UNKNOWN,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.OUTCOME_UNKNOWN: {
        RunStatus.RECONCILING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class AgentRun(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="agent_runs",
    )
    status = models.CharField(
        max_length=32,
        choices=RunStatus.choices,
        default=RunStatus.QUEUED,
        db_index=True,
    )
    objective = models.CharField(max_length=500)
    state_version = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    max_steps = models.PositiveIntegerField(default=20)
    max_tool_invocations = models.PositiveIntegerField(default=50)
    max_runtime_seconds = models.PositiveIntegerField(default=900)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.id} ({self.status})"

    def transition_to(self, new_status):
        if new_status not in RunStatus.values:
            raise ValidationError("Unknown run state.")

        if new_status == self.status:
            raise ValidationError("Run is already in that state.")

        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise ValidationError(
                f"Invalid run transition: {self.status} -> {new_status}"
            )

        self.status = new_status
        self.state_version += 1

    def clean(self):
        super().clean()

        if self.status in TERMINAL_STATES and not self.finished_at:
            raise ValidationError(
                {"finished_at": "Terminal runs require a finish timestamp."}
            )


class ExecutionStepStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    WAITING_APPROVAL = "WAITING_APPROVAL", "Waiting for approval"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN", "Outcome unknown"
    CANCELLED = "CANCELLED", "Cancelled"


class ExecutionStep(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.PROTECT,
        related_name="steps",
    )
    sequence = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=32,
        choices=ExecutionStepStatus.choices,
        default=ExecutionStepStatus.PENDING,
    )
    input_summary = models.JSONField(default=dict, blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"],
                name="unique_run_step_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.run_id}: step {self.sequence} ({self.name})"


class ToolInvocationStatus(models.TextChoices):
    RECORDED = "RECORDED", "Recorded"
    AUTHORIZED = "AUTHORIZED", "Authorized"
    DENIED = "DENIED", "Denied"
    STARTED = "STARTED", "Started"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN", "Outcome unknown"


class SideEffectClass(models.TextChoices):
    READ_ONLY = "READ_ONLY", "Read only"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE", "Idempotent write"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE", "Non-idempotent write"
    UNKNOWN = "UNKNOWN", "Unknown"


class ToolInvocation(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    step = models.ForeignKey(
        ExecutionStep,
        on_delete=models.PROTECT,
        related_name="tool_invocations",
    )
    tool_name = models.CharField(max_length=100)
    tool_version = models.CharField(max_length=50)
    attempt_number = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=200, blank=True)
    side_effect_class = models.CharField(
        max_length=32,
        choices=SideEffectClass.choices,
        default=SideEffectClass.UNKNOWN,
    )
    status = models.CharField(
        max_length=32,
        choices=ToolInvocationStatus.choices,
        default=ToolInvocationStatus.RECORDED,
    )
    request_summary = models.JSONField(default=dict, blank=True)
    response_summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    lease_owner = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    request_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["step", "attempt_number"],
                name="unique_step_tool_attempt",
            ),
        ]

    def __str__(self):
        return f"{self.tool_name} attempt {self.attempt_number}"


class AuditEvent(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="saffron_audit_events",
    )
    event_type = models.CharField(max_length=100)
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    state_version = models.PositiveBigIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["run", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} ({self.run_id})"


class PolicyDecisionStatus(models.TextChoices):
    ALLOW = "ALLOW", "Allowed"
    DENY = "DENY", "Denied"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL", "Requires approval"


class PolicyDecision(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    invocation = models.OneToOneField(
        ToolInvocation,
        on_delete=models.PROTECT,
        related_name="policy_decision",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="policy_decisions",
    )
    status = models.CharField(
        max_length=32,
        choices=PolicyDecisionStatus.choices,
    )
    reason = models.CharField(max_length=300)
    policy_version = models.CharField(max_length=50)
    payload_hash = models.CharField(max_length=64)
    target_resource = models.CharField(max_length=300)
    context_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"


class ApprovalRequest(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    decision = models.OneToOneField(
        PolicyDecision,
        on_delete=models.PROTECT,
        related_name="approval_request",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_tool_approvals",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decided_tool_approvals",
    )
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    payload_hash = models.CharField(max_length=64)
    target_resource = models.CharField(max_length=300)
    policy_version = models.CharField(max_length=50)
    context_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ReconciliationOutcome(models.TextChoices):
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    INCONCLUSIVE = "INCONCLUSIVE", "Inconclusive"


class ReconciliationEvidence(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    invocation = models.ForeignKey(
        ToolInvocation,
        on_delete=models.PROTECT,
        related_name="reconciliation_evidence",
    )
    outcome = models.CharField(
        max_length=20,
        choices=ReconciliationOutcome.choices,
    )
    source = models.CharField(max_length=100)
    external_reference = models.CharField(max_length=300, blank=True)
    details = models.JSONField(default=dict, blank=True)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at", "-recorded_at"]
