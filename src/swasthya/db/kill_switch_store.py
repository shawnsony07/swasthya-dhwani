"""DB-backed `KillSwitchStore` (`swasthya.gateway.kill_switch.KillSwitchStore`
Protocol), so the API (where an admin flips the switch) and the voice
agent (where `ActionGateway` checks it before every dispatch) — two
separate processes — actually see the same state.

Lives here, not in `gateway/kill_switch.py`, so that module stays
DB-free; this is the "glue" layer combining the gateway's Protocol with a
real session, the same role `entrypoint.py`'s adapters play for
`WorkflowSink`/`FhirSink`. Both `src/swasthya/voice/entrypoint.py` and
`src/swasthya/api/app.py` import this directly rather than each
reimplementing it, since both processes must read/write the exact same
row.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from swasthya.db.models import KillSwitchRow
from swasthya.gateway.kill_switch import KillSwitchState

_ROW_ID = 1


class DbKillSwitchStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self) -> KillSwitchState:
        with self._session_factory() as session:
            row = session.get(KillSwitchRow, _ROW_ID)
            if row is None:
                return KillSwitchState()
            return KillSwitchState(
                active=row.active,
                changed_by=row.changed_by,
                changed_at=row.changed_at,
                reason=row.reason,
            )

    def set(self, state: KillSwitchState) -> None:
        with self._session_factory() as session:
            row = session.get(KillSwitchRow, _ROW_ID)
            if row is None:
                row = KillSwitchRow(id=_ROW_ID)
                session.add(row)
            row.active = state.active
            row.changed_by = state.changed_by
            row.changed_at = state.changed_at
            row.reason = state.reason
            session.commit()
