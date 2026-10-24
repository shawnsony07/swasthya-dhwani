"""Interface between the LiveKit-specific agent glue (`agent.py`,
`entrypoint.py`) and the pure conversation/read-back logic (`conversation.py`).

Nothing here touches LiveKit, Gemini, or Sarvam directly — it only depends on
`swasthya.contracts` and `swasthya.interpreter`. That is deliberate: the glue
layer is hard to unit-test without a live LiveKit room, so every decision
that can be made in pure Python lives on this side of the line and is fully
covered by tests. See docs/architecture.md section 4 ("Confirmation loop ·
8 states, 3 outcomes") for the state diagram this implements.
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from swasthya.contracts import ActionOutcome, SpeechOnset, Tier, TriageData, TriageResult


class ConversationOutcomeKind(str, Enum):
    """What the voice agent should do next, decided by pure logic."""

    SAY_ONE_SHOT_SUMMARY = "say_one_shot_summary"
    SAY_PER_FACT_READBACK = "say_per_fact_readback"
    SAY_REASK = "say_reask"
    SAY_EMERGENCY_WINDOW = "say_emergency_window"
    AWAIT_CONFIRMATION = "await_confirmation"
    CONTINUE_GATHERING = "continue_gathering"
    REFERRAL_READY = "referral_ready"
    HUMAN_HANDOFF = "human_handoff"
    ABANDONED_WITH_CALLBACK = "abandoned_with_callback"
    EMERGENCY_ESCALATED = "emergency_escalated"
    EMERGENCY_CALL_FAILED = "emergency_call_failed"


class ConversationOutcome(BaseModel):
    kind: ConversationOutcomeKind
    speak_text: str = ""
    tier: Tier | None = None
    hospital_tier_required: str | None = None
    task_id: str | None = None
    reason: str | None = None
    triage_data: TriageData | None = None
    fhir_write_failed: bool = False


class FactKey(str, Enum):
    IDENTIFIER = "identifier"
    SYMPTOMS = "symptoms"
    DURATION = "duration"
    WARNING_SIGNS = "warning_signs"


class PendingFact(BaseModel):
    """One fact awaiting read-back confirmation."""

    key: FactKey
    interpreted_value: str
    alternatives: list[str] = []
    confidence: float
    impairment_signals: list[str] = []
    speech_onset: SpeechOnset = SpeechOnset.UNKNOWN
    raw_transcript: str = ""
    interpreter_model: str = ""


class RuleEngine(Protocol):
    """The subset of `swasthya.protocol.kerala_protocol_mcp` the conversation
    orchestrator needs. Defined as a Protocol so tests can inject a fake
    without importing the real rule engine, and so this module never needs
    to know the rule engine's internal matrix-loading details."""

    def query(self, symptoms: list[str], warning_signs: list[str]) -> TriageResult: ...

    def apply_floor(
        self,
        result: TriageResult,
        speech_impairment_signals: list[str],
        speech_onset: SpeechOnset,
        interpretation_confidence: float,
    ) -> TriageResult: ...


class WorkflowSink(Protocol):
    """The subset of `swasthya.workflow.weft_workflow` the orchestrator
    needs to hand a completed or handed-off case to."""

    def submit_task(self, is_time_critical: bool) -> str:
        """Returns a new task_id."""
        ...

    def mark_awaiting_approval(self, task_id: str, tier: Tier, hospital: str | None) -> None: ...

    def mark_human_handoff(self, task_id: str, reason: str) -> None: ...

    def save_triage_snapshot(self, task_id: str, triage: TriageData) -> None:
        """Persists the raw transcript / interpreted text / confidence /
        symptoms snapshot the doctor dashboard displays (architecture.md
        section 12's "raw vs interpreted vs confidence panel"). Called once
        a case reaches a referral or handoff decision — never for a case
        still mid-confirmation, since the snapshot should reflect the final
        confirmed facts, not an in-progress guess."""
        ...

    def find_open_task_for_identifier(self, patient_identifier: str) -> str | None:
        """Architecture.md loop L26: a second call from the same patient
        while an earlier case is still open joins that case rather than
        starting a new one. "Open" means any non-terminal `TaskState`
        (not `COMPLETED`/`FAILED`/`CANCELED`) — an `AWAITING_APPROVAL` or
        `HUMAN_HANDOFF` case still counts as open. Returns the most
        recently created matching task_id, or `None` if there isn't one
        (the common case — most calls aren't duplicates)."""
        ...


class FhirSink(Protocol):
    """The subset of `swasthya.fhir.adapter` the orchestrator needs to
    persist a confirmed case. Async because the real adapter makes HTTP
    calls to HAPI FHIR — this is the one Protocol on this file's boundary
    that is not sync, so every `ConversationOrchestrator` method able to
    reach `finalize_and_route` (directly or by completing the last required
    fact) must itself be async. See architecture.md section 6 ("FHIR
    writes") and section 8: a FHIR failure must not crash the call, so
    implementations are expected to raise `swasthya.fhir.exceptions.
    FhirUnavailableError`/`FhirRejectedError` rather than anything
    orchestrator code would need to special-case, and the orchestrator
    treats either as "proceed without FHIR history" per that section."""

    async def record_triage(self, triage: TriageData) -> str:
        """Resolves/creates the FHIR Patient, writes symptom Observations
        and the interpretation Provenance, and returns the patient's FHIR
        id for a following `record_referral` call."""
        ...

    async def record_referral(
        self, patient_fhir_id: str, tier: Tier, hospital: str | None
    ) -> str:
        """Writes the referral ServiceRequest and returns its FHIR id."""
        ...


class EmergencyDispatcher(Protocol):
    """The subset of `swasthya.gateway.action_gateway` the orchestrator
    needs for F4 (emergency escalation). Async for the same reason
    `FhirSink` is: the real implementation calls through `ActionGateway`,
    which calls a real `EmergencyCallProvider`.

    Deliberately a single coarse method rather than exposing the gateway's
    allow-list/rate-limit/kill-switch machinery here — this module should
    not need to know how a target contact is resolved or how many are
    tried; `dispatch_emergency` owns all of that (architecture.md F7: try
    enrolled contacts in order, fall back to the on-call contact if none
    are enrolled, per loop L22)."""

    async def dispatch_emergency(self, patient_id: str, message: str) -> ActionOutcome:
        """Raises the emergency action end to end — allow-list/contact
        resolution, confirmation window accounting, dispatch, and the
        dashboard alert on failure are all the implementation's job.
        Returns the outcome of the *last* attempt (e.g. `EMERGENCY_CALLED`
        if any contact answered, `EMERGENCY_CALL_FAILED` if every attempt
        failed)."""
        ...


MAX_READBACK_FAILURES = 2
