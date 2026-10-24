import type { TriageSnapshot } from "@/lib/types";

/**
 * Raw-vs-interpreted-vs-confidence panel (architecture.md section 12):
 * raw transcript and interpreted text side by side, confidence as both a
 * number and a visual indicator, impairment signals as tags, speech
 * onset, confirmed_by. Interpreted content is labelled "machine-
 * interpreted" per the doc's honesty-cues requirement (section 7/12).
 * `triage_snapshot: null` renders "No snapshot available" rather than
 * crashing (handled by the caller, not here).
 */
export default function TriagePanel({ snapshot }: { snapshot: TriageSnapshot }) {
  const confidencePercent = Math.round(
    Math.min(Math.max(snapshot.interpretation_confidence, 0), 1) * 100
  );
  const confidenceColor =
    confidencePercent >= 75
      ? "bg-green-500"
      : confidencePercent >= 40
        ? "bg-amber-500"
        : "bg-red-500";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-slate-900">
        Triage snapshot
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-medium text-slate-500">Raw transcript</h3>
          <p className="mt-1 rounded-md bg-slate-50 p-3 text-sm text-slate-800 whitespace-pre-wrap">
            {snapshot.raw_transcript || "—"}
          </p>
        </div>
        <div>
          <h3 className="text-sm font-medium text-slate-500">
            Interpreted text{" "}
            <span className="ml-1 rounded bg-indigo-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-indigo-700">
              machine-interpreted
            </span>
          </h3>
          <p className="mt-1 rounded-md bg-indigo-50 p-3 text-sm text-slate-800 whitespace-pre-wrap">
            {snapshot.interpreted_text || "—"}
          </p>
        </div>
      </div>

      <div className="mt-4">
        <h3 className="text-sm font-medium text-slate-500">
          Interpretation confidence
        </h3>
        <div className="mt-1 flex items-center gap-3">
          <div
            className="h-2 flex-1 rounded-full bg-slate-200"
            role="progressbar"
            aria-valuenow={confidencePercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Interpretation confidence"
          >
            <div
              className={`h-2 rounded-full ${confidenceColor}`}
              style={{ width: `${confidencePercent}%` }}
            />
          </div>
          <span className="text-sm font-semibold text-slate-700">
            {confidencePercent}%
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-medium text-slate-500">
            Impairment signals
          </h3>
          {snapshot.speech_impairment_signals.length === 0 ? (
            <p className="mt-1 text-sm text-slate-400">None recorded</p>
          ) : (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {snapshot.speech_impairment_signals.map((signal) => (
                <li
                  key={signal}
                  className="rounded-full border border-purple-300 bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-800"
                >
                  {signal}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <h3 className="font-medium text-slate-500">Speech onset</h3>
            <p className="mt-1 text-slate-800">{snapshot.speech_onset}</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-500">Confirmed by</h3>
            <p className="mt-1 text-slate-800">{snapshot.confirmed_by}</p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500 sm:grid-cols-2">
        <div>
          Symptoms:{" "}
          <span className="text-slate-700">
            {snapshot.symptoms.length ? snapshot.symptoms.join(", ") : "none"}
          </span>{" "}
          · Duration: {snapshot.symptom_duration_days} day(s)
        </div>
        <div>
          Warning signs:{" "}
          <span className="text-slate-700">
            {snapshot.warning_signs_present.length
              ? snapshot.warning_signs_present.join(", ")
              : "none"}
          </span>
        </div>
        <div>Interpreter model: {snapshot.interpreter_model || "unknown"}</div>
        <div>Protocol version: {snapshot.protocol_version || "unknown"}</div>
      </div>
    </div>
  );
}
