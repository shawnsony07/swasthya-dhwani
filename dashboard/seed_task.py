import sys
sys.path.insert(0, "../src")

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from swasthya.contracts import TaskState
from swasthya.db.models import Task
from swasthya.workflow.weft_workflow import submit_task, transition

engine = create_engine("sqlite:///demo.db")
Session = sessionmaker(bind=engine)
session = Session()

task_id = "demo-task-stroke-001"
existing = session.get(Task, task_id)
if existing is not None:
    session.delete(existing)
    session.commit()

task = submit_task(
    session,
    task_id,
    is_time_critical=True,
    patient_identifier_hash="hash-demo-0001",
)
session.commit()

task = transition(session, task_id, TaskState.WORKING, actor="rule_engine")
task.tier = "C1"
task.hospital = "stroke_unit_or_tertiary"
task.triage_snapshot = {
    "raw_transcript": "ente... mukham... valathu bhagam... thala karangunnilla",
    "interpreted_text": "My face and right side feel numb, started suddenly about an hour ago.",
    "interpretation_confidence": 0.62,
    "symptoms": ["facial_droop", "arm_weakness", "speech_difficulty"],
    "symptom_duration_days": 0,
    "warning_signs_present": ["facial_droop"],
    "speech_impairment_signals": ["slurred", "word_finding_pause"],
    "speech_onset": "new",
    "confirmed_by": "patient",
    "interpreter_model": "gemini-2.5-flash",
    "protocol_version": "2025.11.01",
}
session.commit()

task = transition(session, task_id, TaskState.AWAITING_APPROVAL, actor="rule_engine")
session.commit()

print("seeded", task.task_id, task.state, task.tier, task.hospital)

# A second task with no triage_snapshot, to exercise the "No snapshot
# available" path, and a non-time-critical one in a routine state.
task_id_2 = "demo-task-no-snapshot-002"
existing2 = session.get(Task, task_id_2)
if existing2 is not None:
    session.delete(existing2)
    session.commit()
submit_task(session, task_id_2, is_time_critical=False, patient_identifier_hash="hash-demo-0002")
session.commit()
t2 = transition(session, task_id_2, TaskState.WORKING, actor="rule_engine")
t2.tier = "B"
t2.hospital = "district_hospital"
session.commit()
t2 = transition(session, task_id_2, TaskState.HUMAN_HANDOFF, actor="rule_engine")
session.commit()
print("seeded", t2.task_id, t2.state, t2.tier, t2.hospital, "triage_snapshot=", t2.triage_snapshot)

session.close()
