"""Per-patient allow-list of contacts and devices.

Per architecture.md section 4 step 2 and section 7's safety table ("speech
cannot add devices or contacts"): the only way an entry gets added is a
direct, explicit call to `AllowList.add_entry` from trusted code (the nurse
enrollment flow — not built in this module). There is deliberately no path
from an `ActionRequest`, an LLM output, or any speech-derived payload into
`add_entry`; the gateway only ever calls `is_allowed`.
"""
from __future__ import annotations

from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class AllowListStore(Protocol):
    """Storage seam so a Postgres-backed store can replace the in-memory
    default without any change to `AllowList` or the gateway."""

    def get(self, patient_id: str) -> set[str]: ...

    def get_ordered(self, patient_id: str) -> list[str]:
        """Same entries as `get`, in enrollment order. Needed for F7's
        "contacts are called in the order the nurse set" — a plain `set`
        has no order, so the store must track it separately. A
        Postgres-backed store would order by an explicit priority column
        instead of insertion order; this in-memory default uses insertion
        order as its best available proxy."""
        ...

    def add(self, patient_id: str, target: str) -> None: ...


class InMemoryAllowListStore:
    """Default store: a plain dict, process-local. Fine for the demo; a
    Postgres-backed `AllowListStore` is the pilot step."""

    def __init__(self) -> None:
        self._entries: dict[str, set[str]] = {}
        self._order: dict[str, list[str]] = {}

    def get(self, patient_id: str) -> set[str]:
        return self._entries.get(patient_id, set())

    def get_ordered(self, patient_id: str) -> list[str]:
        return list(self._order.get(patient_id, []))

    def add(self, patient_id: str, target: str) -> None:
        if target not in self._entries.setdefault(patient_id, set()):
            self._order.setdefault(patient_id, []).append(target)
        self._entries[patient_id].add(target)


class AllowList:
    """Checks a target against a patient's enrolled contacts/devices.

    `kind` ("contact" or "device") is recorded for audit/debugging purposes
    only; the check itself is keyed on patient + target.
    """

    def __init__(self, store: AllowListStore | None = None) -> None:
        self._store: AllowListStore = store or InMemoryAllowListStore()

    def is_allowed(self, patient_id: str, target: str) -> bool:
        allowed = target in self._store.get(patient_id)
        logger.info(
            "allowlist.checked", patient_id=patient_id, target=target, allowed=allowed
        )
        return allowed

    def ordered_targets(self, patient_id: str) -> list[str]:
        """Enrolled targets for `patient_id`, in the order the nurse set
        them (F7: contacts are called in this order, first answered wins)."""
        return self._store.get_ordered(patient_id)

    def add_entry(self, patient_id: str, target: str, kind: str) -> None:
        """Trusted-code-only entry point (e.g. nurse enrollment). Never call
        this from a path that can be influenced by speech or an LLM
        output."""
        self._store.add(patient_id, target)
        logger.info(
            "allowlist.entry_added", patient_id=patient_id, target=target, kind=kind
        )
