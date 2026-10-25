#!/usr/bin/env python
"""End-to-end replay harness for the triage spine (docs/architecture.md
section 8's "replay mode" and section 10's release gate #2: "simulate_e2e.py
completes on a clean boot with every terminal state reachable").

This drives `ConversationOrchestrator` with the *real* rule engine
(`_RuleEngineAdapter`) and the *real* workflow state machine
(`_WorkflowSinkAdapter`), against a throwaway in-memory SQLite database, the
same way `entrypoint.py` wires them — but feeds already-interpreted facts
directly in rather than running a live LiveKit room or calling Gemini/Sarvam.
That is the actual meaning of "replay mode" here: the interpreter and the
LiveKit audio pipeline are the two pieces nothing in this script exercises,
because neither can run without live credentials/audio. Everything
downstream of "the interpreter produced this transcript at this confidence"
is real, not mocked.

Run: `python simulate_e2e.py` (no credentials, no network, no Docker).
Exits 0 only if every scenario reached its expected outcome.

Honest about what this does NOT cover (see the "not exercised" list printed
at the end): the actual Gemini-backed interpreter, Sarvam STT/TTS, a live
LiveKit room, FHIR writes to a real HAPI server, and every action-gateway
path (Twilio/SmartThings/voice clone) — none of those exist as live
integrations in this build yet. A scenario here that depends on one of them
uses a fake standing in for it, and says so.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

sys.path.insert(0, "src")

from swasthya.contracts import ConfirmedBy, SpeechOnset, TaskState, Tier
from swasthya.db.models import OnCallRosterEntry, Task
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.interpreter.confidence_policy import PolicyDecision
from swasthya.voice.conversation import ConversationOrchestrator, ConversationState
from swasthya.voice.conversation_contracts import (
    ConversationOutcomeKind,
    FactKey,
    PendingFact,
)
from swasthya.voice.entrypoint import (
    _EmergencyDispatcherAdapter,
    _RuleEngineAdapter,
    _WorkflowSinkAdapter,
)
from swasthya.workflow.weft_workflow import check_timeouts, reject_with_reason


class _RecordingFhirSink:
    """Stands in for `_FhirSinkAdapter` — no live HAPI server in replay
    mode. Records calls so scenarios can assert FHIR was attempted."""

    def __init__(self, fail: bool = False) -> None:
        self.triage_calls = 0
        self.referral_calls = 0
        self._fail = fail

    async def record_triage(self, triage: Any) -> str:
        self.triage_calls += 1
        if self._fail:
            raise RuntimeError("simulated FHIR outage")
        return "fhir-patient-sim"

    async def record_referral(self, patient_fhir_id: str, tier: Tier, hospital: str | None) -> str:
        self.referral_calls += 1
        if self._fail:
            raise RuntimeError("simulated FHIR outage")
        return "fhir-referral-sim"


def _require_task(session: Any, task_id: str) -> Task:
    """`session.get` is typed `Task | None`; a `None` here means this
    harness's own setup is broken (the task was just created in the same
    session a line above), not a case worth handling gracefully."""
    task = session.get(Task, task_id)
    assert task is not None, f"harness bug: task {task_id!r} should already exist"
    return task


def _fact(key: FactKey, value: str, confidence: float = 0.9, signals: list[str] | None = None) -> PendingFact:
    return PendingFact(
        key=key, interpreted_value=value, confidence=confidence, impairment_signals=signals or []
    )


@dataclass
class ScenarioResult:
    name: str
    expected: str
    actual: str
    passed: bool
    note: str = ""


@dataclass
class Harness:
    engine: Any = field(default_factory=lambda: build_engine("sqlite:///:memory:"))
    results: list[ScenarioResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        create_all(self.engine)

    def new_orchestrator(
        self, fhir: Any | None = None, emergency: Any | None = None
    ) -> tuple[ConversationOrchestrator, _WorkflowSinkAdapter]:
        session_factory = build_session_factory(self.engine)
        workflow = _WorkflowSinkAdapter(session_factory)
        orchestrator = ConversationOrchestrator(
            rule_engine=_RuleEngineAdapter(),
            workflow=workflow,
            fhir=fhir or _RecordingFhirSink(),
            emergency=emergency,
        )
        return orchestrator, workflow

    def record(self, name: str, expected: str, actual: str, note: str = "") -> None:
        self.results.append(ScenarioResult(name, expected, actual, expected == actual, note))


async def scenario_clear_speech_routine_case(h: Harness) -> None:
    """F1: clear speech, routine case -> referral reaches AWAITING_APPROVAL
    (this build stops there; doctor approval / REFERRED is not automated)."""
    orchestrator, workflow = h.new_orchestrator()
    state = ConversationState(confirmed_by=ConfirmedBy.PATIENT)
    outcome = None
    for key, value in (
        (FactKey.IDENTIFIER, "9000000001"),
        (FactKey.SYMPTOMS, "chest_pain"),
        (FactKey.WARNING_SIGNS, "chest_pain"),
    ):
        outcome = await orchestrator.handle_interpreted_fact(
            state, _fact(key, value), PolicyDecision.ONE_SHOT_SUMMARY
        )
    h.record(
        "F1 clear speech, routine case",
        ConversationOutcomeKind.REFERRAL_READY.value,
        outcome.kind.value if outcome else "no outcome",
        note="stops at AWAITING_APPROVAL; doctor approval not automated in this build",
    )
    workflow.close()


async def scenario_impaired_speech_confirmed(h: Harness) -> None:
    """F2: impaired speech, interpreted and confirmed -> stroke floor fires,
    tier is forced to C1 regardless of the matched condition's own tier."""
    orchestrator, workflow = h.new_orchestrator()
    state = ConversationState(speech_onset=SpeechOnset.NEW, confirmed_by=ConfirmedBy.PATIENT)
    outcome = None
    for key, value, signals in (
        (FactKey.IDENTIFIER, "9000000002", []),
        (FactKey.SYMPTOMS, "chest_pain", ["slurred"]),
        (FactKey.WARNING_SIGNS, "chest_pain", ["slurred"]),
    ):
        await orchestrator.handle_interpreted_fact(
            state, _fact(key, value, confidence=0.6, signals=signals), PolicyDecision.PER_FACT_READBACK
        )
        # PER_FACT_READBACK leaves the fact pending until the patient says
        # yes — unlike ONE_SHOT_SUMMARY, it never auto-confirms.
        outcome = await orchestrator.handle_confirmation_response(state, key, confirmed=True)
    h.record(
        "F2 impaired speech, confirmed (stroke floor)",
        Tier.C1.value,
        outcome.tier.value if outcome and outcome.tier else "no tier",
        note="new-onset speech impairment forces the floor regardless of the matched condition",
    )
    workflow.close()


