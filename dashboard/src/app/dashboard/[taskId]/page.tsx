"use client";

import { use, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import TriagePanel from "@/components/TriagePanel";
import {
  ConfidenceMeter,
  LatencyBadge,
  DurationDisplay,
} from "@/components/Telemetry";
import { useTask } from "./useTask";
import ApproveRejectActions from "./ApproveRejectActions";
import { fetchAuditTimeline } from "@/lib/api";
import type { AuditTimeline, Tier } from "@/lib/types";

function AuditTimelinePanel({ taskId }: { taskId: string }) {
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const [timeline, setTimeline] = useState<AuditTimeline | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const t = await fetchAuditTimeline(accessToken, taskId);
      setTimeline(t);
    } catch {
      // timeline is supplemental
    } finally {
      setLoading(false);
    }
  }, [accessToken, taskId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="skeleton" style={{ height: 100 }} />;
  if (!timeline || timeline.events.length === 0) return null;

  const TONE: Record<string, string> = {
    rejected: "loud",
    failed: "loud",
    auto_escalated: "loud",
    approved: "ok",
    completed: "ok",
  };

  return (
    <div className="panel">
      <div className="panel-title">
        Audit Timeline
        <small>{timeline.events.length} events</small>
      </div>
      <ol className="timeline" aria-label="Case audit timeline">
        {timeline.events.map((ev) => (
          <li
            key={ev.seq}
            className="tl-item"
            data-tone={TONE[ev.to_state ?? ""] ?? undefined}
          >
            <div className="tl-name">
              {ev.action}
              {ev.to_state && (
                <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 6, fontSize: 12 }}>
                  → {ev.to_state}
                </span>
              )}
            </div>
            <div className="tl-meta">
              <span className="mono">{ev.actor}</span>
              {" · "}
              <RelativeTime iso={ev.ts} />
            </div>
            {ev.note && <div className="tl-detail">{ev.note}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function TaskDetailPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = use(params);
  const { data: session } = useSession();
  const { task, setTask, loading, error, notFound, refetch } = useTask(taskId);

  const isDoctor = (session as { roles?: string[] })?.roles?.includes("doctor") ?? false;

  return (
    <div className="shell">
      <div className="page" style={{ maxWidth: 1100 }}>
        <Link href="/dashboard" className="btn btn-sm" style={{ marginBottom: 20, display: "inline-flex" }}>
          ← Back to queue
        </Link>

        {loading ? (
          <div>
            <div className="skeleton" style={{ height: 140, marginBottom: 16 }} />
            <div className="skeleton" style={{ height: 220 }} />
          </div>
        ) : notFound ? (
          <div role="alert" className="panel" style={{ textAlign: "center", padding: 48 }}>
            <p style={{ fontSize: 20, fontWeight: 700 }}>Case not found</p>
            <p className="page-sub" style={{ marginTop: 8 }}>No case with ID &quot;{taskId}&quot; exists.</p>
          </div>
        ) : error ? (
          <div role="alert" className="alert">
            <p style={{ fontWeight: 700 }}>Could not load case.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>{error}</p>
            <button type="button" onClick={refetch} className="btn btn-sm btn-danger" style={{ marginTop: 8 }}>
              Try again
            </button>
          </div>
        ) : task ? (
          <div className="detail-grid">
            {/* ── Left column ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

              {/* Case header */}
              <div className="panel">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 16 }}>
                  <TierBadge tier={task.tier as Tier | null} />
                  <StateBadge state={task.state} />
                  {task.is_time_critical && <TimeCriticalBadge />}
                </div>

                <div className="facts">
                  <dl className="fact">
                    <dt>Case ID</dt>
                    <dd className="mono" style={{ fontSize: 13 }}>{task.task_id}</dd>
                  </dl>
                  <dl className="fact">
                    <dt>Facility</dt>
                    <dd>{task.hospital ?? "Not yet assigned"}</dd>
                  </dl>
                  <dl className="fact">
                    <dt>Created</dt>
                    <dd><RelativeTime iso={task.created_at} /></dd>
                  </dl>
                  <dl className="fact">
                    <dt>Last updated</dt>
                    <dd><RelativeTime iso={task.updated_at} /></dd>
                  </dl>
                  <dl className="fact" style={{ gridColumn: "1 / -1" }}>
                    <dt>Patient ID (hashed)</dt>
                    <dd className="mono" style={{ fontSize: 11, wordBreak: "break-all" }}>
                      {task.patient_identifier_hash}
                    </dd>
                  </dl>
                </div>
              </div>

              {/* Call telemetry */}
              {task.call_metrics ? (
                <div className="panel">
                  <div className="panel-title">
                    Call Telemetry
                    {task.call_metrics.livekit_room_id && (
                      <small className="mono">{task.call_metrics.livekit_room_id}</small>
                    )}
                  </div>
                  <div className="tiles">
                    <div className="tile">
                      <div className="tile-name">
                        STT Confidence
                        <em>Speech-to-Text</em>
                      </div>
                      <div className="tile-body">
                        <ConfidenceMeter
                          value={task.call_metrics.stt_confidence_mean}
                          label="STT confidence"
                          large
                        />
                      </div>
                    </div>

                    <div className="tile">
                      <div className="tile-name">
                        TTS Latency
                        <em>Text-to-Speech</em>
                      </div>
                      <div className="tile-body" style={{ marginTop: 8 }}>
                        <LatencyBadge ms={task.call_metrics.tts_latency_mean_ms} />
                      </div>
                    </div>

                    <div className="tile">
                      <div className="tile-name">
                        Call Duration
                        <em>Total session</em>
                      </div>
                      <div className="tile-body" style={{ marginTop: 8 }}>
                        <DurationDisplay seconds={task.call_metrics.call_duration_s} />
                      </div>
                    </div>

                    <div className="tile">
                      <div className="tile-name">
                        Speech Ratio
                        <em>VAD active speech</em>
                      </div>
                      <div className="tile-body">
                        <ConfidenceMeter
                          value={task.call_metrics.vad_speech_ratio}
                          label="Speech ratio"
                        />
                      </div>
                    </div>

                    {task.call_metrics.interruption_count !== null && (
                      <div className="tile">
                        <div className="tile-name">
                          Interruptions
                          <em>Dysfluency events</em>
                        </div>
                        <div className="tile-body" style={{ marginTop: 8 }}>
                          <span
                            className="mono"
                            style={{
                              fontSize: 28,
                              fontWeight: 700,
                              color:
                                task.call_metrics.interruption_count > 5
                                  ? "var(--c1)"
                                  : task.call_metrics.interruption_count > 2
                                  ? "var(--c2)"
                                  : "var(--ok)",
                            }}
                          >
                            {task.call_metrics.interruption_count}
                          </span>
                        </div>
                      </div>
                    )}

                    {task.call_metrics.recorded_at && (
                      <div className="tile">
                        <div className="tile-name">Recorded at</div>
                        <div className="tile-body" style={{ marginTop: 8, fontSize: 13 }}>
                          <RelativeTime iso={task.call_metrics.recorded_at} />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="notice">
                  No call telemetry available for this case — the session may not have completed.
                </div>
              )}

              {/* Triage snapshot */}
              {task.triage_snapshot ? (
                <TriagePanel snapshot={task.triage_snapshot} />
              ) : (
                <div className="panel empty">No triage snapshot available.</div>
              )}

              {/* Actions */}
              {isDoctor ? (
                <ApproveRejectActions task={task} onUpdated={setTask} />
              ) : (
                <div className="notice">
                  Read-only view — only the doctor role can approve or reject.
                </div>
              )}
            </div>

            {/* ── Right column ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <AuditTimelinePanel taskId={taskId} />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
