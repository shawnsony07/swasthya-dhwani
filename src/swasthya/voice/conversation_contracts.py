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

from swasthya.contracts import SpeechOnset, Tier, TriageData, TriageResult


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


class ConversationOutcome(BaseModel):
    kind: ConversationOutcomeKind
    speak_text: str = ""
    tier: Tier | None = None
    hospital_tier_required: str | None = None
    task_id: str | None = None
    reason: str | None = None
    triage_data: TriageData | None = None


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


MAX_READBACK_FAILURES = 2
