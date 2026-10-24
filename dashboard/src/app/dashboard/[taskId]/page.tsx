"use client";

import { use } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import TriagePanel from "@/components/TriagePanel";
import { useTask } from "./useTask";
import ApproveRejectActions from "./ApproveRejectActions";

export default function TaskDetailPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = use(params);
  const { data: session } = useSession();
  const { task, setTask, loading, error, notFound, refetch } = useTask(taskId);

  const isDoctor = session?.roles?.includes("doctor") ?? false;

  return (
    <div className="mx-auto max-w-3xl">
      <Link
        href="/dashboard"
        className="mb-4 inline-block text-sm font-medium text-blue-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        ← Back to dashboard
      </Link>

      {loading ? (
        <p className="rounded-md border border-slate-200 bg-white p-6 text-center text-slate-500">
          Loading task…
        </p>
      ) : notFound ? (
        <div role="alert" className="rounded-md border border-slate-300 bg-slate-50 p-6 text-center text-slate-700">
          Task &quot;{taskId}&quot; was not found.
        </div>
      ) : error ? (
        <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-4 text-red-800">
          <p className="font-semibold">Could not load this task.</p>
          <p className="text-sm">{error}</p>
          <button
            type="button"
            onClick={refetch}
            className="mt-2 rounded-md border border-red-400 px-3 py-1.5 text-sm font-medium hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
          >
            Try again
          </button>
        </div>
      ) : task ? (
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <TierBadge tier={task.tier} />
              <StateBadge state={task.state} />
              {task.is_time_critical ? <TimeCriticalBadge /> : null}
            </div>
            <dl className="mt-3 grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
              <div>
                <dt className="font-medium text-slate-500">Hospital</dt>
                <dd className="text-slate-900">{task.hospital ?? "Not yet assigned"}</dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Updated</dt>
                <dd className="text-slate-900">
                  <RelativeTime iso={task.updated_at} />
                </dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Created</dt>
                <dd className="text-slate-900">
                  <RelativeTime iso={task.created_at} />
                </dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Task ID</dt>
                <dd className="font-mono text-xs text-slate-700">{task.task_id}</dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Patient identifier (hashed)</dt>
                <dd className="font-mono text-xs text-slate-700 break-all">
                  {task.patient_identifier_hash}
                </dd>
              </div>
            </dl>
          </div>

          {task.triage_snapshot ? (
            <TriagePanel snapshot={task.triage_snapshot} />
          ) : (
            <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-slate-500">
              No snapshot available
            </div>
          )}

          {isDoctor ? (
            <ApproveRejectActions task={task} onUpdated={setTask} />
          ) : (
            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              Read-only view — only the doctor role can approve or reject.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
