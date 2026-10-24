"""Shared, versioned data contracts for the triage spine.

Every module (rule engine, FHIR adapter, interpreter, workflow, action
gateway) imports from here rather than redefining these shapes. See
docs/architecture.md section 6 for the narrative version of these contracts.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "2025.11.01"


# ---------------------------------------------------------------------------
# TRIAGE_DATA v2 (architecture.md section 6)
# ---------------------------------------------------------------------------


class SpeechOnset(str, Enum):
    NEW = "new"
    CHRONIC = "chronic"
    UNKNOWN = "unknown"


class ConfirmedBy(str, Enum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    NONE = "none"


class TriageData(BaseModel):
    schema_version: Literal[2] = 2

    patient_identifier: str
    identifier_type: str

    symptoms: list[str] = Field(default_factory=list)
    symptom_duration_days: int = 0
    warning_signs_present: list[str] = Field(default_factory=list)
    patient_language_verbatim: str = ""

    raw_transcript: str = ""
    interpreted_text: str = ""
    interpretation_confidence: float = 0.0
    speech_impairment_signals: list[str] = Field(default_factory=list)
    speech_onset: SpeechOnset = SpeechOnset.UNKNOWN

    confirmed_by: ConfirmedBy = ConfirmedBy.NONE
    interpreter_model: str = ""
    protocol_version: str = PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Interpreter output contract (architecture.md section 4)
# ---------------------------------------------------------------------------

IMPAIRMENT_SIGNALS = (
    "slurred",
    "word_finding_pause",
    "broken_phrases",
    "slow_rate",
    "repetition",
)


class InterpreterOutput(BaseModel):
    interpretation: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: list[str] = Field(default_factory=list)
    impairment_signals: list[str] = Field(default_factory=list)
    emergency_terms_heard: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rule engine result contract
# ---------------------------------------------------------------------------


class Tier(str, Enum):
    A = "A"
    B = "B"
    C1 = "C1"
    C2 = "C2"


class TriageResult(BaseModel):
    """Pure function output of the rule engine. Never set by an LLM field."""

    matched: bool
    tier: Tier | None = None
    condition: str | None = None
    hospital_tier_required: str | None = None
    floor_applied: bool = False
    floor_reason: str | None = None
    protocol_version: str = PROTOCOL_VERSION
    no_match_reason: str | None = None  # set when matched is False (T3)


# ---------------------------------------------------------------------------
# A2A task states (architecture.md section 6)
# ---------------------------------------------------------------------------


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    AWAITING_APPROVAL = "awaiting_approval"
    HUMAN_HANDOFF = "human_handoff"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_ESCALATED = "auto_escalated"
    AWAITING_HOSPITAL = "awaiting_hospital"
    AMBULANCE_REQUESTED = "ambulance_requested"
    FOLLOW_UP = "follow_up"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATES = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
)

# Allowed transitions, enforced by the workflow state machine.
ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.SUBMITTED: frozenset({TaskState.WORKING}),
    TaskState.WORKING: frozenset(
        {TaskState.AWAITING_APPROVAL, TaskState.HUMAN_HANDOFF, TaskState.FAILED}
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {TaskState.APPROVED, TaskState.REJECTED, TaskState.AUTO_ESCALATED}
    ),
    TaskState.HUMAN_HANDOFF: frozenset({TaskState.APPROVED, TaskState.REJECTED}),
    TaskState.APPROVED: frozenset({TaskState.AWAITING_HOSPITAL, TaskState.COMPLETED}),
    TaskState.AUTO_ESCALATED: frozenset(
        {TaskState.AWAITING_HOSPITAL, TaskState.COMPLETED}
    ),
    TaskState.REJECTED: frozenset({TaskState.WORKING}),
    TaskState.AWAITING_HOSPITAL: frozenset(
        {TaskState.FOLLOW_UP, TaskState.AWAITING_HOSPITAL}
    ),
    TaskState.AMBULANCE_REQUESTED: frozenset(
        {TaskState.FOLLOW_UP, TaskState.FAILED}
    ),
    TaskState.FOLLOW_UP: frozenset({TaskState.COMPLETED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELED: frozenset(),
}


# ---------------------------------------------------------------------------
# Action gateway contract (architecture.md section 4)
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    EMERGENCY_CALL = "emergency_call"
    DEVICE_COMMAND = "device_command"
    SPEAK_AS_PATIENT = "speak_as_patient"


class ConfirmedByAction(str, Enum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    EMERGENCY_WINDOW = "emergency_window"


class ActionRequest(BaseModel):
    action_id: str
    idempotency_key: str
    type: ActionType
    target: str
    payload: dict = Field(default_factory=dict)
    confirmed_by: ConfirmedByAction
    confirmed_at: datetime
    expires_at: datetime


class ActionOutcome(str, Enum):
    EMERGENCY_CALLED = "EMERGENCY_CALLED"
    EMERGENCY_CALL_FAILED = "EMERGENCY_CALL_FAILED"
    DEVICE_ACTION_DONE = "DEVICE_ACTION_DONE"
    DEVICE_ACTION_FAILED = "DEVICE_ACTION_FAILED"
    SPOKEN_AS_PATIENT = "SPOKEN_AS_PATIENT"
    SPOKEN_NEUTRAL = "SPOKEN_NEUTRAL"
    REJECTED = "REJECTED"


class AuditEvent(BaseModel):
    task_id: str
    event: str
    actor: str  # patient | caregiver | agent | rule_engine | doctor | system
    timestamp: datetime
    protocol_version: str = PROTOCOL_VERSION
    model_id: str | None = None
    detail: dict = Field(default_factory=dict)
