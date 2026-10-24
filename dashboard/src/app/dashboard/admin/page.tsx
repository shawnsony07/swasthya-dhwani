"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { fetchAdminMetrics } from "@/lib/api";
import type { AdminMetrics } from "@/lib/types";
import { formatStateName, formatPercent, formatMs, formatDuration } from "@/lib/formatters";
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
  awaiting_hospital: "var(--info)",
  ambulance_requested: "var(--info)",
  follow_up: "var(--info)",
  approved: "var(--ok)",
  completed: "var(--ok)",
  rejected: "var(--muted)",
};

function BarChart({
  data,
  colors,
  total,
  label,
  isState = false,
}: {
  data: Record<string, number>;
  colors: Record<string, string>;
  total: number;
  label: string;
  isState?: boolean;
}) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  return (
    <div className="ladder" role="list" aria-label={label}>
      {entries.map(([key, count]) => {
        const pct = total > 0 ? (count / total) * 100 : 0;
        const color = colors[key] ?? "var(--muted)";
        const displayLabel = isState ? formatStateName(key) : `Tier ${key}`;
        return (
          <div key={key} className="ladder-row" role="listitem">
            <span className="ladder-label" style={{ color }} title={key}>
              {displayLabel}
            </span>
            <div className="ladder-bar" role="presentation">
              <i style={{ width: `${Math.max(pct, 2)}%`, "--bar": color } as React.CSSProperties} />
            </div>
            <span className="ladder-count" style={{ color }}>
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

  const total = metrics?.total_cases ?? 0;

  return (
    <div className="shell">
      <div className="page">
        {/* Header */}
        <div className="page-head">
          <div>
            <p className="eyebrow">System Telemetry &amp; Health</p>
            <h1 className="page-title">Admin Operations Console</h1>
            <p className="page-sub">
              Live aggregate performance telemetry, tier routing distributions, and emergency safeguards.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--muted)" }} className="mono" suppressHydrationWarning>
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
          <div className="grid grid-kpi" style={{ marginBottom: 24 }}>
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="skeleton" style={{ height: 104 }} />
            ))}
          </div>
        ) : error ? (
          <div role="alert" className="alert" style={{ marginBottom: 24 }}>
            <p style={{ fontWeight: 700 }}>Could not load metrics.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
          </div>
        ) : metrics ? (
          <>
            {/* KPI Telemetry Grid */}
            <div className="grid grid-kpi" style={{ marginBottom: 24 }}>
              <div className="kpi">
                <div className="kpi-label">Total Cases</div>
                <div className="kpi-value">{metrics.total_cases}</div>
                <div className="kpi-note">All lifetime intake</div>
              </div>

              <div className="kpi">
                <div className="kpi-label">Open Cases</div>
                <div className="kpi-value">{metrics.open_cases}</div>
                <div className="kpi-note">Active in pipeline</div>
              </div>

              <div className={`kpi ${metrics.time_critical > 0 ? "kpi-alert" : ""}`}>
                <div className="kpi-label">Critical Cases</div>
                <div className="kpi-value">{metrics.time_critical}</div>
                <div className="kpi-note">Time-critical acute</div>
              </div>

              <div className="kpi">
                <div className="kpi-label">Avg STT Confidence</div>
                <div className="kpi-value">
                  {formatPercent(metrics.stt_confidence?.mean)}
                </div>
                <div className="kpi-note">{metrics.stt_confidence?.samples ?? 0} voice samples</div>
              </div>

              <div className="kpi">
                <div className="kpi-label">Avg Voice TTFB</div>
                <div className="kpi-value">
                  {formatMs(metrics.tts_ttfb_ms?.mean)}
                </div>
                <div className="kpi-note">{metrics.tts_ttfb_ms?.samples ?? 0} speech syntheses</div>
              </div>

              <div className="kpi">
                <div className="kpi-label">Avg Call Duration</div>
                <div className="kpi-value">
                  {formatDuration(metrics.call_duration_seconds?.mean)}
                </div>
                <div className="kpi-note">{metrics.call_duration_seconds?.samples ?? 0} completed calls</div>
              </div>
            </div>

            {/* Distribution Charts */}
            <div className="grid grid-2" style={{ marginBottom: 24 }}>
              {/* Cases by Tier */}
              <div className="panel">
                <div className="panel-title">
                  <span>Cases by Kerala Acuity Tier</span>
                  <small>Protocol v2026.03.01</small>
                </div>
                <BarChart
                  data={metrics.by_tier}
                  colors={TIER_COLOR}
                  total={total}
                  label="Cases by Acuity Tier"
                />
                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    marginTop: 18,
                    fontSize: 11.5,
                    color: "var(--muted)",
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ color: "var(--ta)" }}>◆ A — ASHA/PHC</span>
                  <span style={{ color: "var(--tb)" }}>◆ B — CHC/Taluk</span>
                  <span style={{ color: "var(--c2)" }}>◆ C1 — District Hospital</span>
                  <span style={{ color: "var(--c1)" }}>◆ C2 — Tertiary / Stroke Center</span>
                </div>
              </div>

              {/* Cases by State */}
              <div className="panel">
                <div className="panel-title">
                  <span>Cases by Pipeline State</span>
                  <small>Workflow distribution</small>
                </div>
                <BarChart
                  data={metrics.by_state}
                  colors={STATE_COLOR}
                  total={total}
                  label="Cases by Workflow State"
                  isState
                />
              </div>
            </div>

            {/* Safeguards Notice */}
            <div
              className="notice"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 12,
              }}
            >
              <span>
                <strong>Kerala Emergency Safeguard v1.4:</strong> All C1/C2 acute cases auto-escalate after 30 min if unreviewed. Unreviewed stroke alerts page the regional medical officer directly.
              </span>
              <span style={{ color: "var(--brass)", fontSize: 12, fontWeight: 600 }}>
                Safety Principle: Uncertainty never lowers acuity.
              </span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
