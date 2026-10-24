"""FastAPI app factory. `uvicorn swasthya.api.app:app` serves this.

Lifespan responsibilities (docs/api_contract.md and architecture.md
section 10):

1. Build the engine/session factory once, stash on `app.state` — every
   request's `get_db` dependency reads it from there (see `api/db.py`).
2. Run `create_all` so a fresh dev DB has tables without needing
   `alembic upgrade head` first (a real deployment still runs the
   migration; this is a convenience, not a replacement — see
   `db/session.py`'s own docstring on this).
3. Log loudly if `AUTH_DISABLED=true` — this must never be a silent gap.
4. Start the background timeout-escalation loop: the first real caller of
   `weft_workflow.check_timeouts` on an actual schedule anywhere in this
   system (T4's fix only mattered once something calls it periodically).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from swasthya.api.routers import admin, alerts, health, tasks
from swasthya.db.models import OnCallRosterEntry
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.workflow.exceptions import MissingHospitalForEscalationError
from swasthya.workflow.weft_workflow import check_timeouts

logger = structlog.get_logger(__name__)

_TIMEOUT_CHECK_INTERVAL_SECONDS = 30.0


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _timeout_seconds() -> tuple[float, float]:
    default = float(os.environ.get("DOCTOR_APPROVAL_TIMEOUT_SECONDS", "900"))
    time_critical = float(
        os.environ.get("DOCTOR_APPROVAL_TIMEOUT_SECONDS_TIME_CRITICAL", "180")
    )
    return default, time_critical


async def _timeout_loop(session_factory) -> None:
    """Calls `check_timeouts` every 30 seconds against a fresh session.

    A missing hospital on a task that reached AWAITING_APPROVAL is a bug
    upstream (the rule engine should have set one before that transition —
    see `_WorkflowSinkAdapter.mark_awaiting_approval`'s own guard), not
    something this loop should swallow and keep going past silently: it
    logs the offending task_id loudly and continues to the next sweep
    rather than crashing the whole loop over one bad row.
    """
    default_timeout, time_critical_timeout = _timeout_seconds()

    while True:
        await asyncio.sleep(_TIMEOUT_CHECK_INTERVAL_SECONDS)
        session: Session = session_factory()
        try:
            roster = list(session.scalars(select(OnCallRosterEntry)))
            escalated = check_timeouts(
                session,
                now=datetime.now(UTC),
                default_timeout_seconds=default_timeout,
                time_critical_timeout_seconds=time_critical_timeout,
                roster=roster,
            )
            session.commit()
            for task in escalated:
                logger.warning(
                    "api.timeout_escalated",
                    task_id=task.task_id,
                    hospital=task.hospital,
                    is_time_critical=task.is_time_critical,
                )
        except MissingHospitalForEscalationError as exc:
            logger.error("api.timeout_check_missing_hospital", detail=str(exc))
            session.rollback()
        except Exception:
            logger.exception("api.timeout_check_failed")
            session.rollback()
        finally:
            session.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if os.environ.get("AUTH_DISABLED", "").strip().lower() == "true":
        logger.warning(
            "api.auth_disabled",
            detail_message=(
                "AUTH_DISABLED=true: every request is treated as role 'admin'. "
                "This must never be set outside local/offline development."
            ),
        )

    engine = build_engine()
    create_all(engine)
    session_factory = build_session_factory(engine)
    app.state.session_factory = session_factory

    timeout_task = asyncio.create_task(_timeout_loop(session_factory))
    try:
        yield
    finally:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Swasthya-Dhwani triage API", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(alerts.router)
    app.include_router(admin.router)

    return app


app = create_app()
