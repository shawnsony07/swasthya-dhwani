"""FHIR R4 adapter: the only module that talks to HAPI FHIR.

Target write shape (docs/architecture.md section 6, "FHIR writes"):

- Symptoms as FHIR ``Observation`` resources.
- The interpretation as a ``Provenance`` resource naming the interpreter
  model and confidence.
- The referral as a ``ServiceRequest`` resource.
- Every decision as an ``AuditEvent`` resource.
- A ``Patient`` resource write/lookup (by identifier), since every other
  resource here needs a subject reference.

No existing adapter was found to trace against (architecture.md section 16
notes this explicitly: "Not traced: FHIR adapter writes"), so the resource
shapes below are a reasonable, HAPI-compatible reading of the target list
and are documented in detail in this module's docstrings and in the final
report to the team.

Resilience (section 8): every outbound call has a connect/total timeout and
at most one jittered retry on transient failures (5xx, connect errors,
timeouts); 4xx responses are never retried. A completely unreachable server,
or one that keeps failing after the retry, raises ``FhirUnavailableError`` so
callers can proceed without FHIR history instead of crashing the call.

Privacy (section 9, S9): this module never logs raw transcript text, raw
audio, or an unredacted patient identifier. See ``swasthya.fhir.redact``.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx
import structlog
from fhir.resources.R4B.auditevent import AuditEvent as FhirAuditEvent
from fhir.resources.R4B.auditevent import AuditEventAgent, AuditEventSource
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.extension import Extension
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from swasthya.contracts import AuditEvent, TriageData
from swasthya.fhir.exceptions import FhirRejectedError, FhirUnavailableError
from swasthya.fhir.redact import hash_identifier, redact_text

log = structlog.get_logger(__name__)

DEFAULT_BASE_URL: Final[str] = "http://localhost:8080/fhir"

_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
_TOTAL_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_ATTEMPTS: Final[int] = 2  # one initial attempt + at most one retry

_CONFIDENCE_EXTENSION_URL: Final[str] = (
    "https://swasthya-dhwani.example/fhir/StructureDefinition/interpretation-confidence"
)
_INTERPRETER_MODEL_EXTENSION_URL: Final[str] = (
    "https://swasthya-dhwani.example/fhir/StructureDefinition/interpreter-model"
)
_IDENTIFIER_SYSTEM: Final[str] = "https://swasthya-dhwani.example/fhir/patient-identifier"

# Referral tiers that warrant an "urgent" ServiceRequest.priority (section 5/6).
_URGENT_TIERS: Final[frozenset[str]] = frozenset({"C1", "C2"})


def _base_url() -> str:
    return os.environ.get("HAPI_FHIR_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(_TOTAL_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=_base_url(), timeout=_timeout())


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


async def _send(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any],
    op_name: str,
) -> httpx.Response:
    """POST/PUT a resource to HAPI with one jittered retry on transient failures.

    4xx responses raise FhirRejectedError immediately (no retry: a retry
    cannot fix a validation error). Connection failures, timeouts, and 5xx
    responses that persist past the retry raise FhirUnavailableError.
    """
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            wait=wait_random_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        ):
            with attempt:
                response = await client.request(method, path, json=json_body)
                response.raise_for_status()
                return response
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500:
            log.warning(
                "fhir_write_failed_after_retry",
                op=op_name,
                status_code=status,
            )
            raise FhirUnavailableError(
                f"HAPI FHIR returned {status} for {op_name} after retry"
            ) from exc
        log.error("fhir_write_rejected", op=op_name, status_code=status)
        raise FhirRejectedError(
            f"HAPI FHIR rejected {op_name} with {status}", status_code=status
        ) from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning("fhir_unreachable", op=op_name, error_type=type(exc).__name__)
        raise FhirUnavailableError(f"HAPI FHIR unreachable for {op_name}") from exc

    # Unreachable in practice: AsyncRetrying with reraise=True always either
    # returns from the loop body or raises. Satisfies type checkers.
    raise FhirUnavailableError(f"HAPI FHIR request for {op_name} did not complete")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------


async def get_or_create_patient(patient_identifier: str, identifier_type: str) -> str:
    """Look up a Patient by identifier, creating one if none exists.

    Returns the HAPI-assigned Patient resource id. All other writes in this
    module take that id as their subject reference, per architecture.md
    section 6: "symptoms as Observations... all need a subject reference."
    """
    id_hash = hash_identifier(patient_identifier)
    async with _new_client() as client:
        try:
            search = await client.get(
                "/Patient",
                params={"identifier": f"{_IDENTIFIER_SYSTEM}|{patient_identifier}"},
            )
            search.raise_for_status()
            bundle = search.json()
            entries = bundle.get("entry") or []
            if entries:
                patient_id = entries[0]["resource"]["id"]
                log.info("fhir_patient_found", patient_id_hash=id_hash)
                return str(patient_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                log.error(
                    "fhir_patient_search_rejected",
                    patient_id_hash=id_hash,
                    status_code=exc.response.status_code,
                )
                raise FhirRejectedError(
                    "HAPI FHIR rejected Patient search",
                    status_code=exc.response.status_code,
                ) from exc
            log.warning("fhir_patient_search_failed", patient_id_hash=id_hash)
            raise FhirUnavailableError("HAPI FHIR unreachable for Patient search") from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("fhir_unreachable", op="patient_search", patient_id_hash=id_hash)
            raise FhirUnavailableError("HAPI FHIR unreachable for Patient search") from exc

        patient = Patient(
            identifier=[
                Identifier(system=_IDENTIFIER_SYSTEM, value=patient_identifier, type=CodeableConcept(
                    text=identifier_type
                ))
            ]
        )
        response = await _send(
            client,
            "POST",
            "/Patient",
            json_body=patient.model_dump(exclude_none=True, mode="json"),
            op_name="create_patient",
        )
        patient_id = str(response.json()["id"])
        log.info("fhir_patient_created", patient_id_hash=id_hash)
        return patient_id


# ---------------------------------------------------------------------------
# Triage record: Observations (symptoms) + Provenance (interpretation)
# ---------------------------------------------------------------------------


def _build_symptom_observation(symptom: str, patient_fhir_id: str, when: datetime) -> Observation:
    return Observation(
        status="final",
        category=[
            CodeableConcept(
                coding=[
                    Coding(
                        system="http://terminology.hl7.org/CodeSystem/observation-category",
                        code="exam",
                        display="exam",
                    )
                ]
            )
        ],
        code=CodeableConcept(text=symptom),
        subject=Reference(reference=f"Patient/{patient_fhir_id}"),
        effectiveDateTime=when,
        valueString=symptom,
    )


def _build_interpretation_provenance(
    triage: TriageData, observation_ids: list[str], when: datetime
) -> Provenance:
    return Provenance(
        target=[Reference(reference=f"Observation/{obs_id}") for obs_id in observation_ids],
        recorded=when,
        agent=[
            ProvenanceAgent(
                who=Reference(display=triage.interpreter_model or "unknown-interpreter"),
            )
        ],
        extension=[
            Extension(
                url=_INTERPRETER_MODEL_EXTENSION_URL,
                valueString=triage.interpreter_model or "unknown-interpreter",
            ),
            Extension(
                url=_CONFIDENCE_EXTENSION_URL,
                valueDecimal=Decimal(str(triage.interpretation_confidence)),
            ),
        ],
    )


async def write_triage_record(triage: TriageData, patient_fhir_id: str) -> dict[str, Any]:
    """Write symptom Observations and an interpretation Provenance to HAPI.

    Returns a dict of created resource ids:
    ``{"patient_fhir_id": ..., "observation_ids": [...], "provenance_id": ...}``.
    Raises FhirUnavailableError / FhirRejectedError on failure; it does not
    swallow errors itself, so callers decide (per architecture.md section 8)
    whether to proceed without history.

    Never logs triage.raw_transcript or triage.interpreted_text; only their
    redacted lengths and a hash of the patient identifier.
    """
    id_hash = hash_identifier(triage.patient_identifier)
    when = _now()
    log.info(
        "fhir_write_triage_record_started",
        patient_id_hash=id_hash,
        symptom_count=len(triage.symptoms),
        raw_transcript=redact_text(triage.raw_transcript),
        interpreted_text=redact_text(triage.interpreted_text),
    )

    async with _new_client() as client:
        observation_ids: list[str] = []
        for symptom in triage.symptoms:
            resource = _build_symptom_observation(symptom, patient_fhir_id, when)
            response = await _send(
                client,
                "POST",
                "/Observation",
                json_body=resource.model_dump(exclude_none=True, mode="json"),
                op_name="create_observation",
            )
            observation_ids.append(str(response.json()["id"]))

        provenance_resource = _build_interpretation_provenance(triage, observation_ids, when)
        provenance_response = await _send(
            client,
            "POST",
            "/Provenance",
            json_body=provenance_resource.model_dump(exclude_none=True, mode="json"),
            op_name="create_provenance",
        )
        provenance_id = str(provenance_response.json()["id"])

    log.info(
        "fhir_write_triage_record_completed",
        patient_id_hash=id_hash,
        observation_count=len(observation_ids),
        provenance_id=provenance_id,
    )
    return {
        "patient_fhir_id": patient_fhir_id,
        "observation_ids": observation_ids,
        "provenance_id": provenance_id,
    }


# ---------------------------------------------------------------------------
# Referral: ServiceRequest
# ---------------------------------------------------------------------------


async def write_referral(patient_fhir_id: str, tier: str, hospital: str | None) -> str:
    """Write the referral as a ServiceRequest and return its HAPI id."""
    priority = "urgent" if tier in _URGENT_TIERS else "routine"
    resource = ServiceRequest(
        status="active",
        intent="order",
        subject=Reference(reference=f"Patient/{patient_fhir_id}"),
        code=CodeableConcept(text=f"Referral - tier {tier}"),
        priority=priority,
        authoredOn=_now(),
        locationCode=[CodeableConcept(text=hospital)] if hospital else None,
    )
    async with _new_client() as client:
        response = await _send(
            client,
            "POST",
            "/ServiceRequest",
            json_body=resource.model_dump(exclude_none=True, mode="json"),
            op_name="create_service_request",
        )
    service_request_id = str(response.json()["id"])
    log.info(
        "fhir_write_referral_completed",
        tier=tier,
        hospital_known=hospital is not None,
        service_request_id=service_request_id,
    )
    return service_request_id


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


def _build_audit_event(event: AuditEvent) -> FhirAuditEvent:
    extensions = (
        [Extension(url=_INTERPRETER_MODEL_EXTENSION_URL, valueString=event.model_id)]
        if event.model_id
        else None
    )
    return FhirAuditEvent(
        type=Coding(
            system="http://swasthya-dhwani.example/fhir/audit-event-type",
            code=event.event,
            display=event.event,
        ),
        action="E",
        recorded=event.timestamp,
        outcome="0",
        agent=[
            AuditEventAgent(
                who=Reference(display=event.actor),
                requestor=event.actor in {"patient", "caregiver", "doctor"},
            )
        ],
        source=AuditEventSource(observer=Reference(display="swasthya-dhwani-fhir-adapter")),
        extension=extensions,
    )


async def write_audit_event(event: AuditEvent) -> str:
    """Write one decision/step as a FHIR AuditEvent and return its HAPI id.

    `event.detail` may contain arbitrary step metadata; callers are
    responsible for not putting raw transcript/audio/identifiers into it,
    same as every other field this adapter writes. This function itself
    never logs `event.detail`.
    """
    resource = _build_audit_event(event)
    body = resource.model_dump(exclude_none=True, mode="json")

    async with _new_client() as client:
        response = await _send(
            client,
            "POST",
            "/AuditEvent",
            json_body=body,
            op_name="create_audit_event",
        )
    audit_event_id = str(response.json()["id"])
    log.info(
        "fhir_write_audit_event_completed",
        task_id=event.task_id,
        audit_event_type=event.event,
        audit_event_id=audit_event_id,
    )
    return audit_event_id
