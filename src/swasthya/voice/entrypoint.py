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
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta

import structlog
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import google, sarvam
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from swasthya.contracts import (
    TERMINAL_STATES,
    ActionOutcome,
    ActionRequest,
    ActionType,
    ConfirmedByAction,
    SpeechOnset,
    TaskState,
    Tier,
    TriageData,
    TriageResult,
)
from swasthya.db.kill_switch_store import DbKillSwitchStore
from swasthya.db.models import Task
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.fhir import adapter as fhir_adapter
from swasthya.fhir.redact import hash_identifier
from swasthya.gateway.action_gateway import ActionGateway
from swasthya.gateway.allowlist import AllowList
from swasthya.gateway.kill_switch import KillSwitch
from swasthya.gateway.providers.base import EmergencyCallProvider
from swasthya.gateway.providers.null_providers import (
    LoggingDeviceProvider,
    LoggingEmergencyCallProvider,
    NeutralVoiceProvider,
)
from swasthya.gateway.rate_limiter import RateLimiter
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
        self.call_metrics: CallMetricsCollector | None = None
        self._snapshot_task_ids: list[str] = []

    def finalize_call_metrics(self) -> None:
        """Re-stamp call_metrics with the real end time/duration on every
        task this call saved a snapshot for. Failure here must never break
        call teardown."""
        if self.call_metrics is None:
            return
        try:
            data = self.call_metrics.snapshot()
            for task_id in self._snapshot_task_ids:
                task = self._session.get(Task, task_id)
                if task is not None and task.triage_snapshot is not None:
                    task.triage_snapshot = {**task.triage_snapshot, "call_metrics": data}
            self._session.commit()
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            logger.warning("voice.call_metrics_finalize_failed", error=str(exc))

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
        if self.call_metrics is not None:
            task.triage_snapshot = {
                **task.triage_snapshot,
                "call_metrics": self.call_metrics.snapshot(),
            }
        if task_id not in self._snapshot_task_ids:
            self._snapshot_task_ids.append(task_id)
        self._session.commit()

    def find_open_task_for_identifier(self, patient_identifier: str) -> str | None:
        target_hash = hash_identifier(patient_identifier)
        terminal_values = [state.value for state in TERMINAL_STATES]
        stmt = (
            select(Task)
            .where(Task.patient_identifier_hash == target_hash)
            .where(Task.state.notin_(terminal_values))
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        task = self._session.scalars(stmt).first()
        return task.task_id if task is not None else None


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


# Process-wide, not per-call: the kill switch, rate limiter, and allow-list
# all hold state that must persist across calls (a kill switch engaged for
# one call must still be engaged for the next; a rate limit is meaningless
# if it resets every call). Built lazily so importing this module never
# has side effects.
_action_gateway: ActionGateway | None = None
_gateway_allow_list: AllowList | None = None


def _build_emergency_call_provider() -> EmergencyCallProvider:
    """Real Twilio is opt-in via `EMERGENCY_CALL_PROVIDER=twilio`, never
    the default — a deployment with no Twilio credentials configured must
    fall back to the logging provider, not crash or silently fail every
    emergency call. `TwilioEmergencyCallProvider.__init__` itself raises
    `TwilioConfigurationError` if credentials are missing, so choosing
    `twilio` without `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/
    `TWILIO_FROM_NUMBER` fails loudly at startup, not on the first real
    emergency."""
    provider_choice = os.environ.get("EMERGENCY_CALL_PROVIDER", "logging").strip().lower()
    if provider_choice == "twilio":
        from swasthya.gateway.providers.twilio_provider import TwilioEmergencyCallProvider

        logger.info("gateway.emergency_provider", provider="twilio")
        return TwilioEmergencyCallProvider()
    logger.info("gateway.emergency_provider", provider="logging")
    return LoggingEmergencyCallProvider()


def _get_action_gateway() -> tuple[ActionGateway, AllowList]:
    global _action_gateway, _gateway_allow_list
    if _action_gateway is None:
        _gateway_allow_list = AllowList()
        # SmartThings/a real voice-clone vendor are not wired in — no
        # credentials for them exist yet. The emergency call provider is
        # real Twilio when EMERGENCY_CALL_PROVIDER=twilio is set, the
        # logging stand-in otherwise — see _build_emergency_call_provider.
        # The kill switch is DB-backed (not the in-memory default) because
        # it must be the same switch an admin flips from the API process
        # — see DbKillSwitchStore's docstring.
        _action_gateway = ActionGateway(
            allow_list=_gateway_allow_list,
            rate_limiter=RateLimiter(),
            kill_switch=KillSwitch(DbKillSwitchStore(_get_session_factory())),
            emergency_provider=_build_emergency_call_provider(),
            device_provider=LoggingDeviceProvider(),
            voice_provider=NeutralVoiceProvider(),
        )
    assert _gateway_allow_list is not None
    return _action_gateway, _gateway_allow_list


class _EmergencyDispatcherAdapter:
    """Adapts `ActionGateway` to the `conversation_contracts.
    EmergencyDispatcher` Protocol. Resolves which contacts to try and in
    what order (architecture.md F7/L22), then dispatches through the real
    gateway policy (allow-list, rate limit, kill switch, idempotency,
    audit) exactly as any other action would.
    """

    _ACTION_EXPIRY_SECONDS = 30.0

    async def dispatch_emergency(self, patient_id: str, message: str) -> ActionOutcome:
        gateway, allow_list = _get_action_gateway()
        effective_patient_id = patient_id or "unknown_caller"

        targets = allow_list.ordered_targets(effective_patient_id)
        if not targets:
            # L22: an unenrolled (or not-yet-identified) caller still gets
            # a real emergency target — the on-call contact, not silence.
            default_contact = os.environ.get("DEFAULT_EMERGENCY_CONTACT", "")
            if default_contact:
                # Registering the fallback contact here is trusted system
                # configuration, not speech-derived input — the allow-list
                # rule it must never violate is "speech cannot add
                # contacts," which this isn't.
                allow_list.add_entry(
                    effective_patient_id, default_contact, kind="contact"
                )
                targets = [default_contact]

        if not targets:
            logger.error(
                "emergency.no_target_configured", patient_id=effective_patient_id
            )
            return ActionOutcome.EMERGENCY_CALL_FAILED

        now = datetime.now(UTC)
        outcome = ActionOutcome.EMERGENCY_CALL_FAILED
        for target in targets:
            action = ActionRequest(
                action_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
                type=ActionType.EMERGENCY_CALL,
                target=target,
                payload={"message": message},
                confirmed_by=ConfirmedByAction.EMERGENCY_WINDOW,
                confirmed_at=now,
                expires_at=now + timedelta(seconds=self._ACTION_EXPIRY_SECONDS),
            )
            outcome = await gateway.dispatch(action, effective_patient_id)
            if outcome is ActionOutcome.EMERGENCY_CALLED:
                return outcome
            logger.warning(
                "emergency.contact_attempt_failed",
                patient_id=effective_patient_id,
                target=target,
                outcome=outcome.value,
            )
        return outcome


def _build_llm() -> FallbackAdapter:
    primary_model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
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
        # The plugin's own defaults don't work against the live API as of
        # this build: `speaker` defaults to `None` (Sarvam 400s with no
        # speaker), and `model` defaults to "bulbul:v2", which Sarvam has
        # since deprecated server-side ("Model 'bulbul:v2' has been
        # deprecated. Please use 'bulbul:v3' instead."). Both overridden
        # here and verified against the real API: a bulbul:v3 + "priya"
        # request returns real synthesized Malayalam audio.
        tts=sarvam.TTS(
            target_language_code="ml-IN",
            model=os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3"),
            speaker=os.environ.get("SARVAM_TTS_VOICE", "priya"),
        ),
        # AgentSession bundles Silero VAD by default (livekit-agents 1.6+);
        # no explicit vad= needed, and the standalone silero plugin package
        # this would otherwise use is deprecated.
    )

    workflow_sink = _WorkflowSinkAdapter(_get_session_factory())
    workflow_sink.call_metrics = CallMetricsCollector(
        room=ctx.room.name,
        channel="sip" if str(ctx.room.name).startswith("sip-") else "web",
        language="ml-IN",
        stt_model="sarvam",
        tts_model=os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3"),
        tts_voice=os.environ.get("SARVAM_TTS_VOICE", "priya"),
        llm_model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    )

    def _on_metrics(ev: object) -> None:
        try:
            workflow_sink.call_metrics.ingest_livekit_metric(getattr(ev, "metrics", ev))  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a call
            logger.warning("voice.call_metrics_ingest_failed", error=str(exc))

    session.on("metrics_collected", _on_metrics)
    ctx.add_shutdown_callback(_close_workflow_sink(workflow_sink))

    orchestrator = ConversationOrchestrator(
        rule_engine=_RuleEngineAdapter(),
        workflow=workflow_sink,
        fhir=_FhirSinkAdapter(),
        emergency=_EmergencyDispatcherAdapter(),
    )

    async def _disconnect_room() -> None:
        try:
            logger.info("voice.room_disconnecting", room=ctx.room.name)
            await ctx.room.disconnect()
        except Exception as exc:
            logger.warning("voice.room_disconnect_error", error=str(exc))

    agent = MalayalamTriageAgent(orchestrator, on_session_end=_disconnect_room)

    await session.start(agent=agent, room=ctx.room)
    logger.info("voice.session_started", room=ctx.room.name)


def _close_workflow_sink(workflow_sink: _WorkflowSinkAdapter) -> Callable[[], Coroutine[None, None, None]]:
    async def _callback() -> None:
        workflow_sink.finalize_call_metrics()
        workflow_sink.close()

    return _callback


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
