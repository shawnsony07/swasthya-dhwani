"""Pydantic request/response models for the dashboard API.

Field names and nesting match `docs/api_contract.md` exactly — that file
is authoritative; this module is its typed mirror, not an independent
design.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from swasthya.contracts import TaskState, Tier


class CallMetrics(BaseModel):
    """Per-call telemetry captured by the voice agent. Every field is
    optional: a value is only present when it was actually measured, and
    the dashboard renders absent values as "no data" rather than zero."""

    model_config = ConfigDict(extra="ignore")

    connected_at: str | None = None
    ended_at: str | None = None
    call_duration_seconds: float | None = None
    channel: str | None = None  # "web" | "sip" | "unknown"
    room: str | None = None
    language: str | None = None
    stt_model: str | None = None
    stt_confidence_mean: float | None = None
    stt_utterances: int | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_ttfb_ms_mean: float | None = None
    tts_turns: int | None = None
    llm_model: str | None = None
    llm_ttft_ms_mean: float | None = None
    eou_delay_ms_mean: float | None = None
    readback_attempts: int | None = None
    fallback_used: bool | None = None


class TriageSnapshot(BaseModel):
    """Mirrors the dict shape `_WorkflowSinkAdapter.save_triage_snapshot`
    writes into `Task.triage_snapshot` (see `src/swasthya/voice/entrypoint.py`).

    `extra="ignore"` rather than `"forbid"`: this is a point-in-time
    display snapshot (per `Task.triage_snapshot`'s own docstring), not a
    schema the workflow enforces — an older snapshot predating a future
    field addition should still render, not 500.
    """

    model_config = ConfigDict(extra="ignore")

    raw_transcript: str = ""
    interpreted_text: str = ""
    interpretation_confidence: float = 0.0
    symptoms: list[str] = Field(default_factory=list)
    symptom_duration_days: int = 0
    warning_signs_present: list[str] = Field(default_factory=list)
    speech_impairment_signals: list[str] = Field(default_factory=list)
    speech_onset: str = "unknown"
    confirmed_by: str = "none"
    interpreter_model: str = ""
    protocol_version: str = ""
    call_metrics: CallMetrics | None = None


class TaskSummary(BaseModel):
    task_id: str
    state: TaskState
    tier: Tier | None = None
    hospital: str | None = None
    is_time_critical: bool
    created_at: datetime
    updated_at: datetime
    interpretation_confidence: float | None = None
    call_duration_seconds: float | None = None
    language: str | None = None


class TaskDetail(TaskSummary):
    patient_identifier_hash: str
    triage_snapshot: TriageSnapshot | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]
    next_cursor: str | None = None


class ApproveRequest(BaseModel):
    actor: str = Field(min_length=1)


class RejectRequest(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class KillSwitchStatus(BaseModel):
    active: bool
    changed_by: str | None = None
    changed_at: datetime | None = None
    reason: str | None = None


class EngageKillSwitchRequest(BaseModel):
    by: str = Field(min_length=1)
    reason: str | None = None


class DisableKillSwitchRequest(BaseModel):
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RosterEntry(BaseModel):
    id: int
    role: str
    contact: str
    priority_order: int
    active: bool


class RosterEntryCreate(BaseModel):
    role: str = Field(min_length=1)
    contact: str = Field(min_length=1)
    priority_order: int = Field(ge=0)
    active: bool = True


class RosterEntryUpdate(BaseModel):
    """All fields optional: a PATCH only changes what's provided."""

    role: str | None = Field(default=None, min_length=1)
    contact: str | None = Field(default=None, min_length=1)
    priority_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class HospitalResponseRequest(BaseModel):
    actor: str = Field(min_length=1)
    accepted: bool
    re_route_hospital: str | None = None
    reason: str | None = None


class AmbulanceStatusRequest(BaseModel):
    actor: str = Field(min_length=1)
    dispatched: bool
    vehicle_id: str | None = None
    reason: str | None = None


class FollowUpRequest(BaseModel):
    actor: str = Field(min_length=1)
    reached_care: bool
    notes: str | None = None


class PurgeRetentionRequest(BaseModel):
    actor: str = Field(default="system", min_length=1)
    retention_days: int = Field(default=90, ge=1)


class PurgeRetentionResponse(BaseModel):
    purged_tasks: int
    cutoff: datetime


class AuditEventOut(BaseModel):
    id: int
    task_id: str
    event: str
    actor: str
    timestamp: datetime
    protocol_version: str
    model_id: str | None = None
    detail: dict = Field(default_factory=dict)


class TierBucket(BaseModel):
    tier: Tier
    label: str
    referral_window: str
    count: int


class RoutedCase(BaseModel):
    task_id: str
    state: TaskState
    tier: Tier | None = None
    is_time_critical: bool
    updated_at: datetime


class FacilityRoute(BaseModel):
    hospital: str
    total: int
    open: int
    by_tier: dict[str, int]
    cases: list[RoutedCase]


class RoutingBoard(BaseModel):
    protocol_version: str
    clinically_signed_off: bool
    tiers: list[TierBucket]
    facilities: list[FacilityRoute]
    unrouted: int
    total: int


class MetricDistribution(BaseModel):
    """mean is None when no sample exists (never 0 as a stand-in)."""

    mean: float | None = None
    samples: int = 0


class ConfidenceBand(BaseModel):
    label: str
    count: int


class AdminMetrics(BaseModel):
    total_cases: int
    open_cases: int
    time_critical: int
    by_tier: dict[str, int]
    by_state: dict[str, int]
    auto_escalated: int
    human_handoff: int
    interpretation_confidence: MetricDistribution
    confidence_bands: list[ConfidenceBand]
    stt_confidence: MetricDistribution
    call_duration_seconds: MetricDistribution
    tts_ttfb_ms: MetricDistribution
    llm_ttft_ms: MetricDistribution
    decision_latency_seconds: MetricDistribution
