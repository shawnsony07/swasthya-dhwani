"""The action gateway: the only code allowed to dispatch a real-world action.

Implements the exact 5-step policy from architecture.md section 4
("Action gateway"):

1. Reject unless `confirmed_by` is set and `expires_at` has not passed.
   `ConfirmedByAction.EMERGENCY_WINDOW` is a valid confirmation value, not a
   bypass of this check — it still must carry a real `confirmed_at`/
   `expires_at`.
2. Check `target` against the patient's `AllowList` — reject if absent.
   Speech/LLM output can never add an entry; see `allowlist.py`.
3. Check the rate limiter and the kill switch.
4. Write an `action_requested` `AuditEvent` before dispatch.
5. Dispatch to the provider for `action.type`, record the outcome, write a
   follow-up audit event, and raise a dashboard alert on failure.

Two deliberate design choices beyond the doc's literal wording, both
documented where they bite:

* `action_requested` is written unconditionally, before step 1's
  confirmation check — not only "before dispatch" as the literal step 4
  ordering suggests. The point of an audit trail is that *every* request
  leaves a trace, including ones immediately rejected; a trail that skips
  rejected requests would hide exactly the attempts worth reviewing later.

* Kill-switch vs. emergency calls (architecture.md section 4 step 3, "With
  the kill switch on, the emergency path still alerts doctors on the
  dashboard"; section 8's resilience table: "Emergency path falls back to a
  dashboard alert plus the caller instruction; other actions are refused").
  Read together, those two sources say the kill switch blocks *dispatch* of
  every action type, emergency calls included — it does not carve out an
  exception that still rings a real phone while every other action is
  blocked. What it must never block is the *alert*: this gateway raises a
  dashboard alert for an emergency call any time that call is rejected or
  fails, kill-switch-caused or not, so a blocked emergency action is loud
  instead of silent. See `dispatch()` and the `_raises_alert` helper.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import structlog
from pydantic import BaseModel

from swasthya.contracts import (
    ActionOutcome,
    ActionRequest,
    ActionType,
    AuditEvent,
    ConfirmedByAction,
)
from swasthya.gateway.allowlist import AllowList
from swasthya.gateway.kill_switch import KillSwitch
from swasthya.gateway.providers.base import (
    DeviceCommandProvider,
    EmergencyCallProvider,
    VoiceCloneProvider,
)
from swasthya.gateway.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

# Outcomes that always warrant a dashboard alert, regardless of action type.
_FAILURE_OUTCOMES = frozenset(
    {ActionOutcome.EMERGENCY_CALL_FAILED, ActionOutcome.DEVICE_ACTION_FAILED}
)


class DashboardAlert(BaseModel):
    """What gets raised on the doctor dashboard for a failed/blocked action."""

    action_id: str
    patient_id: str
    action_type: ActionType
    outcome: ActionOutcome
    message: str


class IdempotencyStore(Protocol):
    def get(self, key: str) -> ActionOutcome | None: ...

    def set(self, key: str, outcome: ActionOutcome) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._results: dict[str, ActionOutcome] = {}

    def get(self, key: str) -> ActionOutcome | None:
        return self._results.get(key)

    def set(self, key: str, outcome: ActionOutcome) -> None:
        self._results[key] = outcome


AuditSink = Callable[[AuditEvent], None]
AlertSink = Callable[[DashboardAlert], None]


def _default_audit_sink_factory() -> tuple[AuditSink, list[AuditEvent]]:
    events: list[AuditEvent] = []

    def sink(event: AuditEvent) -> None:
        events.append(event)

    return sink, events


def _default_alert_sink_factory() -> tuple[AlertSink, list[DashboardAlert]]:
    alerts: list[DashboardAlert] = []

    def sink(alert: DashboardAlert) -> None:
        alerts.append(alert)

    return sink, alerts


class ActionGateway:
    def __init__(
        self,
        *,
        allow_list: AllowList,
        rate_limiter: RateLimiter,
        kill_switch: KillSwitch,
        emergency_provider: EmergencyCallProvider,
        device_provider: DeviceCommandProvider,
        voice_provider: VoiceCloneProvider,
        idempotency_store: IdempotencyStore | None = None,
        audit_sink: AuditSink | None = None,
        alert_sink: AlertSink | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._allow_list = allow_list
        self._rate_limiter = rate_limiter
        self._kill_switch = kill_switch
        self._emergency_provider = emergency_provider
        self._device_provider = device_provider
        self._voice_provider = voice_provider
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()

        if audit_sink is None:
            audit_sink, self.audit_events = _default_audit_sink_factory()
        else:
            self.audit_events = []
        self._audit_sink = audit_sink

        if alert_sink is None:
            alert_sink, self.alerts = _default_alert_sink_factory()
        else:
            self.alerts = []
        self._alert_sink = alert_sink
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    # -- audit / alert helpers -------------------------------------------------

    def _audit(
        self, action: ActionRequest, event: str, actor: str = "system", **detail: object
    ) -> None:
        audit_event = AuditEvent(
            task_id=action.action_id,
            event=event,
            actor=actor,
            timestamp=self._now_fn(),
            detail=dict(detail),
        )
        self._audit_sink(audit_event)
        logger.info(
            "gateway.audit", audit_event_name=event, action_id=action.action_id, **detail
        )

    def _alert(
        self, action: ActionRequest, patient_id: str, outcome: ActionOutcome, message: str
    ) -> None:
        alert = DashboardAlert(
            action_id=action.action_id,
            patient_id=patient_id,
            action_type=action.type,
            outcome=outcome,
            message=message,
        )
        self._alert_sink(alert)
        logger.warning(
            "gateway.dashboard_alert",
            action_id=action.action_id,
            patient_id=patient_id,
            outcome=outcome,
            alert_message=message,
        )

    def _maybe_alert_on_outcome(
        self, action: ActionRequest, patient_id: str, outcome: ActionOutcome, message: str
    ) -> None:
        is_failure = outcome in _FAILURE_OUTCOMES
        is_blocked_emergency = (
            action.type is ActionType.EMERGENCY_CALL and outcome is ActionOutcome.REJECTED
        )
        if is_failure or is_blocked_emergency:
            self._alert(action, patient_id, outcome, message)

    # -- policy steps 1-3 -------------------------------------------------------

    def _check_confirmation(self, action: ActionRequest) -> str | None:
        if action.confirmed_by is None:  # structurally always set by the model
            return "not confirmed"
        if action.expires_at <= self._now_fn():
            return "confirmation expired"
        return None

    def _check_allow_list(self, action: ActionRequest, patient_id: str) -> str | None:
        if not self._allow_list.is_allowed(patient_id, action.target):
            return "target not on allow-list"
        return None

    def _check_rate_and_kill_switch(
        self, action: ActionRequest, patient_id: str
    ) -> str | None:
        if not self._rate_limiter.allow(patient_id):
            return "rate limit exceeded"
        if self._kill_switch.is_active:
            return "kill switch is on"
        return None

    # -- dispatch ---------------------------------------------------------------

    async def dispatch(self, action: ActionRequest, patient_id: str) -> ActionOutcome:
        cached = self._idempotency.get(action.idempotency_key)
        if cached is not None:
            logger.info(
                "gateway.idempotent_replay",
                action_id=action.action_id,
                idempotency_key=action.idempotency_key,
                outcome=cached,
            )
            return cached

        # Step 4 (moved to the front deliberately, see module docstring):
        # every request leaves a trace, rejected or not.
        self._audit(
            action,
            "action_requested",
            actor=_actor_for(action.confirmed_by),
            action_type=action.type.value,
            target=action.target,
        )

        for check in (
            lambda: self._check_confirmation(action),
            lambda: self._check_allow_list(action, patient_id),
            lambda: self._check_rate_and_kill_switch(action, patient_id),
        ):
            rejection_reason = check()
            if rejection_reason is not None:
                logger.warning(
                    "gateway.rejected",
                    action_id=action.action_id,
                    reason=rejection_reason,
                )
                self._audit(action, "action_rejected", reason=rejection_reason)
                self._maybe_alert_on_outcome(
                    action, patient_id, ActionOutcome.REJECTED, rejection_reason
                )
                self._idempotency.set(action.idempotency_key, ActionOutcome.REJECTED)
                return ActionOutcome.REJECTED

        self._audit(action, "action_dispatched", action_type=action.type.value)
        outcome = await self._dispatch_to_provider(action)
        self._idempotency.set(action.idempotency_key, outcome)
        self._maybe_alert_on_outcome(
            action, patient_id, outcome, f"{action.type.value} ended in {outcome.value}"
        )
        return outcome

    async def _dispatch_to_provider(self, action: ActionRequest) -> ActionOutcome:
        if action.type is ActionType.EMERGENCY_CALL:
            message = action.payload.get("message", "")
            outcome = await self._emergency_provider.call(action.target, message)
            self._audit(
                action,
                "call_answered" if outcome == ActionOutcome.EMERGENCY_CALLED else "call_failed",
                outcome=outcome.value,
            )
            return outcome

        if action.type is ActionType.DEVICE_COMMAND:
            outcome = await self._device_provider.send_command(action.target, action.payload)
            self._audit(action, "device_state_read", outcome=outcome.value)
            return outcome

        if action.type is ActionType.SPEAK_AS_PATIENT:
            text = action.payload.get("text", "")
            consent_recorded = bool(action.payload.get("consent_recorded", False))
            # Consent gating happens here, at the gateway, not only inside the
            # provider: a missing consent record must never even offer a
            # clone_id to the provider (architecture.md section 4 F8 and
            # section 7's clone-consent row).
            effective_clone_id = action.payload.get("clone_id") if consent_recorded else None
            _audio, outcome = await self._voice_provider.synthesize(text, effective_clone_id)
            self._audit(
                action,
                "clone_used",
                outcome=outcome.value,
                spoke_as_patient=outcome == ActionOutcome.SPOKEN_AS_PATIENT,
            )
            return outcome

        raise AssertionError(f"Unhandled action type: {action.type!r}")


def _actor_for(confirmed_by: ConfirmedByAction) -> str:
    if confirmed_by == ConfirmedByAction.PATIENT:
        return "patient"
    if confirmed_by == ConfirmedByAction.CAREGIVER:
        return "caregiver"
    return "agent"
