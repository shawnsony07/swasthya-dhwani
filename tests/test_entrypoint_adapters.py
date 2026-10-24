"""Integration test for the adapters in `entrypoint.py`: the real rule
engine and the real `weft_workflow` state machine, wired together through
`ConversationOrchestrator`, against an in-memory SQLite database.

This is the one place the triage spine (protocol + db + workflow) and the
voice layer (conversation.py) are exercised together rather than each
against its own fakes — everything else in the suite tests one module at a
time. FHIR is still faked here (no live HAPI server in CI); that boundary
is already covered by `test_conversation.py`'s FHIR-resilience tests.
"""
from __future__ import annotations

from swasthya.contracts import ConfirmedBy, SpeechOnset, TaskState, Tier
from swasthya.db.models import Task
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.interpreter.confidence_policy import PolicyDecision
from swasthya.voice.conversation import ConversationOrchestrator, ConversationState
from swasthya.voice.conversation_contracts import FactKey, PendingFact
from swasthya.voice.entrypoint import _RuleEngineAdapter, _WorkflowSinkAdapter


class _FakeFhirSink:
    def __init__(self) -> None:
        self.triage_calls = 0
        self.referral_calls = 0

    async def record_triage(self, triage: object) -> str:
        self.triage_calls += 1
        return "fhir-patient-1"

    async def record_referral(self, patient_fhir_id: str, tier: Tier, hospital: str | None) -> str:
        self.referral_calls += 1
        return "fhir-referral-1"


def _confirmed_fact(key: FactKey, value: str, *, confidence: float = 0.9) -> PendingFact:
    return PendingFact(key=key, interpreted_value=value, confidence=confidence)


async def _confirm_all_required_facts(
    orchestrator: ConversationOrchestrator, state: ConversationState, *, symptom_value: str
) -> None:
    for key, value in (
        (FactKey.IDENTIFIER, "9999999999"),
        (FactKey.SYMPTOMS, symptom_value),
        (FactKey.WARNING_SIGNS, symptom_value),
    ):
        outcome = await orchestrator.handle_interpreted_fact(
            state, _confirmed_fact(key, value), PolicyDecision.ONE_SHOT_SUMMARY
        )
    return outcome


def _build_adapters(engine) -> tuple[_RuleEngineAdapter, _WorkflowSinkAdapter]:
    session_factory = build_session_factory(engine)
    return _RuleEngineAdapter(), _WorkflowSinkAdapter(session_factory)


async def test_stroke_symptoms_escalate_to_c1_and_persist_time_critical_task():
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    rule_engine, workflow = _build_adapters(engine)
    fhir = _FakeFhirSink()
    orchestrator = ConversationOrchestrator(rule_engine=rule_engine, workflow=workflow, fhir=fhir)
    state = ConversationState(speech_onset=SpeechOnset.NEW, confirmed_by=ConfirmedBy.PATIENT)

    outcome = await _confirm_all_required_facts(orchestrator, state, symptom_value="facial_droop")

    assert outcome.kind.value == "referral_ready"
    assert outcome.tier is Tier.C1
    assert fhir.triage_calls == 1
    assert fhir.referral_calls == 1

    with build_session_factory(engine)() as session:
        task = session.get(Task, outcome.task_id)
        assert task is not None
        assert task.state == TaskState.AWAITING_APPROVAL.value
        assert task.tier == "C1"
        assert task.hospital == "stroke_unit_or_tertiary"
        assert task.is_time_critical is True
        # save_triage_snapshot: the dashboard's raw/interpreted/confidence
        # panel reads this, and the raw identifier must never land here —
        # only its hash.
        assert task.triage_snapshot is not None
        assert task.triage_snapshot["symptoms"] == ["facial_droop"]
        assert task.triage_snapshot["speech_onset"] == "new"
        assert task.patient_identifier_hash != "9999999999"
        assert task.patient_identifier_hash  # non-empty

    workflow.close()


async def test_unrecognised_symptoms_route_to_human_handoff_not_silent_tier():
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    rule_engine, workflow = _build_adapters(engine)
    fhir = _FakeFhirSink()
    orchestrator = ConversationOrchestrator(rule_engine=rule_engine, workflow=workflow, fhir=fhir)
    state = ConversationState()

    outcome = await _confirm_all_required_facts(
        orchestrator, state, symptom_value="nonexistent_symptom_xyz"
    )

    assert outcome.kind.value == "human_handoff"
    assert fhir.triage_calls == 1
    assert fhir.referral_calls == 0  # no tier to refer against

    with build_session_factory(engine)() as session:
        task = session.get(Task, outcome.task_id)
        assert task is not None
        assert task.state == TaskState.HUMAN_HANDOFF.value
        assert task.tier is None  # never a silent default tier (T3)

    workflow.close()


async def test_mark_awaiting_approval_rejects_missing_hospital():
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    _, workflow = _build_adapters(engine)
    task_id = workflow.submit_task(is_time_critical=False)

    try:
        workflow.mark_awaiting_approval(task_id, Tier.B, hospital=None)
    except ValueError as exc:
        assert "hospital=None" in str(exc)
    else:
        raise AssertionError("expected ValueError for hospital=None")
    finally:
        workflow.close()
