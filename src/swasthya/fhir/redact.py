"""Logging-safe redaction helpers.

architecture.md S9: "No raw audio or full patient identifiers in application
logs; identifiers are hashed in traces." Every log statement in this package
that might carry a patient identifier, transcript, or other free-text clinical
content MUST go through one of these helpers first.
"""
from __future__ import annotations

import hashlib

_HASH_PREFIX_LEN = 12


def hash_identifier(identifier: str) -> str:
    """Return a short, non-reversible trace token for a patient identifier.

    Never log `identifier` itself; log the return value of this function.
    """
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:_HASH_PREFIX_LEN]}"


def redact_text(text: str | None) -> str:
    """Return a safe stand-in for free text that must never reach logs.

    Used for raw transcripts, interpreted text, and any other patient
    speech content. Only a length is kept, which is enough to debug
    "was this field empty" without exposing clinical content.
    """
    if not text:
        return "<empty>"
    return f"<redacted:{len(text)} chars>"
