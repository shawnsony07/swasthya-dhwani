import type { TriageSnapshot } from "@/lib/types";
import { ConfidenceMeter } from "./Telemetry";

/**
 * Raw-vs-interpreted-vs-confidence panel (architecture.md section 12):
 * raw transcript and interpreted text side by side, confidence as both a
 * number and a visual indicator, impairment signals as tags, speech
 * onset, confirmed_by. Interpreted content is labelled "machine-
 * interpreted" per the doc's honesty-cues requirement (section 7/12).
 */
export default function TriagePanel({ snapshot }: { snapshot: TriageSnapshot }) {
  const confidence = Math.min(Math.max(snapshot.interpretation_confidence, 0), 1);

  return (
    <div className="panel">
      <div className="panel-title">
        Triage Snapshot
        <small className="mono">{snapshot.protocol_version}</small>
      </div>

      {/* Transcript compare */}
      <div className="grid grid-2" style={{ gap: 12, marginBottom: 16 }}>
        <div className="say">
          <div className="say-label">
            <span>Raw transcript</span>
            <span aria-hidden="true">🎙</span>
          </div>
          <p className="say-text" style={{ fontSize: 14 }}>
            {snapshot.raw_transcript || "—"}
          </p>
        </div>
        <div className="say say-machine">
          <div className="say-label">
            <span>Machine-interpreted</span>
            <span className="tag" aria-label="AI generated interpretation">AI</span>
          </div>
          <p className="say-text" style={{ fontSize: 14 }}>
            {snapshot.interpreted_text || "—"}
          </p>
        </div>
      </div>

      {/* Confidence meter */}
      <div className="tile" style={{ marginBottom: 16 }}>
        <div className="tile-name">
          Interpretation Confidence
          <em>speech-to-intent</em>
        </div>
        <div className="tile-body" style={{ marginTop: 10 }}>
          <ConfidenceMeter value={confidence} label="Interpretation confidence" large />
        </div>
      </div>

      {/* Clinical signals */}
      <div className="grid grid-2" style={{ gap: 12 }}>
        <div>
          <p style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
            Symptoms
          </p>
          <div className="tags">
            {snapshot.symptoms.length === 0 ? (
              <span style={{ color: "var(--muted)", fontSize: 13 }}>None recorded</span>
            ) : (
              snapshot.symptoms.map((s) => (
                <span key={s} className="tag">{s}</span>
              ))
            )}
          </div>
          {snapshot.symptom_duration_days > 0 && (
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
              Duration: <strong style={{ color: "var(--text-dim)" }}>{snapshot.symptom_duration_days} day(s)</strong>
            </p>
          )}
        </div>

        <div>
          <p style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
            Warning Signs
          </p>
          <div className="tags">
            {snapshot.warning_signs_present.length === 0 ? (
              <span style={{ color: "var(--muted)", fontSize: 13 }}>None</span>
            ) : (
              snapshot.warning_signs_present.map((w) => (
                <span key={w} className="tag tag-warn">{w}</span>
              ))
            )}
          </div>
        </div>

        <div>
          <p style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
            Speech Impairment Signals
          </p>
          <div className="tags">
            {snapshot.speech_impairment_signals.length === 0 ? (
              <span style={{ color: "var(--muted)", fontSize: 13 }}>None</span>
            ) : (
              snapshot.speech_impairment_signals.map((sig) => (
                <span key={sig} className="tag tag-crit">{sig}</span>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="facts">
            <dl className="fact">
              <dt>Speech onset</dt>
              <dd>{snapshot.speech_onset || "—"}</dd>
            </dl>
            <dl className="fact">
              <dt>Confirmed by</dt>
              <dd>{snapshot.confirmed_by || "—"}</dd>
            </dl>
            <dl className="fact">
              <dt>Interpreter model</dt>
              <dd className="mono" style={{ fontSize: 11 }}>{snapshot.interpreter_model || "unknown"}</dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
