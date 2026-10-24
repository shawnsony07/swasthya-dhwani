"""The confirmation-loop state machine (docs/architecture.md section 4,
"confirmation loop · 8 states, 3 outcomes", and loop L1 in section 14).

This module is deliberately LiveKit-free and Gemini-free: it is the pure
decision logic sitting between the (separately built) voice agent glue and
the rule engine / workflow. It depends only on `swasthya.contracts` and
`swasthya.voice.conversation_contracts` (plus `swasthya.interpreter
.confidence_policy.PolicyDecision` as an input type), so it is fully
unit-testable with no network, no audio, and no LiveKit.

Upstream responsibilities (NOT this module's job):
* Running `speech_interpreter.interpret_clip` to get an `InterpreterOutput`.
* Running `confidence_policy.decide` to turn that output into a
  `PolicyDecision`. `handle_interpreted_fact` takes the already-decided
  `PolicyDecision` as a parameter rather than re-deriving confidence
  thresholds, so this module never duplicates `confidence_policy`'s logic.
* Routing `emergency_terms_heard` (a field on `InterpreterOutput`, not on
  `PendingFact`) to `handle_emergency_terms` before this module ever sees a
  `PendingFact` for that turn — see the note on `PendingFact` below.
"""
from __future__ import annotations

from typing import Final

import structlog

from swasthya.contracts import ConfirmedBy, SpeechOnset, Tier, TriageData, TriageResult
from swasthya.interpreter.confidence_policy import PolicyDecision
from swasthya.voice.conversation_contracts import (
    MAX_READBACK_FAILURES,
    ConversationOutcome,
    ConversationOutcomeKind,
    FactKey,
    FhirSink,
    PendingFact,
    RuleEngine,
    WorkflowSink,
)

logger = structlog.get_logger(__name__)

# Facts that must be confirmed before `finalize_and_route` can run the rule
# engine. DURATION is intentionally excluded — architecture.md section 6 lists
# `symptom_duration_days` with a default of 0, so a call can be triaged
# without it.
REQUIRED_FACTS: Final[tuple[FactKey, ...]] = (
    FactKey.IDENTIFIER,
    FactKey.SYMPTOMS,
    FactKey.WARNING_SIGNS,
)


class ConversationState:
    """Per-call mutable state for one confirmation loop.

    `confirmed_facts` holds one `PendingFact` per key once it has been
    accepted (either directly, via one-shot summary, or via per-fact
    read-back) — these are the values `finalize_and_route` assembles into a
    `TriageData`. `pending_facts` holds the fact currently awaiting a
    yes/no response (summary or per-fact read-back); it is cleared once a
    confirmation response resolves it.
    """

    def __init__(
        self,
        *,
        patient_identifier: str = "",
        speech_onset: SpeechOnset = SpeechOnset.UNKNOWN,
        confirmed_by: ConfirmedBy = ConfirmedBy.NONE,
    ) -> None:
        self.confirmed_facts: dict[FactKey, PendingFact] = {}
        self.pending_facts: dict[FactKey, PendingFact] = {}
        self.readback_failure_counts: dict[FactKey, int] = {}
        self.rejection_counts: dict[FactKey, int] = {}

        self.confirmed_by: ConfirmedBy = confirmed_by
        self.speech_onset: SpeechOnset = speech_onset
        self.is_time_critical: bool = False
        self.patient_identifier: str = patient_identifier
        self.task_id: str | None = None

    # -- convenience helpers -------------------------------------------------

    def all_required_facts_confirmed(self) -> bool:
        return all(key in self.confirmed_facts for key in REQUIRED_FACTS)

    def has_any_confirmed_fact(self) -> bool:
        return bool(self.confirmed_facts)

    def minimum_confirmed_confidence(self) -> float:
        """The call's overall `interpretation_confidence` is the lowest
        confidence among all confirmed facts, not an average or the most
        recent value. Rationale: `apply_acuity_floor`'s confidence floor
        exists to catch a call where the interpreter was unsure about
        *any* confirmed fact — one weak fact (even if it happens to be
        "duration") is exactly the signal the floor is meant to react to,
        and averaging it away would let a single shaky interpretation hide
        behind several easy ones. If nothing is confirmed yet, returns 1.0
        (an empty min is treated as "no evidence of low confidence")."""
        if not self.confirmed_facts:
            return 1.0
        return min(fact.confidence for fact in self.confirmed_facts.values())


