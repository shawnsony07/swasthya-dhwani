"""Tests for the pure confirmation-loop state machine
(docs/architecture.md section 4 and loop L1 in section 14).

Uses fake `RuleEngine`/`WorkflowSink` implementations that satisfy the
Protocols in `swasthya.voice.conversation_contracts` — no import from
`protocol/` or `workflow/` is needed, keeping this module's tests decoupled
from the real rule engine and workflow database layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from swasthya.contracts import SpeechOnset, Tier, TriageResult
from swasthya.interpreter.confidence_policy import PolicyDecision
from swasthya.voice.conversation import ConversationOrchestrator, ConversationState
from swasthya.voice.conversation_contracts import (
    MAX_READBACK_FAILURES,
    ConversationOutcomeKind,
    FactKey,
    PendingFact,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeRuleEngine:
    query_result: TriageResult
    floor_result: TriageResult | None = None
    query_calls: list[tuple[list[str], list[str]]] = field(default_factory=list)
    floor_calls: list[tuple] = field(default_factory=list)

    def query(self, symptoms: list[str], warning_signs: list[str]) -> TriageResult:
        self.query_calls.append((symptoms, warning_signs))
        return self.query_result

    def apply_floor(
        self,
        result: TriageResult,
        speech_impairment_signals: list[str],
        speech_onset: SpeechOnset,
        interpretation_confidence: float,
    ) -> TriageResult:
        self.floor_calls.append(
            (result, speech_impairment_signals, speech_onset, interpretation_confidence)
        )
        return self.floor_result if self.floor_result is not None else result


@dataclass
class FakeWorkflowSink:
    next_task_id: str = "task-1"
    calls: list[tuple] = field(default_factory=list)

    def submit_task(self, is_time_critical: bool) -> str:
        self.calls.append(("submit_task", is_time_critical))
        return self.next_task_id

    def mark_awaiting_approval(self, task_id: str, tier, hospital) -> None:
        self.calls.append(("mark_awaiting_approval", task_id, tier, hospital))

    def mark_human_handoff(self, task_id: str, reason: str) -> None:
        self.calls.append(("mark_human_handoff", task_id, reason))


def make_fact(
    key: FactKey,
    value: str = "fever",
    confidence: float = 0.95,
    alternatives: list[str] | None = None,
    impairment_signals: list[str] | None = None,
    speech_onset: SpeechOnset = SpeechOnset.UNKNOWN,
) -> PendingFact:
    return PendingFact(
        key=key,
        interpreted_value=value,
        confidence=confidence,
        alternatives=alternatives or [],
        impairment_signals=impairment_signals or [],
        speech_onset=speech_onset,
        raw_transcript=f"raw:{value}",
        interpreter_model="gemini-test",
    )


def matched_result(tier=Tier.B, hospital="taluk", floor_applied=False, floor_reason=None):
    return TriageResult(
        matched=True,
        tier=tier,
        condition="fever_case",
        hospital_tier_required=hospital,
        floor_applied=floor_applied,
        floor_reason=floor_reason,
    )


def no_match_result(reason="nothing matched"):
    return TriageResult(matched=False, no_match_reason=reason)


@pytest.fixture
def orchestrator():
    engine = FakeRuleEngine(query_result=matched_result())
    sink = FakeWorkflowSink()
    return ConversationOrchestrator(engine, sink), engine, sink


# ---------------------------------------------------------------------------
# handle_interpreted_fact
# ---------------------------------------------------------------------------


def test_one_shot_summary_for_clean_high_confidence_fact(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.SYMPTOMS, value="fever, cough", confidence=0.97)

    outcome = orch.handle_interpreted_fact(state, fact, PolicyDecision.ONE_SHOT_SUMMARY)

    assert outcome.kind == ConversationOutcomeKind.SAY_ONE_SHOT_SUMMARY
    assert state.confirmed_facts[FactKey.SYMPTOMS] is fact


def test_per_fact_readback_for_impaired_or_mid_confidence_fact(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(
        FactKey.SYMPTOMS,
        value="chest pain",
        confidence=0.6,
        alternatives=["chess pain"],
        impairment_signals=["slurred"],
    )

    outcome = orch.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)

    assert outcome.kind == ConversationOutcomeKind.SAY_PER_FACT_READBACK
    assert "chest pain" in outcome.speak_text
    assert "or did you mean chess pain?" in outcome.speak_text
    assert state.pending_facts[FactKey.SYMPTOMS] is fact
    assert FactKey.SYMPTOMS not in state.confirmed_facts


def test_reask_increments_failure_counter(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.SYMPTOMS, confidence=0.1)

    outcome = orch.handle_interpreted_fact(state, fact, PolicyDecision.REASK)

    assert outcome.kind == ConversationOutcomeKind.SAY_REASK
    assert state.readback_failure_counts[FactKey.SYMPTOMS] == 1


def test_third_reask_attempt_triggers_human_handoff_never_third_reask(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.SYMPTOMS, confidence=0.1)

    outcomes = [
        orch.handle_interpreted_fact(state, fact, PolicyDecision.REASK)
        for _ in range(MAX_READBACK_FAILURES + 1)
    ]

    # First MAX_READBACK_FAILURES attempts are re-asks...
    for outcome in outcomes[:MAX_READBACK_FAILURES]:
        assert outcome.kind == ConversationOutcomeKind.SAY_REASK
    # ...the one that pushes the counter past the max is a handoff, never a
    # third SAY_REASK.
    assert outcomes[-1].kind == ConversationOutcomeKind.HUMAN_HANDOFF
    assert outcomes[-1].kind != ConversationOutcomeKind.SAY_REASK


def test_emergency_skip_decision_is_rejected(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.SYMPTOMS)
    with pytest.raises(ValueError):
        orch.handle_interpreted_fact(state, fact, PolicyDecision.EMERGENCY_SKIP)


# ---------------------------------------------------------------------------
# handle_confirmation_response
# ---------------------------------------------------------------------------


def test_confirmation_accepted_finalizes_fact(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.WARNING_SIGNS, value="none", confidence=0.6)
    orch.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)

    outcome = orch.handle_confirmation_response(state, FactKey.WARNING_SIGNS, confirmed=True)

    assert outcome.kind == ConversationOutcomeKind.CONTINUE_GATHERING
    assert state.confirmed_facts[FactKey.WARNING_SIGNS].interpreted_value == "none"
    assert FactKey.WARNING_SIGNS not in state.pending_facts


def test_confirmation_rejected_twice_triggers_human_handoff(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.WARNING_SIGNS, value="none", confidence=0.6)
    orch.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)

    first = orch.handle_confirmation_response(state, FactKey.WARNING_SIGNS, confirmed=False)
    assert first.kind == ConversationOutcomeKind.SAY_REASK

    # re-present (second read-back attempt) then reject again
    orch.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)
    second = orch.handle_confirmation_response(state, FactKey.WARNING_SIGNS, confirmed=False)

    assert second.kind == ConversationOutcomeKind.HUMAN_HANDOFF


def test_silence_models_as_confirmed_false_counts_as_failed_attempt(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()
    fact = make_fact(FactKey.WARNING_SIGNS, value="none", confidence=0.6)
    orch.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)

    outcome = orch.handle_confirmation_response(
        state, FactKey.WARNING_SIGNS, confirmed=False, patient_said_alternative_instead=None
    )
    assert outcome.kind == ConversationOutcomeKind.SAY_REASK
    assert state.rejection_counts[FactKey.WARNING_SIGNS] == 1


# ---------------------------------------------------------------------------
# finalize_and_route — full happy path
# ---------------------------------------------------------------------------


def _confirm_all_required(orch, state):
    identifier = make_fact(FactKey.IDENTIFIER, value="9876543210", confidence=0.98)
    symptoms = make_fact(FactKey.SYMPTOMS, value="fever, cough", confidence=0.95)
    warning = make_fact(FactKey.WARNING_SIGNS, value="none", confidence=0.95)

    orch.handle_interpreted_fact(state, identifier, PolicyDecision.ONE_SHOT_SUMMARY)
    orch.handle_interpreted_fact(state, symptoms, PolicyDecision.ONE_SHOT_SUMMARY)
    outcome = orch.handle_interpreted_fact(state, warning, PolicyDecision.ONE_SHOT_SUMMARY)
    return outcome


def test_full_happy_path_calls_rule_engine_and_workflow_in_order_and_returns_referral_ready():
    engine = FakeRuleEngine(query_result=matched_result(tier=Tier.B, hospital="taluk"))
    sink = FakeWorkflowSink(next_task_id="task-happy")
    orch = ConversationOrchestrator(engine, sink)
    state = ConversationState(patient_identifier="9876543210")

    identifier = make_fact(FactKey.IDENTIFIER, value="9876543210", confidence=0.98)
    symptoms = make_fact(FactKey.SYMPTOMS, value="fever, cough", confidence=0.95)
    warning = make_fact(FactKey.WARNING_SIGNS, value="none", confidence=0.95)
    orch.handle_interpreted_fact(state, identifier, PolicyDecision.ONE_SHOT_SUMMARY)
    orch.handle_interpreted_fact(state, symptoms, PolicyDecision.ONE_SHOT_SUMMARY)
    outcome = orch.handle_interpreted_fact(state, warning, PolicyDecision.ONE_SHOT_SUMMARY)

    assert outcome.kind == ConversationOutcomeKind.REFERRAL_READY
    assert outcome.task_id == "task-happy"
    assert outcome.tier == Tier.B
    assert outcome.triage_data is not None
    assert outcome.triage_data.symptoms == ["fever", "cough"]

    assert len(engine.query_calls) == 1
    assert len(engine.floor_calls) == 1
    assert sink.calls[0][0] == "submit_task"
    assert sink.calls[1] == ("mark_awaiting_approval", "task-happy", Tier.B, "taluk")


def test_no_match_still_submits_task_and_returns_human_handoff():
    engine = FakeRuleEngine(query_result=no_match_result("unrecognised symptom combination"))
    sink = FakeWorkflowSink(next_task_id="task-nomatch")
    orch = ConversationOrchestrator(engine, sink)
    state = ConversationState(patient_identifier="111")

    outcome = _confirm_all_required(orch, state)

    assert outcome.kind == ConversationOutcomeKind.HUMAN_HANDOFF
    assert outcome.task_id == "task-nomatch"
    assert sink.calls[0] == ("submit_task", False)
    assert sink.calls[1] == (
        "mark_human_handoff",
        "task-nomatch",
        "unrecognised symptom combination",
    )


# ---------------------------------------------------------------------------
# Time-critical detection
# ---------------------------------------------------------------------------


def test_stroke_floor_triggered_case_submits_time_critical_true():
    base = matched_result(tier=Tier.B)
    floored = matched_result(
        tier=Tier.C1,
        hospital="stroke_unit_or_tertiary",
        floor_applied=True,
        floor_reason="speech_impairment_signals=['slurred'] ... forces the stroke tier floor",
    )
    engine = FakeRuleEngine(query_result=base, floor_result=floored)
    sink = FakeWorkflowSink(next_task_id="task-stroke")
    orch = ConversationOrchestrator(engine, sink)
    state = ConversationState(speech_onset=SpeechOnset.NEW)

    outcome = _confirm_all_required(orch, state)

    assert outcome.kind == ConversationOutcomeKind.REFERRAL_READY
    assert outcome.tier == Tier.C1
    assert sink.calls[0] == ("submit_task", True)


def test_routine_case_submits_time_critical_false():
    engine = FakeRuleEngine(query_result=matched_result(tier=Tier.A, hospital="phc"))
    sink = FakeWorkflowSink(next_task_id="task-routine")
    orch = ConversationOrchestrator(engine, sink)
    state = ConversationState()

    outcome = _confirm_all_required(orch, state)

    assert outcome.kind == ConversationOutcomeKind.REFERRAL_READY
    assert sink.calls[0] == ("submit_task", False)


# ---------------------------------------------------------------------------
# Emergency terms
# ---------------------------------------------------------------------------


def test_emergency_terms_heard_returns_emergency_window_immediately(orchestrator):
    orch, _, _ = orchestrator
    state = ConversationState()

    outcome = orch.handle_emergency_terms(state)

    assert outcome.kind == ConversationOutcomeKind.SAY_EMERGENCY_WINDOW


# ---------------------------------------------------------------------------
# Silence / disconnect
# ---------------------------------------------------------------------------


def test_silence_with_zero_confirmed_facts_creates_no_callback_task(orchestrator):
    orch, _, sink = orchestrator
    state = ConversationState()

    outcome = orch.handle_silence_or_disconnect(state)

    assert outcome.kind == ConversationOutcomeKind.ABANDONED_WITH_CALLBACK
    assert outcome.task_id is None
    assert sink.calls == []


def test_silence_with_at_least_one_confirmed_fact_creates_callback_task(orchestrator):
    orch, _, sink = orchestrator
    state = ConversationState(patient_identifier="123")
    identifier = make_fact(FactKey.IDENTIFIER, value="123", confidence=0.9)
    orch.handle_interpreted_fact(state, identifier, PolicyDecision.ONE_SHOT_SUMMARY)

    outcome = orch.handle_silence_or_disconnect(state)

    assert outcome.kind == ConversationOutcomeKind.ABANDONED_WITH_CALLBACK
    assert outcome.task_id is not None
    assert outcome.triage_data is not None
    assert sink.calls[0][0] == "submit_task"
    assert sink.calls[1][0] == "mark_human_handoff"
