"use client";

import { useState } from "react";
import Link from "next/link";
import { useT } from "@/lib/i18n";
import { NEEDS_APPROVAL_STATES } from "@/lib/types";
import { StateBadge, TierBadge, TimeCriticalBadge } from "@/components/badges";
import RelativeTime from "@/components/RelativeTime";
import { useTasks } from "./useTasks";

type FilterTab = "needs_approval" | "all";

export default function DashboardPage() {
  const { t } = useT();
  const { tasks, loading, error, refetch, connectionState } = useTasks();
  const [filter, setFilter] = useState<FilterTab>("needs_approval");

  const visibleTasks =
    filter === "needs_approval"
      ? tasks.filter((task) => NEEDS_APPROVAL_STATES.includes(task.state))
      : tasks;

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Task filter" className="flex gap-2">
          <button
            type="button"
            role="tab"
            aria-selected={filter === "needs_approval"}
            onClick={() => setFilter("needs_approval")}
            className={`rounded-md px-4 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
              filter === "needs_approval"
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {t("filter.needsApproval")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filter === "all"}
            onClick={() => setFilter("all")}
            className={`rounded-md px-4 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
              filter === "all"
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {t("filter.all")}
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span
            aria-hidden="true"
            className={`inline-block h-2 w-2 rounded-full ${
              connectionState === "open"
                ? "bg-green-500"
                : connectionState === "error"
                  ? "bg-red-500"
                  : "bg-amber-400"
            }`}
          />
          <span>
            {connectionState === "open"
              ? "Live"
              : connectionState === "error"
                ? "Reconnecting..."
                : "Connecting..."}
          </span>
          <button
            type="button"
            onClick={refetch}
            className="rounded-md border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            Refresh
          </button>
        </div>
      </div>

      {loading && tasks.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-white p-6 text-center text-slate-500">
          Loading tasks…
        </p>
      ) : error ? (
        <div
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 p-4 text-red-800"
        >
          <p className="font-semibold">Could not load tasks.</p>
          <p className="text-sm">{error}</p>
          <button
            type="button"
            onClick={refetch}
            className="mt-2 rounded-md border border-red-400 px-3 py-1.5 text-sm font-medium hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
          >
            Try again
          </button>
        </div>
      ) : visibleTasks.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-white p-6 text-center text-slate-500">
          No tasks to show.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {visibleTasks.map((task) => (
            <li key={task.task_id}>
              <Link
                href={`/dashboard/${encodeURIComponent(task.task_id)}`}
                className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-blue-400 hover:shadow focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <TierBadge tier={task.tier} />
                  <StateBadge state={task.state} />
                  {task.is_time_critical ? <TimeCriticalBadge /> : null}
                </div>
                <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2 text-sm text-slate-600">
                  <span>
                    Hospital:{" "}
                    <strong className="text-slate-900">
                      {task.hospital ?? "Not yet assigned"}
                    </strong>
                  </span>
                  <span className="text-slate-500">
                    Updated <RelativeTime iso={task.updated_at} />
                  </span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  Task {task.task_id}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
