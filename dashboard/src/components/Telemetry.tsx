"use client";

import React from "react";

/** Animated bar-graph confidence meter */
export function ConfidenceMeter({
  value,
  label,
  large = false,
}: {
  value: number | null;
  label: string;
  large?: boolean;
}) {
  if (value === null) {
    return (
      <div className="meter">
        <span className="meter-nodata" aria-label={`${label}: no data`}>
          — no data
        </span>
      </div>
    );
  }

  const pct = Math.round(value * 100);
  const colorClass =
    pct >= 75 ? "meter-good" : pct >= 50 ? "meter-mid" : "meter-low";
  const bars = 8;
  const activeBars = Math.round((pct / 100) * bars);

  return (
    <div className={`meter ${colorClass} ${large ? "gauge-lg" : ""}`} role="meter" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <span className="meter-bars" aria-hidden="true">
        {Array.from({ length: bars }, (_, i) => (
          <i key={i} data-on={i < activeBars ? "true" : "false"} />
        ))}
      </span>
      <span className="meter-val">{pct}%</span>
    </div>
  );
}

/** Latency value with colour coding */
export function LatencyBadge({ ms }: { ms: number | null }) {
  if (ms === null) return <span className="meter-nodata">— ms</span>;
  const color =
    ms < 300 ? "var(--ok)" : ms < 600 ? "var(--c2)" : "var(--c1)";
  return (
    <span
      className="mono"
      style={{ color, fontSize: 15, fontWeight: 700 }}
    >
      {Math.round(ms)}
      <span style={{ fontSize: 12, fontWeight: 400, color: "var(--muted)" }}>
        {" "}ms
      </span>
    </span>
  );
}

/** Duration in human-readable m:ss */
export function DurationDisplay({ seconds }: { seconds: number | null }) {
  if (seconds === null) return <span className="meter-nodata">—</span>;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return (
    <span className="mono" style={{ fontWeight: 700 }}>
      {m}:{String(s).padStart(2, "0")}
      <span style={{ fontSize: 12, fontWeight: 400, color: "var(--muted)" }}>
        {" "}min
      </span>
    </span>
  );
}

/** Inline KPI stat tile */
export function StatTile({
  label,
  value,
  unit,
  alert = false,
  note,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  alert?: boolean;
  note?: string;
}) {
  return (
    <div className={`panel kpi ${alert ? "kpi-alert" : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}
