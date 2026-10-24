"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { fetchRoutingBoard } from "@/lib/api";
import type { RoutingBoard, FacilityRoute, RoutedCase } from "@/lib/types";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import { formatHospitalName } from "@/lib/formatters";
import type { Tier, TaskState } from "@/lib/types";

const TIER_COLOR: Record<string, string> = {
  C1: "var(--c1)",
  C2: "var(--c2)",
  B: "var(--tb)",
  A: "var(--ta)",
};

/** Case chip inside a facility card */
function CaseChip({ entry }: { entry: RoutedCase }) {
  const color = entry.tier ? TIER_COLOR[entry.tier] ?? "var(--muted)" : "var(--muted)";
  return (
    <Link
      href={`/dashboard/${encodeURIComponent(entry.task_id)}`}
      className="case-chip"
      style={{ borderLeftColor: color }}
      aria-label={`Case ${entry.task_id}, ${entry.state}${entry.is_time_critical ? ", critical" : ""}`}
      title={`${entry.state} · ${entry.is_time_critical ? "TIME CRITICAL" : "Routine"}`}
    >
      <span className="mono" style={{ fontWeight: 600 }}>{entry.task_id}</span>
      {entry.is_time_critical && <span aria-hidden="true"> 🛑</span>}
    </Link>
  );
}

