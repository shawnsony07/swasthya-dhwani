"""Safe default provider implementations.

These are not test doubles bolted on for convenience — until a real Twilio,
SmartThings, or voice-cloning vendor is wired in, these ARE the production
behavior. They do nothing destructive: no real network call is ever placed,
and `NeutralVoiceProvider` is literally what F8 does today, per the product
decision that Sarvam has no voice cloning.
"""
from __future__ import annotations

import re

import structlog

from swasthya.contracts import ActionOutcome

logger = structlog.get_logger(__name__)

# A target is treated as a usable demo/test contact or device id if it looks
# like a phone number, or an opaque alnum/dash/underscore id, and does not
# contain the literal marker "invalid" or "offline" — those markers exist so
# tests (and demo scripts) can force a failure outcome deterministically,
# without a real vendor to simulate busy/no-answer/offline against.
_LOOKS_USABLE = re.compile(r"^[A-Za-z0-9+_\-]{3,64}$")
_FORCED_FAILURE_MARKERS = ("invalid", "offline")


def _target_is_usable(target: str) -> bool:
    if not target:
        return False
    lowered = target.lower()
    if any(marker in lowered for marker in _FORCED_FAILURE_MARKERS):
        return False
    return bool(_LOOKS_USABLE.match(target))


class LoggingEmergencyCallProvider:
    """Logs the call attempt instead of placing a real Twilio call.

    Demo/test targets (anything that doesn't carry a forced-failure marker,
    see `_target_is_usable`) report `EMERGENCY_CALLED`; targets that look
    invalid or marked offline report `EMERGENCY_CALL_FAILED`, exactly the
    shape a real vendor failure (busy, no answer, API error) would produce.
    """

    async def call(self, target: str, message: str) -> ActionOutcome:
        # `message` collides with stdlib logging's reserved LogRecord
        # attribute once structlog is routed through stdlib (as a real
        # deployment's logging config typically does) — renamed to
        # `call_message` here for the same reason the FHIR adapter renamed
        # its own `event` kwarg.
        if not _target_is_usable(target):
            logger.warning(
                "emergency_call.simulated_failure", target=target, call_message=message
            )
            return ActionOutcome.EMERGENCY_CALL_FAILED

        logger.info("emergency_call.simulated", target=target, call_message=message)
        return ActionOutcome.EMERGENCY_CALLED


class LoggingDeviceProvider:
    """Logs the command and simulates a device-state read-back.

    Per architecture.md section 4 step 5, a command is never trusted on the
    send acknowledgement alone — the state is always read back. This stub
    "reads back" a simulated state: it mirrors `payload` for a usable
    target, and reports a mismatch (`DEVICE_ACTION_FAILED`) for a target
    carrying a forced-failure marker, standing in for an offline or
    rejecting device.
    """

    async def send_command(self, target: str, payload: dict) -> ActionOutcome:
        logger.info("device_command.simulated_send", target=target, payload=payload)

        if not _target_is_usable(target):
            logger.warning(
                "device_command.state_mismatch", target=target, payload=payload
            )
            return ActionOutcome.DEVICE_ACTION_FAILED

        # Simulated read-back: a real provider would re-query the vendor API
        # here and compare the reported state against `payload`.
        logger.info("device_command.state_read_back", target=target, payload=payload)
        return ActionOutcome.DEVICE_ACTION_DONE


class NeutralVoiceProvider:
    """The real F8 behavior today: Sarvam's neutral preset voice, always.

    Sarvam does not support voice cloning, so this provider never attempts
    one — it always returns `SPOKEN_NEUTRAL`, regardless of `clone_id`. It
    exists so the gateway's provider seam is exercised identically whether
    or not a cloning vendor is ever plugged in.
    """

    async def synthesize(
        self, text: str, clone_id: str | None
    ) -> tuple[bytes, ActionOutcome]:
        logger.info("voice.synthesized_neutral", text_len=len(text), clone_id=clone_id)
        # Placeholder audio payload; a real implementation calls Sarvam TTS.
        audio = f"[neutral-voice-audio]{text}".encode()
        return audio, ActionOutcome.SPOKEN_NEUTRAL
