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
from typing import Protocol

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class KillSwitchState(BaseModel):
    active: bool = False
    changed_by: str | None = None
    changed_at: datetime | None = None
    reason: str | None = None


class KillSwitchStore(Protocol):
    """Storage seam so a DB-backed store (`swasthya.db.kill_switch_store.
    DbKillSwitchStore`) can replace the in-memory default without any
    change to `KillSwitch` or the gateway.

    A DB-backed store is not an optional upgrade for this one setting the
    way it is for `AllowList`/`RateLimiter`: the API (where an admin flips
    the switch) and the voice agent (where `ActionGateway` reads it before
    every dispatch) are separate processes, so in-memory state here would
    silently never be seen by the other process. Any real deployment must
    use the DB-backed store."""

    def get(self) -> KillSwitchState: ...

    def set(self, state: KillSwitchState) -> None: ...


class InMemoryKillSwitchStore:
    """Default store: a single process-local state object. Fine for
    tests and single-process usage; see `KillSwitchStore`'s docstring for
    why a real deployment needs the DB-backed store instead."""

    def __init__(self) -> None:
        self._state = KillSwitchState()

    def get(self) -> KillSwitchState:
        return self._state

    def set(self, state: KillSwitchState) -> None:
        self._state = state


class KillSwitch:
    def __init__(self, store: KillSwitchStore | None = None) -> None:
        self._store = store or InMemoryKillSwitchStore()

    @property
    def is_active(self) -> bool:
        return self._store.get().active

    @property
    def state(self) -> KillSwitchState:
        return self._store.get().model_copy()

    def engage(self, by: str, reason: str | None = None) -> KillSwitchState:
        """Turns the kill switch ON. No reason required — this is the
        panic-button path and must never be slowed down by validation."""
        new_state = KillSwitchState(
            active=True,
            changed_by=by,
            changed_at=datetime.now(UTC),
            reason=reason,
        )
        self._store.set(new_state)
        logger.warning("kill_switch.engaged", by=by, reason=reason)
        return new_state.model_copy()

    def disable(self, by: str, reason: str) -> KillSwitchState:
        """Turns the kill switch OFF (re-enable). A non-empty `reason` is
        mandatory per loop L34 — raises ValueError without one."""
        if not reason or not reason.strip():
            logger.error("kill_switch.disable_rejected_no_reason", by=by)
            raise ValueError("A reason is required to re-enable the kill switch (L34).")

        new_state = KillSwitchState(
            active=False,
            changed_by=by,
            changed_at=datetime.now(UTC),
            reason=reason,
        )
        self._store.set(new_state)
        logger.warning("kill_switch.disabled", by=by, reason=reason)
        return new_state.model_copy()
