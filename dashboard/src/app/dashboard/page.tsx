"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useT } from "@/lib/i18n";
import { NEEDS_APPROVAL_STATES } from "@/lib/types";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import { useTasks } from "./useTasks";
import { fetchAdminMetrics } from "@/lib/api";
import { useSession } from "next-auth/react";
import type { AdminMetrics, TaskSummary, Tier } from "@/lib/types";

type FilterTab = "needs_approval" | "all" | "critical";

const RAIL_CLASS: Record<string, string> = {
  C1: "rail-C1",
  C2: "rail-C2",
  B: "rail-B",
  A: "rail-A",
};

function LiveDot({ state }: { state: string }) {
  return (
    <span className="live-dot" data-state={state}>
      <i aria-hidden="true" />
      {state === "open" ? "Live" : state === "error" ? "Reconnecting…" : "Connecting…"}
    </span>
  );
}

function CaseRow({ task, index }: { task: TaskSummary; index: number }) {
  const railClass = task.tier ? RAIL_CLASS[task.tier] ?? "" : "";
  return (
    <Link
      href={`/dashboard/${encodeURIComponent(task.task_id)}`}
      className="case-row"
      style={{ "--i": index } as React.CSSProperties}
      aria-label={`Case ${task.task_id}, tier ${task.tier ?? "unassigned"}, ${task.state}${task.is_time_critical ? ", time critical" : ""}`}
    >
      <span className={`rail ${railClass}`} aria-hidden="true" />
      <span>
        <span className="cell-title mono">{task.task_id}</span>
        {task.hospital && (
          <span className="cell-sub">{task.hospital}</span>
        )}
      </span>
      <span>
        <TierBadge tier={task.tier as Tier | null} />
      </span>
      <span>
        <StateBadge state={task.state} />
        {task.is_time_critical && (
          <span style={{ marginLeft: 6 }}>
            <TimeCriticalBadge />
          </span>
        )}
      </span>
      <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
        <RelativeTime iso={task.updated_at} />
      </span>
      <span className="cell-sub" style={{ fontSize: 11 }}>
        Created <RelativeTime iso={task.created_at} />
      </span>
      <span aria-hidden="true" style={{ color: "var(--muted)", fontSize: 18, textAlign: "right" }}>›</span>
    </Link>
  );
}

