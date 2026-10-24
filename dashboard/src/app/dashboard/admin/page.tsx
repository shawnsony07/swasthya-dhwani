"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { fetchAdminMetrics } from "@/lib/api";
import type { AdminMetrics } from "@/lib/types";
import { ConfidenceMeter, LatencyBadge, DurationDisplay } from "@/components/Telemetry";
import Link from "next/link";

const TIER_COLOR: Record<string, string> = {
  C1: "var(--c1)",
  C2: "var(--c2)",
  B: "var(--tb)",
  A: "var(--ta)",
};

const STATE_COLOR: Record<string, string> = {
  working: "var(--info)",
  awaiting_approval: "var(--brass)",
  human_handoff: "var(--c1)",
  auto_escalated: "var(--c2)",
  approved: "var(--ok)",
  completed: "var(--ok)",
  rejected: "var(--muted)",
};

function BarChart({
  data,
  colors,
  total,
  label,
}: {
  data: Record<string, number>;
  colors: Record<string, string>;
  total: number;
  label: string;
}) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  return (
    <div className="ladder" role="list" aria-label={label}>
      {entries.map(([key, count]) => {
        const pct = total > 0 ? (count / total) * 100 : 0;
        const color = colors[key] ?? "var(--muted)";
        return (
          <div key={key} className="ladder-row" role="listitem">
            <span className="mono" style={{ fontSize: 12, color }}>
              {key}
            </span>
            <div className="ladder-bar" role="presentation">
              <i style={{ width: `${pct}%`, "--bar": color } as React.CSSProperties} />
            </div>
            <span
              className="mono"
              style={{ fontSize: 13, fontWeight: 700, color, minWidth: 32, textAlign: "right" }}
            >
              {count}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function AdminPage() {
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const load = useCallback(async () => {
    try {
      setError(null);
      const m = await fetchAdminMetrics(accessToken);
      setMetrics(m);
      setLastRefresh(new Date());
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

  const total = metrics?.total_tasks ?? 0;

  return (
    <div className="shell">
      <div className="page">
        <div className="page-head">
          <div>
            <p className="eyebrow">System Overview</p>
            <h1 className="page-title">Admin Metrics</h1>
            <p className="page-sub">
              Aggregate performance data across all Kerala health tiers — refreshed every 30 s.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
            <button type="button" onClick={load} className="btn btn-sm">
              ↺ Refresh
            </button>
            <Link href="/dashboard/routing" className="btn btn-sm btn-primary">
              Routing Board →
            </Link>
          </div>
        </div>

        {loading ? (
          <div className="grid grid-kpi">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton" style={{ height: 96 }} />
            ))}
          </div>
        ) : error ? (
          <div role="alert" className="alert">
            <p style={{ fontWeight: 700 }}>Could not load metrics.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
          </div>
        ) : metrics ? (
          <>
            {/* KPI Strip */}
            <div className="grid grid-kpi" style={{ marginBottom: 24 }}>
              <div className="panel kpi">
                <div className="kpi-label">Total Cases</div>
                <div className="kpi-value">{metrics.total_tasks}</div>
                <div className="kpi-note">All time</div>
              </div>

              <div className={`panel kpi ${metrics.pending_approval > 0 ? "kpi-alert" : ""}`}>
                <div className="kpi-label">Pending Approval</div>
                <div className="kpi-value">{metrics.pending_approval}</div>
                <div className="kpi-note">Needs action</div>
              </div>

              <div className={`panel kpi ${metrics.critical_cases > 0 ? "kpi-alert" : ""}`}>
                <div className="kpi-label">Critical Cases</div>
                <div className="kpi-value">{metrics.critical_cases}</div>
                <div className="kpi-note">🛑 Time-sensitive</div>
              </div>

              <div className="panel kpi">
                <div className="kpi-label">Avg STT Confidence</div>
                <div className="kpi-value" style={{ fontSize: 28, marginTop: 8 }}>
                  <ConfidenceMeter
                    value={metrics.avg_stt_confidence}
                    label="Average STT confidence"
                    large
                  />
                </div>
              </div>

              <div className="panel kpi">
                <div className="kpi-label">Avg TTS Latency</div>
                <div className="kpi-value" style={{ fontSize: 28, marginTop: 8 }}>
                  <LatencyBadge ms={metrics.avg_tts_latency_ms} />
                </div>
              </div>

              <div className="panel kpi">
                <div className="kpi-label">Avg Call Duration</div>
                <div className="kpi-value" style={{ fontSize: 28, marginTop: 8 }}>
                  <DurationDisplay seconds={metrics.avg_call_duration_s} />
                </div>
              </div>
            </div>

            {/* Bar charts */}
            <div className="grid grid-2">
              <div className="panel">
                <div className="panel-title">
                  Cases by Tier
                  <small>Kerala health protocol</small>
                </div>
                {Object.keys(metrics.by_tier).length === 0 ? (
                  <p className="empty">No tier data.</p>
                ) : (
                  <BarChart
                    data={metrics.by_tier}
                    colors={TIER_COLOR}
                    total={total}
                    label="Cases by tier"
                  />
                )}

                {/* Tier legend */}
                <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 10, fontSize: 11 }}>
                  <span style={{ color: "var(--ta)" }}>◆ A — ASHA/PHC (primary)</span>
                  <span style={{ color: "var(--tb)" }}>◆ B — CHC/Taluk</span>
                  <span style={{ color: "var(--c2)" }}>◆ C1 — District Hospital</span>
                  <span style={{ color: "var(--c1)" }}>◆ C2 — Tertiary/Stroke Unit</span>
                </div>
              </div>

              <div className="panel">
                <div className="panel-title">
                  Cases by State
                  <small>Workflow distribution</small>
                </div>
                {Object.keys(metrics.by_state).length === 0 ? (
                  <p className="empty">No state data.</p>
                ) : (
                  <BarChart
                    data={metrics.by_state}
                    colors={STATE_COLOR}
                    total={total}
                    label="Cases by state"
                  />
                )}
              </div>
            </div>

            {/* Compliance notice */}
            <div className="notice" style={{ marginTop: 20 }}>
              <strong>Kerala Health Protocol v1.4</strong> — All cases auto-escalate to C1 after 30 min
              without approval. C2 cases receive immediate tertiary notification.
              Triage follows Government of Kerala Emergency Response Guidelines.
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
