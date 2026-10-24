"""Shared fixtures for the API test suite.

Each test gets a fresh FastAPI app over a fresh in-memory SQLite DB — no
real Postgres, no real Keycloak. `AUTH_DISABLED=true` is the default for
most tests (treats every request as role `admin`, which also satisfies
`doctor`-gated routes since `admin1` is seeded with both roles in the real
realm); tests that specifically exercise role enforcement override
`get_current_roles` directly instead of relying on a real JWT.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from swasthya.api.app import create_app
from swasthya.contracts import TaskState, Tier
from swasthya.db.models import Task
from swasthya.workflow.weft_workflow import submit_task, transition


@pytest.fixture()
def api_app(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_app()
    with TestClient(app) as client:
        yield app, client


@pytest.fixture()
def client(api_app):
    _app, client = api_app
    return client


def seed_awaiting_approval_task(
    app, *, task_id: str = "task-api-1", tier: Tier = Tier.B, hospital: str = "taluk_hq"
) -> str:
    """Creates a task that has already reached AWAITING_APPROVAL with a
    tier/hospital set and a triage snapshot — the shape the API's
    `GET /tasks/{id}` and approve/reject endpoints expect to operate on,
    mirroring what `_WorkflowSinkAdapter` does in the real pipeline.
    Returns the task_id; callers re-query a fresh session for anything
    beyond that, rather than reusing a detached ORM object."""
    session_factory = app.state.session_factory
    with session_factory() as session:  # type: Session
        submit_task(session, task_id=task_id, is_time_critical=False)
        transition(session, task_id, TaskState.WORKING, actor="agent")
        task = session.get(Task, task_id)
        task.tier = tier.value
        task.hospital = hospital
        task.triage_snapshot = {
            "raw_transcript": "chest ache since yesterday",
            "interpreted_text": "chest pain since yesterday",
            "interpretation_confidence": 0.82,
            "symptoms": ["chest_pain"],
            "symptom_duration_days": 1,
            "warning_signs_present": ["chest_pain"],
            "speech_impairment_signals": [],
            "speech_onset": "unknown",
            "confirmed_by": "patient",
            "interpreter_model": "gemini-2.5-flash",
            "protocol_version": "2025.11.01",
        }
        transition(session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
        session.commit()
        return task_id
