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
  const accessToken = (session as { accessToken?: string })?.accessToken;
  const actor = (session as { username?: string })?.username ?? "unknown";

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
    <div className="panel">
      <div className="panel-title">Doctor Actions</div>

      {actionError && (
        <div role="alert" className="alert" style={{ marginBottom: 14 }}>
          {actionError}
        </div>
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={handleApprove}
          disabled={submitting !== null}
          className="btn btn-ok"
        >
          {submitting === "approve" ? "Approving…" : `✓ ${t("action.approve")}`}
        </button>
        <button
          type="button"
          onClick={() => setShowRejectForm((v) => !v)}
          disabled={submitting !== null}
          className="btn btn-danger"
        >
          {t("action.reject")}
        </button>
      </div>

      {showRejectForm && (
        <form onSubmit={handleReject} style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          <label htmlFor="reject-reason" className="label">
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
            className="textarea"
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={reasonError ? "reject-reason-error" : undefined}
          />
          {reasonError && (
            <p id="reject-reason-error" style={{ fontSize: 13, color: "var(--c1)" }} role="alert">
              {reasonError}
            </p>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              disabled={submitting !== null}
              className="btn btn-danger"
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
              className="btn"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
