"""Twilio status callback webhook endpoint (architecture.md loop L15, security S11).

`POST /webhooks/twilio/call-status` receives real-time updates as emergency
outbound calls transition across queued, ringing, in-progress, completed,
busy, failed, no-answer, or canceled.

Per S11, every request is validated against Twilio's HMAC-SHA1 signature
using the shared `TWILIO_AUTH_TOKEN`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

import structlog
from fastapi import APIRouter, Form, Header, HTTPException, Request, Response, status

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


def validate_twilio_signature(
    url: str,
    params: dict[str, str],
    signature: str | None,
    auth_token: str,
) -> bool:
    """Validates the X-Twilio-Signature header using Twilio's HMAC-SHA1 algorithm.

    https://www.twilio.com/docs/usage/security#validating-requests
    """
    if not signature or not auth_token:
        return False

    # Sort parameter keys alphabetically by unicode point and append key+value
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    mac = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1)
    computed = base64.b64encode(mac.digest()).decode("ascii")
    return hmac.compare_digest(computed, signature)


@router.post("/call-status", status_code=status.HTTP_200_OK)
async def twilio_call_status_webhook(
    request: Request,
    call_sid: str = Form(..., alias="CallSid"),
    call_status: str = Form(..., alias="CallStatus"),
    to: str = Form("", alias="To"),
    from_: str = Form("", alias="From"),
    call_duration: str | None = Form(None, alias="CallDuration"),
    x_twilio_signature: str | None = Header(None, alias="X-Twilio-Signature"),
) -> Response:
    """Receives Twilio call status callbacks and logs terminal outcomes."""
    auth_disabled = os.environ.get("AUTH_DISABLED", "").strip().lower() == "true"
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")

    if not auth_disabled:
        # Reconstruct the request URL as seen by Twilio
        url = str(request.url)
        form_data = await request.form()
        params = {k: str(v) for k, v in form_data.items()}

        if not validate_twilio_signature(url, params, x_twilio_signature, auth_token):
            logger.warning("twilio.webhook_signature_invalid", call_sid=call_sid)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio signature",
            )

    logger.info(
        "twilio.call_status_callback",
        call_sid=call_sid,
        call_status=call_status,
        target_suffix=to[-4:] if to else "",
        duration=call_duration,
    )

    # Return valid empty TwiML response per Twilio webhook conventions
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )
