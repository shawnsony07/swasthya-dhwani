"""Per-request DB session dependency.

The engine/session factory is built once at app startup (`app.py`'s
lifespan) and stashed on `app.state` — this module only wraps that
factory into a FastAPI dependency so each request gets its own
short-lived `Session`, closed when the request finishes.

Tests override `get_db` directly (`app.dependency_overrides[get_db] =
...`), the same pattern the rest of the suite uses for swapping in an
in-memory SQLite session factory.
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