class ConversationOrchestrator:
    """Pure decision logic for the confirmation loop. Construct one per call
    (or reuse across calls — it is stateless; all state lives on the
    `ConversationState` passed into each method)."""

    def __init__(self, rule_engine: RuleEngine, workflow: WorkflowSink, fhir: FhirSink) -> None:
        self._rule_engine = rule_engine
        self._workflow = workflow
        self._fhir = fhir

    # -------------------------------------------------------------------
    # L1 — read-back confirmation
    # -------------------------------------------------------------------

    async def handle_interpreted_fact(
        self,
        state: ConversationState,
        fact: PendingFact,
        decision: PolicyDecision,
    ) -> ConversationOutcome:
        """Decide what to say next for one freshly-interpreted fact.

        `decision` is the `PolicyDecision` already produced upstream by
        `confidence_policy.decide` — this function never re-derives
        confidence thresholds itself (per the brief: the thresholds belong
        to `confidence_policy`, not to this module).

        `decision` must not be `EMERGENCY_SKIP`: that row is handled by
        `handle_emergency_terms` on a separate path, before a `PendingFact`
        for this turn is ever built (see module docstring and
        `PendingFact`'s note below about `emergency_terms_heard` not being a
        field on `PendingFact`). `decision` must also not be
        `ACUITY_FLOOR_STROKE`: `confidence_policy.decide` documents that it
        never returns that value itself.
        """
        if decision is PolicyDecision.EMERGENCY_SKIP:
            raise ValueError(
                "handle_interpreted_fact received EMERGENCY_SKIP; the caller must "
                "route emergency terms via handle_emergency_terms before building "
                "a PendingFact for this turn."
            )
        if decision is PolicyDecision.ACUITY_FLOOR_STROKE:
            raise ValueError(
                "ACUITY_FLOOR_STROKE is a clinical decision owned by "
                "apply_acuity_floor, not a confidence_policy.decide outcome; "
                "handle_interpreted_fact cannot act on it."
            )

        if decision is PolicyDecision.ONE_SHOT_SUMMARY:
            state.confirmed_facts[fact.key] = fact
            logger.info(
                "conversation.one_shot_summary",
                fact_key=fact.key.value,
                confidence=fact.confidence,
            )
            # A one-shot fact needs no per-fact yes/no (architecture.md
            # section 4's confidence-policy table), so it is provisionally
            # confirmed the moment it is stored — there is no separate
            # confirmation step gating it. If storing it happens to
            # complete the required-fact set, route immediately rather
            # than waiting on a confirmation call that will never come for
            # this fact; the end-of-call summary read-back the voice glue
            # speaks from `speak_text` is a courtesy recap, not an
            # additional gate on routing.
            if state.all_required_facts_confirmed():
                return await self.finalize_and_route(state)
            return ConversationOutcome(
                kind=ConversationOutcomeKind.SAY_ONE_SHOT_SUMMARY,
                speak_text=fact.interpreted_value,
            )

        if decision is PolicyDecision.PER_FACT_READBACK:
            state.pending_facts[fact.key] = fact
            speak_text = fact.interpreted_value
            if fact.alternatives:
                speak_text = f"{speak_text}... or did you mean {fact.alternatives[0]}?"
            logger.info(
                "conversation.per_fact_readback",
                fact_key=fact.key.value,
                confidence=fact.confidence,
                impairment_signals=fact.impairment_signals,
            )
            return ConversationOutcome(
                kind=ConversationOutcomeKind.SAY_PER_FACT_READBACK,
                speak_text=speak_text,
            )

        # decision is PolicyDecision.REASK
        count = state.readback_failure_counts.get(fact.key, 0) + 1
        state.readback_failure_counts[fact.key] = count
        logger.info(
            "conversation.reask",
            fact_key=fact.key.value,
            confidence=fact.confidence,
            failure_count=count,
        )
        if count > MAX_READBACK_FAILURES:
            logger.warning(
                "conversation.human_handoff",
                reason="readback_failures_exceeded",
                fact_key=fact.key.value,
                failure_count=count,
            )
            return ConversationOutcome(
                kind=ConversationOutcomeKind.HUMAN_HANDOFF,
                reason=(
                    f"Fact {fact.key.value!r} failed read-back/re-ask "
                    f"{count} times (max {MAX_READBACK_FAILURES})."
                ),
            )
        return ConversationOutcome(
            kind=ConversationOutcomeKind.SAY_REASK,
            speak_text="I didn't catch that clearly, could you say it again?",
        )

    async def handle_confirmation_response(
        self,
        state: ConversationState,
        fact_key: FactKey,
        confirmed: bool,
        patient_said_alternative_instead: str | None = None,
    ) -> ConversationOutcome:
        """Resolve a yes/no (or silence, modelled as `confirmed=False` with
        no alternative) to a per-fact or summary read-back."""
        pending = state.pending_facts.get(fact_key)

        if confirmed:
            finalized: PendingFact | None
            if pending is not None:
                finalized = (
                    pending.model_copy(update={"interpreted_value": patient_said_alternative_instead})
                    if patient_said_alternative_instead is not None
                    else pending
                )
            elif patient_said_alternative_instead is not None:
                # No pending record (e.g. confirming a one-shot summary
                # fact) but the patient corrected it — honour the correction.
                finalized = PendingFact(
                    key=fact_key,
                    interpreted_value=patient_said_alternative_instead,
                    confidence=1.0,
                )
            else:
                finalized = state.confirmed_facts.get(fact_key)
                if finalized is None:
                    raise ValueError(
                        f"No pending or previously-confirmed fact for {fact_key.value!r} "
                        "to confirm."
                    )

            state.confirmed_facts[fact_key] = finalized
            state.pending_facts.pop(fact_key, None)
            state.rejection_counts.pop(fact_key, None)
            logger.info("conversation.fact_confirmed", fact_key=fact_key.value)

            if state.all_required_facts_confirmed():
                return await self.finalize_and_route(state)
            return ConversationOutcome(kind=ConversationOutcomeKind.CONTINUE_GATHERING)

        # Rejected (including silence).
        count = state.rejection_counts.get(fact_key, 0) + 1
        state.rejection_counts[fact_key] = count
        logger.info(
            "conversation.fact_rejected",
            fact_key=fact_key.value,
            rejection_count=count,
        )
        # Unlike the re-ask counter above (which allows MAX_READBACK_FAILURES
        # re-asks and hands off on the attempt that *exceeds* that count),
        # "rejected twice" (architecture.md L1: "HUMAN_HANDOFF after 2
        # failures") hands off as soon as the count *reaches*
        # MAX_READBACK_FAILURES — the second rejection is itself the
        # disqualifying one, there is no third read-back offered.
        if count >= MAX_READBACK_FAILURES:
            logger.warning(
                "conversation.human_handoff",
                reason="confirmation_rejected_twice",
                fact_key=fact_key.value,
                rejection_count=count,
            )
            return ConversationOutcome(
                kind=ConversationOutcomeKind.HUMAN_HANDOFF,
                reason=(
                    f"Fact {fact_key.value!r} rejected {count} times "
                    f"(max {MAX_READBACK_FAILURES})."
                ),
            )
        return ConversationOutcome(
            kind=ConversationOutcomeKind.SAY_REASK,
            speak_text="Sorry, let's try that again — could you repeat it?",
        )

    # -------------------------------------------------------------------
    # Route to the rule engine once every required fact is confirmed
    # -------------------------------------------------------------------

    async def finalize_and_route(self, state: ConversationState) -> ConversationOutcome:
        if not state.all_required_facts_confirmed():
            missing = [k.value for k in REQUIRED_FACTS if k not in state.confirmed_facts]
            raise ValueError(f"finalize_and_route called with missing facts: {missing}")

        triage_data = self._build_triage_data(state)

        base_result: TriageResult = self._rule_engine.query(
            triage_data.symptoms, triage_data.warning_signs_present
        )
        result: TriageResult = self._rule_engine.apply_floor(
            base_result,
            triage_data.speech_impairment_signals,
            state.speech_onset,
            triage_data.interpretation_confidence,
        )

        # FHIR write happens before the workflow sink is told anything, but a
        # FHIR outage (architecture.md section 8: "FHIR (HAPI) down -> triage
        # proceeds on confirmed data without history") must never swallow a
        # referral or a handoff. `FhirSink` implementations are expected to
        # raise rather than silently degrade, so this boundary catches
        # broadly and only records the failure on the outcome for the
        # dashboard to show ("History unavailable" per the resilience table).
        patient_fhir_id, fhir_write_failed = await self._record_triage_best_effort(triage_data)
        if result.matched and result.tier is not None and not fhir_write_failed:
            try:
                await self._fhir.record_referral(
                    patient_fhir_id, result.tier, result.hospital_tier_required
                )
            except Exception:  # noqa: BLE001 - FHIR outage must never block a referral
                logger.warning(
                    "conversation.fhir_record_referral_failed",
                    task_id=state.task_id,
                    tier=result.tier.value,
                )
                fhir_write_failed = True

        if not result.matched:
            logger.warning(
                "conversation.no_match",
                no_match_reason=result.no_match_reason,
            )
            task_id = self._workflow.submit_task(is_time_critical=False)
            state.task_id = task_id
            self._workflow.mark_human_handoff(
                task_id, reason=result.no_match_reason or "No matching protocol condition."
            )
            return ConversationOutcome(
                kind=ConversationOutcomeKind.HUMAN_HANDOFF,
                task_id=task_id,
                reason=result.no_match_reason,
                triage_data=triage_data,
                fhir_write_failed=fhir_write_failed,
            )

        # Time-critical if the final tier is the stroke tier (C1) or the
        # stroke-floor explicitly fired. We check both rather than tier
        # alone because a non-stroke condition could in principle be
        # escalated to C1 by its own matrix entry (e.g. an
        # `escalated_tier`), and the brief calls out "tier is C1 OR the
        # stroke acuity floor fired" as the two signals to check.
        stroke_floor_fired = result.floor_applied and bool(
            result.floor_reason and "stroke" in result.floor_reason.lower()
        )
        if result.tier is None:
            # Invariant: `matched=True` must always carry a tier — the rule
            # engine never leaves a matched case without one. If this ever
            # fires, that invariant broke upstream and silently proceeding
            # would be exactly the "quiet default" bug T3 exists to prevent.
            raise ValueError(
                "Rule engine returned matched=True with no tier; refusing to "
                "silently approve a referral with no tier."
            )

        is_time_critical = result.tier == Tier.C1 or stroke_floor_fired
        state.is_time_critical = is_time_critical

        task_id = self._workflow.submit_task(is_time_critical=is_time_critical)
        state.task_id = task_id
        self._workflow.mark_awaiting_approval(
            task_id, result.tier, result.hospital_tier_required
        )
        logger.info(
            "conversation.referral_ready",
            task_id=task_id,
            tier=result.tier.value if result.tier else None,
            is_time_critical=is_time_critical,
        )
        return ConversationOutcome(
            kind=ConversationOutcomeKind.REFERRAL_READY,
            task_id=task_id,
            tier=result.tier,
            hospital_tier_required=result.hospital_tier_required,
            triage_data=triage_data,
            fhir_write_failed=fhir_write_failed,
        )

    def _build_triage_data(self, state: ConversationState) -> TriageData:
        identifier_fact = state.confirmed_facts[FactKey.IDENTIFIER]
        symptoms_fact = state.confirmed_facts[FactKey.SYMPTOMS]
        warning_signs_fact = state.confirmed_facts[FactKey.WARNING_SIGNS]
        duration_fact = state.confirmed_facts.get(FactKey.DURATION)

        all_signals: list[str] = []
        for fact in state.confirmed_facts.values():
            for signal in fact.impairment_signals:
                if signal not in all_signals:
                    all_signals.append(signal)

        duration_days = 0
        if duration_fact is not None:
            try:
                duration_days = int(duration_fact.interpreted_value)
            except ValueError:
                duration_days = 0

        return TriageData(
            patient_identifier=state.patient_identifier or identifier_fact.interpreted_value,
            identifier_type="phone",
            symptoms=_split_list_value(symptoms_fact.interpreted_value),
            symptom_duration_days=duration_days,
            warning_signs_present=_split_list_value(warning_signs_fact.interpreted_value),
            raw_transcript=symptoms_fact.raw_transcript,
            interpreted_text=symptoms_fact.interpreted_value,
            interpretation_confidence=state.minimum_confirmed_confidence(),
            speech_impairment_signals=all_signals,
            speech_onset=state.speech_onset,
            confirmed_by=state.confirmed_by,
            interpreter_model=symptoms_fact.interpreter_model,
        )

    async def _record_triage_best_effort(self, triage_data: TriageData) -> tuple[str, bool]:
        """Call `FhirSink.record_triage`, never letting a FHIR outage block
        the referral/handoff that follows (architecture.md section 8: "FHIR
        down -> triage proceeds on confirmed data without history"). Returns
        `(patient_fhir_id, fhir_write_failed)` — on failure `patient_fhir_id`
        is `""` (there is nothing to key a referral write off of, so a
        following `record_referral` attempt is skipped by the caller) and
        `fhir_write_failed` is `True` so the outcome and the dashboard can
        show the degraded state instead of silently losing it."""
        try:
            return await self._fhir.record_triage(triage_data), False
        except Exception:  # noqa: BLE001 - FHIR outage must never block the call
            logger.warning(
                "conversation.fhir_record_triage_failed",
                patient_identifier_known=bool(triage_data.patient_identifier),
            )
            return "", True

    # -------------------------------------------------------------------
    # Emergency path (architecture.md F4 / L3) — bypasses the rest of the loop
    # -------------------------------------------------------------------

    def handle_emergency_terms(self, state: ConversationState) -> ConversationOutcome:
        """Signal the 5-second emergency confirmation window immediately.
        Timing itself (the 5-second clock, the actual emergency call) is the
        voice agent glue's responsibility (architecture.md section 4, action
        gateway) — this method only decides *that* the emergency path
        applies and returns the outcome kind that tells the caller to take
        over."""
        logger.warning("conversation.emergency_terms_heard", task_id=state.task_id)
        return ConversationOutcome(
            kind=ConversationOutcomeKind.SAY_EMERGENCY_WINDOW,
            speak_text=(
                "This sounds like it could be an emergency. Please confirm within "
                "5 seconds if you need an ambulance."
            ),
        )

    # -------------------------------------------------------------------
    # Silence / abandonment (architecture.md F6, loop L11)
    # -------------------------------------------------------------------

    async def handle_silence_or_disconnect(self, state: ConversationState) -> ConversationOutcome:
        """A caller who goes silent or disconnects mid-call must never leave
        an open loop (architecture.md section 4: "a caller who stops
        responding still ends in a handoff or callback, never an open
        loop").

        Design choice (no fact confirmed yet): with zero confirmed facts
        there is no patient data at all — not even an identifier — for a
        human to call back about, so we deliberately do NOT call
        `WorkflowSink.submit_task`: creating a task with nothing in it would
        just be noise in the nurse queue (architecture.md L11's callback
        queue is for cases with *some* information to act on). We still
        return `ABANDONED_WITH_CALLBACK` so the caller's outcome-kind
        handling stays uniform, but with `task_id=None` and a `reason`
        explaining that no task was created — the voice agent glue can
        branch on `task_id is None` if it needs to distinguish the two
        cases structurally rather than by kind.
        """
        if not state.has_any_confirmed_fact():
            logger.info("conversation.silence_no_facts_no_callback")
            return ConversationOutcome(
                kind=ConversationOutcomeKind.ABANDONED_WITH_CALLBACK,
                task_id=None,
                reason=(
                    "Call ended in silence/disconnect before any fact was "
                    "confirmed; no callback task created (no patient data to "
                    "act on)."
                ),
            )

        partial = self._build_partial_triage_data(state)
        # Best-effort FHIR write: F6 says "partial data is saved if any was
        # confirmed", but a FHIR outage must still never block the callback
        # task from reaching the nurse queue (section 8).
        _, fhir_write_failed = await self._record_triage_best_effort(partial)
        task_id = self._workflow.submit_task(is_time_critical=state.is_time_critical)
        state.task_id = task_id
        self._workflow.mark_human_handoff(
            task_id, reason="Call abandoned (silence/disconnect) with partial facts confirmed."
        )
        logger.warning(
            "conversation.abandoned_with_callback",
            task_id=task_id,
            confirmed_fact_keys=[k.value for k in state.confirmed_facts],
        )
        return ConversationOutcome(
            kind=ConversationOutcomeKind.ABANDONED_WITH_CALLBACK,
            task_id=task_id,
            triage_data=partial,
            fhir_write_failed=fhir_write_failed,
        )

    def _build_partial_triage_data(self, state: ConversationState) -> TriageData:
        identifier_fact = state.confirmed_facts.get(FactKey.IDENTIFIER)
        symptoms_fact = state.confirmed_facts.get(FactKey.SYMPTOMS)
        warning_signs_fact = state.confirmed_facts.get(FactKey.WARNING_SIGNS)
        duration_fact = state.confirmed_facts.get(FactKey.DURATION)

        all_signals: list[str] = []
        for fact in state.confirmed_facts.values():
            for signal in fact.impairment_signals:
                if signal not in all_signals:
                    all_signals.append(signal)

        duration_days = 0
        if duration_fact is not None:
            try:
                duration_days = int(duration_fact.interpreted_value)
            except ValueError:
                duration_days = 0

        return TriageData(
            patient_identifier=state.patient_identifier
            or (identifier_fact.interpreted_value if identifier_fact else ""),
            identifier_type="phone",
            symptoms=_split_list_value(symptoms_fact.interpreted_value) if symptoms_fact else [],
            symptom_duration_days=duration_days,
            warning_signs_present=(
                _split_list_value(warning_signs_fact.interpreted_value)
                if warning_signs_fact
                else []
            ),
            raw_transcript=symptoms_fact.raw_transcript if symptoms_fact else "",
            interpreted_text=symptoms_fact.interpreted_value if symptoms_fact else "",
            interpretation_confidence=state.minimum_confirmed_confidence(),
            speech_impairment_signals=all_signals,
            speech_onset=state.speech_onset,
            confirmed_by=state.confirmed_by,
            interpreter_model=symptoms_fact.interpreter_model if symptoms_fact else "",
        )


def _split_list_value(value: str) -> list[str]:
    """`PendingFact.interpreted_value` is a single string even for
    list-shaped facts (symptoms, warning signs) because the interpreter
    emits one free-text interpretation per turn. Split on commas (the
    read-back/confirmation prompts ask for comma-separated facts) and drop
    empties; a caller that already has a list should pre-join it before
    building the `PendingFact` rather than rely on more elaborate parsing
    here, since any NLP-grade splitting belongs upstream, not in this pure
    state machine."""
    return [item.strip() for item in value.split(",") if item.strip()]
