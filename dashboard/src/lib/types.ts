/** Mirrors docs/api_contract.md and src/swasthya/contracts.py exactly. */

export type TaskState =
  | "working"
  | "awaiting_approval"
  | "human_handoff"
  | "approved"
  | "rejected"
  | "auto_escalated";

export type Tier = "A" | "B" | "C1" | "C2";

export interface TaskSummary {
  task_id: string;
  state: TaskState;
  tier: Tier | null;
  hospital: string | null;
  is_time_critical: boolean;
  created_at: string;
  updated_at: string;
}

export interface TriageSnapshot {
  raw_transcript: string;
  interpreted_text: string;
  interpretation_confidence: number;
  symptoms: string[];
  symptom_duration_days: number;
  warning_signs_present: string[];
  speech_impairment_signals: string[];
  speech_onset: string;
  confirmed_by: string;
  interpreter_model: string;
  protocol_version: string;
}

export interface TaskDetail extends TaskSummary {
  patient_identifier_hash: string;
  triage_snapshot: TriageSnapshot | null;
}

export interface TaskListResponse {
  tasks: TaskSummary[];
  next_cursor: string | null;
}

export interface ApiErrorBody {
  detail: string;
}

/** `event: task_update` payload on GET /alerts/stream. */
export interface TaskUpdateEvent {
  task_id: string;
  state: TaskState;
  tier: Tier | null;
  is_time_critical: boolean;
  updated_at: string;
}

export const NEEDS_APPROVAL_STATES: TaskState[] = [
  "awaiting_approval",
  "auto_escalated",
  "human_handoff",
];
