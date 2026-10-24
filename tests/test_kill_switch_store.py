"""Tests for the DB-backed kill switch store
(src/swasthya/db/kill_switch_store.py) and KillSwitch's store-injection
seam (src/swasthya/gateway/kill_switch.py).
"""
from __future__ import annotations

from swasthya.db.kill_switch_store import DbKillSwitchStore
from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.gateway.kill_switch import KillSwitch


def _store() -> DbKillSwitchStore:
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    return DbKillSwitchStore(build_session_factory(engine))


def test_default_state_is_inactive_with_no_row_yet():
    store = _store()
    state = store.get()
    assert state.active is False
    assert state.changed_by is None


def test_set_then_get_round_trips():
    store = _store()
    switch = KillSwitch(store)

    switch.engage(by="admin1", reason="drill")

    assert switch.is_active is True
    assert switch.state.changed_by == "admin1"
    assert switch.state.reason == "drill"


def test_state_persists_across_separate_store_instances_same_db():
    """The whole point of this store: a second instance (standing in for
    a second process) reading the same engine sees the same state."""
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    session_factory = build_session_factory(engine)

    writer = KillSwitch(DbKillSwitchStore(session_factory))
    writer.engage(by="admin1", reason=None)

    reader = KillSwitch(DbKillSwitchStore(session_factory))
    assert reader.is_active is True
    assert reader.state.changed_by == "admin1"


def test_disable_requires_reason_even_through_the_db_store():
    store = _store()
    switch = KillSwitch(store)
    switch.engage(by="admin1")

    try:
        switch.disable(by="admin1", reason="")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty reason")

    assert switch.is_active is True  # unchanged


def test_in_memory_store_remains_the_default_with_no_store_argument():
    switch = KillSwitch()
    assert switch.is_active is False
    switch.engage(by="admin1")
    assert switch.is_active is True
