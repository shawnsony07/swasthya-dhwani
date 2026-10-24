"""SQLAlchemy 2.0 ORM models for the workflow/persistence layer.

Backs `docs/architecture.md` section 2 ("Application database") and the
A2A task-state table in section 6. These models are deliberately dumb
data holders: the state-machine rules live in
`swasthya.workflow.weft_workflow`, not here.

Note on `patient_identifier_hash` (Task): the raw patient identifier is a
direct identifier under DPDP and must never land in this table or in logs
(architecture.md section 7, S9). Callers hash it (e.g. HMAC-SHA256 with a
server-side key) before calling `submit_task`; this module does not hash
on their behalf because it has no opinion on the hashing scheme or key
management.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Shared declarative base for all Swasthya-Dhwani ORM models."""


class Task(Base):
    """A single triage case moving through the A2A/workflow state machine."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    patient_identifier_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(8), nullable=True)
    hospital: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_time_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    awaiting_approval_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The dashboard's alert card (architecture.md section 12) shows raw
    # transcript, interpreted text, and confidence side by side so a nurse
    # can see what the machine heard — this is the one place a raw
    # transcript is deliberately persisted, not logged (S9 is about logs/
    # traces, not this kind of durable clinical record). A JSON blob,
    # not normalized columns, because it's a point-in-time snapshot for
    # display, not something the workflow state machine queries by field.
    triage_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AuditEventRow(Base):
    """Persisted mirror of `swasthya.contracts.AuditEvent`.

    Kept as a plain row (not reusing the pydantic model directly) because
    the audit log is append-only storage, not a transport contract; see
    architecture.md section 6 for the event vocabulary and section 9 (S6)
    for the append-only requirement.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class OnCallRosterEntry(Base):
    """One entry in the on-call approver roster (architecture.md L21).

    `contact` is stored as an opaque string (phone/pager id); this module
    never dials it — that is the action gateway's job (architecture.md
    section 4), kept deliberately out of scope here.
    """

    __tablename__ = "on_call_roster"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    contact: Mapped[str] = mapped_column(String(128), nullable=False)
    priority_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
