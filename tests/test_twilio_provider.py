"""Tests for the real Twilio emergency call provider
(src/swasthya/gateway/providers/twilio_provider.py). No live Twilio calls —
every HTTP boundary is mocked with respx, matching the pattern already
used for the FHIR adapter.
"""
from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx

from swasthya.contracts import ActionOutcome
from swasthya.gateway.providers.twilio_provider import (
    TwilioConfigurationError,
    TwilioEmergencyCallProvider,
)

BASE_URL = "https://api.twilio.com/2010-04-01"
ACCOUNT_SID = "ACtest000000000000000000000000000"


def _provider(**overrides) -> TwilioEmergencyCallProvider:
    defaults = {
        "account_sid": ACCOUNT_SID,
        "auth_token": "test-auth-token",
        "from_number": "+19897877862",
        "ring_timeout_seconds": 6.0,
    }
    defaults.update(overrides)
    return TwilioEmergencyCallProvider(**defaults)


def _call_response(sid: str, status: str) -> dict:
    return {"sid": sid, "status": status}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_missing_account_sid_raises_at_construction(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    with pytest.raises(TwilioConfigurationError):
        TwilioEmergencyCallProvider(auth_token="t", from_number="+19897877862")


def test_missing_from_number_raises_at_construction(monkeypatch):
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    with pytest.raises(TwilioConfigurationError):
        TwilioEmergencyCallProvider(account_sid=ACCOUNT_SID, auth_token="t")


def test_env_vars_are_read_when_no_explicit_args_given(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", ACCOUNT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "from-env")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+19897877862")
    provider = TwilioEmergencyCallProvider()
    assert provider._account_sid == ACCOUNT_SID
    assert provider._from_number == "+19897877862"


# ---------------------------------------------------------------------------
# Successful call: created, then polling finds "completed"
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
async def test_call_answered_and_completed_returns_emergency_called(respx_mock):
    respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(201, json=_call_response("CAtest1", "queued"))
    )
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest1.json").mock(
        side_effect=[
            httpx.Response(200, json=_call_response("CAtest1", "ringing")),
            httpx.Response(200, json=_call_response("CAtest1", "completed")),
        ]
    )

    provider = _provider()
    outcome = await provider.call("+919037820802", "Emergency escalation test message.")

    assert outcome is ActionOutcome.EMERGENCY_CALLED


@pytest.mark.parametrize("final_status", ["busy", "no-answer", "failed", "canceled"])
@respx.mock(base_url=BASE_URL)
async def test_call_reaching_a_terminal_failure_status_returns_call_failed(
    respx_mock, final_status
):
    respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(201, json=_call_response("CAtest2", "queued"))
    )
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest2.json").mock(
        return_value=httpx.Response(200, json=_call_response("CAtest2", final_status))
    )

    provider = _provider()
    outcome = await provider.call("+919037820802", "test")

    assert outcome is ActionOutcome.EMERGENCY_CALL_FAILED


@respx.mock(base_url=BASE_URL)
async def test_call_creation_rejected_returns_call_failed_without_polling(respx_mock):
    create_route = respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(400, json={"code": 21211, "message": "invalid number"})
    )

    provider = _provider()
    outcome = await provider.call("not-a-real-number", "test")

    assert outcome is ActionOutcome.EMERGENCY_CALL_FAILED
    assert create_route.call_count == 1


@respx.mock(base_url=BASE_URL)
async def test_ring_timeout_elapses_without_terminal_status_returns_call_failed(respx_mock):
    respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(201, json=_call_response("CAtest3", "queued"))
    )
    # Never reaches a terminal status -- always "ringing".
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest3.json").mock(
        return_value=httpx.Response(200, json=_call_response("CAtest3", "ringing"))
    )

    provider = _provider(ring_timeout_seconds=0.1)
    outcome = await provider.call("+919037820802", "test")

    assert outcome is ActionOutcome.EMERGENCY_CALL_FAILED


@respx.mock(base_url=BASE_URL)
async def test_transient_5xx_on_create_is_retried_then_succeeds(respx_mock):
    respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        side_effect=[
            httpx.Response(503, json={"message": "unavailable"}),
            httpx.Response(201, json=_call_response("CAtest4", "queued")),
        ]
    )
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest4.json").mock(
        return_value=httpx.Response(200, json=_call_response("CAtest4", "completed"))
    )

    provider = _provider()
    outcome = await provider.call("+919037820802", "test")

    assert outcome is ActionOutcome.EMERGENCY_CALLED


@respx.mock(base_url=BASE_URL)
async def test_status_callback_url_is_sent_when_configured(respx_mock):
    create_route = respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(201, json=_call_response("CAtest5", "queued"))
    )
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest5.json").mock(
        return_value=httpx.Response(200, json=_call_response("CAtest5", "completed"))
    )

    provider = _provider(status_callback_url="https://example.com/webhooks/twilio/call-status")
    await provider.call("+919037820802", "test")

    sent_body = create_route.calls.last.request.content.decode()
    assert "StatusCallback=https%3A%2F%2Fexample.com" in sent_body


@respx.mock(base_url=BASE_URL)
async def test_message_is_escaped_into_twiml_say_verb(respx_mock):
    create_route = respx_mock.post(f"/Accounts/{ACCOUNT_SID}/Calls.json").mock(
        return_value=httpx.Response(201, json=_call_response("CAtest6", "queued"))
    )
    respx_mock.get(f"/Accounts/{ACCOUNT_SID}/Calls/CAtest6.json").mock(
        return_value=httpx.Response(200, json=_call_response("CAtest6", "completed"))
    )

    provider = _provider()
    await provider.call("+919037820802", 'Patient & caregiver say "help" <now>')

    sent_body = create_route.calls.last.request.content.decode()
    assert "&amp;" in sent_body
    assert "&lt;now&gt;" in sent_body
    assert "&quot;help&quot;" in sent_body
