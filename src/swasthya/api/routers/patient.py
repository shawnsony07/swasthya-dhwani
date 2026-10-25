"""Public patient token endpoint for LiveKit WebRTC triage calls.

Allows patient browsers/mobile devices to request a short-lived LiveKit
token to connect directly to the Malayalam voice triage agent.
"""
from __future__ import annotations

import os
import uuid

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/patient", tags=["patient"])


class PatientTokenRequest(BaseModel):
    name: str | None = Field(default=None, description="Patient name if known")
    district: str | None = Field(default="Kerala", description="Current district")


class PatientTokenResponse(BaseModel):
    token: str
    room: str
    server_url: str
    identity: str


@router.post("/token", response_model=PatientTokenResponse)
@router.get("/token", response_model=PatientTokenResponse)
async def create_patient_voice_token(
    name: str | None = Query(default=None),
    district: str | None = Query(default="Kerala"),
) -> PatientTokenResponse:
    """Issues a WebRTC access token for an inbound patient triage call."""
    from livekit.api import AccessToken, VideoGrants

    api_key = os.environ.get("LIVEKIT_API_KEY", "")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    server_url = os.environ.get(
        "LIVEKIT_URL", "wss://swasthya-dhwani-manv1osr.livekit.cloud"
    )

    if not api_key or not api_secret:
        logger.error("patient.token_missing_credentials")
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be configured")

    clean_id = uuid.uuid4().hex[:8]
    room_name = f"patient-{clean_id}"
    participant_identity = f"patient-{clean_id}"
    participant_name = name.strip() if name and name.strip() else f"Patient {clean_id[:4]}"

    grant = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )

    token_builder = (
        AccessToken(api_key, api_secret)
        .with_identity(participant_identity)
        .with_name(participant_name)
        .with_grants(grant)
        .with_metadata(f'{{"district": "{district}", "channel": "web"}}')
    )

    jwt_token = token_builder.to_jwt()

    logger.info(
        "patient.token_issued",
        room=room_name,
        identity=participant_identity,
        district=district,
    )

    return PatientTokenResponse(
        token=jwt_token,
        room=room_name,
        server_url=server_url,
        identity=participant_identity,
    )
