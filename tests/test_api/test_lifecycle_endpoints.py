"""Tests for hospital response, ambulance status, follow-up, and admin override/purge endpoints
(architecture.md loops L23, L24, L25, L28, L29)."""
from __future__ import annotations

from swasthya.contracts import TaskState
from swasthya.workflow import weft_workflow as wf

from .conftest import seed_awaiting_approval_task


def test_hospital_response_lifecycle_api(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-hosp-flow")

    # Approve task
    client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})

    # Transition to awaiting_hospital via workflow
    with app.state.session_factory() as s:
        wf.transition(s, task_id, TaskState.AWAITING_HOSPITAL, actor="system")
        s.commit()

    # Hospital accepts -> moves to follow_up
    resp = client.post(
        f"/tasks/{task_id}/hospital-response",
        json={"actor": "hospital_coord", "accepted": True},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "follow_up"


def test_hospital_response_declined_reroutes_api(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-hosp-decl")
    client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})

    with app.state.session_factory() as s:
        wf.transition(s, task_id, TaskState.AWAITING_HOSPITAL, actor="system")
        s.commit()

    # Declined with alternative hospital
    resp = client.post(
        f"/tasks/{task_id}/hospital-response",
        json={
            "actor": "hospital_coord",
            "accepted": False,
            "re_route_hospital": "Amrita Institute, Kochi",
            "reason": "Capacity full",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "awaiting_hospital"
    assert data["hospital"] == "Amrita Institute, Kochi"


def test_ambulance_status_lifecycle_api(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-amb-flow")
    client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})

    with app.state.session_factory() as s:
        wf.transition(s, task_id, TaskState.AMBULANCE_REQUESTED, actor="system")
        s.commit()

    resp = client.post(
        f"/tasks/{task_id}/ambulance-status",
        json={"actor": "108_operator", "dispatched": True, "vehicle_id": "KL-01-AB-108"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "follow_up"


def test_follow_up_lifecycle_api(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-fu-flow")
    client.post(f"/tasks/{task_id}/approve", json={"actor": "doctor1"})

    with app.state.session_factory() as s:
        wf.transition(s, task_id, TaskState.AWAITING_HOSPITAL, actor="system")
        wf.transition(s, task_id, TaskState.FOLLOW_UP, actor="hospital")
        s.commit()

    resp = client.post(
        f"/tasks/{task_id}/follow-up",
        json={"actor": "nurse1", "reached_care": True, "notes": "Seen by physician"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "completed"


def test_admin_overrides_endpoint(api_app):
    app, client = api_app
    task_id = seed_awaiting_approval_task(app, task_id="task-override-test")

    # Reject to produce an override event
    client.post(f"/tasks/{task_id}/reject", json={"actor": "doctor1", "reason": "test override"})

    resp = client.get("/admin/overrides")
    assert resp.status_code == 200
    overrides = resp.json()
    assert any(o["task_id"] == task_id and o["event"] == "rejected" for o in overrides)


def test_admin_purge_endpoint(api_app):
    _app, client = api_app
    resp = client.post("/admin/purge", json={"actor": "admin_runner", "retention_days": 30})
    assert resp.status_code == 200
    data = resp.json()
    assert "purged_tasks" in data
    assert "cutoff" in data
