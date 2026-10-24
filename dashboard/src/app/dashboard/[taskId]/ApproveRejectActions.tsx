"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { ApiError, approveTask, rejectTask } from "@/lib/api";
import type { TaskDetail } from "@/lib/types";
import { useT } from "@/lib/i18n";

export default function ApproveRejectActions({
  task,
  onUpdated,
}: {
  task: TaskDetail;
  onUpdated: (task: TaskDetail) => void;
}) {
  const { t } = useT();
  const { data: session } = useSession();
  const accessToken = session?.accessToken;
  const actor = session?.username ?? "unknown";

  const [showRejectForm, setShowRejectForm] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<"approve" | "reject" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const canAct =
    task.state === "awaiting_approval" ||
    task.state === "auto_escalated" ||
    task.state === "human_handoff";

  if (!canAct) return null;

  async function handleApprove() {
    if (!accessToken) return;
    setSubmitting("approve");
    setActionError(null);
    try {
      const updated = await approveTask(accessToken, task.task_id, actor);
      onUpdated(updated);
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? `${err.status === 409 ? "Conflict: " : ""}${err.message}`
          : "Failed to approve task"
      );
    } finally {
      setSubmitting(null);
    }
  }

  async function handleReject(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setReasonError("A reason is required to reject.");
      return;
    }
    if (!accessToken) return;
    setSubmitting("reject");
    setActionError(null);
    setReasonError(null);
    try {
      const updated = await rejectTask(accessToken, task.task_id, actor, reason.trim());
      onUpdated(updated);
      setShowRejectForm(false);
      setReason("");
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? `${err.status === 409 ? "Conflict: " : ""}${err.message}`
          : "Failed to reject task"
      );
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-slate-900">
        Doctor actions
      </h2>

      {actionError ? (
        <p role="alert" className="mb-3 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          {actionError}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleApprove}
          disabled={submitting !== null}
          className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-800"
        >
          {submitting === "approve" ? "Approving…" : t("action.approve")}
        </button>
        <button
          type="button"
          onClick={() => setShowRejectForm((v) => !v)}
          disabled={submitting !== null}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-800"
        >
          {t("action.reject")}
        </button>
      </div>

      {showRejectForm ? (
        <form onSubmit={handleReject} className="mt-4 flex flex-col gap-2">
          <label htmlFor="reject-reason" className="text-sm font-medium text-slate-700">
            Reason for rejection (required)
          </label>
          <textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              if (reasonError) setReasonError(null);
            }}
            rows={3}
            className="rounded-md border border-slate-300 p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={reasonError ? "reject-reason-error" : undefined}
          />
          {reasonError ? (
            <p id="reject-reason-error" className="text-sm text-red-700">
              {reasonError}
            </p>
          ) : null}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={submitting !== null}
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-800"
            >
              {submitting === "reject" ? "Rejecting…" : "Submit rejection"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowRejectForm(false);
                setReason("");
                setReasonError(null);
              }}
              disabled={submitting !== null}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
