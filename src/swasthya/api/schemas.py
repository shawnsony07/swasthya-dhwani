"""Pydantic request/response models for the dashboard API.

Field names and nesting match `docs/api_contract.md` exactly — that file
is authoritative; this module is its typed mirror, not an independent
design.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from swasthya.contracts import TaskState, Tier


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


class TaskSummary(BaseModel):
    task_id: str
    state: TaskState
    tier: Tier | None = None
    hospital: str | None = None
    is_time_critical: bool
    created_at: datetime
    updated_at: datetime


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
