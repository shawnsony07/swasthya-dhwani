"""Read-only admin insights for the clinician/admin portal.

- `GET /admin/routing`: which cases were routed to which facility under
  which tier. The facility is whatever the deterministic rule engine put
  on the task (`hospital_tier_required` from `disease_triage_matrix.json`);
  nothing here recomputes or overrides a tier.
- `GET /admin/metrics`: aggregate call/interpretation telemetry. A metric
  with no samples reports `mean=None`, never 0 - an absent measurement is
  not a measurement of zero.

Tier wording below comes from `hospital_tier_definitions.md`, which is a
DRAFT not signed off by a clinician. `clinically_signed_off` is therefore
reported as False so the UI keeps the disclaimer visible.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from swasthya.api.auth import require_role
from swasthya.api.db import get_db
from swasthya.api.schemas import (
    AdminMetrics,
    ConfidenceBand,
    FacilityRoute,
    MetricDistribution,
    RoutedCase,
    RoutingBoard,
    TierBucket,
)
from swasthya.contracts import PROTOCOL_VERSION, TERMINAL_STATES, TaskState, Tier
from swasthya.db.models import AuditEventRow, Task

router = APIRouter(prefix="/admin")

# (tier, label, referral window) - wording from hospital_tier_definitions.md.
_TIER_META: list[tuple[Tier, str, str]] = [
    (Tier.C1, "Emergency referral", "Immediate"),
    (Tier.C2, "Urgent referral", "Within hours"),
    (Tier.B, "Non-urgent PHC / outpatient", "Within a few days"),
    (Tier.A, "Routine self-care / advice", "No referral indicated"),
]

_TERMINAL_VALUES = {s.value for s in TERMINAL_STATES}
_CLINICAL_ROLES = ("admin", "doctor")


def _dist(values: list[float]) -> MetricDistribution:
    if not values:
        return MetricDistribution(mean=None, samples=0)
    return MetricDistribution(mean=round(fmean(values), 4), samples=len(values))


def _metric(task: Task, key: str) -> float | None:
    metrics = (task.triage_snapshot or {}).get("call_metrics") or {}
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


@router.get("/routing", response_model=RoutingBoard)
def routing_board(
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role(*_CLINICAL_ROLES)),
) -> RoutingBoard:
    tasks = list(db.scalars(select(Task).order_by(Task.updated_at.desc())))

    tier_counts: dict[str, int] = defaultdict(int)
    by_facility: dict[str, list[Task]] = defaultdict(list)
    unrouted = 0
    for task in tasks:
        if task.tier:
            tier_counts[task.tier] += 1
        if task.hospital:
            by_facility[task.hospital].append(task)
        else:
            unrouted += 1

    facilities: list[FacilityRoute] = []
    for hospital, group in by_facility.items():
        by_tier: dict[str, int] = defaultdict(int)
        for t in group:
            by_tier[t.tier or "unassigned"] += 1
        facilities.append(
            FacilityRoute(
                hospital=hospital,
                total=len(group),
                open=sum(1 for t in group if t.state not in _TERMINAL_VALUES),
                by_tier=dict(by_tier),
                cases=[
                    RoutedCase(
                        task_id=t.task_id,
                        state=TaskState(t.state),
                        tier=Tier(t.tier) if t.tier else None,
                        is_time_critical=t.is_time_critical,
                        updated_at=t.updated_at,
                    )
                    for t in group[:25]
                ],
            )
        )
    facilities.sort(key=lambda f: (-f.open, -f.total, f.hospital))

    return RoutingBoard(
        protocol_version=PROTOCOL_VERSION,
        clinically_signed_off=False,
        tiers=[
            TierBucket(tier=tier, label=label, referral_window=window, count=tier_counts.get(tier.value, 0))
            for tier, label, window in _TIER_META
        ],
        facilities=facilities,
        unrouted=unrouted,
        total=len(tasks),
    )


def _decision_latencies(db: Session) -> list[float]:
    """Seconds from `approval_requested` to the first decision event
    (approved / rejected / auto_escalated) per task."""
    decisions = {"approved", "rejected", "auto_escalated"}
    rows = db.scalars(
        select(AuditEventRow)
        .where(AuditEventRow.event.in_(["approval_requested", *decisions]))
        .order_by(AuditEventRow.timestamp.asc(), AuditEventRow.id.asc())
    )
    requested_at: dict[str, object] = {}
    latencies: list[float] = []
    for row in rows:
        if row.event == "approval_requested":
            requested_at[row.task_id] = row.timestamp
        elif row.task_id in requested_at:
            start = requested_at.pop(row.task_id)
            latencies.append((row.timestamp - start).total_seconds())  # type: ignore[operator]
    return latencies


@router.get("/metrics", response_model=AdminMetrics)
def admin_metrics(
    db: Session = Depends(get_db),
    _roles: set[str] = Depends(require_role(*_CLINICAL_ROLES)),
) -> AdminMetrics:
    tasks = list(db.scalars(select(Task)))

    by_tier: dict[str, int] = defaultdict(int)
    by_state: dict[str, int] = defaultdict(int)
    interp: list[float] = []
    stt: list[float] = []
    duration: list[float] = []
    ttfb: list[float] = []
    ttft: list[float] = []
    for task in tasks:
        by_state[task.state] += 1
        if task.tier:
            by_tier[task.tier] += 1
        snap = task.triage_snapshot or {}
        conf = snap.get("interpretation_confidence")
        if isinstance(conf, (int, float)):
            interp.append(float(conf))
        for bucket, key in (
            (stt, "stt_confidence_mean"),
            (duration, "call_duration_seconds"),
            (ttfb, "tts_ttfb_ms_mean"),
            (ttft, "llm_ttft_ms_mean"),
        ):
            value = _metric(task, key)
            if value is not None:
                bucket.append(value)

    bands = [
        ConfidenceBand(label="< 0.60", count=sum(1 for c in interp if c < 0.6)),
        ConfidenceBand(label="0.60 - 0.84", count=sum(1 for c in interp if 0.6 <= c < 0.85)),
        ConfidenceBand(label=">= 0.85", count=sum(1 for c in interp if c >= 0.85)),
    ]

    return AdminMetrics(
        total_cases=len(tasks),
        open_cases=sum(1 for t in tasks if t.state not in _TERMINAL_VALUES),
        time_critical=sum(1 for t in tasks if t.is_time_critical),
        by_tier=dict(by_tier),
        by_state=dict(by_state),
        auto_escalated=by_state.get(TaskState.AUTO_ESCALATED.value, 0),
        human_handoff=by_state.get(TaskState.HUMAN_HANDOFF.value, 0),
        interpretation_confidence=_dist(interp),
        confidence_bands=bands,
        stt_confidence=_dist(stt),
        call_duration_seconds=_dist(duration),
        tts_ttfb_ms=_dist(ttfb),
        llm_ttft_ms=_dist(ttft),
        decision_latency_seconds=_dist(_decision_latencies(db)),
    )
