"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { fetchRoutingBoard } from "@/lib/api";
import type { RoutingBoard, RoutingEntry } from "@/lib/types";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import type { Tier, TaskState } from "@/lib/types";

const TIER_COLOR: Record<string, string> = {
  C1: "var(--c1)",
  C2: "var(--c2)",
  B: "var(--tb)",
  A: "var(--ta)",
};

/** Case chip inside a facility card */
function CaseChip({ entry }: { entry: RoutingEntry }) {
  const color = TIER_COLOR[entry.tier] ?? "var(--muted)";
  return (
    <Link
      href={`/dashboard/${encodeURIComponent(entry.task_id)}`}
      className="case-chip"
      style={{ borderLeftColor: color }}
      aria-label={`Case ${entry.task_id}, ${entry.state}${entry.is_time_critical ? ", critical" : ""}`}
      title={`${entry.state} — ${entry.is_time_critical ? "TIME CRITICAL" : "routine"}`}
    >
      {entry.task_id}
      {entry.is_time_critical && <span aria-hidden="true"> 🛑</span>}
    </Link>
  );
}

/** Individual facility card */
function FacilityCard({
  name,
  entries,
}: {
  name: string;
  entries: RoutingEntry[];
}) {
  const criticalCount = entries.filter((e) => e.is_time_critical).length;
  const pendingCount = entries.filter((e) =>
    ["awaiting_approval", "auto_escalated", "human_handoff"].includes(e.state)
  ).length;

  // Group by tier for the mini summary
  const byTier = entries.reduce<Record<string, number>>((acc, e) => {
    acc[e.tier] = (acc[e.tier] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="facility" style={{ position: "relative" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8 }}>
        <span className="facility-name">{name}</span>
        <div style={{ display: "flex", gap: 6 }}>
          {criticalCount > 0 && (
            <span className="badge crit" style={{ fontSize: 11 }}>
              🛑 {criticalCount} critical
            </span>
          )}
          {pendingCount > 0 && (
            <span className="badge st-awaiting_approval" style={{ fontSize: 11 }}>
              ⏳ {pendingCount} pending
            </span>
          )}
        </div>
      </div>

      {/* Tier mini-summary */}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        {Object.entries(byTier).map(([tier, count]) => (
          <span
            key={tier}
            style={{ fontSize: 11, color: TIER_COLOR[tier] ?? "var(--muted)", fontWeight: 700 }}
          >
            {count}× T{tier}
          </span>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)" }}>
          {entries.length} case{entries.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Case chips */}
      <div className="facility-cases">
        {entries.map((e) => (
          <CaseChip key={e.task_id} entry={e} />
        ))}
      </div>
    </div>
  );
}

/** Flat routing list row */
function RoutingRow({ entry }: { entry: RoutingEntry }) {
  return (
    <tr>
      <td>
        <Link
          href={`/dashboard/${encodeURIComponent(entry.task_id)}`}
          className="mono"
          style={{ color: "var(--brass)", fontSize: 12, fontWeight: 700, textDecoration: "none" }}
        >
          {entry.task_id}
        </Link>
      </td>
      <td><TierBadge tier={entry.tier as Tier | null} /></td>
      <td><StateBadge state={entry.state as TaskState} /></td>
      <td className="mono" style={{ fontSize: 12 }}>{entry.hospital}</td>
      <td>
        {entry.is_time_critical ? <TimeCriticalBadge /> : (
          <span style={{ color: "var(--muted)", fontSize: 12 }}>Routine</span>
        )}
      </td>
      <td style={{ fontSize: 12, color: "var(--muted)" }}>
        <RelativeTime iso={entry.updated_at} />
      </td>
    </tr>
  );
}

type ViewMode = "grid" | "list";

export default function RoutingBoardPage() {
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const [board, setBoard] = useState<RoutingBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>("grid");

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

  const facilities = board?.facilities ?? {};
  const facilityNames = Object.keys(facilities).sort();
  const entries = board?.entries ?? [];
  const totalCritical = entries.filter((e) => e.is_time_critical).length;

  return (
    <div className="shell">
      <div className="page">
        <div className="page-head">
          <div>
            <p className="eyebrow">Kerala Health Routing Protocol</p>
            <h1 className="page-title">Routing Board</h1>
            <p className="page-sub">
              Patient-to-facility routing as per Government of Kerala Emergency Health Guidelines.
              Cases are automatically tiered A→C2 by symptom acuity.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {totalCritical > 0 && (
              <span className="badge crit badge-loud" style={{ fontSize: 13 }}>
                🛑 {totalCritical} critical case{totalCritical !== 1 ? "s" : ""}
              </span>
            )}
            <div role="group" aria-label="View mode" style={{ display: "flex", gap: 4 }}>
              <button
                type="button"
                className="btn btn-sm"
                aria-pressed={view === "grid" ? "true" : "false"}
                onClick={() => setView("grid")}
                style={view === "grid" ? { background: "var(--brass)", color: "#1a1204" } : {}}
              >
                ⊞ Grid
              </button>
              <button
                type="button"
                className="btn btn-sm"
                aria-pressed={view === "list" ? "true" : "false"}
                onClick={() => setView("list")}
                style={view === "list" ? { background: "var(--brass)", color: "#1a1204" } : {}}
              >
                ≡ List
              </button>
            </div>
            <button type="button" onClick={load} className="btn btn-sm">
              ↺ Refresh
            </button>
          </div>
        </div>

        {/* Last updated */}
        {board && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginBottom: 20 }}>
            Board generated <RelativeTime iso={board.generated_at} /> ·{" "}
            {entries.length} total cases across {facilityNames.length} facilities
          </p>
        )}

        {loading ? (
          <div className="grid grid-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton" style={{ height: 140 }} />
            ))}
          </div>
        ) : error ? (
          <div role="alert" className="alert">
            <p style={{ fontWeight: 700 }}>Could not load routing board.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
            <button type="button" onClick={load} className="btn btn-sm btn-danger" style={{ marginTop: 8 }}>
              Try again
            </button>
          </div>
        ) : entries.length === 0 ? (
          <div className="empty">No cases in the routing board yet.</div>
        ) : view === "grid" ? (
          /* ── Grid view (facility cards) ── */
          <div>
            {/* Unrouted / pending tier */}
            {board?.entries.filter((e) => !e.hospital).length ? (
              <div className="panel" style={{ marginBottom: 20, borderColor: "var(--brass-dim)" }}>
                <div className="panel-title">
                  Unrouted / Awaiting Triage
                  <small>{board.entries.filter((e) => !e.hospital).length} cases</small>
                </div>
                <div className="facility-cases">
                  {board.entries
                    .filter((e) => !e.hospital)
                    .map((e) => (
                      <CaseChip key={e.task_id} entry={e} />
                    ))}
                </div>
              </div>
            ) : null}

            <div className="grid grid-2">
              {facilityNames.map((name) => (
                <FacilityCard
                  key={name}
                  name={name}
                  entries={facilities[name] ?? []}
                />
              ))}
            </div>
          </div>
        ) : (
          /* ── List view (flat table) ── */
          <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Case ID</th>
                  <th>Tier</th>
                  <th>State</th>
                  <th>Facility</th>
                  <th>Priority</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {entries
                  .slice()
                  .sort((a, b) => {
                    // Critical first, then by tier severity
                    if (a.is_time_critical !== b.is_time_critical)
                      return a.is_time_critical ? -1 : 1;
                    const tierOrder = { C1: 0, C2: 1, B: 2, A: 3 };
                    return (tierOrder[a.tier as Tier] ?? 9) - (tierOrder[b.tier as Tier] ?? 9);
                  })
                  .map((entry) => (
                    <RoutingRow key={entry.task_id} entry={entry} />
                  ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Kerala protocol reference */}
        <div className="notice" style={{ marginTop: 20 }}>
          <strong>Routing Rules (Kerala Health Guidelines):</strong>
          &nbsp; Tier A → ASHA/PHC &nbsp;·&nbsp; Tier B → CHC or Taluk Hospital &nbsp;·&nbsp;
          Tier C1 → District Hospital &nbsp;·&nbsp; Tier C2 → Medical College / Tertiary / Stroke Unit.
          C2 cases with stroke flags receive instant paging to the neurology on-call team.
        </div>
      </div>
    </div>
  );
}
