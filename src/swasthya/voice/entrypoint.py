"""LiveKit worker entrypoint: wires Sarvam STT/TTS, Gemini (with config-driven
fallback, architecture.md loop L9), Silero VAD, and `MalayalamTriageAgent`
into a running `AgentSession`.

Run with: `python -m swasthya.voice.entrypoint dev` (or `start` in
production) — standard `livekit-agents` CLI, see `livekit.agents.cli`.

Not covered by the automated test suite: this module needs a live LiveKit
room/credentials to execute end-to-end. It is exercised by the (future)
`simulate_e2e.py` replay-mode harness described in docs/architecture.md
section 8, not by pytest. Everything it calls into (`agent.py`'s own logic
delegated to `conversation.py`, the interpreter, the rule engine) is unit
tested on its own.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Coroutine

import structlog
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import google, sarvam
from sqlalchemy.orm import Session, sessionmaker

from swasthya.contracts import SpeechOnset, TaskState, Tier, TriageData, TriageResult
from swasthya.db.models import Task
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.fhir import adapter as fhir_adapter
from swasthya.fhir.redact import hash_identifier
from swasthya.protocol.kerala_protocol_mcp import apply_acuity_floor, query_triage_protocol
from swasthya.voice.agent import MalayalamTriageAgent
from swasthya.voice.conversation import ConversationOrchestrator
from swasthya.workflow.exceptions import TaskNotFoundError
from swasthya.workflow.weft_workflow import new_task_id, submit_task, transition

logger = structlog.get_logger(__name__)


class _RuleEngineAdapter:
    """Adapts the free functions in `kerala_protocol_mcp` to the
    `conversation_contracts.RuleEngine` Protocol the orchestrator expects."""

    def query(self, symptoms: list[str], warning_signs: list[str]) -> TriageResult:
        return query_triage_protocol(symptoms, warning_signs)

    def apply_floor(
        self,
        result: TriageResult,
        speech_impairment_signals: list[str],
        speech_onset: SpeechOnset,
        interpretation_confidence: float,
    ) -> TriageResult:
        confidence_low = float(os.environ.get("INTERPRETER_CONFIDENCE_LOW", "0.35"))
        return apply_acuity_floor(
            result,
            speech_impairment_signals,
            speech_onset,
            interpretation_confidence,
            confidence_low,
        )


class _WorkflowSinkAdapter:
    """Adapts `weft_workflow` (which needs a SQLAlchemy `Session`) to the
    session-less `WorkflowSink` Protocol.

    One instance is constructed per call (see `entrypoint`), opening one
    `Session` for the lifetime of that call and committing after every
    state-changing operation — so a mid-call crash doesn't lose audit rows
    already written for earlier facts, at the cost of one extra round trip
    per transition. That trade-off favors the audit trail (section 9) over
    raw throughput, which is the right side to err on for this module.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session: Session = session_factory()

    def close(self) -> None:
        self._session.close()

    def submit_task(self, is_time_critical: bool) -> str:
        task_id = new_task_id()
        submit_task(self._session, task_id=task_id, is_time_critical=is_time_critical)
        # SUBMITTED -> WORKING immediately: ALLOWED_TRANSITIONS only permits
        # AWAITING_APPROVAL/HUMAN_HANDOFF from WORKING, never straight from
        # SUBMITTED, and the orchestrator's next call is always one of those.
        transition(self._session, task_id, TaskState.WORKING, actor="agent")
        self._session.commit()
        return task_id

    def mark_awaiting_approval(self, task_id: str, tier: Tier, hospital: str | None) -> None:
        if hospital is None:
            # Mirrors the T4 guard in weft_workflow.check_timeouts: a task
            # must never enter AWAITING_APPROVAL with no hospital, or a
            # later timeout would hit MissingHospitalForEscalationError
            # instead of escalating cleanly. Catch it here, at the point
            # the hospital should have been chosen, not downstream.
            raise ValueError(
                f"mark_awaiting_approval called for {task_id} with hospital=None; "
                "the rule engine must set hospital_tier_required for a matched tier."
            )
        task = self._session.get(Task, task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        task.tier = tier.value
        task.hospital = hospital
        transition(self._session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
        self._session.commit()

    def mark_human_handoff(self, task_id: str, reason: str) -> None:
        transition(
            self._session, task_id, TaskState.HUMAN_HANDOFF, actor="rule_engine", reason=reason
        )
        self._session.commit()

    def save_triage_snapshot(self, task_id: str, triage: TriageData) -> None:
        task = self._session.get(Task, task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # `submit_task` (above) creates the row before the identifier is
        # known to this adapter, so this is where `patient_identifier_hash`
        # actually gets set — never the raw identifier itself, matching the
        # S9 constraint the column's own docstring states.
        task.patient_identifier_hash = hash_identifier(triage.patient_identifier)
        task.triage_snapshot = {
            "raw_transcript": triage.raw_transcript,
            "interpreted_text": triage.interpreted_text,
            "interpretation_confidence": triage.interpretation_confidence,
            "symptoms": triage.symptoms,
            "symptom_duration_days": triage.symptom_duration_days,
            "warning_signs_present": triage.warning_signs_present,
            "speech_impairment_signals": triage.speech_impairment_signals,
            "speech_onset": triage.speech_onset.value,
            "confirmed_by": triage.confirmed_by.value,
            "interpreter_model": triage.interpreter_model,
            "protocol_version": triage.protocol_version,
        }
        self._session.commit()


class _FhirSinkAdapter:
    """Adapts the free functions in `swasthya.fhir.adapter` to the
    `conversation_contracts.FhirSink` Protocol the orchestrator expects.

    `adapter.get_or_create_patient`/`write_triage_record`/`write_referral`
    raise `FhirUnavailableError`/`FhirRejectedError` on failure rather than
    returning a sentinel; this adapter deliberately does not catch them —
    `ConversationOrchestrator` is the layer that decides a FHIR failure must
    not block a referral (architecture.md section 8), so catching here would
    just duplicate that policy in two places.
    """

    async def record_triage(self, triage: TriageData) -> str:
        patient_fhir_id = await fhir_adapter.get_or_create_patient(
            triage.patient_identifier, triage.identifier_type
        )
        await fhir_adapter.write_triage_record(triage, patient_fhir_id)
        return patient_fhir_id

    async def record_referral(
        self, patient_fhir_id: str, tier: Tier, hospital: str | None
    ) -> str:
        return await fhir_adapter.write_referral(patient_fhir_id, tier.value, hospital)


def _build_llm() -> FallbackAdapter:
    primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash")
    return FallbackAdapter(
        [google.LLM(model=primary_model), google.LLM(model=fallback_model)],
        attempt_timeout=8.0,
    )


_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    """Builds the process-wide engine/session factory on first use, not at
    import time — importing this module (e.g. from a test) must not try to
    open a database connection. `create_all` is a dev/test convenience; a
    real deployment runs the Alembic migration in `migrations/` instead and
    this call is a no-op against an already-migrated schema."""
    global _session_factory
    if _session_factory is None:
        engine = build_engine()
        create_all(engine)
        _session_factory = build_session_factory(engine)
    return _session_factory


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    session: AgentSession = AgentSession(
        stt=sarvam.STT(language="ml-IN"),
        llm=_build_llm(),
        tts=sarvam.TTS(target_language_code="ml-IN"),
        # AgentSession bundles Silero VAD by default (livekit-agents 1.6+);
        # no explicit vad= needed, and the standalone silero plugin package
        # this would otherwise use is deprecated.
    )

    workflow_sink = _WorkflowSinkAdapter(_get_session_factory())
    ctx.add_shutdown_callback(_close_workflow_sink(workflow_sink))

    orchestrator = ConversationOrchestrator(
        rule_engine=_RuleEngineAdapter(),
        workflow=workflow_sink,
        fhir=_FhirSinkAdapter(),
    )
    agent = MalayalamTriageAgent(orchestrator)

    await session.start(agent=agent, room=ctx.room)
    logger.info("voice.session_started", room=ctx.room.name)


def _close_workflow_sink(workflow_sink: _WorkflowSinkAdapter) -> Callable[[], Coroutine[None, None, None]]:
    async def _callback() -> None:
        workflow_sink.close()

    return _callback


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
