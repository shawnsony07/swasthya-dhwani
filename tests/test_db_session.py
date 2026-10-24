from sqlalchemy import inspect

from swasthya.db.session import build_engine, build_session_factory, create_all
from swasthya.workflow.weft_workflow import submit_task


def test_build_engine_defaults_to_in_memory_sqlite_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = build_engine()
    assert engine.url.drivername == "sqlite"


def test_build_engine_honors_explicit_database_url():
    engine = build_engine("sqlite:///:memory:")
    assert engine.url.drivername == "sqlite"


def test_create_all_creates_expected_tables():
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"tasks", "audit_events", "on_call_roster"} <= tables


def test_session_factory_sessions_can_write_and_read_a_task():
    engine = build_engine("sqlite:///:memory:")
    create_all(engine)
    SessionFactory = build_session_factory(engine)

    with SessionFactory() as session:
        submit_task(session, task_id="task-1", is_time_critical=False)
        session.commit()

    with SessionFactory() as session:
        from swasthya.db.models import Task

        task = session.get(Task, "task-1")
        assert task is not None
        assert task.state == "submitted"
