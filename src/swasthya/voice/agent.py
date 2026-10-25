"""The LiveKit-facing voice agent: `MalayalamTriageAgent`.

This module is deliberately thin. Every decision about what to say next, how
confident the interpreter was, or which tier a case gets lives in
`conversation.py` (pure, unit-tested) and the modules it calls
(`interpreter/`, `protocol/`, `workflow/`). This file's only job is to:

1. Tee each turn's raw audio into a `TurnAudioBuffer` (docs/architecture.md
   section 4) while Sarvam STT produces the transcript, via `stt_node`.
2. In `on_user_turn_completed`, hand the transcript + audio clip to the
   speech interpreter, run the confidence policy, and feed the result into
   the pure `ConversationOrchestrator`.
3. Speak whatever scripted line the orchestrator decided on via
   `session.say()` — never via free LLM generation — then raise
   `StopResponse` so Gemini's own automatic reply for that turn is
   suppressed. Scripted safety lines (read-backs, re-asks, the emergency
   window, handoff notices) must be exact, not paraphrased by the model.
   Only when the orchestrator says `CONTINUE_GATHERING` do we let the normal
   LLM-driven conversation proceed (e.g. to ask the next question).

Slot-filling is intentionally simple for this pass: facts are gathered in a
fixed order (identifier, symptoms, warning signs, duration) rather than via
full NLU slot extraction from free dialogue. Real multi-turn, any-order slot
filling is future work — tracked in docs/architecture.md's "Could build" /
roadmap tiers, not promised here.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import structlog
from livekit import rtc
from livekit.agents import Agent, ModelSettings, StopResponse, llm, stt

from swasthya.contracts import ConfirmedBy, SpeechOnset
from swasthya.interpreter.confidence_policy import PolicyDecision, decide
from swasthya.interpreter.speech_interpreter import InterpretationFailed, interpret_clip
from swasthya.voice.audio_tee import TurnAudioBuffer
from swasthya.voice.conversation import ConversationOrchestrator, ConversationState
from swasthya.voice.conversation_contracts import (
    ConversationOutcome,
    ConversationOutcomeKind,
    FactKey,
    PendingFact,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = structlog.get_logger(__name__)

# Fixed slot-filling order for this pass (see module docstring). The agent
# asks for these in sequence; which one a given turn's speech is interpreted
# against is whichever is first still-unconfirmed.
_SLOT_ORDER: tuple[FactKey, ...] = (
    FactKey.IDENTIFIER,
    FactKey.SYMPTOMS,
    FactKey.WARNING_SIGNS,
    FactKey.DURATION,
)

_SLOT_PROMPTS_ML: dict[FactKey, str] = {
    FactKey.IDENTIFIER: "നിങ്ങളുടെ പേരോ തിരിച്ചറിയൽ നമ്പറോ പറയാമോ?",
    FactKey.SYMPTOMS: "ശരി. നിങ്ങൾക്ക് ഇപ്പോൾ എന്തൊക്കെ ബുദ്ധിമുട്ടുകൾ അല്ലെങ്കിൽ ലക്ഷണങ്ങളാണ് ഉള്ളത്?",
    FactKey.WARNING_SIGNS: "മനസ്സിലായി. നെഞ്ചുവേദന, ശ്വാസതടസ്സം, പെട്ടെന്നുള്ള തളർച്ച തുടങ്ങിയ അപായ ലക്ഷണങ്ങൾ ഉണ്ടോ?",
    FactKey.DURATION: "ഈ ലക്ഷണങ്ങൾ തുടങ്ങിയിട്ട് എത്ര സമയമായി?",
}

_OPENING_LINE = (
    "ഇത് ഒരു ട്രയാജ് പിന്തുണയാണ്, രോഗനിർണയം അല്ല. "  # triage support, not diagnosis
    "നിങ്ങളുടെ പേരോ തിരിച്ചറിയൽ നമ്പറോ പറയാമോ?"
)

_EMERGENCY_WINDOW_SECONDS = 5.0

# Crude keyword match for "the patient said something that counts as
# cancelling the emergency window" — English and Malayalam. This is a
# deliberately simple heuristic, not NLU: a false negative (treating a real
# cancel as a non-cancel) still only results in a 108/112 prompt and a
# dashboard alert, never a missed emergency, so the heuristic is allowed to
# err toward escalating rather than toward cancelling.
_CANCELLATION_KEYWORDS = (
    "no",
    "cancel",
    "stop",
    "nothing",
    "i'm fine",
    "im fine",
    "വേണ്ട",  # venda - "don't need (it)"
    "ഇല്ല",  # illa - "no"
)


def _looks_like_cancellation(transcript: str) -> bool:
    lowered = transcript.strip().lower()
    return any(keyword in lowered for keyword in _CANCELLATION_KEYWORDS)


def _confidence_thresholds() -> tuple[float, float]:
    high = float(os.environ.get("INTERPRETER_CONFIDENCE_HIGH", "0.75"))
    low = float(os.environ.get("INTERPRETER_CONFIDENCE_LOW", "0.35"))
    return high, low


class MalayalamTriageAgent(Agent):
    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        *,
        room: rtc.Room | None = None,
        on_session_end: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are a calm Malayalam-speaking triage support voice agent for "
                "Swasthya-Dhwani. You are NOT a diagnostic tool. Ask one short "
                "question at a time: identifier, symptoms, duration, warning signs. "
                "Allow long pauses — the caller may have impaired speech. Never "
                "state a tier, a diagnosis, or a hospital recommendation yourself; "
                "that is decided by a separate rule engine and read back to the "
                "caller by the system, not generated by you."
            ),
        )
        self._orchestrator = orchestrator
        self._room = room
        self._on_session_end = on_session_end
        self._state = ConversationState()
        self._audio_buffer = TurnAudioBuffer()
        self._confidence_high, self._confidence_low = _confidence_thresholds()
        self._gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self._interpreter_api_key = os.environ.get("GEMINI_API_KEY", "")
        # Set while the 5-second emergency confirmation window (F4) is
        # open; the next turn to arrive cancels it. If nothing arrives,
        # the task itself fires the default-to-escalate path (see
        # `_start_emergency_window`).
        self._emergency_task: asyncio.Task[None] | None = None
        self._is_agent_speaking: bool = False
        self._mute_stt_until: float = 0.0
        self._last_spoken_line: str = ""

    async def _set_speaking_state(self, is_speaking: bool, text: str = "") -> None:
        self._is_agent_speaking = is_speaking
        if is_speaking and text:
            self._last_spoken_line = text.strip()
            # Malayalam speech rate in Sarvam Bulbul:v3 is ~10-12 chars/sec
            duration = max(3.5, len(text) * 0.12) + 0.8
            self._mute_stt_until = asyncio.get_event_loop().time() + duration
            logger.info("voice.agent_speaking_started", text_len=len(text), mute_duration=round(duration, 2))

            async def _auto_unmute(wait_s: float) -> None:
                await asyncio.sleep(wait_s)
                if self._is_agent_speaking:
                    await self._set_speaking_state(is_speaking=False)

            asyncio.create_task(_auto_unmute(duration))

        if self._room and self._room.local_participant:
            try:
                state_data = json.dumps({
                    "type": "agent_state",
                    "state": "speaking" if is_speaking else "listening",
                }).encode("utf-8")
                await self._room.local_participant.publish_data(state_data, reliable=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice.publish_agent_state_failed", error=str(exc))

    async def speak_opening(self) -> None:
        """Speaks the triage opening disclaimer and question in Malayalam."""
        logger.info("voice.speaking_opening_line")
        await self._set_speaking_state(True, text=_OPENING_LINE)
        try:
            self.session.say(_OPENING_LINE, add_to_chat_ctx=False, allow_interruptions=False)
        except Exception as exc:  # noqa: BLE001
            logger.error("voice.speak_opening_failed", error=str(exc))
        if self._room and self._room.local_participant:
            try:
                data = json.dumps({"type": "transcript", "sender": "agent", "text": _OPENING_LINE}).encode("utf-8")
                await self._room.local_participant.publish_data(data, reliable=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice.publish_opening_failed", error=str(exc))

    # -- audio tee --------------------------------------------------------

    async def stt_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncGenerator[stt.SpeechEvent, None]:
        async def _tee() -> AsyncIterable[rtc.AudioFrame]:
            async for frame in audio:
                now = asyncio.get_event_loop().time()
                if self._is_agent_speaking or now < self._mute_stt_until:
                    # Drop audio frames while agent's TTS is active (prevents acoustic feedback / self-hearing)
                    continue
                self._audio_buffer.push(frame)
                yield frame

        async for event in Agent.default.stt_node(self, _tee(), model_settings):
            now = asyncio.get_event_loop().time()
            if self._is_agent_speaking or now < self._mute_stt_until:
                # Discard speech events detected while the agent was speaking
                continue
            if event.type == stt.SpeechEventType.START_OF_SPEECH:
                # A fresh turn starts: drop anything left over from a turn
                # that never produced a final transcript (e.g. the caller
                # cleared their throat and stopped).
                self._audio_buffer.discard()
            yield event

    # -- per-turn interpretation and scripted response --------------------

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        now = asyncio.get_event_loop().time()
        if self._is_agent_speaking or now < self._mute_stt_until:
            logger.info("voice.dropped_echo_during_agent_speech")
            self._audio_buffer.snapshot_and_clear()
            raise StopResponse

        transcript = new_message.text_content or ""
        audio_clip = self._audio_buffer.snapshot_and_clear()

        # Echo filter: if transcript matches or is contained in the last spoken agent prompt, reject it
        cleaned_transcript = transcript.strip().lower()
        if self._last_spoken_line and cleaned_transcript:
            cleaned_spoken = self._last_spoken_line.lower()
            if cleaned_transcript in cleaned_spoken or cleaned_spoken in cleaned_transcript:
                logger.warning("voice.dropped_transcript_matching_agent_prompt", transcript=cleaned_transcript)
                raise StopResponse

        if transcript.strip() and self._room and self._room.local_participant:
            try:
                data = json.dumps({"type": "transcript", "sender": "patient", "text": transcript.strip()}).encode("utf-8")
                asyncio.create_task(self._room.local_participant.publish_data(data, reliable=True))
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice.publish_user_transcript_failed", error=str(exc))

        if self._emergency_task is not None:
            # Any turn arriving while the 5-second window is open resolves
            # it immediately — we don't wait out the rest of the window
            # once we have an answer, cancelled or not.
            self._emergency_task.cancel()
            self._emergency_task = None
            cancelled = _looks_like_cancellation(transcript)
            outcome = await self._orchestrator.handle_emergency_confirmation(
                self._state, cancelled=cancelled
            )
            await self._apply_outcome(outcome)
            if outcome.kind is not ConversationOutcomeKind.CONTINUE_GATHERING:
                raise StopResponse
            return

        if not transcript.strip() and not audio_clip:
            outcome = await self._orchestrator.handle_silence_or_disconnect(self._state)
            await self._apply_outcome(outcome)
            raise StopResponse

        try:
            interpreted = await interpret_clip(
                audio_bytes=audio_clip,
                transcript_hint=transcript,
                model=self._gemini_model,
                api_key=self._interpreter_api_key,
            )
        except InterpretationFailed:
            logger.warning("voice.interpretation_failed")
            outcome = await self._orchestrator.handle_interpreted_fact(
                self._state,
                fact=self._pending_fact_for_slot(
                    transcript=transcript, confidence=0.0, impairment_signals=[]
                ),
                decision=PolicyDecision.REASK,
            )
            await self._apply_outcome(outcome)
            raise StopResponse

        # Verify reported emergency terms against utterance text to eliminate model hallucinations
        is_real_emergency = False
        if interpreted.emergency_terms_heard:
            combined = (transcript + " " + interpreted.interpretation).lower()
            EMERGENCY_SUBSTRINGS = (
                "നെഞ്ച", "heart", "chest", "ശ്വാസ", "breath", "chok",
                "പക്ഷാഘാത", "stroke", "paraly", "തളർ", "droop", "രക്തസ്രാവ",
                "bleed", "ബോധ", "faint", "unconscious", "collapse", "അപസ്മാര", "seizure", "fit"
            )
            for term in interpreted.emergency_terms_heard:
                t_lower = term.lower()
                if any(sub in t_lower for sub in EMERGENCY_SUBSTRINGS) and any(sub in combined for sub in EMERGENCY_SUBSTRINGS):
                    is_real_emergency = True
                    break

        if is_real_emergency:
            outcome = self._orchestrator.handle_emergency_terms(self._state)
            await self._apply_outcome(outcome)
            self._start_emergency_window()
            raise StopResponse

        decision = decide(interpreted, self._confidence_high, self._confidence_low)
        fact = self._pending_fact_for_slot(
            transcript=interpreted.interpretation,
            confidence=interpreted.confidence,
            impairment_signals=interpreted.impairment_signals,
            alternatives=interpreted.alternatives,
            raw_transcript=transcript,
        )
        outcome = await self._orchestrator.handle_interpreted_fact(self._state, fact, decision)
        await self._apply_outcome(outcome)

        if outcome.kind is not ConversationOutcomeKind.CONTINUE_GATHERING:
            raise StopResponse
        # CONTINUE_GATHERING: fall through, let the normal LLM flow ask the
        # next question — no StopResponse, no scripted line to speak.

    def _start_emergency_window(self) -> None:
        """Starts the 5-second clock for F4's confirmation window. If the
        patient's next turn arrives first, `on_user_turn_completed` cancels
        this task and resolves the window itself. If nothing arrives within
        5 seconds, this task resolves it instead — `cancelled=False`, which
        `handle_emergency_confirmation` treats as "proceed" (fail toward
        care, not toward waiting indefinitely for a confirmation that may
        never come from someone in genuine distress)."""

        async def _timeout_escalate() -> None:
            await asyncio.sleep(_EMERGENCY_WINDOW_SECONDS)
            self._emergency_task = None
            outcome = await self._orchestrator.handle_emergency_confirmation(
                self._state, cancelled=False
            )
            await self._apply_outcome(outcome)

        self._emergency_task = asyncio.create_task(_timeout_escalate())

    def _pending_fact_for_slot(
        self,
        *,
        transcript: str,
        confidence: float,
        impairment_signals: list[str],
        alternatives: list[str] | None = None,
        raw_transcript: str = "",
    ) -> PendingFact:
        slot = next(
            (k for k in _SLOT_ORDER if k not in self._state.confirmed_facts), FactKey.SYMPTOMS
        )
        return PendingFact(
            key=slot,
            interpreted_value=transcript,
            alternatives=alternatives or [],
            confidence=confidence,
            impairment_signals=impairment_signals,
            speech_onset=self._state.speech_onset or SpeechOnset.UNKNOWN,
            raw_transcript=raw_transcript or transcript,
            interpreter_model=self._gemini_model,
        )

    async def _apply_outcome(self, outcome: ConversationOutcome) -> None:
        text_to_speak = outcome.speak_text
        if outcome.kind is ConversationOutcomeKind.REFERRAL_READY:
            tier_val = outcome.tier.value if outcome.tier else ""
            text_to_speak = (
                f"നിങ്ങളുടെ വിവരങ്ങൾ വിജയകരമായി രേഖപ്പെടുത്തിയിട്ടുണ്ട്. "
                f"ട്രയാജ് മുൻഗണന: {tier_val}. ഡോക്ടറുടെ അനുമതിക്കായി അയച്ചിരിക്കുന്നു. നന്ദി."
            )
        elif outcome.kind is ConversationOutcomeKind.HUMAN_HANDOFF:
            text_to_speak = (
                "നിങ്ങളുടെ സംസാരം വ്യക്തമായി മനസ്സിലാക്കാൻ സാധിച്ചില്ല. "
                "കൂടുതൽ സഹായത്തിനായി ഒരു ആരോഗ്യ പ്രവർത്തകനിലേക്ക് ഈ കോൾ മാറ്റുന്നു."
            )
        elif outcome.kind is ConversationOutcomeKind.SAY_REASK:
            text_to_speak = "ക്ഷമിക്കണം, നിങ്ങൾ പറഞ്ഞത് വ്യക്തമായില്ല. ദയവായി ഒന്നുകൂടി പറയാമോ?"
        elif outcome.kind is ConversationOutcomeKind.SAY_EMERGENCY_WINDOW:
            text_to_speak = (
                "ഇതൊരു അടിയന്തര സാഹചര്യമായി തോന്നുന്നു. "
                "ആംബുലൻസ് ആവശ്യമുണ്ടെങ്കിൽ ദയവായി അഞ്ച് സെക്കൻഡിനുള്ളിൽ പറയുക."
            )
        elif outcome.kind is ConversationOutcomeKind.SAY_ONE_SHOT_SUMMARY:
            next_slot = next((k for k in _SLOT_ORDER if k not in self._state.confirmed_facts), None)
            if next_slot and next_slot in _SLOT_PROMPTS_ML:
                text_to_speak = _SLOT_PROMPTS_ML[next_slot]

        if text_to_speak:
            await self._set_speaking_state(True, text=text_to_speak)
            try:
                self.session.say(text_to_speak, add_to_chat_ctx=False, allow_interruptions=False)
            except Exception as exc:  # noqa: BLE001
                logger.error("voice.say_failed", error=str(exc))
            if self._room and self._room.local_participant:
                try:
                    data = json.dumps({"type": "transcript", "sender": "agent", "text": text_to_speak}).encode("utf-8")
                    asyncio.create_task(self._room.local_participant.publish_data(data, reliable=True))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("voice.publish_agent_transcript_failed", error=str(exc))

        if outcome.kind is ConversationOutcomeKind.HUMAN_HANDOFF:
            logger.warning("voice.human_handoff", task_id=outcome.task_id, reason=outcome.reason)
        elif outcome.kind is ConversationOutcomeKind.REFERRAL_READY:
            logger.info(
                "voice.referral_ready", task_id=outcome.task_id, tier=outcome.tier
            )
        elif outcome.kind is ConversationOutcomeKind.ABANDONED_WITH_CALLBACK:
            logger.warning("voice.abandoned_with_callback", task_id=outcome.task_id)
        elif outcome.kind is ConversationOutcomeKind.JOINED_EXISTING_CASE:
            logger.info("voice.joined_existing_case", task_id=outcome.task_id)

        terminal_kinds = {
            ConversationOutcomeKind.REFERRAL_READY,
            ConversationOutcomeKind.HUMAN_HANDOFF,
            ConversationOutcomeKind.ABANDONED_WITH_CALLBACK,
            ConversationOutcomeKind.EMERGENCY_ESCALATED,
            ConversationOutcomeKind.EMERGENCY_CALL_FAILED,
        }
        if outcome.kind in terminal_kinds and self._on_session_end is not None:
            async def _delayed_end() -> None:
                # Allow 6 seconds for TTS playback to conclude before disconnecting
                await asyncio.sleep(6.0)
                try:
                    await self._on_session_end()
                except Exception as exc:
                    logger.warning("voice.on_session_end_failed", error=str(exc))

            asyncio.create_task(_delayed_end())

    def mark_confirmed_by(self, confirmed_by: ConfirmedBy) -> None:
        """Called by the glue layer when a caregiver identifies themselves
        on the call (architecture.md "Caregiver path")."""
        self._state.confirmed_by = confirmed_by
