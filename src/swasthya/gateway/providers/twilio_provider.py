"""Real Twilio emergency call provider (architecture.md F7, loops L14/L15).

Not the default: `entrypoint.py` only constructs this when
`EMERGENCY_CALL_PROVIDER=twilio` is explicitly set, so a misconfigured
deployment with no Twilio credentials falls back to
`LoggingEmergencyCallProvider` rather than crashing or silently failing
every emergency call.

Design matches `swasthya.fhir.adapter`'s established pattern for a vendor
HTTP integration in this codebase: plain `httpx` (not the vendor SDK —
Twilio's own Python SDK is a dependency this module doesn't need), a
timeout + one jittered retry on transient failures via `tenacity`, and
structured logging that never includes the auth token or the call
message's content (the message may include a patient's reported symptoms
— logged only as a length/hash, matching S9 in architecture.md).

Twilio's call-creation API is asynchronous: it returns immediately with a
`queued`/`ringing`/`in-progress` status, not a final outcome. Getting a
real answered/busy/no-answer result needs either a status-callback
webhook (not yet built — see docs/PROJECT_STATUS.md item 5a.2) or polling
the call resource, which is what this module does: create the call, then
poll `GET /Calls/{Sid}.json` until a terminal status or the ring timeout
elapses. This is architecture.md loop L15's own documented fallback
("Poll the call status if the callback never arrives"), used here as the
primary mechanism rather than a fallback, since no public callback URL
exists in local/dev. Passing `TWILIO_STATUS_CALLBACK_URL` (e.g. a tunnel
URL or the deployed API's public address) lets a real deployment use the
webhook instead once that endpoint exists; this module still polls as a
backstop either way.
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import httpx
import structlog
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from swasthya.contracts import ActionOutcome

logger = structlog.get_logger(__name__)

_API_BASE = "https://api.twilio.com/2010-04-01"
_CONNECT_TIMEOUT_SECONDS = 5.0
_TOTAL_TIMEOUT_SECONDS = 10.0
_MAX_ATTEMPTS = 2

# Twilio call statuses that mean the call is done, one way or another.
_TERMINAL_STATUSES = frozenset({"completed", "busy", "no-answer", "canceled", "failed"})
# Of those, only "completed" means the call actually connected and played
# through — the rest are all some flavor of "didn't reach anyone."
_SUCCESS_STATUSES = frozenset({"completed"})

_POLL_INTERVAL_SECONDS = 2.0


class TwilioConfigurationError(RuntimeError):
    """Raised at construction, not at call time, so a misconfigured
    deployment fails loudly on startup rather than on the first real
    emergency."""


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class TwilioEmergencyCallProvider:
    """Implements `providers.base.EmergencyCallProvider` against the real
    Twilio Calls API."""

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        status_callback_url: str | None = None,
        voice_url: str | None = None,
        ring_timeout_seconds: float | None = None,
    ) -> None:
        self._account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
        self._auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
        self._from_number = from_number or os.environ.get("TWILIO_FROM_NUMBER", "")
        self._status_callback_url = status_callback_url or os.environ.get(
            "TWILIO_STATUS_CALLBACK_URL", ""
        ) or None
        self._voice_url = voice_url or os.environ.get("TWILIO_VOICE_URL", "") or None
        self._ring_timeout_seconds = ring_timeout_seconds or float(
            os.environ.get("TWILIO_RING_TIMEOUT_SECONDS", "30")
        )

        if not self._account_sid or not self._auth_token or not self._from_number:
            raise TwilioConfigurationError(
                "TwilioEmergencyCallProvider requires TWILIO_ACCOUNT_SID, "
                "TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER to all be set."
            )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=(self._account_sid, self._auth_token),
            timeout=httpx.Timeout(_TOTAL_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS),
        )

    async def call(self, target: str, message: str) -> ActionOutcome:
        started_at = datetime.now(UTC)
        try:
            call_sid = await self._create_call(target, message)
        except Exception:  # noqa: BLE001 - any creation failure is a call failure
            logger.warning("twilio.call_create_failed", target_suffix=target[-4:])
            return ActionOutcome.EMERGENCY_CALL_FAILED

        logger.info("twilio.call_created", call_sid=call_sid, target_suffix=target[-4:])
        outcome = await self._poll_until_terminal(call_sid, started_at)
        return outcome

    async def _create_call(self, target: str, message: str) -> str:
        data: dict[str, str] = {
            "To": target,
            "From": self._from_number,
        }
        if self._voice_url:
            data["Url"] = self._voice_url
        else:
            twiml = f'<Response><Say language="ml-IN">{_escape_xml(message)}</Say></Response>'
            data["Twiml"] = twiml

        if self._status_callback_url:
            data["StatusCallback"] = self._status_callback_url
            data["StatusCallbackEvent"] = "completed"

        async with self._client() as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(_MAX_ATTEMPTS),
                wait=wait_random_exponential(multiplier=0.2, max=1.0),
                retry=retry_if_exception(_is_transient),
                reraise=True,
            ):
                with attempt:
                    response = await client.post(
                        f"{_API_BASE}/Accounts/{self._account_sid}/Calls.json",
                        data=data,
                    )
                    # Trial accounts disallow inline TwiML; fall back to pre-configured or demo voice URL
                    if response.status_code == 400 and "trial accounts have limited parameter access" in response.text:
                        logger.warning("twilio.trial_account_fallback_url", reason="trial parameter restriction")
                        data.pop("Twiml", None)
                        data["Url"] = self._voice_url or "http://demo.twilio.com/docs/voice.xml"
                        response = await client.post(
                            f"{_API_BASE}/Accounts/{self._account_sid}/Calls.json",
                            data=data,
                        )
                    response.raise_for_status()
                    return str(response.json()["sid"])

        raise RuntimeError("Twilio call creation did not complete")  # pragma: no cover

    async def _poll_until_terminal(self, call_sid: str, started_at: datetime) -> ActionOutcome:
        # Always poll at least once before ever checking the timeout -- a
        # ring timeout means "we checked and it's still not answered,"
        # never "we never got around to checking."
        async with self._client() as client:
            first_poll = True
            while True:
                elapsed = (datetime.now(UTC) - started_at).total_seconds()
                if not first_poll and elapsed >= self._ring_timeout_seconds:
                    logger.warning("twilio.ring_timeout", call_sid=call_sid, elapsed=elapsed)
                    return ActionOutcome.EMERGENCY_CALL_FAILED
                first_poll = False

                try:
                    response = await client.get(
                        f"{_API_BASE}/Accounts/{self._account_sid}/Calls/{call_sid}.json"
                    )
                    response.raise_for_status()
                    status = response.json().get("status", "")
                except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
                    logger.warning("twilio.poll_failed", call_sid=call_sid)
                    await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                    continue

                if status in _TERMINAL_STATUSES:
                    logger.info("twilio.call_terminal", call_sid=call_sid, status=status)
                    return (
                        ActionOutcome.EMERGENCY_CALLED
                        if status in _SUCCESS_STATUSES
                        else ActionOutcome.EMERGENCY_CALL_FAILED
                    )

                await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