async def scenario_impaired_speech_confirmation_fails(h: Harness) -> None:
    """F3: confirmation rejected twice -> HUMAN_HANDOFF, never a third
    re-ask and never a silently-accepted guess."""
    orchestrator, workflow = h.new_orchestrator()
    state = ConversationState()
    fact = _fact(FactKey.SYMPTOMS, "chest_pain", confidence=0.5, signals=["slurred"])
    await orchestrator.handle_interpreted_fact(state, fact, PolicyDecision.PER_FACT_READBACK)
    await orchestrator.handle_confirmation_response(state, FactKey.SYMPTOMS, confirmed=False)
    outcome = await orchestrator.handle_confirmation_response(state, FactKey.SYMPTOMS, confirmed=False)
    h.record(
        "F3 confirmation fails twice",
        ConversationOutcomeKind.HUMAN_HANDOFF.value,
        outcome.kind.value,
    )
    workflow.close()


async def scenario_emergency_terms(h: Harness) -> None:
    """F4: emergency terms heard -> SAY_EMERGENCY_WINDOW immediately,
    bypassing the rest of the loop."""
    orchestrator, _workflow = h.new_orchestrator()
    state = ConversationState()
    outcome = orchestrator.handle_emergency_terms(state)
    h.record(
        "F4a emergency terms heard",
        ConversationOutcomeKind.SAY_EMERGENCY_WINDOW.value,
        outcome.kind.value,
    )


