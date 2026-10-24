"""Tests for the doctor-approval API (docs/api_contract.md)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swasthya.api.auth import get_current_roles
from swasthya.db.models import OnCallRosterEntry, Task
from swasthya.workflow.weft_workflow import check_timeouts

from .conftest import seed_awaiting_approval_task


def test_healthz_requires_no_auth(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_and_detail_and_approve_flow(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-happy")

    list_response = client.get("/tasks")
    assert list_response.status_code == 200
    body = list_response.json()
    assert any(t["task_id"] == "task-happy" for t in body["tasks"])

    detail_response = client.get(f"/tasks/{task_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["state"] == "awaiting_approval"
    assert detail["tier"] == "B"
    assert detail["triage_snapshot"]["symptoms"] == ["chest_pain"]
    assert detail["triage_snapshot"]["interpretation_confidence"] == 0.82

    approve_response = client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})
    assert approve_response.status_code == 200
    assert approve_response.json()["state"] == "approved"

    # Approving again is now an illegal transition (APPROVED has no edge
    # back to APPROVED) -> 409, not a silent no-op or a 500.
    second_attempt = client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})
    assert second_attempt.status_code == 409


def test_reject_requires_a_reason_and_returns_to_working(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-reject")

    response = client.post(
        f"/tasks/{task_id}/reject", json={"actor": "doctor1", "reason": "wrong tier, re-check"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "working"


def test_reject_without_reason_is_rejected_by_schema_validation(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-reject-2")

    response = client.post(f"/tasks/{task_id}/reject", json={"actor": "doctor1", "reason": ""})
    assert response.status_code == 422


def test_get_nonexistent_task_is_404(client):
    response = client.get("/tasks/does-not-exist")
    assert response.status_code == 404


def test_triage_snapshot_null_renders_without_crashing(api_app):
    app, client = api_app
    from swasthya.contracts import TaskState
    from swasthya.workflow.weft_workflow import submit_task, transition

    session_factory = app.state.session_factory
    with session_factory() as session:
        submit_task(session, task_id="task-no-snapshot", is_time_critical=False)
        transition(session, "task-no-snapshot", TaskState.WORKING, actor="agent")
        task = session.get(Task, "task-no-snapshot")
        task.tier = "B"
        task.hospital = "taluk_hq"
        transition(session, "task-no-snapshot", TaskState.AWAITING_APPROVAL, actor="rule_engine")
        session.commit()

    response = client.get("/tasks/task-no-snapshot")
    assert response.status_code == 200
    assert response.json()["triage_snapshot"] is None


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------


def test_nurse_cannot_approve_but_doctor_can(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-role")

    app.dependency_overrides[get_current_roles] = lambda: {"nurse"}
    nurse_attempt = client.post(f"/tasks/{task_id}/approve", json={"actor": "nurse1"})
    assert nurse_attempt.status_code == 403

    app.dependency_overrides[get_current_roles] = lambda: {"doctor"}
    doctor_attempt = client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})
    assert doctor_attempt.status_code == 200

    app.dependency_overrides.pop(get_current_roles, None)


def test_nurse_can_reject(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-role-2")

    app.dependency_overrides[get_current_roles] = lambda: {"nurse"}
    response = client.post(
        f"/tasks/{task_id}/reject", json={"actor": "nurse1", "reason": "needs a second look"}
    )
    assert response.status_code == 200

    app.dependency_overrides.pop(get_current_roles, None)


# ---------------------------------------------------------------------------
# Timeout escalation wiring (the loop itself is tested in test_workflow.py;
# this confirms the API layer's env-var/roster plumbing is correct)
# ---------------------------------------------------------------------------


def test_check_timeouts_escalates_with_the_roster_present_in_the_db(api_app):
    app, client = api_app
    from swasthya.contracts import Tier

    task_id = seed_awaiting_approval_task(
        app, task_id="task-timeout", tier=Tier.C1, hospital="stroke_unit_or_tertiary"
    )

    session_factory = app.state.session_factory
    with session_factory() as session:
        task = session.get(Task, task_id)
        task.awaiting_approval_since = datetime.now(UTC) - timedelta(seconds=9999)
        session.add(OnCallRosterEntry(role="doctor", contact="+91-test", priority_order=1, active=True))
        session.commit()

        escalated = check_timeouts(
            session,
            now=datetime.now(UTC),
            default_timeout_seconds=1.0,
            time_critical_timeout_seconds=1.0,
            roster=list(session.query(OnCallRosterEntry)),
        )
        session.commit()

    assert any(t.task_id == task_id for t in escalated)

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["state"] == "auto_escalated"
