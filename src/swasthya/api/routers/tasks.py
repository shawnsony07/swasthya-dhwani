"""`GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/approve`,
`POST /tasks/{id}/reject` -- exactly per docs/api_contract.md.

Pagination cursor scheme: tasks are ordered newest-first by
`(updated_at, task_id)` (the `task_id` tiebreak matters because several
tasks can share the same `updated_at` timestamp, e.g. two rows touched in
the same timeout sweep). A cursor is the base64url encoding of
`"<updated_at.isoformat()>|<task_id>"` -- the position of the last row
already returned. The next page asks for rows strictly after that
position in the ordering: `updated_at < cursor.updated_at OR
(updated_at == cursor.updated_at AND task_id < cursor.task_id)`. Opaque
to the client by design (contract: "opaque string from a previous
response's `next_cursor`"), so this encoding can change later without
breaking the contract.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from swasthya.api.auth import get_current_roles, require_role
from swasthya.api.db import get_db
from swasthya.api.schemas import (
    ApproveRequest,
    RejectRequest,
    TaskDetail,
    TaskListResponse,
    TaskSummary,
    TriageSnapshot,
)
from swasthya.contracts import TaskState, Tier
from swasthya.db.models import Task
from swasthya.workflow.exceptions import IllegalTransitionError, TaskNotFoundError
from swasthya.workflow.weft_workflow import reject_with_reason, transition

logger = structlog.get_logger(__name__)

router = APIRouter()


def _encode_cursor(task: Task) -> str:
    raw = f"{task.updated_at.isoformat()}|{task.task_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        updated_at_str, task_id = raw.split("|", 1)
        return datetime.fromisoformat(updated_at_str), task_id
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor"
        ) from exc


def _to_summary(task: Task) -> TaskSummary:
    return TaskSummary(
        task_id=task.task_id,
        state=TaskState(task.state),
        tier=Tier(task.tier) if task.tier else None,
        hospital=task.hospital,
        is_time_critical=task.is_time_critical,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _to_detail(task: Task) -> TaskDetail:
    snapshot = TriageSnapshot(**task.triage_snapshot) if task.triage_snapshot else None
    return TaskDetail(
        **_to_summary(task).model_dump(),
        patient_identifier_hash=task.patient_identifier_hash,
        triage_snapshot=snapshot,
    )


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    state: TaskState | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(get_current_roles),
) -> TaskListResponse:
    stmt = select(Task).order_by(Task.updated_at.desc(), Task.task_id.desc())

    if state is not None:
        stmt = stmt.where(Task.state == state.value)

    if cursor is not None:
        cursor_updated_at, cursor_task_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Task.updated_at < cursor_updated_at,
                and_(
                    Task.updated_at == cursor_updated_at,
                    Task.task_id < cursor_task_id,
                ),
            )
        )

    rows = list(db.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
    return TaskListResponse(tasks=[_to_summary(task) for task in rows], next_cursor=next_cursor)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(get_current_roles),
) -> TaskDetail:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"task {task_id!r} not found")
    return _to_detail(task)


@router.post("/tasks/{task_id}/approve", response_model=TaskDetail)
def approve_task(
    task_id: str,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("doctor")),
) -> TaskDetail:
    try:
        task = transition(db, task_id, TaskState.APPROVED, actor=body.actor)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    logger.info("api.task_approved", task_id=task_id, actor=body.actor)
    return _to_detail(task)


@router.post("/tasks/{task_id}/reject", response_model=TaskDetail)
def reject_task(
    task_id: str,
    body: RejectRequest,
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role("doctor", "nurse")),
) -> TaskDetail:
    try:
        task = reject_with_reason(db, task_id, reason=body.reason, actor=body.actor)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    logger.info("api.task_rejected", task_id=task_id, actor=body.actor, reason=body.reason)
    return _to_detail(task)