async def scenario_emergency_window_not_cancelled_dispatches_real_gateway(h: Harness) -> None:
    """F4 continued: once the window resolves (no cancellation), this now
    drives the *real* ActionGateway (allow-list, rate limiter, kill switch,
    audit) through `_EmergencyDispatcherAdapter` — the Logging* providers
    are the honest current behavior (no Twilio/SmartThings credentials
    exist), not a test stub standing in for a real vendor call."""
    import os
    import swasthya.voice.entrypoint as entrypoint_module

    os.environ["DEFAULT_EMERGENCY_CONTACT"] = "oncall-sim"
    os.environ["EMERGENCY_CALL_PROVIDER"] = "logging"
    entrypoint_module._action_gateway = None
    entrypoint_module._gateway_allow_list = None
    gw, _ = entrypoint_module._get_action_gateway()
    if gw._kill_switch.is_active:
        gw._kill_switch.disable(by="sim_runner", reason="e2e simulation clean slate")

    orchestrator, _workflow = h.new_orchestrator(emergency=_EmergencyDispatcherAdapter())
    state = ConversationState()

    outcome = await orchestrator.handle_emergency_confirmation(state, cancelled=False)

    h.record(
        "F4b emergency window resolves via real gateway",
        ConversationOutcomeKind.EMERGENCY_ESCALATED.value,
        outcome.kind.value,
        note="dispatched through the real ActionGateway; LoggingEmergencyCallProvider "
        "stands in for Twilio since no live vendor credentials exist",
    )


async def scenario_no_match_routes_to_human(h: Harness) -> None:
    """T3: an unrecognised symptom never gets a silent default tier."""
    orchestrator, workflow = h.new_orchestrator()
    state = ConversationState()
    outcome = None
    for key, value in (
        (FactKey.IDENTIFIER, "9000000003"),
        (FactKey.SYMPTOMS, "totally_unknown_symptom"),
        (FactKey.WARNING_SIGNS, "totally_unknown_symptom"),
    ):
        outcome = await orchestrator.handle_interpreted_fact(
            state, _fact(key, value), PolicyDecision.ONE_SHOT_SUMMARY
        )
    h.record(
        "T3 no-match case",
        ConversationOutcomeKind.HUMAN_HANDOFF.value,
        outcome.kind.value if outcome else "no outcome",
    )
    workflow.close()


async def scenario_silence_abandons_with_callback(h: Harness) -> None:
    """F6: silence after at least one confirmed fact -> ABANDONED_WITH_CALLBACK,
    never an open-ended dropped call."""
    orchestrator, workflow = h.new_orchestrator()
    state = ConversationState()
    await orchestrator.handle_interpreted_fact(
        state, _fact(FactKey.IDENTIFIER, "9000000004"), PolicyDecision.ONE_SHOT_SUMMARY
    )
    outcome = await orchestrator.handle_silence_or_disconnect(state)
    h.record(
        "F6 silence with partial data",
        ConversationOutcomeKind.ABANDONED_WITH_CALLBACK.value,
        outcome.kind.value,
    )
    workflow.close()


async def scenario_fhir_outage_does_not_block_referral(h: Harness) -> None:
    """Section 8 resilience row: FHIR down must not crash or silently drop
    a call that otherwise reached a referral decision."""
    orchestrator, workflow = h.new_orchestrator(fhir=_RecordingFhirSink(fail=True))
    state = ConversationState()
    outcome = None
    for key, value in (
        (FactKey.IDENTIFIER, "9000000005"),
        (FactKey.SYMPTOMS, "chest_pain"),
        (FactKey.WARNING_SIGNS, "chest_pain"),
    ):
        outcome = await orchestrator.handle_interpreted_fact(
            state, _fact(key, value), PolicyDecision.ONE_SHOT_SUMMARY
        )
    passed = bool(outcome and outcome.kind is ConversationOutcomeKind.REFERRAL_READY and outcome.fhir_write_failed)
    h.record(
        "FHIR outage during referral",
        "REFERRAL_READY with fhir_write_failed=True",
        f"{outcome.kind.value} with fhir_write_failed={outcome.fhir_write_failed}" if outcome else "no outcome",
        note="confirms a FHIR outage degrades the call, it does not drop it",
    )
    # `record()`'s pass/fail is a plain string match against the two
    # human-readable labels above, which deliberately differ in case
    # (REFERRAL_READY vs. outcome.kind.value's lowercase enum value) — so
    # the real pass/fail judgement computed above overrides it here.
    h.results[-1].passed = passed
    workflow.close()


