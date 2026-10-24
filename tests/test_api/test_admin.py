"""Tests for the admin router: kill switch (L19/L34) and on-call roster
(L21) management.
"""
from __future__ import annotations

from swasthya.api.auth import get_current_roles


def test_kill_switch_defaults_to_inactive(client):
    response = client.get("/admin/kill-switch")
    assert response.status_code == 200
    assert response.json()["active"] is False


def test_engage_then_disable_round_trip(client):
    engage = client.post("/admin/kill-switch/engage", json={"by": "admin1"})
    assert engage.status_code == 200
    assert engage.json()["active"] is True
    assert engage.json()["changed_by"] == "admin1"

    status_check = client.get("/admin/kill-switch")
    assert status_check.json()["active"] is True

    disable = client.post(
        "/admin/kill-switch/disable", json={"by": "admin1", "reason": "drill complete"}
    )
    assert disable.status_code == 200
    assert disable.json()["active"] is False
    assert disable.json()["reason"] == "drill complete"


def test_disable_without_reason_is_422(client):
    client.post("/admin/kill-switch/engage", json={"by": "admin1"})
    response = client.post("/admin/kill-switch/disable", json={"by": "admin1", "reason": ""})
    assert response.status_code == 422


def test_kill_switch_state_is_shared_across_requests(client):
    """Each request builds its own KillSwitch(DbKillSwitchStore(...)) —
    this proves state survives across that per-request reconstruction,
    i.e. it's actually reading the DB, not an object held in memory."""
    client.post("/admin/kill-switch/engage", json={"by": "admin1", "reason": "test"})
    response = client.get("/admin/kill-switch")
    assert response.json()["active"] is True


def test_non_admin_cannot_touch_kill_switch(api_app):
    app, client = api_app
    app.dependency_overrides[get_current_roles] = lambda: {"doctor"}
    try:
        response = client.post("/admin/kill-switch/engage", json={"by": "doctor1"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_roles, None)


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def test_roster_crud_flow(client):
    create = client.post(
        "/admin/roster",
        json={"role": "doctor", "contact": "+91-test-1", "priority_order": 1, "active": True},
    )
    assert create.status_code == 201
    entry_id = create.json()["id"]

    listed = client.get("/admin/roster")
    assert listed.status_code == 200
    assert any(e["id"] == entry_id for e in listed.json())

    updated = client.patch(f"/admin/roster/{entry_id}", json={"active": False})
    assert updated.status_code == 200
    assert updated.json()["active"] is False
    assert updated.json()["contact"] == "+91-test-1"  # untouched fields preserved

    deleted = client.delete(f"/admin/roster/{entry_id}")
    assert deleted.status_code == 204

    listed_again = client.get("/admin/roster")
    assert not any(e["id"] == entry_id for e in listed_again.json())


def test_update_nonexistent_roster_entry_is_404(client):
    response = client.patch("/admin/roster/999999", json={"active": False})
    assert response.status_code == 404


def test_delete_nonexistent_roster_entry_is_404(client):
    response = client.delete("/admin/roster/999999")
    assert response.status_code == 404


def test_non_admin_cannot_manage_roster(api_app):
    app, client = api_app
    app.dependency_overrides[get_current_roles] = lambda: {"nurse"}
    try:
        response = client.get("/admin/roster")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_roles, None)
