"""Clinician/admin portal endpoints: audit timeline, routing board, metrics,
and call-metrics plumbing (collector + summary exposure)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swasthya.contracts import Tier
from swasthya.db.models import Task
from swasthya.voice.call_metrics import CallMetricsCollector

from .conftest import seed_awaiting_approval_task


def _set_metrics(app, task_id: str, metrics: dict) -> None:
    with app.state.session_factory() as session:
        task = session.get(Task, task_id)
        task.triage_snapshot = {**task.triage_snapshot, "call_metrics": metrics}
        session.commit()


def test_audit_timeline_is_chronological_and_404s(api_app):
    app, client = api_app
    tid = seed_awaiting_approval_task(app)
    body = client.get(f"/tasks/{tid}/audit").json()
    events = [e["event"] for e in body]
    assert events[0] == "call_started"
    assert "approval_requested" in events
    assert client.get("/tasks/nope/audit").status_code == 404


def test_summary_exposes_metrics_only_when_present(api_app):
    app, client = api_app
    tid = seed_awaiting_approval_task(app)
    summary = client.get("/tasks").json()["tasks"][0]
    assert summary["interpretation_confidence"] == 0.82
    assert summary["call_duration_seconds"] is None  # never fabricated
    _set_metrics(app, tid, {"call_duration_seconds": 93.5, "language": "ml-IN"})
    summary = client.get("/tasks").json()["tasks"][0]
    assert summary["call_duration_seconds"] == 93.5
    assert summary["language"] == "ml-IN"
    detail = client.get(f"/tasks/{tid}").json()
    assert detail["triage_snapshot"]["call_metrics"]["language"] == "ml-IN"


def test_routing_board_groups_by_facility_and_tier(api_app):
    app, client = api_app
    seed_awaiting_approval_task(app, task_id="a", tier=Tier.C1, hospital="stroke_unit_or_tertiary")
    seed_awaiting_approval_task(app, task_id="b", tier=Tier.B, hospital="PHC")
    seed_awaiting_approval_task(app, task_id="c", tier=Tier.C1, hospital="stroke_unit_or_tertiary")
    board = client.get("/admin/routing").json()
    assert board["total"] == 3
    assert board["clinically_signed_off"] is False
    tiers = {t["tier"]: t["count"] for t in board["tiers"]}
    assert tiers == {"C1": 2, "C2": 0, "B": 1, "A": 0}
    top = board["facilities"][0]
    assert top["hospital"] == "stroke_unit_or_tertiary"
    assert top["total"] == 2 and top["by_tier"] == {"C1": 2}


def test_metrics_report_none_without_samples(api_app):
    app, client = api_app
    tid = seed_awaiting_approval_task(app)
    m = client.get("/admin/metrics").json()
    assert m["total_cases"] == 1
    assert m["interpretation_confidence"]["samples"] == 1
    assert m["stt_confidence"] == {"mean": None, "samples": 0}
    assert m["call_duration_seconds"]["mean"] is None
    _set_metrics(app, tid, {"call_duration_seconds": 100, "stt_confidence_mean": 0.9})
    m = client.get("/admin/metrics").json()
    assert m["call_duration_seconds"]["mean"] == 100
    assert m["stt_confidence"]["mean"] == 0.9


def test_collector_omits_unmeasured_and_rounds():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    c = CallMetricsCollector(room="r", channel="web", now=t0)
    snap = c.snapshot(now=t0 + timedelta(seconds=61.26))
    assert snap["call_duration_seconds"] == 61.3
    assert "stt_confidence_mean" not in snap and "tts_ttfb_ms_mean" not in snap
    c.record_stt_confidence(0.8)
    c.record_stt_confidence(1.4)  # out of range -> ignored
    c.record_tts_ttfb(0.25)

    class _M:
        type = "llm_metrics"
        ttft = 0.5

    c.ingest_livekit_metric(_M())
    snap = c.snapshot(now=t0 + timedelta(seconds=5))
    assert snap["stt_confidence_mean"] == 0.8 and snap["stt_utterances"] == 1
    assert snap["tts_ttfb_ms_mean"] == 250.0
    assert snap["llm_ttft_ms_mean"] == 500.0
