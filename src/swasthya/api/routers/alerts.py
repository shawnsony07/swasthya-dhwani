"""`GET /alerts/stream` -- Server-Sent Events, per docs/api_contract.md.

Poll-and-diff every 2 seconds against the DB rather than a true push —
this is architecture.md loop L7's own documented fallback ("Dashboard
polls the task endpoint"), made explicit here rather than pretending to be
a push system. Each connection tracks which `(task_id, updated_at)` pairs
it has already sent; a task is re-sent only when its `updated_at` advances
past what this connection last saw. A reconnecting client gets no replay
of missed events — the contract says so explicitly, and the dashboard is
expected to re-fetch `GET /tasks` on (re)connect to catch up.
"""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from swasthya.api.auth import get_current_roles_sse
from swasthya.contracts import TaskState
from swasthya.db.models import Task

logger = structlog.get_logger(__name__)

router = APIRouter()

_ALERT_STATES = (
    TaskState.AWAITING_APPROVAL.value,
    TaskState.AUTO_ESCALATED.value,
    TaskState.HUMAN_HANDOFF.value,
)
_POLL_INTERVAL_SECONDS = 2.0


async def _event_stream(request: Request):
    session_factory = request.app.state.session_factory
    last_sent: dict[str, str] = {}  # task_id -> last-sent updated_at isoformat

    while True:
        if await request.is_disconnected():
            logger.info("alerts.client_disconnected")
            break

        session = session_factory()
        try:
            stmt = select(Task).where(Task.state.in_(_ALERT_STATES))
            for task in session.scalars(stmt):
                updated_at_iso = task.updated_at.isoformat()
                if last_sent.get(task.task_id) == updated_at_iso:
                    continue
                last_sent[task.task_id] = updated_at_iso
                yield {
                    "event": "task_update",
                    "data": json.dumps(
                        {
                            "task_id": task.task_id,
                            "state": task.state,
                            "tier": task.tier,
                            "is_time_critical": task.is_time_critical,
                            "updated_at": updated_at_iso,
                        }
                    ),
                }
        finally:
            session.close()

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


@router.get("/alerts/stream")
async def alerts_stream(
    request: Request, _roles: set[str] = Depends(get_current_roles_sse)
) -> EventSourceResponse:
    # Auth accepts either a normal `Authorization` header or a `?token=`
    # query param (see `get_current_roles_sse`) — the browser's native
    # `EventSource` cannot set custom headers, so the dashboard is expected
    # to connect with the token in the URL for this one endpoint.
    return EventSourceResponse(_event_stream(request))
