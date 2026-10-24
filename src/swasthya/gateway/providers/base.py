"""Provider Protocols for the action gateway.

`action_gateway.py` depends only on these Protocols, never on a concrete
vendor SDK. That is the seam that lets a real Twilio/SmartThings/voice-clone
vendor get plugged in later without touching gateway policy code.

None of these Protocols may raise for ordinary vendor failure. A failure is
always a normal return value (`ActionOutcome.*_FAILED`, or
`SPOKEN_NEUTRAL` for the voice clone) so the gateway's control flow stays
simple and every failure is visible on the dashboard rather than bubbling up
as an exception.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from swasthya.contracts import ActionOutcome


@runtime_checkable
class EmergencyCallProvider(Protocol):
    """Places (or simulates) an emergency call to a contact.

    Implementations must never raise for a normal call failure (busy, no
    answer, vendor error) — they return `ActionOutcome.EMERGENCY_CALL_FAILED`
    instead, so the gateway can try the next contact or raise a dashboard
    alert without special-casing exceptions.
    """

    async def call(self, target: str, message: str) -> ActionOutcome: ...


@runtime_checkable
class DeviceCommandProvider(Protocol):
    """Sends a command to a SmartThings-style device.

    Per architecture.md section 4 step 5 ("the device state is read back"),
    an implementation must send the command and then read the device's
    state back, reporting `DEVICE_ACTION_FAILED` on a mismatch rather than
    trusting the send acknowledgement alone.
    """

    async def send_command(self, target: str, payload: dict) -> ActionOutcome: ...


@runtime_checkable
class VoiceCloneProvider(Protocol):
    """Synthesizes speech, optionally in a patient's cloned voice.

    Sarvam (the locked TTS vendor, see architecture.md section 2) does not
    support voice cloning — only fixed/preset voices. So the *real* behavior
    today is always the neutral fallback; `clone_id` is accepted so a future
    cloning vendor can implement this same Protocol without changing the
    gateway. Per architecture.md section 4 F8: "no clone, no consent record,
    or a vendor error all fall back to the neutral voice". This method must
    never raise for those cases — it returns `SPOKEN_NEUTRAL` audio instead.

    Returns `(audio_bytes, outcome)` where `outcome` is
    `ActionOutcome.SPOKEN_AS_PATIENT` only when a real `clone_id` was used
    and synthesis with it actually succeeded, and
    `ActionOutcome.SPOKEN_NEUTRAL` in every other case (missing clone_id,
    missing consent record, vendor error).
    """

    async def synthesize(
        self, text: str, clone_id: str | None
    ) -> tuple[bytes, ActionOutcome]: ...
