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

import structlog
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import google, sarvam

from swasthya.contracts import SpeechOnset, Tier, TriageResult
from swasthya.protocol.kerala_protocol_mcp import apply_acuity_floor, query_triage_protocol
from swasthya.voice.agent import MalayalamTriageAgent
from swasthya.voice.conversation import ConversationOrchestrator
from swasthya.workflow.weft_workflow import submit_task

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
    """Adapts `weft_workflow` (which needs a SQLAlchemy Session) to the
    session-less `WorkflowSink` Protocol. A real deployment injects a
    request-scoped session here; see the TODO below."""

    def __init__(self) -> None:
        # TODO(pilot): replace with a real SQLAlchemy session factory wired
        # to DATABASE_URL once this agent runs inside the full service mesh
        # rather than standalone. Tracked as a known gap, not hidden.
        self._session = None

    def submit_task(self, is_time_critical: bool) -> str:
        if self._session is None:
            raise RuntimeError(
                "WorkflowSinkAdapter has no database session configured; "
                "wire DATABASE_URL and a session factory before deploying."
            )
        task = submit_task(self._session, task_id=_new_task_id(), is_time_critical=is_time_critical)
        return task.task_id

    def mark_awaiting_approval(self, task_id: str, tier: object, hospital: str | None) -> None:
        raise NotImplementedError("wire to weft_workflow.transition(AWAITING_APPROVAL) once the session is live")

    def mark_human_handoff(self, task_id: str, reason: str) -> None:
        raise NotImplementedError("wire to weft_workflow.transition(HUMAN_HANDOFF) once the session is live")


def _new_task_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _build_llm() -> FallbackAdapter:
    primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash")
    return FallbackAdapter(
        [google.LLM(model=primary_model), google.LLM(model=fallback_model)],
        attempt_timeout=8.0,
    )


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

    orchestrator = ConversationOrchestrator(
        rule_engine=_RuleEngineAdapter(), workflow=_WorkflowSinkAdapter()
    )
    agent = MalayalamTriageAgent(orchestrator)

    await session.start(agent=agent, room=ctx.room)
    logger.info("voice.session_started", room=ctx.room.name)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
