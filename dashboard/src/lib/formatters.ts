/**
 * Formatting helpers for clinical triage presentation.
 * Guarantees safe outputs without NaN, undefined, or awkward underscores.
 */

export function formatHospitalName(raw: string | null | undefined): string {
  if (!raw) return "Facility Unassigned";
  const map: Record<string, string> = {
    stroke_unit_or_tertiary: "Tertiary Stroke Center",
    CHC_FRU_with_cardiac_care: "CHC FRU · Cardiac Care",
    CHC_FRU_with_oxygen: "CHC FRU · Oxygen Capable",
    CHC_FRU_trauma_capable: "CHC FRU · Trauma Center",
    taluk_hq: "Taluk Headquarters Hospital",
    PHC: "Primary Health Centre (PHC)",
    medical_college: "Government Medical College Hospital",
    district_hospital: "District Hospital",
  };
  if (map[raw]) return map[raw];
  return raw
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatStateName(state: string | null | undefined): string {
  if (!state) return "Unknown";
  const map: Record<string, string> = {
    working: "In Intake",
    awaiting_approval: "Awaiting Review",
    human_handoff: "Human Handoff",
    approved: "Approved & Routed",
    rejected: "Rejected",
    auto_escalated: "Auto-Escalated",
    awaiting_hospital: "Hospital Paged",
    ambulance_requested: "Ambulance Dispatched",
    follow_up: "In Follow-Up",
    completed: "Care Completed",
    canceled: "Canceled",
    failed: "Workflow Failed",
  };
  return map[state] || state.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return `${Math.round(value)} ms`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "—";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m === 0) return `${rem}s`;
  return `${m}m ${rem}s`;
}
