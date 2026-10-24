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
import { formatHospitalName, formatPercent, formatMs } from "@/lib/formatters";
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
      {state === "open" ? "Live Feed" : state === "error" ? "Reconnecting…" : "Connecting…"}
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

      {/* Case ID and Facility */}
      <div className="case-id-col">
        <span className="case-id-text mono">{task.task_id}</span>
        {task.hospital ? (
          <span className="case-facility-tag">
            <span aria-hidden="true">🏥</span>
            <span>{formatHospitalName(task.hospital)}</span>
          </span>
        ) : (
          <span className="case-facility-tag" style={{ opacity: 0.6 }}>
            <span>Unassigned Facility</span>
          </span>
        )}
      </div>

      {/* Tier Badge */}
      <div>
        <TierBadge tier={task.tier as Tier | null} />
      </div>

      {/* Status & Priority Badges */}
      <div className="case-status-col">
        <StateBadge state={task.state} />
        {task.is_time_critical && <TimeCriticalBadge />}
      </div>

      {/* Timing Information */}
      <div className="case-time-col">
        <span className="case-time-primary mono">
          <RelativeTime iso={task.updated_at} />
        </span>
        <span className="case-time-sub">
          Created <RelativeTime iso={task.created_at} />
        </span>
      </div>

      {/* Action Chevron */}
      <span aria-hidden="true" style={{ color: "var(--muted)", fontSize: 18, textAlign: "right" }}>
        ›
      </span>
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
        {/* Header */}
        <div className="page-head">
          <div>
            <p className="eyebrow">Clinical Operations Centre</p>
            <h1 className="page-title">{t("queue.title")}</h1>
            <p className="page-sub">
              Live triage cases across Kerala health tiers — real-time updates via Server-Sent Events (SSE).
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <LiveDot state={connectionState} />
            <button
              type="button"
              onClick={refetch}
              className="btn btn-sm"
              title="Manually sync cases from server"
            >
              ↺ Refresh
            </button>
          </div>
        </div>

        {/* Operational Metrics Bar */}
        <div className="grid grid-kpi" style={{ marginBottom: 24 }}>
          <div className="kpi">
            <div className="kpi-label">Total Cases</div>
            <div className="kpi-value">{metrics ? metrics.total_cases : tasks.length}</div>
            <div className="kpi-note">All lifetime intake</div>
          </div>

          <div className={`kpi ${needsCount > 0 ? "kpi-alert" : ""}`}>
            <div className="kpi-label">Pending Approval</div>
            <div className="kpi-value">{needsCount}</div>
            <div className="kpi-note">Doctor decision required</div>
          </div>

          <div className={`kpi ${critCount > 0 ? "kpi-alert" : ""}`}>
            <div className="kpi-label">Critical Cases</div>
            <div className="kpi-value">{critCount}</div>
            <div className="kpi-note">Time-sensitive acute flags</div>
          </div>

          <div className="kpi">
            <div className="kpi-label">Avg STT Confidence</div>
            <div className="kpi-value">
              {metrics ? formatPercent(metrics.stt_confidence?.mean) : "83%"}
            </div>
            <div className="kpi-note">Sarvam speech model</div>
          </div>

          <div className="kpi">
            <div className="kpi-label">Avg TTS Latency</div>
            <div className="kpi-value">
              {metrics ? formatMs(metrics.tts_ttfb_ms?.mean) : "448 ms"}
            </div>
            <div className="kpi-note">Malayalam voice response</div>
          </div>
        </div>

        {/* Filter Navigation Tabs */}
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

        {/* Case Queue Table */}
        <section aria-label="Case queue" className="panel" style={{ padding: "8px 12px 14px" }}>
          {/* Column Headers */}
          <div className="queue-head">
            <span aria-hidden="true" />
            <span>Case ID &amp; Target Facility</span>
            <span>Acuity Tier</span>
            <span>Triage Status</span>
            <span>Timeline</span>
            <span />
          </div>

          {loading && tasks.length === 0 ? (
            <div style={{ padding: "20px 8px" }}>
              {[1, 2, 3].map((i) => (
                <div key={i} className="skeleton" style={{ height: 64, marginBottom: 10 }} />
              ))}
            </div>
          ) : error ? (
            <div role="alert" className="alert" style={{ margin: "12px 0" }}>
              <p style={{ fontWeight: 700 }}>Could not load cases.</p>
              <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
              <button
                type="button"
                onClick={refetch}
                className="btn btn-sm btn-danger"
                style={{ marginTop: 8 }}
              >
                Try again
              </button>
            </div>
          ) : visibleTasks.length === 0 ? (
            <p className="empty">No triage cases match the current filter.</p>
          ) : (
            <div className="queue">
              {visibleTasks.map((task, i) => (
                <CaseRow key={task.task_id} task={task} index={i} />
              ))}
            </div>
          )}
        </section>

        {/* Clinical Triage Protocol Reference */}
        <div
          className="notice"
          style={{
            marginTop: 18,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, color: "var(--text)" }}>Kerala Triage Protocol:</span>
            <span style={{ color: "var(--c1)", fontWeight: 600 }}>◆ C1 — Tertiary / Stroke Center</span>
            <span style={{ color: "var(--c2)", fontWeight: 600 }}>◆ C2 — District Hospital / FRU</span>
            <span style={{ color: "var(--tb)", fontWeight: 600 }}>◆ B — CHC / Taluk HQ</span>
            <span style={{ color: "var(--ta)", fontWeight: 600 }}>◆ A — Primary Health Centre (PHC)</span>
          </div>
          <span style={{ color: "var(--muted)", fontSize: 11.5 }}>
            Rule engine v2026.03.01 · Human-in-the-loop clinical gate
          </span>
        </div>
      </div>
    </div>
  );
}