export default function DashboardPage() {
  const { t } = useT();
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const { tasks, loading, error, refetch, connectionState } = useTasks();
  const [filter, setFilter] = useState<FilterTab>("needs_approval");
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);

  const loadMetrics = useCallback(async () => {
    try {
      const m = await fetchAdminMetrics(accessToken);
      setMetrics(m);
    } catch {
      // non-fatal: metrics panel degrades gracefully
    }
  }, [accessToken]);

  useEffect(() => {
    loadMetrics();
    const id = setInterval(loadMetrics, 30_000);
    return () => clearInterval(id);
  }, [loadMetrics]);

  const visibleTasks =
    filter === "needs_approval"
      ? tasks.filter((task) => NEEDS_APPROVAL_STATES.includes(task.state))
      : filter === "critical"
      ? tasks.filter((task) => task.is_time_critical)
      : tasks;

  const needsCount = tasks.filter((t) => NEEDS_APPROVAL_STATES.includes(t.state)).length;
  const critCount = tasks.filter((t) => t.is_time_critical).length;

  return (
    <div className="shell">
      <div className="page">
        {/* Page header */}
        <div className="page-head">
          <div>
            <p className="eyebrow">Clinical Operations Centre</p>
            <h1 className="page-title">Patient Queue</h1>
            <p className="page-sub">
              Live triage cases across Kerala health tiers — auto-refreshed via SSE.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <LiveDot state={connectionState} />
            <button type="button" onClick={refetch} className="btn btn-sm">
              ↺ Refresh
            </button>
          </div>
        </div>

        {/* KPI bar */}
        {metrics && (
          <div className="grid grid-kpi" style={{ marginBottom: 22 }}>
            <div className="panel kpi">
              <div className="kpi-label">Total Cases</div>
              <div className="kpi-value">{metrics.total_tasks}</div>
            </div>
            <div className={`panel kpi ${metrics.pending_approval > 0 ? "kpi-alert" : ""}`}>
              <div className="kpi-label">Pending Approval</div>
              <div className="kpi-value">{metrics.pending_approval}</div>
            </div>
            <div className={`panel kpi ${metrics.critical_cases > 0 ? "kpi-alert" : ""}`}>
              <div className="kpi-label">Critical Cases</div>
              <div className="kpi-value">{metrics.critical_cases}</div>
            </div>
            {metrics.avg_stt_confidence !== null && (
              <div className="panel kpi">
                <div className="kpi-label">Avg STT Confidence</div>
                <div className="kpi-value">
                  {Math.round((metrics.avg_stt_confidence ?? 0) * 100)}
                  <span className="kpi-unit">%</span>
                </div>
              </div>
            )}
            {metrics.avg_tts_latency_ms !== null && (
              <div className="panel kpi">
                <div className="kpi-label">Avg TTS Latency</div>
                <div className="kpi-value">
                  {Math.round(metrics.avg_tts_latency_ms ?? 0)}
                  <span className="kpi-unit">ms</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Filter chips */}
        <div
          role="tablist"
          aria-label="Case filter"
          style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}
        >
          <button
            type="button"
            role="tab"
            aria-selected={filter === "needs_approval"}
            onClick={() => setFilter("needs_approval")}
            className="chip"
            aria-pressed={filter === "needs_approval" ? "true" : "false"}
          >
            {t("filter.needsApproval")}
            <span className="n">{needsCount}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filter === "critical"}
            onClick={() => setFilter("critical")}
            className="chip"
            aria-pressed={filter === "critical" ? "true" : "false"}
          >
            🛑 Critical
            <span className="n">{critCount}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filter === "all"}
            onClick={() => setFilter("all")}
            className="chip"
            aria-pressed={filter === "all" ? "true" : "false"}
          >
            {t("filter.all")}
            <span className="n">{tasks.length}</span>
          </button>
        </div>

        {/* Case queue table */}
        <section aria-label="Case queue" className="panel" style={{ padding: 0, overflow: "hidden" }}>
          {/* Column headers */}
          <div className="queue-head" style={{ padding: "12px 16px 10px 22px" }}>
            <span aria-hidden="true" />
            <span>Case ID / Facility</span>
            <span>Tier</span>
            <span>Status</span>
            <span>Updated</span>
            <span>Created</span>
            <span />
          </div>

          {loading && tasks.length === 0 ? (
            <div style={{ padding: "32px 16px" }}>
              {[1, 2, 3].map((i) => (
                <div key={i} className="skeleton" style={{ height: 60, marginBottom: 10 }} />
              ))}
            </div>
          ) : error ? (
            <div role="alert" className="alert" style={{ margin: 16 }}>
              <p style={{ fontWeight: 700 }}>Could not load cases.</p>
              <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
              <button type="button" onClick={refetch} className="btn btn-sm btn-danger" style={{ marginTop: 8 }}>
                Try again
              </button>
            </div>
          ) : visibleTasks.length === 0 ? (
            <p className="empty">No cases match this filter.</p>
          ) : (
            <div className="queue" style={{ padding: "8px 16px 16px" }}>
              {visibleTasks.map((task, i) => (
                <CaseRow key={task.task_id} task={task} index={i} />
              ))}
            </div>
          )}
        </section>

        {/* Tier legend */}
        <div className="notice" style={{ marginTop: 16, fontSize: 12, display: "flex", gap: 16, flexWrap: "wrap" }}>
          <strong>Kerala Health Tiers:</strong>
          <span style={{ color: "var(--ta)" }}>◆ A — ASHA/PHC</span>
          <span style={{ color: "var(--tb)" }}>◆ B — CHC/Taluk</span>
          <span style={{ color: "var(--c2)" }}>◆ C1 — District Hospital</span>
          <span style={{ color: "var(--c1)" }}>◆ C2 — Tertiary/Stroke Unit</span>
        </div>
      </div>
    </div>
  );
}
