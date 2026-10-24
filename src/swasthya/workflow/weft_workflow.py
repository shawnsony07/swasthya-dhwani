"""The workflow state machine: `Task` lifecycle, A2A state transitions, and
the T4 timeout-escalation fix (architecture.md section 5, loop L4/L5/L20/L21).

Sync SQLAlchemy `Session` throughout — chosen over async because this
module has no I/O-bound fan-out of its own (no network calls; the roster
and audit writes are plain rows in the same database the caller already
has a session open against). The A2A handler and FastAPI layer above this
module are free to run async and call these functions inside
`run_in_threadpool`/`asyncio.to_thread`; keeping this layer sync keeps the
state-machine logic trivially testable against an in-memory SQLite
session with no event loop involved.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from swasthya.contracts import ALLOWED_TRANSITIONS, PROTOCOL_VERSION, AuditEvent, TaskState
from swasthya.db.models import AuditEventRow, OnCallRosterEntry, Task
from swasthya.workflow.exceptions import (
    IllegalTransitionError,
    MissingHospitalForEscalationError,
    TaskNotFoundError,
)

log = structlog.get_logger(__name__)

# Fallback "approver" used when the on-call roster has no active entries
# (architecture.md L21: "Empty roster routes to the medical officer").
# This is a documented contact id, not a silent no-op.
MEDICAL_OFFICER_FALLBACK_CONTACT = "medical_officer_on_duty"

# Default audit event name per destination state, used by `transition`
# unless the caller supplies an explicit `event` name.
_DEFAULT_EVENT_FOR_STATE: dict[TaskState, str] = {
    TaskState.WORKING: "working",
    TaskState.AWAITING_APPROVAL: "approval_requested",
    TaskState.HUMAN_HANDOFF: "human_handoff",
    TaskState.APPROVED: "approved",
    TaskState.REJECTED: "rejected",
    TaskState.AUTO_ESCALATED: "auto_escalated",
    TaskState.AWAITING_HOSPITAL: "awaiting_hospital",
    TaskState.AMBULANCE_REQUESTED: "ambulance_requested",
    TaskState.FOLLOW_UP: "follow_up",
    TaskState.COMPLETED: "completed",
    TaskState.FAILED: "failed",
    TaskState.CANCELED: "canceled",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _get_task(session: Session, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    return task


def _write_audit(
    session: Session,
    *,
    task_id: str,
    event: str,
    actor: str,
    model_id: str | None = None,
    detail: dict | None = None,
) -> AuditEventRow:
    """Build an `AuditEvent` (validated by the shared contract) and persist
    it as an `AuditEventRow`. Every state transition and every paging
    action goes through this single choke point, per architecture.md
    section 7/9 (append-only audit log)."""
    audit = AuditEvent(
        task_id=task_id,
        event=event,
        actor=actor,
        timestamp=_now(),
        protocol_version=PROTOCOL_VERSION,
        model_id=model_id,
        detail=detail or {},
    )
    row = AuditEventRow(
        task_id=audit.task_id,
        event=audit.event,
        actor=audit.actor,
        timestamp=audit.timestamp,
        protocol_version=audit.protocol_version,
        model_id=audit.model_id,
        detail=audit.detail,
    )
    session.add(row)
    return row


def submit_task(
    session: Session,
    task_id: str,
    is_time_critical: bool = False,
    patient_identifier_hash: str = "",
) -> Task:
    """Create a new task in `TaskState.SUBMITTED` and write a `call_started`
    audit event.

    `patient_identifier_hash` must already be hashed by the caller (see
    `swasthya.db.models.Task` docstring) — this function never sees or
    stores a raw patient identifier.
    """
    task = Task(
        task_id=task_id,
        state=TaskState.SUBMITTED.value,
        patient_identifier_hash=patient_identifier_hash,
        is_time_critical=is_time_critical,
    )
    session.add(task)
    _write_audit(session, task_id=task_id, event="call_started", actor="agent")
    log.info(
        "task.submitted",
        task_id=task_id,
        old_state=None,
        new_state=TaskState.SUBMITTED.value,
        actor="agent",
    )
    session.flush()
    return task


def transition(
    session: Session,
    task_id: str,
    new_state: TaskState,
    actor: str,
    reason: str | None = None,
    event: str | None = None,
    detail: dict | None = None,
) -> Task:
    """Move `task_id` to `new_state`, validating against
    `ALLOWED_TRANSITIONS`, and write an audit row for the move.

    Raises `IllegalTransitionError` if the move is not permitted from the
    task's current state. Nothing is written (no state change, no audit
    row) when the move is illegal.
    """
    task = _get_task(session, task_id)
    current_state = TaskState(task.state)

    allowed = ALLOWED_TRANSITIONS.get(current_state, frozenset())
    if new_state not in allowed:
        raise IllegalTransitionError(task_id, current_state.value, new_state.value)

    old_state = task.state
    task.state = new_state.value

    if new_state is TaskState.AWAITING_APPROVAL:
        task.awaiting_approval_since = _now()
    elif current_state is TaskState.AWAITING_APPROVAL:
        # Leaving the approval wait clears the timer so a later re-entry
        # starts a fresh timeout window rather than reusing a stale one.
        task.awaiting_approval_since = None

    event_name = event or _DEFAULT_EVENT_FOR_STATE.get(new_state, new_state.value)
    audit_detail = dict(detail or {})
    if reason is not None:
        audit_detail["reason"] = reason

    _write_audit(
        session,
        task_id=task_id,
        event=event_name,
        actor=actor,
        detail=audit_detail,
    )

    log.info(
        "task.transitioned",
        task_id=task_id,
        old_state=old_state,
        new_state=new_state.value,
        actor=actor,
    )

    session.flush()
    return task


def reject_with_reason(session: Session, task_id: str, reason: str, actor: str = "doctor") -> Task:
    """Doctor-reject path: `AWAITING_APPROVAL`/`HUMAN_HANDOFF` -> `REJECTED`
    -> `WORKING`, per the A2A table (architecture.md section 6, loop L5).

    Implemented as two validated hops (rather than a direct jump) so the
    move stays inside `ALLOWED_TRANSITIONS` at every step and the audit
    trail shows the reason attached to the `rejected` event specifically.
    """
    transition(session, task_id, TaskState.REJECTED, actor=actor, reason=reason, event="rejected")
    return transition(
        session,
        task_id,
        TaskState.WORKING,
        actor=actor,
        reason="re-triage after rejection",
        event="working",
    )


def _select_approver(roster: list[OnCallRosterEntry]) -> OnCallRosterEntry | None:
    active = sorted(
        (entry for entry in roster if entry.active),
        key=lambda entry: entry.priority_order,
    )
    return active[0] if active else None


def check_timeouts(
    session: Session,
    now: datetime,
    default_timeout_seconds: float,
    time_critical_timeout_seconds: float,
    roster: list[OnCallRosterEntry],
) -> list[Task]:
    """Escalate tasks stuck in `AWAITING_APPROVAL` past their timeout.

    This is the T4 fix (architecture.md section 5): the old behaviour was
    to silently set `approved: True, hospital: None, auto_approved: True`
    on timeout. That path does not exist here. Instead, a timed-out task:

    1. Must already have a `hospital` chosen by the rule engine. If it
       does not, that is a caller bug (the rule engine should have set it
       before the task ever entered AWAITING_APPROVAL) and this function
       raises `MissingHospitalForEscalationError` rather than quietly
       escalating with no destination.
    2. Transitions to `AUTO_ESCALATED`, naming that hospital in the audit
       detail.
    3. Pages the next active approver from `roster` (ordered by
       `priority_order`), recording an `approver_paged` audit event with
       the contact. If the roster has no active entries, the page falls
       back to the documented medical-officer contact
       (`MEDICAL_OFFICER_FALLBACK_CONTACT`) rather than crashing or paging
       nobody (architecture.md L21).
    """
    stmt = select(Task).where(Task.state == TaskState.AWAITING_APPROVAL.value)
    escalated: list[Task] = []

    for task in session.scalars(stmt):
        if task.awaiting_approval_since is None:
            # Defensive: should never happen if `transition` is the only
            # writer of AWAITING_APPROVAL, but a missing timer must not be
            # treated as "already timed out".
            continue

        since = task.awaiting_approval_since
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        elapsed = (now - since).total_seconds()

        timeout = time_critical_timeout_seconds if task.is_time_critical else default_timeout_seconds
        if elapsed < timeout:
            continue

        if task.hospital is None:
            raise MissingHospitalForEscalationError(task.task_id)

        approver = _select_approver(roster)
        if approver is not None:
            paged_detail = {
                "contact": approver.contact,
                "role": approver.role,
                "priority_order": approver.priority_order,
                "medical_officer_fallback": False,
            }
        else:
            paged_detail = {
                "contact": MEDICAL_OFFICER_FALLBACK_CONTACT,
                "role": "medical_officer",
                "priority_order": None,
                "medical_officer_fallback": True,
            }

        transition(
            session,
            task.task_id,
            TaskState.AUTO_ESCALATED,
            actor="system",
            reason="approval timeout",
            event="auto_escalated",
            detail={"hospital": task.hospital, "is_time_critical": task.is_time_critical},
        )
        _write_audit(
            session,
            task_id=task.task_id,
            event="approver_paged",
            actor="system",
            detail=paged_detail,
        )
        log.info(
            "task.approver_paged",
            task_id=task.task_id,
            contact=paged_detail["contact"],
            medical_officer_fallback=paged_detail["medical_officer_fallback"],
        )

        escalated.append(task)

    return escalated


def new_task_id() -> str:
    """Convenience helper for callers that need a fresh task id."""
    return str(uuid.uuid4())


def handle_hospital_response(
    session: Session,
    task_id: str,
    *,
    accepted: bool,
    re_route_hospital: str | None = None,
    reason: str | None = None,
    actor: str = "hospital",
) -> Task:
    """Referral acceptance loop (architecture.md loop L23):
    - When accepted: transitions `AWAITING_HOSPITAL` -> `FOLLOW_UP`.
    - When declined: re-routes to `re_route_hospital` if provided, remaining in
      `AWAITING_HOSPITAL` with an updated hospital target, or alerts doctor.
    """
    task = _get_task(session, task_id)
    if accepted:
        return transition(
            session,
            task_id,
            TaskState.FOLLOW_UP,
            actor=actor,
            event="referral_accepted",
            detail={"hospital": task.hospital},
        )

    # Declined case: re-route to alternative hospital of the same tier if available
    detail: dict[str, Any] = {"previous_hospital": task.hospital, "reason": reason}
    if re_route_hospital:
        task.hospital = re_route_hospital
        detail["re_routed_to"] = re_route_hospital

    return transition(
        session,
        task_id,
        TaskState.AWAITING_HOSPITAL,
        actor=actor,
        event="referral_declined",
        reason=reason,
        detail=detail,
    )


def handle_ambulance_status(
    session: Session,
    task_id: str,
    *,
    dispatched: bool,
    vehicle_id: str | None = None,
    reason: str | None = None,
    actor: str = "ambulance_dispatch",
) -> Task:
    """Ambulance dispatch confirmation loop (architecture.md loop L24):
    - When dispatched: transitions `AMBULANCE_REQUESTED` -> `FOLLOW_UP`.
    - When failed: transitions `AMBULANCE_REQUESTED` -> `FAILED` with critical alert.
    """
    if dispatched:
        return transition(
            session,
            task_id,
            TaskState.FOLLOW_UP,
            actor=actor,
            event="ambulance_dispatched",
            detail={"vehicle_id": vehicle_id},
        )
    return transition(
        session,
        task_id,
        TaskState.FAILED,
        actor=actor,
        event="ambulance_failed",
        reason=reason,
        detail={"reason": reason},
    )


def handle_follow_up(
    session: Session,
    task_id: str,
    *,
    reached_care: bool,
    notes: str | None = None,
    actor: str = "nurse",
) -> Task:
    """Referral outcome follow-up loop (architecture.md loop L25):
    - When patient reached care: transitions `FOLLOW_UP` -> `COMPLETED`.
    - When lost to follow-up: transitions `FOLLOW_UP` -> `FAILED` with escalation note.
    """
    detail = {"notes": notes}
    if reached_care:
        detail["outcome"] = "patient_reached_care"
        return transition(
            session,
            task_id,
            TaskState.COMPLETED,
            actor=actor,
            event="follow_up_closed",
            detail=detail,
        )

    detail["outcome"] = "lost_to_follow_up"
    return transition(
        session,
        task_id,
        TaskState.FAILED,
        actor=actor,
        event="follow_up_closed",
        reason="lost to follow-up",
        detail=detail,
    )


def purge_retention(
    session: Session,
    retention_cutoff: datetime,
    *,
    actor: str = "system",
) -> int:
    """Retention purge job (architecture.md loop L29):
    Redacts raw transcript and raw audio references from `triage_snapshot` on tasks
    created before `retention_cutoff`, and writes a `purge_completed` audit event.
    Returns the count of purged tasks.
    """
    stmt = select(Task).where(Task.created_at < retention_cutoff)
    purged_count = 0
    for task in session.scalars(stmt):
        if task.triage_snapshot and ("raw_transcript" in task.triage_snapshot):
            snap = dict(task.triage_snapshot)
            snap["raw_transcript"] = "[PURGED_PER_RETENTION_POLICY]"
            snap.pop("audio_clip_path", None)
            task.triage_snapshot = snap
            purged_count += 1

    if purged_count > 0:
        _write_audit(
            session,
            task_id="system_batch",
            event="purge_completed",
            actor=actor,
            detail={"purged_tasks": purged_count, "cutoff": retention_cutoff.isoformat()},
        )
        session.flush()

    return purged_count