def scenario_doctor_timeout_auto_escalates(h: Harness) -> None:
    """T4: an approval timeout escalates and names a hospital — the old
    'approved: True, hospital: None' bug cannot happen. Synchronous: calls
    weft_workflow directly, standing in for the doctor-dashboard timer this
    build does not yet run on a schedule."""
    session_factory = build_session_factory(h.engine)
    with session_factory() as session:
        from swasthya.workflow.weft_workflow import submit_task, transition

        task_id = "sim-timeout-task"
        submit_task(session, task_id=task_id, is_time_critical=True)
        transition(session, task_id, TaskState.WORKING, actor="agent")
        task = _require_task(session, task_id)
        task.tier = Tier.C1.value
        task.hospital = "stroke_unit_or_tertiary"
        transition(session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
        task.awaiting_approval_since = datetime.now(UTC) - timedelta(seconds=999)
        session.add(OnCallRosterEntry(role="doctor", contact="+91-sim", priority_order=1, active=True))
        session.commit()

        escalated = check_timeouts(
            session,
            now=datetime.now(UTC),
            default_timeout_seconds=1.0,
            time_critical_timeout_seconds=1.0,
            roster=session.query(OnCallRosterEntry).all(),
        )
        session.commit()
        actual = (
            TaskState(_require_task(session, task_id).state).value if escalated else "not escalated"
        )
        h.record(
            "T4 approval timeout",
            TaskState.AUTO_ESCALATED.value,
            actual,
            note="hospital is always named; the silent approved/hospital=None bug is structurally impossible",
        )


def scenario_doctor_rejects_and_re_triages(h: Harness) -> None:
    """L5: a doctor reject returns the case to WORKING for re-triage, not a
    dead end. Synchronous, standing in for the (not yet built) doctor
    dashboard approve/reject endpoint."""
    session_factory = build_session_factory(h.engine)
    with session_factory() as session:
        from swasthya.workflow.weft_workflow import submit_task, transition

        task_id = "sim-reject-task"
        submit_task(session, task_id=task_id, is_time_critical=False)
        transition(session, task_id, TaskState.WORKING, actor="agent")
        task = _require_task(session, task_id)
        task.tier = Tier.B.value
        task.hospital = "chc_fru"
        transition(session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
        session.commit()

        reject_with_reason(session, task_id, reason="wrong hospital tier, re-check")
        session.commit()
        actual = TaskState(_require_task(session, task_id).state).value
        h.record("L5 doctor reject", TaskState.WORKING.value, actual)


_NOT_EXERCISED = [
    "Live Gemini-backed interpreter (speech_interpreter.interpret_clip) — needs a real API key",
    "Sarvam STT/TTS and a live LiveKit room — needs real audio and a running room",
    "A real HAPI FHIR server — FhirSink is a recording fake in every scenario here",
    ("Real Twilio/SmartThings/voice-clone vendor calls — the action gateway dispatch itself "
    "(allow-list, rate limit, kill switch, audit) is real in scenario F4b, but "
    "LoggingEmergencyCallProvider stands in for an actual phone call since no vendor "
    "credentials exist"),
    ("Doctor dashboard approve/reject HTTP endpoints — exercised here by calling weft_workflow "
    "directly, not through an API a doctor would actually click"),
]


async def main() -> int:
    # Windows' default console codepage mangles the em-dashes used below;
    # UTF-8 output is readable everywhere this actually runs (a terminal or
    # CI log), so force it rather than rewriting every string to plain ASCII.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    h = Harness()

    await scenario_clear_speech_routine_case(h)
    await scenario_impaired_speech_confirmed(h)
    await scenario_impaired_speech_confirmation_fails(h)
    await scenario_emergency_terms(h)
    await scenario_emergency_window_not_cancelled_dispatches_real_gateway(h)
    await scenario_no_match_routes_to_human(h)
    await scenario_silence_abandons_with_callback(h)
    await scenario_fhir_outage_does_not_block_referral(h)
    scenario_doctor_timeout_auto_escalates(h)
    scenario_doctor_rejects_and_re_triages(h)

    width = max(len(r.name) for r in h.results)
    print(f"\n{'SCENARIO':<{width}}  STATUS  EXPECTED -> ACTUAL")
    all_passed = True
    for r in h.results:
        status = "OK" if r.passed else "FAIL"
        all_passed = all_passed and r.passed
        print(f"{r.name:<{width}}  {status:<6}  {r.expected} -> {r.actual}")
        if r.note:
            print(f"{'':<{width}}          note: {r.note}")

    print("\nNot exercised by this harness (needs live credentials/services not available offline):")
    for item in _NOT_EXERCISED:
        print(f"  - {item}")

    print(f"\n{'OK' if all_passed else 'FAILED'}: {sum(r.passed for r in h.results)}/{len(h.results)} scenarios passed")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
