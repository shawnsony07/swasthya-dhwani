"""Seed SYNTHETIC demo cases so the clinician/admin portal has something to
show before real calls exist.

    python scripts/seed_demo.py            # (re)create demo cases
    python scripts/seed_demo.py --clear    # remove them

Every row is synthetic: task ids are `demo-*` and patient hashes start with
`demo_`. Nothing here is real patient data, and the tiers come from the
draft (non-signed-off) matrix - this is a UI demo, not clinical evidence.
Safe to re-run: existing `demo-*` rows are replaced.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete  # noqa: E402

from swasthya.contracts import PROTOCOL_VERSION  # noqa: E402
from swasthya.db.models import AuditEventRow, Task  # noqa: E402
from swasthya.db.session import build_engine, build_session_factory, create_all  # noqa: E402

# (suffix, state, tier, hospital, time_critical, minutes_ago, conf, symptoms,
#  warnings, raw_ml, interpreted, duration_s, stt_conf, ttfb_ms, channel,
#  readbacks, fallback, events)
CASES = [
    ("01", "awaiting_approval", "C1", "stroke_unit_or_tertiary", True, 4, 0.91,
     ["speech_difficulty", "facial_droop"], ["facial_droop", "speech_difficulty"],
     "അച്ഛന് സംസാരിക്കാൻ പറ്റുന്നില്ല, മുഖം ഒരു വശത്തേക്ക് കോടി",
     "Father cannot speak, face drooping on one side", 118.4, 0.88, 412, "sip", 1, False,
     ["working", "approval_requested"]),
    ("02", "auto_escalated", "C1", "CHC_FRU_with_cardiac_care", True, 21, 0.84,
     ["chest_pain", "sweating"], ["crushing_pressure"],
     "നെഞ്ചിൽ വല്ലാത്ത ഭാരം, വിയർക്കുന്നു",
     "Heavy pressure in chest, sweating", 96.0, 0.83, 455, "web", 0, False,
     ["working", "approval_requested", "auto_escalated"]),
    ("03", "human_handoff", "C2", "CHC_FRU_with_oxygen", False, 9, 0.46,
     ["breathing_difficulty"], [],
     "ശ്വാസം... മുട്ടൽ... കുട്ടിക്ക്",
     "Breathing trouble - child (low confidence)", 142.7, 0.52, 690, "sip", 3, True,
     ["working", "human_handoff"]),
    ("04", "awaiting_hospital", "C2", "CHC_FRU_with_cardiac_care", False, 33, 0.88,
     ["chest_pain"], ["radiating_arm_pain"],
     "നെഞ്ചുവേദന ഇടതു കൈയിലേക്ക് പടരുന്നു",
     "Chest pain radiating to left arm", 101.2, 0.9, 398, "web", 1, False,
     ["working", "approval_requested", "approved", "awaiting_hospital"]),
    ("05", "ambulance_requested", "C1", "CHC_FRU_trauma_capable", True, 47, 0.93,
     ["trauma", "bleeding"], ["uncontrolled_bleeding"],
     "ബൈക്ക് അപകടം, കാലിൽ നിന്ന് ചോര നിൽക്കുന്നില്ല",
     "Bike accident, leg bleeding not stopping", 74.9, 0.94, 371, "sip", 0, False,
     ["working", "approval_requested", "approved", "ambulance_requested"]),
    ("06", "follow_up", "B", "PHC", False, 190, 0.9,
     ["fever", "headache"], [],
     "മൂന്ന് ദിവസമായി പനിയും തലവേദനയും",
     "Fever and headache for three days", 88.3, 0.91, 360, "web", 0, False,
     ["working", "approval_requested", "approved", "awaiting_hospital", "follow_up"]),
    ("07", "completed", "B", "PHC", False, 520, 0.95,
     ["fever", "body_ache"], [],
     "പനിയും ശരീരവേദനയും",
     "Fever and body ache", 61.0, 0.96, 340, "web", 0, False,
     ["working", "approval_requested", "approved", "completed"]),
    ("08", "rejected", "C2", "CHC_FRU_with_oxygen", False, 260, 0.58,
     ["breathing_difficulty", "cough"], [],
     "ചുമയും ശ്വാസംമുട്ടും",
     "Cough and breathlessness", 133.5, 0.61, 610, "sip", 2, True,
     ["working", "approval_requested", "rejected"]),
    ("09", "working", None, None, False, 1, 0.0,
     [], [], "", "", 0.0, 0.0, 0, "web", 0, False, ["working"]),
    ("10", "awaiting_approval", "C2", "CHC_FRU_with_cardiac_care", False, 6, 0.79,
     ["chest_pain", "nausea"], [],
     "നെഞ്ചിൽ വേദന, ഓക്കാനം",
     "Chest pain with nausea", 109.8, 0.77, 505, "web", 1, False,
     ["working", "approval_requested"]),
    ("11", "awaiting_approval", "B", "PHC", False, 14, 0.87,
     ["fever", "chills"], [],
     "ചൂടും വിറയലും",
     "Fever with chills", 70.4, 0.89, 388, "web", 0, False,
     ["working", "approval_requested"]),
    ("12", "completed", "C1", "stroke_unit_or_tertiary", True, 1500, 0.9,
     ["arm_weakness"], ["arm_weakness"],
     "ഇടതു കൈ തളർന്നു പോയി",
     "Left arm gone weak", 92.1, 0.9, 402, "sip", 0, False,
     ["working", "approval_requested", "approved", "ambulance_requested", "completed"]),
]


def _decision_actor(event: str) -> str:
    return {
        "working": "agent",
        "approval_requested": "rule_engine",
        "human_handoff": "rule_engine",
        "auto_escalated": "system",
        "approved": "doctor1",
        "rejected": "doctor1",
        "awaiting_hospital": "system",
        "ambulance_requested": "nurse1",
        "follow_up": "nurse1",
        "completed": "nurse1",
    }.get(event, "system")


def seed(clear_only: bool = False) -> int:
    engine = build_engine()
    create_all(engine)
    factory = build_session_factory(engine)
    now = datetime.now(UTC)
    with factory() as session:
        session.execute(delete(AuditEventRow).where(AuditEventRow.task_id.like("demo-%")))
        session.execute(delete(Task).where(Task.task_id.like("demo-%")))
        if clear_only:
            session.commit()
            return 0
        for (sfx, state, tier, hospital, critical, mins, conf, symptoms, warnings,
             raw, interp, dur, stt, ttfb, channel, readbacks, fallback, events) in CASES:
            created = now - timedelta(minutes=mins) - timedelta(seconds=dur)
            ended = now - timedelta(minutes=mins)
            task_id = f"demo-{sfx}"
            snapshot = None
            if raw:
                snapshot = {
                    "raw_transcript": raw,
                    "interpreted_text": interp,
                    "interpretation_confidence": conf,
                    "symptoms": symptoms,
                    "symptom_duration_days": 3 if "fever" in symptoms else 0,
                    "warning_signs_present": warnings,
                    "speech_impairment_signals": ["slurred_speech"] if "speech_difficulty" in symptoms else [],
                    "speech_onset": "acute" if "speech_difficulty" in symptoms else "unknown",
                    "confirmed_by": "patient" if conf >= 0.7 else "caregiver",
                    "interpreter_model": "gemini-flash-latest (synthetic demo)",
                    "protocol_version": PROTOCOL_VERSION,
                    "call_metrics": {
                        "connected_at": created.isoformat(),
                        "ended_at": ended.isoformat(),
                        "call_duration_seconds": dur,
                        "channel": channel,
                        "room": f"demo-room-{sfx}",
                        "language": "ml-IN",
                        "stt_model": "sarvam",
                        "stt_confidence_mean": stt,
                        "stt_utterances": 6,
                        "tts_model": "bulbul:v3",
                        "tts_voice": "priya",
                        "tts_ttfb_ms_mean": float(ttfb),
                        "tts_turns": 7,
                        "llm_model": "gemini-flash-latest",
                        "llm_ttft_ms_mean": 520.0,
                        "eou_delay_ms_mean": 640.0,
                        "readback_attempts": readbacks,
                        "fallback_used": fallback,
                    },
                }
            session.add(
                Task(
                    task_id=task_id,
                    state=state,
                    patient_identifier_hash=f"demo_{sfx}_" + "ab12cd34ef56" * 4,
                    tier=tier,
                    hospital=hospital,
                    is_time_critical=critical,
                    awaiting_approval_since=ended if state == "awaiting_approval" else None,
                    triage_snapshot=snapshot,
                    created_at=created,
                    updated_at=ended,
                )
            )
            session.add(
                AuditEventRow(
                    task_id=task_id, event="call_started", actor="agent", timestamp=created,
                    protocol_version=PROTOCOL_VERSION, detail={"synthetic_demo": True},
                )
            )
            step = max(dur / max(len(events), 1), 1.0)
            for i, event in enumerate(events):
                at = created + timedelta(seconds=step * (i + 1))
                if event in ("approved", "rejected", "auto_escalated", "completed"):
                    at = ended + timedelta(seconds=45 * (i % 3 + 1))
                detail = {}
                if event == "rejected":
                    detail["reason"] = "Needs in-person assessment first (synthetic)"
                if event == "auto_escalated":
                    detail["reason"] = "No doctor decision before timeout"
                session.add(
                    AuditEventRow(
                        task_id=task_id, event=event, actor=_decision_actor(event), timestamp=at,
                        protocol_version=PROTOCOL_VERSION, detail=detail,
                    )
                )
        session.commit()
    return len(CASES)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="remove demo-* cases only")
    args = parser.parse_args()
    n = seed(clear_only=args.clear)
    print("cleared demo cases" if args.clear else f"seeded {n} synthetic demo cases")
