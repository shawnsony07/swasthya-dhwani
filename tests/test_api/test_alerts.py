"""Tests for `GET /alerts/stream` (docs/api_contract.md).

Deliberately does NOT drive this through `TestClient`'s HTTP streaming —
`_event_stream` loops forever (`while True`) until the request disconnects,
and exercising that over a real (even if in-process) HTTP stream turned
out to hang under Starlette's `TestClient`/httpx transport in practice.
Testing the async generator directly is faster, deterministic, and avoids
depending on TestClient's streaming semantics at all — every wait here is
bounded by a fake `is_disconnected` that flips to `True` after a fixed
number of polls, never by a real timeout.
"""
from __future__ import annotations

from swasthya.api.routers import alerts as alerts_module
from swasthya.contracts import TaskState
from swasthya.workflow.weft_workflow import submit_task, transition

from .conftest import seed_awaiting_approval_task


class _FakeRequest:
    """Minimal stand-in for `starlette.requests.Request`: `_event_stream`
    only ever calls `.app.state.session_factory` and `await
    .is_disconnected()`."""

    def __init__(self, app, *, disconnect_after: int) -> None:
        self.app = app
        self._disconnect_after = disconnect_after
        self._calls = 0

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


async def test_stream_emits_an_event_for_a_task_awaiting_approval(api_app, monkeypatch):
    app, _client = api_app
    monkeypatch.setattr(alerts_module, "_POLL_INTERVAL_SECONDS", 0.0)
    task_id = seed_awaiting_approval_task(app, task_id="sse-task-1")

    request = _FakeRequest(app, disconnect_after=1)
    events = [event async for event in alerts_module._event_stream(request)]

    assert any(task_id in event["data"] for event in events)
    assert all(event["event"] == "task_update" for event in events)


async def test_stream_does_not_emit_a_task_that_is_not_in_an_alert_state(api_app, monkeypatch):
    app, _client = api_app
    monkeypatch.setattr(alerts_module, "_POLL_INTERVAL_SECONDS", 0.0)

    session_factory = app.state.session_factory
    with session_factory() as session:
        submit_task(session, task_id="working-task", is_time_critical=False)
        transition(session, "working-task", TaskState.WORKING, actor="agent")
        session.commit()

    request = _FakeRequest(app, disconnect_after=1)
    events = [event async for event in alerts_module._event_stream(request)]

    assert not any("working-task" in event["data"] for event in events)


async def test_stream_does_not_resend_a_task_whose_updated_at_has_not_changed(
    api_app, monkeypatch
):
    app, _client = api_app
    monkeypatch.setattr(alerts_module, "_POLL_INTERVAL_SECONDS", 0.0)
    task_id = seed_awaiting_approval_task(app, task_id="sse-task-2")

    request = _FakeRequest(app, disconnect_after=3)
    events = [event async for event in alerts_module._event_stream(request)]

    matching = [e for e in events if task_id in e["data"]]
    assert len(matching) == 1  # sent once across 3 polls, not re-sent every poll
