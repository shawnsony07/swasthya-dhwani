"""Typed exceptions for the FHIR adapter.

architecture.md section 8 ("FHIR (HAPI) down -> Triage proceeds on confirmed
data without history") requires calling code to be able to catch a single,
specific exception for "the FHIR server is not reachable" rather than let an
unhandled httpx error crash the triage flow.
"""
from __future__ import annotations


class FhirAdapterError(Exception):
    """Base class for all errors raised by swasthya.fhir.adapter."""


class FhirUnavailableError(FhirAdapterError):
    """The HAPI FHIR server could not be reached, or failed repeatedly.

    Raised for connection failures, timeouts, and 5xx responses that persist
    after the single permitted retry. Callers should catch this and proceed
    without FHIR history per architecture.md section 8, rather than let the
    call fail outright.
    """


class FhirRejectedError(FhirAdapterError):
    """HAPI rejected the request outright (a non-retryable 4xx response).

    This signals a bug in the request we built (bad resource shape, bad
    reference, validation failure) rather than an outage, so it is not
    retried and is distinguished from FhirUnavailableError.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
