"""Tests for the workflow state machine (swasthya.workflow.weft_workflow).

Uses an in-memory SQLite engine created directly via SQLAlchemy -- no real
Postgres or testcontainers needed. Covers the T4 safety fix and the
on-call roster / medical-officer fallback (L21) per
docs/architecture.md.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from swasthya.contracts import TaskState
from swasthya.db.models import AuditEventRow, Base, OnCallRosterEntry, Task
from swasthya.workflow import weft_workflow as wf
from swasthya.workflow.exceptions import (
    IllegalTransitionError,
    MissingHospitalForEscalationError,
)

DEFAULT_TIMEOUT = 900.0
TIME_CRITICAL_TIMEOUT = 180.0


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _audit_events(session: Session, task_id: str) -> list[AuditEventRow]:
    stmt = select(AuditEventRow).where(AuditEventRow.task_id == task_id)
    return list(session.scalars(stmt))


def _make_awaiting_task(
    session: Session,
    task_id: str = "t1",
    *,
    hospital: str | None = "General Hospital, Ernakulam",
    is_time_critical: bool = False,
    seconds_ago: float = 1000.0,
) -> Task:
    task = wf.submit_task(session, task_id, is_time_critical=is_time_critical)
    wf.transition(session, task_id, TaskState.WORKING, actor="rule_engine")
    task.hospital = hospital
    task.tier = "C1"
    wf.transition(session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
    # Backdate the approval timer so check_timeouts sees it as overdue.
    task.awaiting_approval_since = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    session.flush()
    return task


def _roster(*, active: bool = True) -> list[OnCallRosterEntry]:
    return [
        OnCallRosterEntry(role="doctor", contact="+91-900-000-0002", priority_order=2, active=active),
        OnCallRosterEntry(role="doctor", contact="+91-900-000-0001", priority_order=1, active=active),
        OnCallRosterEntry(role="nurse", contact="+91-900-000-0003", priority_order=3, active=False),
    ]


# ---------------------------------------------------------------------------
# Legal / illegal transitions
# ---------------------------------------------------------------------------


def test_legal_transition_succeeds_and_writes_audit_row(session: Session) -> None:
    wf.submit_task(session, "t1")
    task = wf.transition(session, "t1", TaskState.WORKING, actor="rule_engine")

    assert task.state == TaskState.WORKING.value
    events = [row.event for row in _audit_events(session, "t1")]
    assert "call_started" in events
    assert "working" in events


def test_illegal_transition_raises_and_writes_nothing(session: Session) -> None:
    wf.submit_task(session, "t1")
    before = _audit_events(session, "t1")

    with pytest.raises(IllegalTransitionError):
        # SUBMITTED cannot jump straight to AWAITING_APPROVAL.
        wf.transition(session, "t1", TaskState.AWAITING_APPROVAL, actor="rule_engine")

    task = session.get(Task, "t1")
    assert task.state == TaskState.SUBMITTED.value
    after = _audit_events(session, "t1")
    assert len(after) == len(before)


# ---------------------------------------------------------------------------
# T4: timeout escalation
# ---------------------------------------------------------------------------


def test_check_timeouts_escalates_past_default_window(session: Session) -> None:
    _make_awaiting_task(session, "t1", seconds_ago=1000.0)
    roster = _roster()
    session.add_all(roster)
    session.flush()

    escalated = wf.check_timeouts(
        session,
        now=datetime.now(UTC),
        default_timeout_seconds=DEFAULT_TIMEOUT,
        time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
        roster=roster,
    )

    assert len(escalated) == 1
    task = escalated[0]
    assert task.state == TaskState.AUTO_ESCALATED.value
    assert task.hospital == "General Hospital, Ernakulam"

    events = _audit_events(session, "t1")
    paged = [e for e in events if e.event == "approver_paged"]
    assert len(paged) == 1
    assert paged[0].detail["contact"] == "+91-900-000-0001"  # top priority_order, active
    assert paged[0].detail["medical_officer_fallback"] is False

    escalated_events = [e for e in events if e.event == "auto_escalated"]
    assert len(escalated_events) == 1
    assert escalated_events[0].detail["hospital"] == "General Hospital, Ernakulam"


def test_check_timeouts_time_critical_escalates_before_default_window(session: Session) -> None:
    # 300s elapsed: past the 180s time-critical window, but well under the
    # 900s default window. Must still escalate because is_time_critical.
    _make_awaiting_task(session, "t1", is_time_critical=True, seconds_ago=300.0)
    roster = _roster()
    session.add_all(roster)
    session.flush()

    escalated = wf.check_timeouts(
        session,
        now=datetime.now(UTC),
        default_timeout_seconds=DEFAULT_TIMEOUT,
        time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
        roster=roster,
    )

    assert len(escalated) == 1
    assert escalated[0].state == TaskState.AUTO_ESCALATED.value


def test_check_timeouts_not_yet_due_is_left_alone(session: Session) -> None:
    _make_awaiting_task(session, "t1", is_time_critical=False, seconds_ago=10.0)
    roster = _roster()
    session.add_all(roster)
    session.flush()

    escalated = wf.check_timeouts(
        session,
        now=datetime.now(UTC),
        default_timeout_seconds=DEFAULT_TIMEOUT,
        time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
        roster=roster,
    )

    assert escalated == []
    task = session.get(Task, "t1")
    assert task.state == TaskState.AWAITING_APPROVAL.value


def test_check_timeouts_raises_when_hospital_is_none(session: Session) -> None:
    _make_awaiting_task(session, "t1", hospital=None, seconds_ago=1000.0)
    roster = _roster()
    session.add_all(roster)
    session.flush()

    with pytest.raises(MissingHospitalForEscalationError):
        wf.check_timeouts(
            session,
            now=datetime.now(UTC),
            default_timeout_seconds=DEFAULT_TIMEOUT,
            time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
            roster=roster,
        )

    # The old T4 bug: never ends up "approved" with no hospital.
    task = session.get(Task, "t1")
    assert task.state == TaskState.AWAITING_APPROVAL.value


def test_check_timeouts_empty_roster_falls_back_to_medical_officer(session: Session) -> None:
    _make_awaiting_task(session, "t1", seconds_ago=1000.0)
    # No active roster entries at all -- must not crash.
    roster: list[OnCallRosterEntry] = [
        OnCallRosterEntry(role="nurse", contact="x", priority_order=1, active=False),
    ]
    session.add_all(roster)
    session.flush()

    escalated = wf.check_timeouts(
        session,
        now=datetime.now(UTC),
        default_timeout_seconds=DEFAULT_TIMEOUT,
        time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
        roster=roster,
    )

    assert len(escalated) == 1
    events = _audit_events(session, "t1")
    paged = [e for e in events if e.event == "approver_paged"]
    assert len(paged) == 1
    assert paged[0].detail["medical_officer_fallback"] is True
    assert paged[0].detail["contact"] == wf.MEDICAL_OFFICER_FALLBACK_CONTACT


def test_check_timeouts_truly_empty_roster_list_falls_back(session: Session) -> None:
    _make_awaiting_task(session, "t1", seconds_ago=1000.0)

    escalated = wf.check_timeouts(
        session,
        now=datetime.now(UTC),
        default_timeout_seconds=DEFAULT_TIMEOUT,
        time_critical_timeout_seconds=TIME_CRITICAL_TIMEOUT,
        roster=[],
    )

    assert len(escalated) == 1
    paged = [e for e in _audit_events(session, "t1") if e.event == "approver_paged"]
    assert paged[0].detail["medical_officer_fallback"] is True


# ---------------------------------------------------------------------------
# Reject path
# ---------------------------------------------------------------------------


def test_reject_with_reason_returns_task_to_working(session: Session) -> None:
    _make_awaiting_task(session, "t1", seconds_ago=0.0)

    task = wf.reject_with_reason(session, "t1", reason="wrong tier, re-check symptoms")

    assert task.state == TaskState.WORKING.value
    events = _audit_events(session, "t1")
    rejected = [e for e in events if e.event == "rejected"]
    assert len(rejected) == 1
    assert rejected[0].detail["reason"] == "wrong tier, re-check symptoms"
