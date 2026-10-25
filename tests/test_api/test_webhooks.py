"""Tests for the Twilio status callback webhook endpoint (src/swasthya/api/routers/webhooks.py)."""
from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi.testclient import TestClient

from swasthya.api.app import create_app
from swasthya.api.routers.webhooks import validate_twilio_signature


def _compute_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    mac = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("ascii")


def test_signature_validation_helper():
    url = "https://example.com/webhooks/twilio/call-status"
    params = {"CallSid": "CA123456", "CallStatus": "completed", "From": "+19897877862", "To": "+919037820802"}
    token = "test-auth-token-123"

    sig = _compute_signature(url, params, token)
    assert validate_twilio_signature(url, params, sig, token) is True
    assert validate_twilio_signature(url, params, "bad-signature", token) is False
    assert validate_twilio_signature(url, params, None, token) is False
    assert validate_twilio_signature(url, params, sig, "") is False


def test_webhook_returns_403_when_signature_is_invalid_and_auth_enabled(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "valid-secret-token")

    app = create_app()
    client = TestClient(app, base_url="http://testserver")

    response = client.post(
        "/webhooks/twilio/call-status",
        data={"CallSid": "CA12345", "CallStatus": "completed", "To": "+919037820802"},
        headers={"X-Twilio-Signature": "invalid-sig"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Twilio signature"


def test_webhook_accepts_valid_signature(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    token = "my-secret-auth-token"
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)

    app = create_app()
    client = TestClient(app, base_url="http://testserver")

    url = "http://testserver/webhooks/twilio/call-status"
    params = {"CallSid": "CA99999", "CallStatus": "completed", "From": "+1000", "To": "+91000"}
    sig = _compute_signature(url, params, token)

    response = client.post(
        "/webhooks/twilio/call-status",
        data=params,
        headers={"X-Twilio-Signature": sig},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert "<Response></Response>" in response.text


def test_webhook_bypasses_signature_when_auth_disabled(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")

    app = create_app()
    client = TestClient(app, base_url="http://testserver")

    response = client.post(
        "/webhooks/twilio/call-status",
        data={"CallSid": "CA111", "CallStatus": "busy", "To": "+91000"},
    )
    assert response.status_code == 200
    assert "<Response></Response>" in response.text
