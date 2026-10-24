"""Admin controls: the kill switch (architecture.md loops L19/L34) and
on-call roster management (L21).

Both were backend-complete and tested (`src/swasthya/gateway/kill_switch.py`,
`src/swasthya/db/models.OnCallRosterEntry`) with no way for a human to
actually use them before this router — a dashboard control or a raw SQL
insert were the only options. This closes that gap.

Role note: architecture.md's L34 says "medical officer role" specifically
for kill-switch re-enable; this build's role set is `doctor`/`nurse`/
`admin` (no distinct `medical officer` role exists in the Keycloak realm
today), so `admin` is used as the closest fit here. Documented, not
silently substituted.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from swasthya.api.auth import require_role
from swasthya.api.db import get_db
from swasthya.api.schemas import (
    DisableKillSwitchRequest,
    EngageKillSwitchRequest,
    KillSwitchStatus,
    PurgeRetentionRequest,
    PurgeRetentionResponse,
    RosterEntry,
    RosterEntryCreate,
    RosterEntryUpdate,
)
from swasthya.db.kill_switch_store import DbKillSwitchStore
from swasthya.db.models import AuditEventRow, OnCallRosterEntry, Task
from swasthya.gateway.kill_switch import KillSwitch
from swasthya.workflow.weft_workflow import purge_retention

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin")


def _get_kill_switch(request: Request) -> KillSwitch:
    return KillSwitch(DbKillSwitchStore(request.app.state.session_factory))


def _to_status(switch: KillSwitch) -> KillSwitchStatus:
    state = switch.state
    return KillSwitchStatus(
        active=state.active,
        changed_by=state.changed_by,
        changed_at=state.changed_at,
        reason=state.reason,
    )


@router.get("/kill-switch", response_model=KillSwitchStatus)
def get_kill_switch_status(
    switch: KillSwitch = Depends(_get_kill_switch),
    _roles: set[str] = Depends(require_role("admin")),
) -> KillSwitchStatus:
    return _to_status(switch)


@router.post("/kill-switch/engage", response_model=KillSwitchStatus)
def engage_kill_switch(
    body: EngageKillSwitchRequest,
    switch: KillSwitch = Depends(_get_kill_switch),
    _roles: set[str] = Depends(require_role("admin")),
) -> KillSwitchStatus:
    switch.engage(by=body.by, reason=body.reason)
    logger.warning("api.kill_switch_engaged", by=body.by)
    return _to_status(switch)


@router.post("/kill-switch/disable", response_model=KillSwitchStatus)
def disable_kill_switch(
    body: DisableKillSwitchRequest,
    switch: KillSwitch = Depends(_get_kill_switch),
    _roles: set[str] = Depends(require_role("admin")),
) -> KillSwitchStatus:
    try:
        switch.disable(by=body.by, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    logger.warning("api.kill_switch_disabled", by=body.by, reason=body.reason)
    return _to_status(switch)


# ---------------------------------------------------------------------------
# On-call roster (L21)
# ---------------------------------------------------------------------------


def _roster_to_schema(row: OnCallRosterEntry) -> RosterEntry:
    return RosterEntry(
        id=row.id,
        role=row.role,
        contact=row.contact,
        priority_order=row.priority_order,
        active=row.active,
    )


@router.get("/roster", response_model=list[RosterEntry])
def list_roster(
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin")),
) -> list[RosterEntry]:
    stmt = select(OnCallRosterEntry).order_by(OnCallRosterEntry.priority_order)
    return [_roster_to_schema(row) for row in db.scalars(stmt)]


@router.post("/roster", response_model=RosterEntry, status_code=status.HTTP_201_CREATED)
def create_roster_entry(
    body: RosterEntryCreate,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin")),
) -> RosterEntry:
    row = OnCallRosterEntry(
        role=body.role,
        contact=body.contact,
        priority_order=body.priority_order,
        active=body.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("api.roster_entry_created", role=body.role, priority_order=body.priority_order)
    return _roster_to_schema(row)


@router.patch("/roster/{entry_id}", response_model=RosterEntry)
def update_roster_entry(
    entry_id: int,
    body: RosterEntryUpdate,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin")),
) -> RosterEntry:
    row = db.get(OnCallRosterEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"roster entry {entry_id} not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    logger.info("api.roster_entry_updated", entry_id=entry_id, fields=list(updates.keys()))
    return _roster_to_schema(row)


@router.delete("/roster/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_roster_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin")),
) -> None:
    row = db.get(OnCallRosterEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"roster entry {entry_id} not found")
    db.delete(row)
    db.commit()
    logger.info("api.roster_entry_deleted", entry_id=entry_id)


# ---------------------------------------------------------------------------
# Override review (L28)
# ---------------------------------------------------------------------------


@router.get("/overrides", response_model=list[dict[str, Any]])
def list_overrides(
    limit: int = 50,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin", "doctor")),
) -> list[dict[str, Any]]:
    """List rejection, human handoff, and auto-escalation override events for
    clinical review (architecture.md loop L28)."""
    override_events = ("rejected", "auto_escalated", "human_handoff", "referral_declined")
    stmt = (
        select(AuditEventRow)
        .where(AuditEventRow.event.in_(override_events))
        .order_by(AuditEventRow.timestamp.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt))
    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "event": r.event,
            "actor": r.actor,
            "timestamp": r.timestamp.isoformat(),
            "protocol_version": r.protocol_version,
            "detail": r.detail,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Retention purge (L29)
# ---------------------------------------------------------------------------


@router.post("/purge", response_model=PurgeRetentionResponse)
def execute_purge(
    body: PurgeRetentionRequest,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("admin")),
) -> PurgeRetentionResponse:
    """Execute scheduled or manual retention purge of old transcripts and audio
    references (architecture.md loop L29)."""
    cutoff = datetime.now(UTC) - timedelta(days=body.retention_days)
    purged = purge_retention(db, retention_cutoff=cutoff, actor=body.actor)
    db.commit()
    logger.info("api.retention_purged", purged_count=purged, cutoff=cutoff.isoformat(), by=body.actor)
    return PurgeRetentionResponse(purged_tasks=purged, cutoff=cutoff)
