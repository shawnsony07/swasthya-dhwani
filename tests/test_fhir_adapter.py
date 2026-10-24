"""Tests for swasthya.fhir.adapter.

All HTTP to HAPI FHIR is mocked with respx -- no real network calls, no real
HAPI server needed. architecture.md section 9 (S9) requires that no raw
transcript text or unredacted patient identifier ever reaches application
logs, which the caplog-based tests at the bottom assert directly.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx

from swasthya.contracts import AuditEvent, TriageData
from swasthya.fhir import adapter
from swasthya.fhir.exceptions import FhirRejectedError, FhirUnavailableError

BASE_URL = "http://localhost:8080/fhir"

RAW_TRANSCRIPT_SECRET = "patient said: enikku nenju vedana und, this must never appear in logs"
PATIENT_ID_SECRET = "9999988888"


def _triage(**overrides: object) -> TriageData:
    defaults: dict[str, object] = dict(
        patient_identifier=PATIENT_ID_SECRET,
        identifier_type="phone",
        symptoms=["chest pain", "shortness of breath"],
        raw_transcript=RAW_TRANSCRIPT_SECRET,
        interpreted_text="patient reports chest pain",
        interpretation_confidence=0.91,
        interpreter_model="gemini-2.5-flash",
    )
    defaults.update(overrides)
    return TriageData(**defaults)  # type: ignore[arg-type]


def _audit_event(**overrides: object) -> AuditEvent:
    defaults: dict[str, object] = dict(
        task_id="task-123",
        event="tier_assigned",
        actor="rule_engine",
        timestamp=datetime.now(UTC),
        model_id="gemini-2.5-flash",
    )
    defaults.update(overrides)
    return AuditEvent(**defaults)  # type: ignore[arg-type]


def _fhir_created(resource_type: str, resource_id: str) -> dict:
    return {"resourceType": resource_type, "id": resource_id}


# ---------------------------------------------------------------------------
# Successful writes
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
async def test_write_triage_record_creates_observations_and_provenance(respx_mock):
    respx_mock.post("/Observation").mock(
        side_effect=[
            httpx.Response(201, json=_fhir_created("Observation", "obs-1")),
            httpx.Response(201, json=_fhir_created("Observation", "obs-2")),
        ]
    )
    respx_mock.post("/Provenance").mock(
        return_value=httpx.Response(201, json=_fhir_created("Provenance", "prov-1"))
    )

    result = await adapter.write_triage_record(_triage(), patient_fhir_id="patient-1")

    assert result["patient_fhir_id"] == "patient-1"
    assert result["observation_ids"] == ["obs-1", "obs-2"]
    assert result["provenance_id"] == "prov-1"


@respx.mock(base_url=BASE_URL)
async def test_write_referral_creates_service_request(respx_mock):
    respx_mock.post("/ServiceRequest").mock(
        return_value=httpx.Response(201, json=_fhir_created("ServiceRequest", "sr-1"))
    )

    sr_id = await adapter.write_referral("patient-1", tier="C1", hospital="General Hospital")

    assert sr_id == "sr-1"


@respx.mock(base_url=BASE_URL)
async def test_write_audit_event_creates_audit_event(respx_mock):
    respx_mock.post("/AuditEvent").mock(
        return_value=httpx.Response(201, json=_fhir_created("AuditEvent", "ae-1"))
    )

    ae_id = await adapter.write_audit_event(_audit_event())

    assert ae_id == "ae-1"


@respx.mock(base_url=BASE_URL)
async def test_get_or_create_patient_creates_when_not_found(respx_mock):
    respx_mock.get("/Patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "entry": []})
    )
    respx_mock.post("/Patient").mock(
        return_value=httpx.Response(201, json=_fhir_created("Patient", "patient-1"))
    )

    patient_id = await adapter.get_or_create_patient(PATIENT_ID_SECRET, "phone")

    assert patient_id == "patient-1"


@respx.mock(base_url=BASE_URL, assert_all_called=False)
async def test_get_or_create_patient_returns_existing(respx_mock):
    respx_mock.get("/Patient").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "Patient", "id": "existing-1"}}],
            },
        )
    )
    post_route = respx_mock.post("/Patient").mock(
        return_value=httpx.Response(201, json=_fhir_created("Patient", "should-not-be-used"))
    )

    patient_id = await adapter.get_or_create_patient(PATIENT_ID_SECRET, "phone")

    assert patient_id == "existing-1"
    assert post_route.call_count == 0


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
async def test_transient_503_is_retried_once_then_succeeds(respx_mock):
    route = respx_mock.post("/ServiceRequest").mock(
        side_effect=[
            httpx.Response(503, json={"error": "temporarily unavailable"}),
            httpx.Response(201, json=_fhir_created("ServiceRequest", "sr-retry")),
        ]
    )

    sr_id = await adapter.write_referral("patient-1", tier="A", hospital=None)

    assert sr_id == "sr-retry"
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
async def test_persistent_503_raises_fhir_unavailable_after_one_retry(respx_mock):
    route = respx_mock.post("/ServiceRequest").mock(
        return_value=httpx.Response(503, json={"error": "down"})
    )

    with pytest.raises(FhirUnavailableError):
        await adapter.write_referral("patient-1", tier="A", hospital=None)

    # One initial attempt + at most one retry = 2 calls, never more.
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
async def test_4xx_is_not_retried(respx_mock):
    route = respx_mock.post("/ServiceRequest").mock(
        return_value=httpx.Response(422, json={"error": "invalid resource"})
    )

    with pytest.raises(FhirRejectedError):
        await adapter.write_referral("patient-1", tier="A", hospital=None)

    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
async def test_connect_error_raises_fhir_unavailable(respx_mock):
    respx_mock.post("/ServiceRequest").mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(FhirUnavailableError):
        await adapter.write_referral("patient-1", tier="A", hospital=None)


# ---------------------------------------------------------------------------
# Privacy: S9, no raw transcript / unredacted identifier in logs
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
async def test_no_raw_transcript_or_identifier_in_logs(respx_mock, caplog):
    respx_mock.post("/Observation").mock(
        side_effect=[
            httpx.Response(201, json=_fhir_created("Observation", "obs-1")),
            httpx.Response(201, json=_fhir_created("Observation", "obs-2")),
        ]
    )
    respx_mock.post("/Provenance").mock(
        return_value=httpx.Response(201, json=_fhir_created("Provenance", "prov-1"))
    )

    caplog.set_level(logging.DEBUG)
    await adapter.write_triage_record(_triage(), patient_fhir_id="patient-1")

    for record in caplog.records:
        rendered = record.getMessage()
        assert RAW_TRANSCRIPT_SECRET not in rendered
        assert PATIENT_ID_SECRET not in rendered
        for value in getattr(record, "__dict__", {}).values():
            assert RAW_TRANSCRIPT_SECRET != value
            if isinstance(value, str):
                assert RAW_TRANSCRIPT_SECRET not in value
                assert PATIENT_ID_SECRET not in value
