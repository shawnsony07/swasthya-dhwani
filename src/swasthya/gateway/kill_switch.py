"""Global kill switch for the action gateway (loops L19 and L34).

Turning the switch ON (blocking actions) just needs an actor — any admin or
doctor can hit the panic button immediately, no justification required.
Turning it back OFF (re-enabling normal dispatch) requires a non-empty
reason string, per L34: "Switch turned off with a recorded reason and an
audit event" and "Only that role can disable it; a reason is required."
Role enforcement (medical officer only) belongs to the dashboard's auth
layer, not this module; this module enforces the reason requirement, which
is the part that is a programming bug if missed.

Critical interaction with the emergency path (architecture.md section 4
step 3 and section 7): "With the kill switch on, the emergency path still
alerts doctors on the dashboard." The kill switch's `is_active` flag is
read by `ActionGateway` to block *dispatch* of non-emergency actions, but
it must never be consulted to suppress the emergency-alert signal itself —
that alert fires unconditionally for any failed/blocked emergency action.
See `action_gateway.py` for how this is wired.
"""
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class KillSwitchState(BaseModel):
    active: bool = False
    changed_by: str | None = None
    changed_at: datetime | None = None
    reason: str | None = None


class KillSwitch:
    def __init__(self) -> None:
        self._state = KillSwitchState()

    @property
    def is_active(self) -> bool:
        return self._state.active

    @property
    def state(self) -> KillSwitchState:
        return self._state.model_copy()

    def engage(self, by: str, reason: str | None = None) -> KillSwitchState:
        """Turns the kill switch ON. No reason required — this is the
        panic-button path and must never be slowed down by validation."""
        self._state = KillSwitchState(
            active=True,
            changed_by=by,
            changed_at=datetime.now(UTC),
            reason=reason,
        )
        logger.warning("kill_switch.engaged", by=by, reason=reason)
        return self.state

    def disable(self, by: str, reason: str) -> KillSwitchState:
        """Turns the kill switch OFF (re-enable). A non-empty `reason` is
        mandatory per loop L34 — raises ValueError without one."""
        if not reason or not reason.strip():
            logger.error("kill_switch.disable_rejected_no_reason", by=by)
            raise ValueError("A reason is required to re-enable the kill switch (L34).")

        self._state = KillSwitchState(
            active=False,
            changed_by=by,
            changed_at=datetime.now(UTC),
            reason=reason,
        )
        logger.warning("kill_switch.disabled", by=by, reason=reason)
        return self.state
