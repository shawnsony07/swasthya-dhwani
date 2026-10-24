/** Mirrors docs/api_contract.md and src/swasthya/contracts.py exactly. */

export type TaskState =
  | "working"
  | "awaiting_approval"
  | "human_handoff"
  | "approved"
  | "rejected"
  | "auto_escalated"
  | "awaiting_hospital"
  | "ambulance_requested"
  | "follow_up"
  | "completed"
  | "canceled"
  | "failed";

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

export interface CallMetrics {
  call_duration_s: number | null;
  stt_confidence_mean: number | null;
  tts_latency_mean_ms: number | null;
  vad_speech_ratio: number | null;
  interruption_count: number | null;
  livekit_room_id: string | null;
  recorded_at: string | null;
}

export interface TaskDetail extends TaskSummary {
  patient_identifier_hash: string;
  triage_snapshot: TriageSnapshot | null;
  call_metrics: CallMetrics | null;
}

export interface TaskListResponse {
  tasks: TaskSummary[];
  next_cursor: string | null;
}

export interface AuditEvent {
  seq: number;
  actor: string;
  action: string;
  from_state: string | null;
  to_state: string | null;
  note: string | null;
  ts: string;
}

export interface AuditTimeline {
  task_id: string;
  events: AuditEvent[];
}

export interface RoutingEntry {
  task_id: string;
  tier: string;
  hospital: string;
  state: string;
  is_time_critical: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoutingBoard {
  generated_at: string;
  entries: RoutingEntry[];
  facilities: Record<string, RoutingEntry[]>;
}

export interface AdminMetrics {
  generated_at: string;
  total_tasks: number;
  by_tier: Record<string, number>;
  by_state: Record<string, number>;
  critical_cases: number;
  pending_approval: number;
  avg_stt_confidence: number | null;
  avg_tts_latency_ms: number | null;
  avg_call_duration_s: number | null;
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
