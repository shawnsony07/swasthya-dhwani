"""SQLAlchemy engine/session factory for the workflow persistence layer.

Kept separate from `models.py` (schema) and `weft_workflow.py` (state
machine logic) so the engine's lifecycle — one per process, long-lived — is
obvious and isn't accidentally recreated per call. `docs/architecture.md`
section 2: Postgres 16 in production; tests and local dev may point
`DATABASE_URL` at SQLite instead (the state machine itself is already
tested against in-memory SQLite in `tests/test_workflow.py`).
"""
from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from swasthya.db.models import Base

_DEFAULT_DATABASE_URL = "sqlite:///:memory:"


def build_engine(database_url: str | None = None) -> Engine:
    """Creates the SQLAlchemy engine for `database_url`, or
    `DATABASE_URL` from the environment, or an in-memory SQLite engine as a
    last resort so a misconfigured dev box fails loud in logs rather than
    refusing to start at all.

    `pool_pre_ping=True` so a dropped Postgres connection (section 8: "FHIR
    down" has its own fallback; a dropped DB connection does not — this is
    the workflow's own state, not optional history) is detected and
    recycled rather than surfacing as a confusing mid-call error.

    An in-memory SQLite URL gets `StaticPool` (one single connection
    shared by every checkout) rather than SQLAlchemy's default per-thread
    pooling for `:memory:` databases. Without it, a caller that creates
    tables on one thread (e.g. a FastAPI app's startup lifespan, which
    `TestClient` runs on a different thread than the test itself) and then
    reads/writes from another thread gets handed a second, separate,
    empty in-memory database — "no such table" even though `create_all`
    already ran. A file-based SQLite path or Postgres URL is unaffected
    (each connection there reads the same durable store already).
    """
    url = database_url or os.environ.get("DATABASE_URL") or _DEFAULT_DATABASE_URL
    is_sqlite_memory = url.startswith("sqlite") and ":memory:" in url
    connect_args: dict[str, object] = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs: dict[str, object] = {"pool_pre_ping": True, "connect_args": connect_args}
    if is_sqlite_memory:
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """Creates the workflow tables if they don't exist yet. A real
    deployment uses the Alembic migration in `migrations/` instead; this is
    for tests and quick local runs where running `alembic upgrade head`
    first is unnecessary ceremony."""
    Base.metadata.create_all(engine)