/** Individual hospital / facility card */
function FacilityCard({ facility }: { facility: FacilityRoute }) {
  const criticalCount = facility.cases.filter((c) => c.is_time_critical).length;
  const pendingCount = facility.cases.filter((c) =>
    ["awaiting_approval", "auto_escalated", "human_handoff"].includes(c.state)
  ).length;
  const pct = facility.total > 0 ? Math.min(100, Math.round((facility.open / facility.total) * 100)) : 0;
  const barColor = pct >= 80 ? "var(--c1)" : pct >= 50 ? "var(--c2)" : "var(--ok)";

  return (
    <div className="facility-card">
      {/* Header */}
      <div className="facility-card-header">
        <div>
          <h3 className="facility-card-title">
            <span aria-hidden="true" style={{ fontSize: 18 }}>🏥</span>
            <span>{formatHospitalName(facility.hospital)}</span>
          </h3>
          <span className="mono" style={{ fontSize: 11, color: "var(--muted)", display: "block", marginTop: 2 }}>
            ID: {facility.hospital}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {criticalCount > 0 && (
            <span className="badge crit" style={{ fontSize: 11.5 }}>
              🛑 {criticalCount} Critical
            </span>
          )}
          {pendingCount > 0 && (
            <span className="badge st-awaiting_approval" style={{ fontSize: 11.5 }}>
              ⏳ {pendingCount} Pending
            </span>
          )}
        </div>
      </div>

      {/* Facility Load Metrics */}
      <div className="facility-stats-row">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>Active Load:</span>
            <strong style={{ color: "var(--text)", fontSize: 13 }}>{facility.open} open</strong>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>/ {facility.total} total</span>
          </div>
          <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: barColor }}>
            {pct}%
          </span>
        </div>
        <div className="facility-load-bar-wrap">
          <div className="facility-load-bar">
            <i style={{ width: `${pct}%`, background: barColor }} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
          {Object.entries(facility.by_tier).map(([tier, count]) => (
            <span
              key={tier}
              className="mono"
              style={{
                fontSize: 11,
                color: TIER_COLOR[tier] ?? "var(--muted)",
                background: "rgba(255, 255, 255, 0.04)",
                padding: "2px 8px",
                borderRadius: 4,
                border: "1px solid var(--line)",
                fontWeight: 700,
              }}
            >
              {count}× Tier {tier}
            </span>
          ))}
        </div>
      </div>

      {/* Case Chips */}
      <div>
        <p style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 10, fontWeight: 700 }}>
          Assigned Cases ({facility.cases.length})
        </p>
        {facility.cases.length === 0 ? (
          <p style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic" }}>
            No active cases routed to this facility.
          </p>
        ) : (
          <div className="facility-cases-chips">
            {facility.cases.map((c) => (
              <CaseChip key={c.task_id} entry={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function RoutingBoardPage() {
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const [board, setBoard] = useState<RoutingBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"grid" | "list">("grid");

  const load = useCallback(async () => {
    try {
      setError(null);
      const b = await fetchRoutingBoard(accessToken);
      setBoard(b);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const facilities = board?.facilities ?? [];
  const allCases: Array<RoutedCase & { hospital: string }> = facilities.flatMap((f) =>
    f.cases.map((c) => ({ ...c, hospital: f.hospital }))
  );
  const totalCritical = allCases.filter((c) => c.is_time_critical).length;

  return (
    <div className="shell">
      <div className="page">
        {/* Page Head */}
        <div className="page-head">
          <div>
            <p className="eyebrow">Kerala Health Routing Protocol</p>
            <h1 className="page-title">Facility Routing Command Board</h1>
            <p className="page-sub">
              Deterministic emergency routing and load distribution across Kerala healthcare facilities.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <div style={{ display: "flex", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
              <button
                type="button"
                onClick={() => setView("grid")}
                className="btn btn-sm"
                style={{
                  borderRadius: 0,
                  border: "none",
                  background: view === "grid" ? "var(--line-strong)" : "transparent",
                  color: view === "grid" ? "var(--text)" : "var(--muted)",
                }}
              >
                ⊞ Facility Grid
              </button>
              <button
                type="button"
                onClick={() => setView("list")}
                className="btn btn-sm"
                style={{
                  borderRadius: 0,
                  border: "none",
                  background: view === "list" ? "var(--line-strong)" : "transparent",
                  color: view === "list" ? "var(--text)" : "var(--muted)",
                }}
              >
                ☰ Case List
              </button>
            </div>
            <button type="button" onClick={load} className="btn btn-sm">
              ↺ Refresh
            </button>
          </div>
        </div>

        {/* Tiers Summary Strip */}
        {board?.tiers && (
          <div className="grid grid-kpi" style={{ marginBottom: 24 }}>
            {board.tiers.map((tBucket) => {
              const color = TIER_COLOR[tBucket.tier] ?? "var(--muted)";
              return (
                <div key={tBucket.tier} className="kpi" style={{ borderLeft: `4px solid ${color}` }}>
                  <div className="kpi-label" style={{ color }}>
                    Tier {tBucket.tier} · {tBucket.referral_window}
                  </div>
                  <div className="kpi-value">
                    {tBucket.count}
                    <span className="kpi-unit">cases</span>
                  </div>
                  <div className="kpi-note">{tBucket.label}</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Main Content */}
        {loading ? (
          <div className="facility-grid">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="skeleton" style={{ height: 200 }} />
            ))}
          </div>
        ) : error ? (
          <div role="alert" className="alert">
            <p style={{ fontWeight: 700 }}>Could not load routing board.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
          </div>
        ) : facilities.length === 0 ? (
          <div className="empty">No facility routes active in the current session.</div>
        ) : view === "grid" ? (
          <div className="facility-grid">
            {facilities.map((fac) => (
              <FacilityCard key={fac.hospital} facility={fac} />
            ))}
          </div>
        ) : (
          <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Case ID</th>
                  <th>Kerala Tier</th>
                  <th>Status</th>
                  <th>Assigned Facility</th>
                  <th>Urgency</th>
                  <th>Last Updated</th>
                </tr>
              </thead>
              <tbody>
                {allCases.map((entry) => (
                  <tr key={entry.task_id}>
                    <td>
                      <Link
                        href={`/dashboard/${encodeURIComponent(entry.task_id)}`}
                        className="mono"
                        style={{ color: "var(--brass)", fontSize: 12.5, fontWeight: 700, textDecoration: "none" }}
                      >
                        {entry.task_id}
                      </Link>
                    </td>
                    <td>
                      <TierBadge tier={entry.tier as Tier | null} />
                    </td>
                    <td>
                      <StateBadge state={entry.state as TaskState} />
                    </td>
                    <td>
                      <span className="case-facility-tag">
                        <span>🏥 {formatHospitalName(entry.hospital)}</span>
                      </span>
                    </td>
                    <td>
                      {entry.is_time_critical ? (
                        <TimeCriticalBadge />
                      ) : (
                        <span style={{ color: "var(--muted)", fontSize: 12 }}>Routine</span>
                      )}
                    </td>
                    <td style={{ fontSize: 12, color: "var(--muted)" }} className="mono">
                      <RelativeTime iso={entry.updated_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Clinical Routing Guidelines Disclaimer */}
        <div className="notice" style={{ marginTop: 22 }}>
          <strong>Kerala Emergency Response Guidelines:</strong> Tier C1 acute cases route to certified Stroke Units or Tertiary Medical Colleges with immediate neuro-critical care. Tier C2 cases route to First Referral Units (FRUs) with cardiac care and oxygen capacity.
        </div>
      </div>
    </div>
  );
}
