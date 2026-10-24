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


# ---------------------------------------------------------------------------
# Hospital response, Ambulance, Follow-up, and Retention Purge (L23, L24, L25, L29)
# ---------------------------------------------------------------------------


def test_handle_hospital_response_accepted(session: Session) -> None:
    task = _make_awaiting_task(session, "t_hosp", seconds_ago=0.0)
    wf.transition(session, "t_hosp", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_hosp", TaskState.AWAITING_HOSPITAL, actor="system")

    updated = wf.handle_hospital_response(session, "t_hosp", accepted=True, actor="hospital_admin")

    assert updated.state == TaskState.FOLLOW_UP.value
    events = _audit_events(session, "t_hosp")
    accepted_ev = [e for e in events if e.event == "referral_accepted"]
    assert len(accepted_ev) == 1
    assert accepted_ev[0].actor == "hospital_admin"


def test_handle_hospital_response_declined_rerouted(session: Session) -> None:
    task = _make_awaiting_task(session, "t_decl", seconds_ago=0.0)
    wf.transition(session, "t_decl", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_decl", TaskState.AWAITING_HOSPITAL, actor="system")

    updated = wf.handle_hospital_response(
        session,
        "t_decl",
        accepted=False,
        re_route_hospital="Aster Medcity, Kochi",
        reason="No ICU beds available",
        actor="hospital_coordinator",
    )

    assert updated.state == TaskState.AWAITING_HOSPITAL.value
    assert updated.hospital == "Aster Medcity, Kochi"
    events = _audit_events(session, "t_decl")
    declined_ev = [e for e in events if e.event == "referral_declined"]
    assert len(declined_ev) == 1
    assert declined_ev[0].detail["re_routed_to"] == "Aster Medcity, Kochi"


def test_handle_ambulance_status_dispatched(session: Session) -> None:
    task = _make_awaiting_task(session, "t_amb", seconds_ago=0.0)
    wf.transition(session, "t_amb", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_amb", TaskState.AMBULANCE_REQUESTED, actor="system")

    updated = wf.handle_ambulance_status(
        session, "t_amb", dispatched=True, vehicle_id="KL-07-CD-1088", actor="108_dispatch"
    )

    assert updated.state == TaskState.FOLLOW_UP.value
    events = _audit_events(session, "t_amb")
    dispatched_ev = [e for e in events if e.event == "ambulance_dispatched"]
    assert len(dispatched_ev) == 1
    assert dispatched_ev[0].detail["vehicle_id"] == "KL-07-CD-1088"


def test_handle_ambulance_status_failed(session: Session) -> None:
    task = _make_awaiting_task(session, "t_amb_fail", seconds_ago=0.0)
    wf.transition(session, "t_amb_fail", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_amb_fail", TaskState.AMBULANCE_REQUESTED, actor="system")

    updated = wf.handle_ambulance_status(
        session, "t_amb_fail", dispatched=False, reason="No ambulances in sector", actor="108_dispatch"
    )

    assert updated.state == TaskState.FAILED.value
    events = _audit_events(session, "t_amb_fail")
    failed_ev = [e for e in events if e.event == "ambulance_failed"]
    assert len(failed_ev) == 1
    assert failed_ev[0].detail["reason"] == "No ambulances in sector"


def test_handle_follow_up_reached_care(session: Session) -> None:
    task = _make_awaiting_task(session, "t_fu", seconds_ago=0.0)
    wf.transition(session, "t_fu", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_fu", TaskState.AWAITING_HOSPITAL, actor="system")
    wf.transition(session, "t_fu", TaskState.FOLLOW_UP, actor="hospital")

    updated = wf.handle_follow_up(
        session, "t_fu", reached_care=True, notes="Patient admitted to neurology", actor="asha_worker"
    )

    assert updated.state == TaskState.COMPLETED.value
    events = _audit_events(session, "t_fu")
    closed_ev = [e for e in events if e.event == "follow_up_closed"]
    assert len(closed_ev) == 1
    assert closed_ev[0].detail["outcome"] == "patient_reached_care"


def test_handle_follow_up_lost_to_follow_up(session: Session) -> None:
    task = _make_awaiting_task(session, "t_lost", seconds_ago=0.0)
    wf.transition(session, "t_lost", TaskState.APPROVED, actor="doctor")
    wf.transition(session, "t_lost", TaskState.AWAITING_HOSPITAL, actor="system")
    wf.transition(session, "t_lost", TaskState.FOLLOW_UP, actor="hospital")

    updated = wf.handle_follow_up(
        session, "t_lost", reached_care=False, notes="Phone switched off after 3 attempts", actor="asha_worker"
    )

    assert updated.state == TaskState.FAILED.value
    events = _audit_events(session, "t_lost")
    closed_ev = [e for e in events if e.event == "follow_up_closed"]
    assert len(closed_ev) == 1
    assert closed_ev[0].detail["outcome"] == "lost_to_follow_up"


def test_purge_retention_redacts_old_tasks(session: Session) -> None:
    task = wf.submit_task(session, "t_old")
    task.created_at = datetime.now(UTC) - timedelta(days=100)
    task.triage_snapshot = {
        "raw_transcript": "അമ്മയ്ക്ക് നെഞ്ചുവേദനയുണ്ട്",
        "interpreted_text": "Chest pain present",
    }
    session.flush()

    cutoff = datetime.now(UTC) - timedelta(days=90)
    purged_count = wf.purge_retention(session, retention_cutoff=cutoff, actor="retention_cron")

    assert purged_count == 1
    assert task.triage_snapshot["raw_transcript"] == "[PURGED_PER_RETENTION_POLICY]"
    assert task.triage_snapshot["interpreted_text"] == "Chest pain present"

    events = _audit_events(session, "system_batch")
    purge_ev = [e for e in events if e.event == "purge_completed"]
    assert len(purge_ev) == 1
    assert purge_ev[0].detail["purged_tasks"] == 1

